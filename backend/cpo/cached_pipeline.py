"""CachedPipeline for CPO v3.0 — Delta evaluation wrapper.

Wraps the existing scheduler pipeline phases with caching:
  - Lots (Phase 1): gene-independent, cached once
  - ToolRuns (Phase 2): cached by (edd_gap, max_edd_span)
  - Machine assignment + Sequencing + Dispatch: per chromosome
  - JIT + VNS + Post-processing: per chromosome

Reuses ALL existing functions from backend.scheduler.*.
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict
from dataclasses import dataclass

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.dispatch import (
    assign_machines,
    per_machine_dispatch,
    sequence_per_machine,
)
from backend.scheduler.jit import jit_dispatch
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scoring import compute_score
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, ScheduleResult, Segment, ToolRun
from backend.types import EngineData

from backend.cpo.chromosome import Chromosome

logger = logging.getLogger(__name__)


@dataclass
class _ParamsProxy:
    """Lightweight params object to inject chromosome genes into existing functions."""
    max_edd_gap: int = 10
    max_edd_span: int = 30
    campaign_window: int = 15
    edd_swap_tolerance: int = 5
    interleave_enabled: bool = True
    jit_threshold: float = 95.0
    jit_buffer_pct: float = 0.05
    edd_assign_threshold: int = 5


class CachedPipeline:
    """Delta-evaluation wrapper over the existing scheduler pipeline."""

    def __init__(self, engine_data: EngineData, config: FactoryConfig):
        self.data = engine_data
        self.config = config
        self._lots: list[Lot] | None = None
        self._runs_cache: dict[tuple[int, int], list[ToolRun]] = {}
        self._fitness_cache: dict[str, tuple[dict, ScheduleResult]] = {}
        self.eval_count = 0
        self.cache_hits = 0

    def _get_lots(self) -> list[Lot]:
        """Lots are gene-independent (cached once)."""
        if self._lots is None:
            self._lots = create_lots(self.data, config=self.config)
        return self._lots

    def _get_runs(self, edd_gap: int, max_edd_span: int) -> list[ToolRun]:
        """Tool runs cached by (edd_gap, max_edd_span)."""
        key = (edd_gap, max_edd_span)
        if key not in self._runs_cache:
            lots = copy.deepcopy(self._get_lots())
            params = _ParamsProxy(max_edd_gap=edd_gap, max_edd_span=max_edd_span)
            self._runs_cache[key] = create_tool_runs(lots, params=params, config=self.config)
        return self._runs_cache[key]

    def evaluate(self, chrom: Chromosome) -> ScheduleResult:
        """Full pipeline evaluation for a chromosome."""
        h = chrom.compute_hash()
        if h in self._fitness_cache:
            self.cache_hits += 1
            return self._fitness_cache[h][1]

        self.eval_count += 1

        # Phase 1+2: lots + tool runs (cached)
        runs = copy.deepcopy(self._get_runs(chrom.edd_gap, chrom.max_edd_span))

        # Phase 3a: Machine assignment (G3 override)
        machine_runs = self._assign_with_choices(runs, chrom.machine_choice)

        # Phase 3b: Sequencing (G4 keys + G6 campaign window)
        machine_runs = self._sequence_with_chromosome(machine_runs, chrom)

        # Auto buffer detection
        from backend.scheduler.scheduler import _detect_buffer_need, _apply_buffer, _shift_engine_data
        global_holidays = set(self.data.holidays) if self.data.holidays else set()
        buffer_days = _detect_buffer_need(runs, config=self.config, machine_runs=machine_runs, holidays=global_holidays)

        data = self.data
        if buffer_days > 0:
            _apply_buffer(runs, buffer_days)
            data = _shift_engine_data(data, buffer_days)
            global_holidays = set(data.holidays) if data.holidays else set()
            machine_runs = self._assign_with_choices(runs, chrom.machine_choice)
            machine_runs = self._sequence_with_chromosome(machine_runs, chrom)

        # Phase 3c: Dispatch
        segments, lots, warnings = per_machine_dispatch(machine_runs, data, config=self.config)

        # Baseline score
        baseline_score = compute_score(segments, lots, data, config=self.config)

        # Phase 4: JIT
        jit_machine_runs = None
        jit_gates = None
        if self.config.jit_enabled and baseline_score["otd"] >= self.config.jit_threshold:
            params = _ParamsProxy(jit_buffer_pct=chrom.buffer_pct)
            jit_segs, jit_lots, jit_warnings, jit_machine_runs, jit_gates = jit_dispatch(
                runs, data, segments, lots, baseline_score,
                params=params, config=self.config,
            )
            segments = jit_segs
            lots = jit_lots
            warnings.extend(jit_warnings)

        # Phase 4b: VNS
        if self.config.vns_enabled and jit_machine_runs is not None and jit_gates is not None:
            from backend.scheduler.vns import vns_polish
            jit_score = compute_score(segments, lots, data, config=self.config)
            vns_segs, vns_lots, vns_score, vns_warnings = vns_polish(
                jit_machine_runs, jit_gates, data, self.config,
                segments, lots, jit_score,
            )
            if (vns_score["setups"] < jit_score["setups"]
                    or vns_score["earliness_avg_days"] < jit_score["earliness_avg_days"]):
                segments = vns_segs
                lots = vns_lots
            warnings.extend(vns_warnings)

        # Unshift buffer
        if buffer_days > 0:
            from backend.scheduler.scheduler import _unshift_segments, _unshift_lots
            segments = _unshift_segments(segments, buffer_days)
            lots = _unshift_lots(lots, buffer_days)
            data = _shift_engine_data(data, -buffer_days)

        # Post-processing
        from backend.scheduler.scheduler import (
            _fix_day_overlaps,
            _serialize_crew_setups,
            _sanitize_segments,
        )
        global_holidays = set(getattr(data, "holidays", []))
        segments = _fix_day_overlaps(segments, self.config, holidays=global_holidays)

        # Crew serialization (safe — revert if tardy worsens)
        pre_crew_score = compute_score(segments, lots, data, config=self.config)
        crew_segments = copy.deepcopy(segments)
        for _ in range(20):
            crew_segments = _serialize_crew_setups(crew_segments, self.config, holidays=global_holidays, crew_priority=chrom.crew_priority)
            crew_segments = _fix_day_overlaps(crew_segments, self.config, holidays=global_holidays)
            crew_segments = _sanitize_segments(crew_segments, self.config, holidays=global_holidays)
        crew_score = compute_score(crew_segments, lots, data, config=self.config)
        if crew_score["tardy_count"] <= pre_crew_score["tardy_count"]:
            segments = crew_segments

        segments = _sanitize_segments(segments, self.config, holidays=global_holidays)

        # Final score
        score = compute_score(segments, lots, data, config=self.config)

        # Day capacity violation count (for fitness penalty)
        day_cap = self.config.day_capacity_min if self.config else DAY_CAP
        day_used: dict[tuple[str, int], float] = defaultdict(float)
        for seg in segments:
            if seg.day_idx >= 0:
                day_used[(seg.machine_id, seg.day_idx)] += seg.prod_min + seg.setup_min
        day_cap_violations = sum(
            1 for total in day_used.values() if total > day_cap + 1.0
        )
        score["day_cap_violations"] = day_cap_violations

        # Weighted setup cost: setup_min × machine utilisation
        machine_total_used: dict[str, float] = {}
        for (m_id, _day), total in day_used.items():
            machine_total_used[m_id] = machine_total_used.get(m_id, 0.0) + total
        n_holidays = len(set(getattr(data, "holidays", []) or []))
        n_work_days = max(data.n_days - n_holidays, 1)
        total_available = float(n_work_days * day_cap)

        weighted_setup_cost = 0.0
        for seg in segments:
            if seg.setup_min > 0 and seg.day_idx >= 0:
                used = machine_total_used.get(seg.machine_id, 0.0)
                util = used / total_available if total_available > 0 else 0.5
                weighted_setup_cost += seg.setup_min * min(util, 1.0)
        score["weighted_setup_cost"] = weighted_setup_cost

        result = ScheduleResult(
            segments=segments,
            lots=lots,
            score=score,
            time_ms=0.0,
            warnings=warnings,
            operator_alerts=[],
        )

        self._fitness_cache[h] = (score, result)
        return result

    def _assign_with_choices(
        self, runs: list[ToolRun], choices: dict[int, int]
    ) -> dict[str, list[ToolRun]]:
        """Machine assignment using chromosome's G3 gene.

        For runs with alt_machine_id, use choices[run_idx] to decide.
        For runs without alt, go to primary.
        """
        if not choices:
            return assign_machines(runs, self.data, config=self.config)

        machine_runs: dict[str, list[ToolRun]] = defaultdict(list)

        for idx, run in enumerate(runs):
            if run.alt_machine_id is None:
                machine_runs[run.machine_id].append(run)
            else:
                choice = choices.get(idx, 0)
                if choice == 1:
                    machine_runs[run.alt_machine_id].append(run)
                else:
                    machine_runs[run.machine_id].append(run)

        return dict(machine_runs)

    def _sequence_with_chromosome(
        self, machine_runs: dict[str, list[ToolRun]], chrom: Chromosome
    ) -> dict[str, list[ToolRun]]:
        """Apply chromosome's G4 sequence keys, then use campaign sequencing with G6."""
        # First apply G4 sort keys to reorder runs per machine
        for m_id, m_runs in machine_runs.items():
            keys = chrom.sequence_keys.get(m_id)
            if keys and len(keys) == len(m_runs):
                # Sort runs by their chromosome keys
                paired = sorted(zip(keys, m_runs), key=lambda x: x[0])
                machine_runs[m_id] = [run for _, run in paired]

        # Then apply campaign sequencing with G6 window
        params = _ParamsProxy(campaign_window=chrom.campaign_window)
        machine_runs = sequence_per_machine(machine_runs, params=params, config=self.config)
        return machine_runs

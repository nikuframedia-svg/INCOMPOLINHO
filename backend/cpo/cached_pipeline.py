"""Offline CachedPipeline for CPO v4 tuning — Delta evaluation wrapper.

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

from backend.calendar import total_machine_capacity
from backend.config.types import FactoryConfig
from backend.cpo.chromosome import Chromosome
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.dispatch import (
    _campaign_sequence,
    _interleave_urgent,
    _two_opt,
    assign_machines,
    per_machine_dispatch,
    sequence_per_machine,
)
from backend.scheduler.jit import jit_dispatch
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.priority import (
    delivery_improves,
    delivery_not_worse,
    enforce_same_deadline_run_priority,
)
from backend.scheduler.resources import rebind_runs_to_machines
from backend.scheduler.scoring import compute_score
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, ScheduleResult, ToolRun
from backend.scheduler.validation import validate_plan
from backend.types import EngineData

logger = logging.getLogger(__name__)


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
            cfg = copy.copy(self.config)
            cfg.max_edd_gap = edd_gap
            cfg.max_edd_span = max_edd_span
            self._runs_cache[key] = create_tool_runs(
                lots,
                config=cfg,
                release_holidays=calendar_holidays(
                    self.data,
                    -14,
                    self.data.n_days + 30,
                ),
            )
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
        from backend.scheduler.scheduler import (
            _apply_buffer,
            _detect_buffer_need,
            _shift_engine_data,
        )

        global_holidays = set(self.data.holidays) if self.data.holidays else set()
        buffer_days = (
            _detect_buffer_need(
                runs,
                config=self.config,
                machine_runs=machine_runs,
                holidays=global_holidays,
            )
            if self.config.auto_buffer
            else 0
        )

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

        # Phase 4: timing policy (JIT or materials window)
        jit_machine_runs = None
        jit_gates = None
        if self.config.jit_enabled:
            jit_cfg = copy.copy(self.config)
            jit_cfg.jit_buffer_pct = chrom.buffer_pct
            _phase4_dispatch = jit_dispatch
            jit_segs, jit_lots, jit_warnings, jit_machine_runs, jit_gates = _phase4_dispatch(
                runs,
                data,
                segments,
                lots,
                baseline_score,
                config=jit_cfg,
            )
            segments = jit_segs
            lots = jit_lots
            warnings.extend(jit_warnings)

        # Phase 4b: VNS
        if self.config.vns_enabled and jit_machine_runs is not None and jit_gates is not None:
            from backend.scheduler.vns import vns_polish

            jit_score = compute_score(segments, lots, data, config=self.config)
            vns_segs, vns_lots, vns_score, vns_warnings = vns_polish(
                jit_machine_runs,
                jit_gates,
                data,
                self.config,
                segments,
                lots,
                jit_score,
            )
            vns_latest_start_gap = float(
                vns_score.get("latest_start_gap_avg_min", 0.0) or 0.0
            )
            jit_latest_start_gap = float(
                jit_score.get("latest_start_gap_avg_min", 0.0) or 0.0
            )
            if delivery_improves(vns_score, jit_score) or (
                delivery_not_worse(vns_score, jit_score)
                and (
                    vns_latest_start_gap > jit_latest_start_gap
                    or (
                        vns_latest_start_gap == jit_latest_start_gap
                        and vns_score["setups"] < jit_score["setups"]
                    )
                )
            ):
                segments = vns_segs
                lots = vns_lots
            warnings.extend(vns_warnings)

        # Unshift buffer
        if buffer_days > 0:
            from backend.scheduler.scheduler import _unshift_lots, _unshift_segments

            segments = _unshift_segments(segments, buffer_days)
            lots = _unshift_lots(lots, buffer_days)
            data = _shift_engine_data(data, -buffer_days)

        # Post-processing
        from backend.scheduler.scheduler import (
            _fix_day_overlaps,
            _sanitize_segments,
            _serialize_crew_safe,
            _serialize_crew_setups,
        )

        global_holidays = set(getattr(data, "holidays", []))
        segments = _fix_day_overlaps(segments, self.config, holidays=global_holidays)

        # Crew serialization (safe — revert if delivery priority worsens)
        pre_crew_score = compute_score(segments, lots, data, config=self.config)
        crew_segments = copy.deepcopy(segments)
        prev_hash = None
        for _ in range(10):  # max 10 passes (convergence typically in 2-3)
            crew_segments = _serialize_crew_setups(
                crew_segments,
                self.config,
                holidays=global_holidays,
                crew_priority=chrom.crew_priority,
            )
            crew_segments = _fix_day_overlaps(crew_segments, self.config, holidays=global_holidays)
            crew_segments = _sanitize_segments(crew_segments, self.config, holidays=global_holidays)
            curr_hash = hash(
                tuple((s.lot_id, s.day_idx, s.start_min, s.end_min) for s in crew_segments)
            )
            if curr_hash == prev_hash:
                break
            prev_hash = curr_hash
        crew_score = compute_score(crew_segments, lots, data, config=self.config)
        if delivery_not_worse(crew_score, pre_crew_score):
            segments = crew_segments
        else:
            # EDD-safe fallback: per-overlap resolution
            safe_segments = copy.deepcopy(segments)
            prev_hash_s = None
            for _ in range(10):
                safe_segments = _serialize_crew_safe(
                    safe_segments,
                    self.config,
                    holidays=global_holidays,
                    crew_priority=chrom.crew_priority,
                )
                safe_segments = _fix_day_overlaps(
                    safe_segments, self.config, holidays=global_holidays
                )
                safe_segments = _sanitize_segments(
                    safe_segments, self.config, holidays=global_holidays
                )
                curr_hash_s = hash(
                    tuple((s.lot_id, s.day_idx, s.start_min, s.end_min) for s in safe_segments)
                )
                if curr_hash_s == prev_hash_s:
                    break
                prev_hash_s = curr_hash_s
            safe_score = compute_score(safe_segments, lots, data, config=self.config)
            if delivery_not_worse(safe_score, pre_crew_score):
                segments = safe_segments

        segments = _sanitize_segments(segments, self.config, holidays=global_holidays)

        # Final score
        score = compute_score(segments, lots, data, config=self.config)
        score["buffer_days"] = buffer_days
        score["_earliness_target"] = self.config.jit_earliness_target if self.config else 5.5

        # Day capacity violation count (for fitness penalty)
        # Use actual segment span (end - start) to account for shift gaps
        day_cap = self.config.day_capacity_min if self.config else DAY_CAP
        day_span: dict[tuple[str, int], float] = defaultdict(float)
        for seg in segments:
            if seg.day_idx >= 0:
                day_span[(seg.machine_id, seg.day_idx)] += seg.end_min - seg.start_min
        day_cap_violations = sum(1 for total in day_span.values() if total > day_cap + 1.0)
        score["day_cap_violations"] = day_cap_violations
        score["hard_violations"] = max(
            int(score.get("hard_violations", 0) or 0),
            len(validate_plan(segments, data, self.config)),
        )

        # Weighted setup cost: setup_min × machine utilisation
        machine_total_used: dict[str, float] = {}
        for (m_id, _day), total in day_span.items():
            machine_total_used[m_id] = machine_total_used.get(m_id, 0.0) + total
        total_available_by_machine = {
            machine.id: float(
                total_machine_capacity(
                    machine.id,
                    range(data.n_days),
                    data,
                    self.config,
                )
            )
            for machine in data.machines
        }

        weighted_setup_cost = 0.0
        for seg in segments:
            if seg.setup_min > 0 and seg.day_idx >= 0:
                used = machine_total_used.get(seg.machine_id, 0.0)
                total_available = total_available_by_machine.get(seg.machine_id, 0.0)
                util = used / total_available if total_available > 0 else 0.5
                weighted_setup_cost += seg.setup_min * min(util, 1.0)
        score["weighted_setup_cost"] = weighted_setup_cost

        from backend.scheduler.operators import compute_operator_alerts

        op_alerts = compute_operator_alerts(segments, self.data, config=self.config)

        result = ScheduleResult(
            segments=segments,
            lots=lots,
            score=score,
            time_ms=0.0,
            warnings=warnings,
            operator_alerts=op_alerts,
            machine_runs=copy.deepcopy(machine_runs),
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

        rebind_runs_to_machines(machine_runs, self.data, self.config)
        return dict(machine_runs)

    def _sequence_with_chromosome(
        self, machine_runs: dict[str, list[ToolRun]], chrom: Chromosome
    ) -> dict[str, list[ToolRun]]:
        """Apply chromosome's G4 sequence keys, then use campaign sequencing with G6."""
        keyed_machines: set[str] = set()
        seq_cfg = copy.copy(self.config)
        seq_cfg.campaign_window = chrom.campaign_window

        # First apply G4 sort keys to reorder runs per machine. For keyed
        # machines, keep that order as the baseline and run campaign heuristics
        # without the EDD pre-sort in sequence_per_machine().
        for m_id, m_runs in machine_runs.items():
            keys = chrom.sequence_keys.get(m_id)
            if keys and len(keys) == len(m_runs):
                paired = sorted(zip(keys, m_runs), key=lambda x: x[0])
                ordered = [run for _, run in paired]
                ordered = _campaign_sequence(ordered, config=seq_cfg)
                if seq_cfg.interleave_enabled:
                    ordered = _interleave_urgent(ordered)
                machine_runs[m_id] = enforce_same_deadline_run_priority(
                    _two_opt(ordered, config=seq_cfg)
                )
                keyed_machines.add(m_id)

        remaining = {
            m_id: runs for m_id, runs in machine_runs.items() if m_id not in keyed_machines
        }
        if remaining:
            sequenced = sequence_per_machine(remaining, config=seq_cfg)
            machine_runs.update(sequenced)
        return machine_runs

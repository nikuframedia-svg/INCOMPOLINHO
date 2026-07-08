"""CPO v4 Optimizer — Trust-loop entry point.

Modes:
  quick  (~200ms): greedy/JIT/VNS baseline only (schedule_all passthrough)
  normal (seconds): baseline + local CP-SAT polish on difficult windows
  deep   (minutes): same operational loop with a larger CP-SAT local budget
  max    (minutes): same operational loop with the largest CP-SAT local budget

GA/MAP-Elites helpers remain in this module for offline tuning experiments, but
the operational optimizer does not call them. Production applies proposals only
after physical and delivery gates pass.
"""

from __future__ import annotations

import copy
import logging
import random
import time
from collections import defaultdict
from contextlib import contextmanager

from backend.config.types import FactoryConfig
from backend.cpo.cached_pipeline import CachedPipeline
from backend.cpo.chromosome import (
    OPERATORS,
    Chromosome,
    crossover_uniform,
)
from backend.cpo.population import (
    FRRMAB,
    MAPElitesArchive,
    OneFifthRule,
    tournament_select,
)
from backend.cpo.surrogate import SurrogateModel
from backend.scheduler.dispatch import assign_machines
from backend.scheduler.gates import HARD_GATE_KEYS, build_gate_report
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import ScheduleResult, Segment, ToolRun
from backend.scheduler.validation import (
    PlanValidationError,
    assert_plan_valid,
    segment_abs,
    validate_plan,
)
from backend.types import EngineData

logger = logging.getLogger(__name__)


# ─── Mode configurations ──────────────────────────────────────────────

MODE_CONFIG = {
    "quick": {"cp_sat": False, "cp_sat_time_per_machine": 0.0, "candidate_budget": 0},
    "normal": {
        "cp_sat": True,
        "cp_sat_time_per_machine": 2.0,
        "candidate_search": True,
        "candidate_budget": 48,
        "final_timing_polish_max_segments": 180,
    },
    "deep": {
        "cp_sat": True,
        "cp_sat_time_per_machine": 10.0,
        "candidate_search": True,
        "candidate_budget": 48,
        "final_timing_polish_max_segments": 320,
    },
    "max": {
        "cp_sat": True,
        "cp_sat_time_per_machine": 20.0,
        "candidate_search": True,
        "candidate_budget": 80,
        "final_timing_polish_max_segments": 0,
    },
}

TRUST_DELIVERY_KEYS = (
    "tardy_count",
    "otd_d_failures",
    "total_tardiness",
    "max_tardiness",
)
PRODUCTIVITY_EARLINESS_CEILING_DAYS = 6.5
DELIVERY_REPAIR_MAX_TARDY_COUNT = 4
DELIVERY_REPAIR_MAX_OTD_D_FAILURES = 4
DELIVERY_REPAIR_MIN_OTD = 98.0
DELIVERY_REPAIR_MIN_OTD_D = 98.0
DELIVERY_REPAIR_MAX_TOTAL_TARDINESS = 8
DELIVERY_REPAIR_MAX_TARDINESS = 3
SCORE_SNAPSHOT_KEYS = (
    "otd",
    "otd_d",
    "tardy_count",
    "otd_d_failures",
    "total_tardiness",
    "max_tardiness",
    "hard_violations",
    "setup_crew_overlaps",
    "machine_overlaps",
    "tool_conflicts",
    "day_cap_violations",
    "blocked_machine_segments",
    "blocked_tool_segments",
    "ghost_segments",
    "setups",
    "setup_time_min",
    "earliness_avg_days",
    "planning_penalty",
    "productivity_earliness_ceiling_days",
    "idle_capacity_min",
    "work_time_min",
    "machine_work_min",
    "bottleneck_machine",
)
DELTA_SCORE_KEYS = (
    "otd",
    "otd_d",
    "tardy_count",
    "otd_d_failures",
    "total_tardiness",
    "max_tardiness",
    "hard_violations",
    "setup_crew_overlaps",
    "machine_overlaps",
    "tool_conflicts",
    "day_cap_violations",
    "setups",
    "setup_time_min",
    "earliness_avg_days",
    "planning_penalty",
)


def optimize(
    engine_data: EngineData,
    mode: str = "normal",
    config: FactoryConfig | None = None,
    seed: int | None = 42,
    audit: bool = False,
) -> ScheduleResult:
    """CPO v4 trust-loop entry point.

    Returns:
        ScheduleResult with an executable local plan/proposal candidate.
        Never returns a physically invalid result or a delivery regression.
    """
    t0 = time.perf_counter()

    if config is None:
        config = FactoryConfig()

    if mode not in MODE_CONFIG:
        raise ValueError(f"Unknown mode: {mode}. Use: {list(MODE_CONFIG)}")

    cfg = MODE_CONFIG[mode]

    # Phase 0: Greedy baseline
    baseline = schedule_all(engine_data, audit=audit, config=config)
    _apply_score_policy(baseline, config)
    baseline_score = baseline.score

    if not baseline_score or not baseline.lots:
        _strip_score_policy(baseline)
        return baseline

    logger.info(
        "CPO v4 baseline: OTD=%.1f%%, setups=%d, earliness=%.1fd, tardy=%d",
        baseline_score.get("otd", 0),
        baseline_score.get("setups", 0),
        baseline_score.get("earliness_avg_days", 0),
        baseline_score.get("tardy_count", 0),
    )

    if mode == "quick":
        elapsed = (time.perf_counter() - t0) * 1000
        baseline.time_ms = round(elapsed, 1)
        _attach_solver_trace(
            baseline,
            _build_solver_trace(
                mode=mode,
                cfg=cfg,
                baseline=baseline,
                final=baseline,
                elapsed_ms=elapsed,
                final_source="baseline",
            ),
        )
        _strip_score_policy(baseline)
        return baseline

    best_result = baseline
    best_config = config
    final_source = "baseline"
    trusted_result = baseline if _is_fully_trusted_score(baseline.score or {}) else None
    trusted_config = config
    trusted_source = "baseline"
    decision_notes: list[str] = []
    candidate_search_trace: dict | None = None
    local_repair_decisions: list[dict] = []
    cp_sat_decisions: list[dict] = []

    if cfg.get("candidate_search"):
        best_result, best_config, shadow_notes, candidate_search_trace = (
            _run_shadow_candidate_search(
                engine_data,
                config,
                baseline,
                mode,
                candidate_budget=int(cfg.get("candidate_budget", 0) or 0),
            )
        )
        decision_notes.extend(shadow_notes)
        if best_result is not baseline:
            final_source = (
                str(candidate_search_trace.get("best_candidate"))
                if candidate_search_trace and candidate_search_trace.get("best_candidate")
                else "candidate_search"
            )
            logger.info(
                "CPO shadow candidate accepted before CP-SAT: OTD=%.1f%%, OTD-D=%.1f%%, tardy=%d",
                best_result.score.get("otd", 0),
                best_result.score.get("otd_d", 0),
                best_result.score.get("tardy_count", 0),
            )
        trusted_result, trusted_config, trusted_source = _remember_trusted_result(
            trusted_result,
            trusted_config,
            trusted_source,
            best_result,
            best_config,
            final_source,
        )

    repaired_result, repair_decision = _try_global_delay_earliness_repair(
        best_result,
        baseline,
        engine_data,
        best_config,
    )
    if repair_decision is not None:
        local_repair_decisions.append(repair_decision)
    if repaired_result is not best_result:
        decision_notes.append(
            "CPO local repair accepted: global suffix delay reduced earliness"
        )
        best_result = repaired_result
        final_source = "global_suffix_earliness_repair"
        trusted_result, trusted_config, trusted_source = _remember_trusted_result(
            trusted_result,
            trusted_config,
            trusted_source,
            best_result,
            best_config,
            final_source,
        )

    if not cfg["cp_sat"]:
        timing_polished_result, timing_polish_decision = _try_final_jit_timing_polish(
            best_result,
            baseline,
            engine_data,
            best_config,
            max_segments=int(cfg.get("final_timing_polish_max_segments", 0) or 0),
        )
        if timing_polish_decision is not None:
            local_repair_decisions.append(timing_polish_decision)
        if timing_polished_result is not best_result:
            decision_notes.append("CPO local repair accepted: final JIT timing polish")
            best_result = timing_polished_result
            final_source = "final_jit_timing_polish"
            trusted_result, trusted_config, trusted_source = _remember_trusted_result(
                trusted_result,
                trusted_config,
                trusted_source,
                best_result,
                best_config,
                final_source,
            )

        elapsed = (time.perf_counter() - t0) * 1000
        best_result.time_ms = round(elapsed, 1)
        if decision_notes:
            best_result.warnings.extend(decision_notes)
        _attach_solver_trace(
            best_result,
            _build_solver_trace(
                mode=mode,
                cfg=cfg,
                baseline=baseline,
                final=best_result,
                elapsed_ms=elapsed,
                final_source=final_source,
                candidate_search_trace=candidate_search_trace,
                local_repair_decisions=local_repair_decisions,
            ),
        )
        _strip_score_policy(best_result)
        return best_result

    # CP-SAT polish on local/bottleneck windows. It is advisory: keep it only if
    # it preserves physical validity, delivery, and the score frontier.
    try:
        from backend.cpo.cpsat_polish import cpsat_polish

        if cfg["cp_sat"]:
            polish_machine_runs = _build_local_machine_runs(engine_data, best_config)
            with _quiet_advisory_solver_logs():
                polished_segs, polished_lots, polished_score = cpsat_polish(
                    best_result.segments,
                    best_result.lots,
                    polish_machine_runs,
                    engine_data,
                    best_config,
                    time_limit_per_machine=cfg["cp_sat_time_per_machine"],
                )
            assert_plan_valid(polished_segs, engine_data, best_config)
            polished_candidate = ScheduleResult(
                segments=polished_segs,
                lots=polished_lots,
                score=polished_score,
                time_ms=0.0,
                warnings=list(best_result.warnings),
                operator_alerts=best_result.operator_alerts,
                journal=baseline.journal,
                machine_runs=polish_machine_runs,
            )
            _apply_score_policy(polished_candidate, best_config)
            if _is_better_candidate(polished_candidate, best_result):
                cp_sat_decisions.append(
                    _candidate_decision(
                        "local_cp_sat_polish",
                        "accepted",
                        "trust-rank improvement",
                        {},
                        None,
                        polished_candidate,
                        best_result,
                        baseline,
                    )
                )
                polished_score["buffer_days"] = best_result.score.get("buffer_days", 0)
                polished_candidate.score = polished_score
                best_result = polished_candidate
                final_source = "local_cp_sat_polish"
                trusted_result, trusted_config, trusted_source = _remember_trusted_result(
                    trusted_result,
                    trusted_config,
                    trusted_source,
                    best_result,
                    best_config,
                    final_source,
                )
                decision_notes.append("CPO candidate accepted: local CP-SAT polish")
            else:
                cp_sat_decisions.append(
                    _candidate_decision(
                        "local_cp_sat_polish",
                        "rejected",
                        _candidate_rejection_reason(polished_candidate, best_result),
                        {},
                        None,
                        polished_candidate,
                        best_result,
                        baseline,
                    )
                )
                decision_notes.append(
                    "CPO candidate rejected: local CP-SAT polish failed trust ranking"
                )
    except (ImportError, RuntimeError, TimeoutError, ValueError, PlanValidationError) as e:
        logger.debug("CP-SAT polish skipped/rejected: %s", e)
        cp_sat_decisions.append(
            _candidate_error_decision("local_cp_sat_polish", {}, None, e)
        )

    timing_polished_result, timing_polish_decision = _try_final_jit_timing_polish(
        best_result,
        baseline,
        engine_data,
        best_config,
        max_segments=int(cfg.get("final_timing_polish_max_segments", 0) or 0),
    )
    if timing_polish_decision is not None:
        local_repair_decisions.append(timing_polish_decision)
    if timing_polished_result is not best_result:
        decision_notes.append("CPO local repair accepted: final JIT timing polish")
        best_result = timing_polished_result
        final_source = "final_jit_timing_polish"
        trusted_result, trusted_config, trusted_source = _remember_trusted_result(
            trusted_result,
            trusted_config,
            trusted_source,
            best_result,
            best_config,
            final_source,
        )

    if validate_plan(best_result.segments, engine_data, best_config):
        logger.warning("CPO candidate invalid after local polish — reverting to trusted plan")
        if trusted_result is not None:
            best_result = trusted_result
            best_config = trusted_config
            final_source = f"trusted_revert_invalid_physics_from_{trusted_source}"
        else:
            best_result = baseline
            best_config = config
            final_source = "baseline_revert_invalid_physics"

    if trusted_result is not None and not _is_fully_trusted_score(best_result.score or {}):
        logger.warning("CPO final result failed delivery trust — reverting to trusted plan")
        best_result = trusted_result
        best_config = trusted_config
        final_source = f"trusted_revert_delivery_from_{trusted_source}"

    # Safety: never return worse than baseline.
    if not _preserves_trust(best_result, baseline):
        logger.warning("CPO local result worse than baseline — reverting to baseline")
        best_result = baseline
        best_config = config
        final_source = "baseline_revert_trust_regression"

    elapsed = (time.perf_counter() - t0) * 1000
    best_result.time_ms = round(elapsed, 1)

    # Propagate journal from baseline (local polish does not generate its own).
    if not best_result.journal and baseline.journal:
        best_result.journal = baseline.journal

    if decision_notes:
        best_result.warnings.extend(decision_notes)

    assert_plan_valid(best_result.segments, engine_data, best_config)
    best_result.gate_report = build_gate_report(
        best_result.segments,
        best_result.lots,
        best_result.score,
        engine_data,
        best_config,
    )
    _attach_solver_trace(
        best_result,
        _build_solver_trace(
            mode=mode,
            cfg=cfg,
            baseline=baseline,
            final=best_result,
            elapsed_ms=elapsed,
            final_source=final_source,
            candidate_search_trace=candidate_search_trace,
            local_repair_decisions=local_repair_decisions,
            cp_sat_decisions=cp_sat_decisions,
        ),
    )

    logger.info(
        "CPO %s: OTD=%.1f%%, setups=%d, earliness=%.1fd, tardy=%d (%.1fs)",
        mode,
        best_result.score.get("otd", 0),
        best_result.score.get("setups", 0),
        best_result.score.get("earliness_avg_days", 0),
        best_result.score.get("tardy_count", 0),
        elapsed / 1000,
    )

    _strip_score_policy(best_result)
    return best_result


def _run_shadow_candidate_search(
    engine_data: EngineData,
    base_config: FactoryConfig,
    baseline: ScheduleResult,
    mode: str,
    candidate_budget: int = 0,
) -> tuple[ScheduleResult, FactoryConfig, list[str], dict]:
    """Try small operational variants and keep only trust-preserving wins."""

    best_result = baseline
    best_config = base_config
    notes: list[str] = []
    accepted = 0
    evaluated = 0
    skipped_by_budget = 0

    candidates = _candidate_configs(
        base_config,
        mode,
        engine_data,
    )
    budget = candidate_budget if candidate_budget > 0 else len(candidates)
    trace: dict = {
        "mode": mode,
        "budget": budget,
        "total_candidates": len(candidates),
        "evaluated": 0,
        "accepted": 0,
        "rejected": 0,
        "errored": 0,
        "skipped_by_budget": 0,
        "delivery_repairs_skipped": 0,
        "best_candidate": None,
        "best_rejected_productivity": None,
        "best_non_applied_productivity": None,
        "trusted_productivity_frontier": [],
        "near_applicable_productivity_frontier": [],
        "decisions": [],
    }

    for idx, (name, candidate_config, changes, crew_priority) in enumerate(candidates):
        if evaluated >= budget:
            skipped_by_budget = len(candidates) - idx
            break
        evaluated += 1
        try:
            with _quiet_advisory_solver_logs():
                candidate = schedule_all(
                    copy.deepcopy(engine_data),
                    audit=False,
                    config=candidate_config,
                    crew_priority=crew_priority,
                )
            _apply_score_policy(candidate, candidate_config)
            assert_plan_valid(candidate.segments, engine_data, candidate_config)
            candidate_repair: dict | None = None
            delivery_repair_decision = _delivery_repair_triage(candidate, best_result)
            if delivery_repair_decision["decision"] == "attempt":
                candidate, delivery_repair = _try_delivery_left_shift_repair(
                    candidate,
                    engine_data,
                    candidate_config,
                )
                candidate_repair = _append_local_repair_decision(
                    candidate_repair,
                    delivery_repair,
                )
            elif delivery_repair_decision["decision"] == "skipped":
                trace["delivery_repairs_skipped"] += 1
                candidate_repair = _append_local_repair_decision(
                    candidate_repair,
                    delivery_repair_decision,
                )
            candidate, earliness_repair = _try_global_delay_earliness_repair(
                candidate,
                baseline,
                engine_data,
                candidate_config,
            )
            candidate_repair = _append_local_repair_decision(
                candidate_repair,
                earliness_repair,
            )
        except (RuntimeError, ValueError, PlanValidationError) as exc:
            notes.append(f"CPO candidate rejected: {name} errored ({exc})")
            trace["errored"] += 1
            trace["decisions"].append(
                _candidate_error_decision(name, changes, crew_priority, exc)
            )
            continue

        if _is_better_candidate(candidate, best_result) and _preserves_trust(
            candidate, baseline
        ):
            previous_best = best_result
            trace["decisions"].append(
                _candidate_decision(
                    name,
                    "accepted",
                    "trust-rank improvement",
                    changes,
                    crew_priority,
                    candidate,
                    best_result,
                    baseline,
                    candidate_repair,
                )
            )
            notes.append(
                "CPO candidate accepted: "
                f"{name} ({_summarize_score(best_result.score)} -> "
                f"{_summarize_score(candidate.score)})"
            )
            best_result = candidate
            best_config = candidate_config
            accepted += 1
            trace["accepted"] += 1
            trace["best_candidate"] = name

            setup_result, setup_config, setup_decision = _try_lns_setup_frontier_candidate(
                source_name=name,
                source_candidate=candidate,
                source_config=candidate_config,
                source_changes=changes,
                crew_priority=crew_priority,
                engine_data=engine_data,
                incumbent=best_result,
                baseline=baseline,
            )
            if setup_decision is not None:
                if (
                    setup_result is not None
                    and setup_config is not None
                    and setup_decision.get("decision") == "accepted"
                ):
                    notes.append(
                        "CPO candidate accepted: "
                        f"{setup_decision['name']} ({_summarize_score(best_result.score)} -> "
                        f"{_summarize_score(setup_result.score)})"
                    )
                    best_result = setup_result
                    best_config = setup_config
                    accepted += 1
                    trace["accepted"] += 1
                    trace["best_candidate"] = str(setup_decision.get("name"))
                elif setup_decision.get("decision") == "errored":
                    trace["errored"] += 1
                else:
                    trace["rejected"] += 1
                    if setup_result is not None:
                        _record_productivity_frontier_miss(
                            trace,
                            setup_decision,
                            setup_result,
                            previous_best,
                        )
                trace["decisions"].append(setup_decision)
        else:
            reason = _candidate_rejection_reason(candidate, best_result)
            decision = _candidate_decision(
                name,
                "rejected",
                reason,
                changes,
                crew_priority,
                candidate,
                best_result,
                baseline,
                candidate_repair,
            )
            _record_productivity_frontier_miss(trace, decision, candidate, best_result)
            notes.append(
                "CPO candidate rejected: "
                f"{name} ({reason}; changes={_format_changes(changes)})"
            )
            trace["rejected"] += 1
            trace["decisions"].append(decision)

            lns_result, lns_config, lns_decision = _try_lns_split_repair_candidate(
                source_name=name,
                source_candidate=candidate,
                source_config=candidate_config,
                source_changes=changes,
                crew_priority=crew_priority,
                engine_data=engine_data,
                incumbent=best_result,
                baseline=baseline,
            )
            if lns_decision is not None:
                if (
                    lns_result is not None
                    and lns_config is not None
                    and lns_decision.get("decision") == "accepted"
                ):
                    notes.append(
                        "CPO candidate accepted: "
                        f"{lns_decision['name']} ({_summarize_score(best_result.score)} -> "
                        f"{_summarize_score(lns_result.score)})"
                    )
                    best_result = lns_result
                    best_config = lns_config
                    accepted += 1
                    trace["accepted"] += 1
                    trace["best_candidate"] = str(lns_decision.get("name"))
                elif lns_decision.get("decision") == "errored":
                    trace["errored"] += 1
                else:
                    trace["rejected"] += 1
                    if lns_result is not None:
                        _record_productivity_frontier_miss(
                            trace,
                            lns_decision,
                            lns_result,
                            best_result,
                        )
                trace["decisions"].append(lns_decision)

            setup_result, setup_config, setup_decision = _try_lns_setup_frontier_candidate(
                source_name=name,
                source_candidate=candidate,
                source_config=candidate_config,
                source_changes=changes,
                crew_priority=crew_priority,
                engine_data=engine_data,
                incumbent=best_result,
                baseline=baseline,
            )
            if setup_decision is not None:
                if (
                    setup_result is not None
                    and setup_config is not None
                    and setup_decision.get("decision") == "accepted"
                ):
                    notes.append(
                        "CPO candidate accepted: "
                        f"{setup_decision['name']} ({_summarize_score(best_result.score)} -> "
                        f"{_summarize_score(setup_result.score)})"
                    )
                    best_result = setup_result
                    best_config = setup_config
                    accepted += 1
                    trace["accepted"] += 1
                    trace["best_candidate"] = str(setup_decision.get("name"))
                elif setup_decision.get("decision") == "errored":
                    trace["errored"] += 1
                else:
                    trace["rejected"] += 1
                    if setup_result is not None:
                        _record_productivity_frontier_miss(
                            trace,
                            setup_decision,
                            setup_result,
                            best_result,
                        )
                trace["decisions"].append(setup_decision)

            combo_candidates = _try_lns_pareto_combo_candidates(
                source_name=name,
                source_candidate=candidate,
                source_config=candidate_config,
                source_changes=changes,
                anchor_decision=setup_decision,
                crew_priority=crew_priority,
                engine_data=engine_data,
                incumbent=best_result,
                baseline=baseline,
            )
            for combo_result, combo_config, combo_decision in combo_candidates:
                if combo_decision is None:
                    continue
                if (
                    combo_result is not None
                    and combo_config is not None
                    and combo_decision.get("decision") == "accepted"
                    and _is_better_candidate(combo_result, best_result)
                    and _preserves_trust(combo_result, baseline)
                ):
                    notes.append(
                        "CPO candidate accepted: "
                        f"{combo_decision['name']} ({_summarize_score(best_result.score)} -> "
                        f"{_summarize_score(combo_result.score)})"
                    )
                    best_result = combo_result
                    best_config = combo_config
                    accepted += 1
                    trace["accepted"] += 1
                    trace["best_candidate"] = str(combo_decision.get("name"))
                elif combo_decision.get("decision") == "errored":
                    trace["errored"] += 1
                else:
                    trace["rejected"] += 1
                    if combo_result is not None:
                        _record_productivity_frontier_miss(
                            trace,
                            combo_decision,
                            combo_result,
                            best_result,
                        )
                trace["decisions"].append(combo_decision)

            safe_result, safe_config, safe_decision = _try_lns_safe_combo_candidate(
                source_name=name,
                source_candidate=candidate,
                source_config=candidate_config,
                source_changes=changes,
                crew_priority=crew_priority,
                engine_data=engine_data,
                incumbent=best_result,
                baseline=baseline,
            )
            if safe_decision is not None:
                if (
                    safe_result is not None
                    and safe_config is not None
                    and safe_decision.get("decision") == "accepted"
                ):
                    notes.append(
                        "CPO candidate accepted: "
                        f"{safe_decision['name']} ({_summarize_score(best_result.score)} -> "
                        f"{_summarize_score(safe_result.score)})"
                    )
                    best_result = safe_result
                    best_config = safe_config
                    accepted += 1
                    trace["accepted"] += 1
                    trace["best_candidate"] = str(safe_decision.get("name"))
                elif safe_decision.get("decision") == "errored":
                    trace["errored"] += 1
                else:
                    trace["rejected"] += 1
                    if safe_result is not None:
                        _record_productivity_frontier_miss(
                            trace,
                            safe_decision,
                            safe_result,
                            best_result,
                        )
                trace["decisions"].append(safe_decision)

    notes.append(
        "CPO candidate search summary: "
        f"evaluated={evaluated}, accepted={accepted}, "
        f"budget={budget}, skipped_by_budget={skipped_by_budget}"
    )
    _reconcile_productivity_frontier_miss(trace, best_result)
    trace["evaluated"] = evaluated
    trace["accepted"] = accepted
    trace["skipped_by_budget"] = skipped_by_budget
    trace["frontier_exhausted"] = skipped_by_budget == 0
    trace["coverage_pct"] = (
        round(evaluated / len(candidates) * 100, 1) if candidates else 100.0
    )
    _summarize_non_applied_productivity(trace, best_result)
    _summarize_candidate_search_trace(trace)
    return best_result, best_config, notes, trace


def _remember_trusted_result(
    current_result: ScheduleResult | None,
    current_config: FactoryConfig,
    current_source: str,
    candidate: ScheduleResult,
    candidate_config: FactoryConfig,
    candidate_source: str,
) -> tuple[ScheduleResult | None, FactoryConfig, str]:
    """Keep the best known fully executable plan as final safety net."""

    if not _is_fully_trusted_score(candidate.score or {}):
        return current_result, current_config, current_source
    if current_result is None:
        return candidate, candidate_config, candidate_source
    if _trust_rank(candidate.score or {}) < _trust_rank(current_result.score or {}):
        return candidate, candidate_config, candidate_source
    return current_result, current_config, current_source


def _try_lns_split_repair_candidate(
    *,
    source_name: str,
    source_candidate: ScheduleResult,
    source_config: FactoryConfig,
    source_changes: dict[str, object],
    crew_priority: list[str] | None,
    engine_data: EngineData,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
) -> tuple[ScheduleResult | None, FactoryConfig | None, dict | None]:
    """Try a tiny LNS split/repair neighborhood around an early-stock frontier."""

    if source_name != "campaign_merge_frontier":
        return None, None, None
    source_score = source_candidate.score or {}
    if not _is_fully_trusted_score(source_score):
        return None, None, None
    if _earliness_excess(source_score) <= 0:
        return None, None, None
    if not _has_setup_productivity_gain(source_score, incumbent.score or {}):
        return None, None, None

    split_moves = _lns_split_moves_from_pressure(
        source_candidate,
        engine_data,
        source_config,
    )
    if not split_moves:
        return None, None, None

    best_result: ScheduleResult | None = None
    best_config: FactoryConfig | None = None
    best_decision: dict | None = None
    best_key: tuple[float, float, float, float] | None = None

    for split_count in (1, 3, 5):
        split_spec = _lns_split_spec(split_moves[:split_count])
        if not split_spec:
            continue

        candidate_name = f"lns_split_repair_{split_count}_for_{source_name}"
        trial, candidate_config, decision = _evaluate_lns_split_spec(
            candidate_name=candidate_name,
            source_config=source_config,
            source_changes=source_changes,
            split_spec=split_spec,
            crew_priority=crew_priority,
            engine_data=engine_data,
            incumbent=incumbent,
            baseline=baseline,
        )
        if decision is None:
            continue
        if decision.get("decision") == "errored":
            if best_decision is None:
                best_decision = decision
            continue
        if trial is None or candidate_config is None:
            continue
        if decision.get("decision") == "accepted":
            return trial, candidate_config, decision

        score = trial.score or {}
        key = (
            _earliness_excess(score),
            float(score.get("earliness_avg_days", 0.0) or 0.0),
            _setup_minutes(score),
            float(score.get("setups", 0) or 0),
        )
        if best_key is None or key < best_key:
            best_key = key
            best_result = trial
            best_config = candidate_config
            best_decision = decision

    return best_result, best_config, best_decision


def _try_lns_safe_combo_candidate(
    *,
    source_name: str,
    source_candidate: ScheduleResult,
    source_config: FactoryConfig,
    source_changes: dict[str, object],
    crew_priority: list[str] | None,
    engine_data: EngineData,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
) -> tuple[ScheduleResult | None, FactoryConfig | None, dict | None]:
    """Greedily compose only LNS split moves that keep full trust gates green."""

    if source_name != "campaign_merge_frontier":
        return None, None, None
    source_score = source_candidate.score or {}
    if not _is_fully_trusted_score(source_score):
        return None, None, None
    if _earliness_excess(source_score) <= 0:
        return None, None, None
    if not _has_setup_productivity_gain(source_score, incumbent.score or {}):
        return None, None, None

    split_moves = _lns_split_moves_from_pressure(
        source_candidate,
        engine_data,
        source_config,
        limit=10,
    )
    if not split_moves:
        return None, None, None

    screened: list[tuple[tuple[float, float, float], tuple[str, int]]] = []
    for move in split_moves:
        trial, _candidate_config, decision = _evaluate_lns_split_spec(
            candidate_name=f"lns_split_screen_for_{source_name}",
            source_config=source_config,
            source_changes=source_changes,
            split_spec=_lns_split_spec([move]),
            crew_priority=crew_priority,
            engine_data=engine_data,
            incumbent=incumbent,
            baseline=baseline,
            apply_earliness_repair=False,
        )
        if trial is None or decision is None:
            continue
        score = trial.score or {}
        if not _is_fully_trusted_score(score):
            continue
        if not _has_setup_productivity_gain(score, incumbent.score or {}):
            continue
        screened.append(
            (
                (
                    float(score.get("earliness_avg_days", 0.0) or 0.0),
                    _setup_minutes(score),
                    float(score.get("setups", 0) or 0),
                ),
                move,
            )
        )

    if not screened:
        return None, None, None

    current_spec: dict[str, list[int]] = {}
    current_score = source_score
    best_result: ScheduleResult | None = None
    best_config: FactoryConfig | None = None
    best_decision: dict | None = None
    candidate_name = f"lns_split_safe_combo_for_{source_name}"

    for _screen_key, move in sorted(screened, key=lambda item: item[0])[:6]:
        trial_spec = _merge_lns_split_specs(current_spec, _lns_split_spec([move]))
        if trial_spec == current_spec:
            continue
        trial, trial_config, decision = _evaluate_lns_split_spec(
            candidate_name=candidate_name,
            source_config=source_config,
            source_changes={
                **source_changes,
                "lns_screening": "greedy_trust_preserving_combo",
            },
            split_spec=trial_spec,
            crew_priority=crew_priority,
            engine_data=engine_data,
            incumbent=incumbent,
            baseline=baseline,
            apply_earliness_repair=False,
        )
        if trial is None or trial_config is None or decision is None:
            continue
        score = trial.score or {}
        if not _is_fully_trusted_score(score):
            continue
        if not _has_setup_productivity_gain(score, incumbent.score or {}):
            continue
        if float(score.get("earliness_avg_days", 0.0) or 0.0) >= float(
            current_score.get("earliness_avg_days", 0.0) or 0.0
        ):
            continue
        current_spec = trial_spec
        current_score = score
        best_result = trial
        best_config = trial_config
        best_decision = decision

    return best_result, best_config, best_decision


def _try_lns_setup_frontier_candidate(
    *,
    source_name: str,
    source_candidate: ScheduleResult,
    source_config: FactoryConfig,
    source_changes: dict[str, object],
    crew_priority: list[str] | None,
    engine_data: EngineData,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
) -> tuple[ScheduleResult | None, FactoryConfig | None, dict | None]:
    """Expose the most productive trusted split move, even when it needs approval.

    The safe-combo LNS candidate is ranked by earliness because it is the closest
    to the default apply envelope. This companion candidate keeps a second,
    productivity-first frontier visible for explicit approval or future repair.
    """

    if source_name != "campaign_merge_frontier":
        return None, None, None
    if not _is_fully_trusted_score(source_candidate.score or {}):
        return None, None, None

    split_moves = _lns_split_moves_from_pressure(
        source_candidate,
        engine_data,
        source_config,
        limit=10,
    )
    if not split_moves:
        return None, None, None

    best_result: ScheduleResult | None = None
    best_config: FactoryConfig | None = None
    best_decision: dict | None = None
    best_split_spec: dict[str, list[int]] | None = None
    best_key: tuple[float, float, float] | None = None
    candidate_name = f"lns_split_setup_frontier_for_{source_name}"

    for move in split_moves:
        split_spec = _lns_split_spec([move])
        trial, trial_config, decision = _evaluate_lns_split_spec(
            candidate_name=candidate_name,
            source_config=source_config,
            source_changes={
                **source_changes,
                "lns_screening": "trusted_setup_frontier",
            },
            split_spec=split_spec,
            crew_priority=crew_priority,
            engine_data=engine_data,
            incumbent=incumbent,
            baseline=baseline,
            apply_earliness_repair=False,
        )
        if decision is None:
            continue
        if decision.get("decision") == "errored":
            if best_decision is None:
                best_decision = decision
            continue
        if trial is None or trial_config is None:
            continue
        score = trial.score or {}
        if not _is_fully_trusted_score(score):
            continue
        if not _has_setup_productivity_gain(score, incumbent.score or {}):
            continue
        key = _productivity_frontier_key(score)
        if best_key is None or key < best_key:
            best_key = key
            best_result = trial
            best_config = trial_config
            best_decision = decision
            best_split_spec = split_spec

    if best_split_spec is None:
        return best_result, best_config, best_decision

    repaired_result, repaired_config, repaired_decision = _evaluate_lns_split_spec(
        candidate_name=candidate_name,
        source_config=source_config,
        source_changes={
            **source_changes,
            "lns_screening": "trusted_setup_frontier",
            "frontier_repair": "best_split_earliness_repair",
        },
        split_spec=best_split_spec,
        crew_priority=crew_priority,
        engine_data=engine_data,
        incumbent=incumbent,
        baseline=baseline,
        apply_earliness_repair=True,
    )
    if (
        repaired_result is not None
        and repaired_config is not None
        and repaired_decision is not None
        and _productivity_frontier_key(repaired_result.score or {})
        <= _productivity_frontier_key(best_result.score or {})
    ):
        return repaired_result, repaired_config, repaired_decision

    return best_result, best_config, best_decision


def _try_lns_pareto_combo_candidates(
    *,
    source_name: str,
    source_candidate: ScheduleResult,
    source_config: FactoryConfig,
    source_changes: dict[str, object],
    anchor_decision: dict | None,
    crew_priority: list[str] | None,
    engine_data: EngineData,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
) -> list[tuple[ScheduleResult | None, FactoryConfig | None, dict | None]]:
    """Explore a tiny split-combo Pareto neighborhood around the setup frontier."""

    if source_name != "campaign_merge_frontier":
        return []
    if not isinstance(anchor_decision, dict):
        return []
    anchor_spec = _normalise_lns_split_spec(
        (anchor_decision.get("changes") or {}).get("forced_run_split_spec")
    )
    anchor_moves = _split_moves_from_spec(anchor_spec)
    if not anchor_moves:
        return []
    source_score = source_candidate.score or {}
    if not _is_fully_trusted_score(source_score):
        return []
    if not _has_setup_productivity_gain(source_score, incumbent.score or {}):
        return []

    split_moves = _lns_split_moves_from_pressure(
        source_candidate,
        engine_data,
        source_config,
        limit=10,
    )
    anchor_set = set(anchor_moves)
    extension_moves = [move for move in split_moves if move not in anchor_set]
    if not extension_moves:
        return []

    evaluated: list[tuple[ScheduleResult | None, FactoryConfig | None, dict | None]] = []
    pair_results: list[tuple[tuple[float, float, float], list[tuple[str, int]]]] = []
    for move in _bounded_combo_extension_moves(extension_moves):
        moves = [*anchor_moves, move]
        result = _evaluate_lns_pareto_combo(
            combo_size=2,
            moves=moves,
            source_name=source_name,
            source_config=source_config,
            source_changes=source_changes,
            crew_priority=crew_priority,
            engine_data=engine_data,
            incumbent=incumbent,
            baseline=baseline,
        )
        evaluated.append(result)
        trial = result[0]
        if trial is None or not _is_fully_trusted_score(trial.score or {}):
            continue
        if not _has_setup_productivity_gain(trial.score or {}, incumbent.score or {}):
            continue
        score = trial.score or {}
        pair_results.append(
            (
                (
                    float(score.get("earliness_avg_days", 999.0) or 999.0),
                    _setup_minutes(score),
                    float(score.get("setups", 999.0) or 999.0),
                ),
                moves,
            )
        )

    if pair_results:
        pair_results.sort(key=lambda item: item[0])
        best_pair_moves = pair_results[0][1]
        best_pair_set = set(best_pair_moves)
        for move in _bounded_combo_extension_moves(extension_moves):
            if move in best_pair_set:
                continue
            evaluated.append(
                _evaluate_lns_pareto_combo(
                    combo_size=3,
                    moves=[*best_pair_moves, move],
                    source_name=source_name,
                    source_config=source_config,
                    source_changes=source_changes,
                    crew_priority=crew_priority,
                    engine_data=engine_data,
                    incumbent=incumbent,
                    baseline=baseline,
                )
            )

    return _pareto_lns_candidate_results(evaluated)[:4]


def _bounded_combo_extension_moves(
    moves: list[tuple[str, int]],
    head: int = 3,
    tail: int = 2,
) -> list[tuple[str, int]]:
    selected: list[tuple[str, int]] = []
    for move in [*moves[:head], *moves[-tail:]]:
        if move not in selected:
            selected.append(move)
    return selected


def _evaluate_lns_pareto_combo(
    *,
    combo_size: int,
    moves: list[tuple[str, int]],
    source_name: str,
    source_config: FactoryConfig,
    source_changes: dict[str, object],
    crew_priority: list[str] | None,
    engine_data: EngineData,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
) -> tuple[ScheduleResult | None, FactoryConfig | None, dict | None]:
    return _evaluate_lns_split_spec(
        candidate_name=f"lns_split_pareto_combo_{combo_size}_for_{source_name}",
        source_config=source_config,
        source_changes={
            **source_changes,
            "lns_screening": "bounded_pareto_combo",
            "combo_size": combo_size,
        },
        split_spec=_lns_split_spec(moves),
        crew_priority=crew_priority,
        engine_data=engine_data,
        incumbent=incumbent,
        baseline=baseline,
        apply_earliness_repair=True,
    )


def _pareto_lns_candidate_results(
    results: list[tuple[ScheduleResult | None, FactoryConfig | None, dict | None]]
) -> list[tuple[ScheduleResult | None, FactoryConfig | None, dict | None]]:
    candidates = [
        {"idx": idx, "score": result[0].score or {}}
        for idx, result in enumerate(results)
        if result[0] is not None and _is_fully_trusted_score(result[0].score or {})
    ]
    keep_indexes = {
        int(item["idx"])
        for item in _pareto_productivity_frontier(candidates)
    }
    filtered = [result for idx, result in enumerate(results) if idx in keep_indexes]
    filtered.sort(
        key=lambda result: (
            float((result[0].score or {}).get("earliness_avg_days", 999.0) or 999.0)
            if result[0] is not None
            else 999.0,
            _productivity_frontier_key(result[0].score or {})
            if result[0] is not None
            else (999.0, 999.0, 999.0),
        )
    )
    return filtered


def _evaluate_lns_split_spec(
    *,
    candidate_name: str,
    source_config: FactoryConfig,
    source_changes: dict[str, object],
    split_spec: dict[str, list[int]],
    crew_priority: list[str] | None,
    engine_data: EngineData,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
    apply_earliness_repair: bool = True,
) -> tuple[ScheduleResult | None, FactoryConfig | None, dict | None]:
    candidate_config = copy.deepcopy(source_config)
    candidate_config.forced_run_splits = split_spec
    candidate_changes = {
        **source_changes,
        "forced_run_splits": _summarize_forced_splits(split_spec),
        "forced_run_split_spec": split_spec,
    }

    try:
        with _quiet_advisory_solver_logs():
            trial = schedule_all(
                copy.deepcopy(engine_data),
                audit=False,
                config=candidate_config,
                crew_priority=crew_priority,
            )
        _apply_score_policy(trial, candidate_config)
        assert_plan_valid(trial.segments, engine_data, candidate_config)
        local_repair: dict | None = None
        delivery_repair_decision = _delivery_repair_triage(trial, incumbent)
        if delivery_repair_decision["decision"] == "attempt":
            trial, delivery_repair = _try_delivery_left_shift_repair(
                trial,
                engine_data,
                candidate_config,
            )
            local_repair = _append_local_repair_decision(
                local_repair,
                delivery_repair,
            )
        elif delivery_repair_decision["decision"] == "skipped":
            local_repair = _append_local_repair_decision(
                local_repair,
                delivery_repair_decision,
            )
        if apply_earliness_repair:
            trial, earliness_repair = _try_global_delay_earliness_repair(
                trial,
                baseline,
                engine_data,
                candidate_config,
            )
            local_repair = _append_local_repair_decision(
                local_repair,
                earliness_repair,
            )
    except (RuntimeError, ValueError, PlanValidationError) as exc:
        return (
            None,
            None,
            _candidate_error_decision(
                candidate_name,
                candidate_changes,
                crew_priority,
                exc,
            ),
        )

    accepted = _is_better_candidate(trial, incumbent) and _preserves_trust(
        trial,
        baseline,
    )
    decision = _candidate_decision(
        candidate_name,
        "accepted" if accepted else "rejected",
        "trust-rank improvement"
        if accepted
        else _candidate_rejection_reason(trial, incumbent),
        candidate_changes,
        crew_priority,
        trial,
        incumbent,
        baseline,
        local_repair,
    )
    return trial, candidate_config, decision


def _lns_split_spec(moves: list[tuple[str, int]]) -> dict[str, list[int]]:
    split_spec: dict[str, list[int]] = {}
    for run_id, position in moves:
        split_spec.setdefault(run_id, []).append(position)
    return split_spec


def _merge_lns_split_specs(
    left: dict[str, list[int]],
    right: dict[str, list[int]],
) -> dict[str, list[int]]:
    merged = {run_id: list(positions) for run_id, positions in left.items()}
    for run_id, positions in right.items():
        bucket = merged.setdefault(run_id, [])
        for position in positions:
            if position not in bucket:
                bucket.append(position)
        bucket.sort()
    return merged


def _normalise_lns_split_spec(raw_spec: object) -> dict[str, list[int]]:
    if not isinstance(raw_spec, dict):
        return {}
    split_spec: dict[str, list[int]] = {}
    for raw_run_id, raw_positions in raw_spec.items():
        run_id = str(raw_run_id)
        if not run_id:
            continue
        try:
            positions = [int(position) for position in raw_positions]  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        clean_positions = sorted({position for position in positions if position > 0})
        if clean_positions:
            split_spec[run_id] = clean_positions
    return split_spec


def _split_moves_from_spec(split_spec: dict[str, list[int]]) -> list[tuple[str, int]]:
    return [
        (run_id, position)
        for run_id, positions in sorted(split_spec.items())
        for position in sorted(positions)
    ]


def _lns_split_moves_from_pressure(
    result: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
    limit: int = 8,
) -> list[tuple[str, int]]:
    base_config = copy.deepcopy(config)
    base_config.forced_run_splits = {}
    lots = create_lots(copy.deepcopy(engine_data), config=base_config)
    runs = create_tool_runs(lots, config=base_config)
    run_by_id = {run.id: run for run in runs}

    moves: list[tuple[str, int]] = []
    seen: set[str] = set()
    for row in _earliness_pressure_report(result, limit=limit).get("top_runs") or []:
        if not isinstance(row, dict):
            continue
        run_id = str(row.get("run_id") or "")
        if not run_id or run_id in seen:
            continue
        run = run_by_id.get(run_id)
        if run is None or len(run.lots) < 2:
            continue
        position = _largest_edd_gap_split_position(run)
        if position is None:
            continue
        seen.add(run_id)
        moves.append((run_id, position))
    return moves


def _largest_edd_gap_split_position(run: ToolRun) -> int | None:
    if len(run.lots) < 2:
        return None
    gaps = [
        (int(run.lots[idx].edd) - int(run.lots[idx - 1].edd), idx)
        for idx in range(1, len(run.lots))
    ]
    gap, position = max(gaps, key=lambda item: (item[0], -item[1]))
    return position if gap > 0 else None


def _summarize_forced_splits(split_spec: dict[str, list[int]]) -> str:
    split_count = sum(len(positions) for positions in split_spec.values())
    run_count = len(split_spec)
    return f"{split_count} split(s) across {run_count} run(s)"


def _record_productivity_frontier_miss(
    trace: dict,
    decision: dict,
    candidate: ScheduleResult,
    incumbent: ScheduleResult,
) -> None:
    """Remember the best rejected productivity gain that still preserved trust."""

    candidate_score = candidate.score or {}
    if not _is_fully_trusted_score(candidate_score):
        return
    incumbent_score = incumbent.score or {}
    if not _has_setup_productivity_gain(candidate_score, incumbent_score):
        return

    current = trace.get("best_rejected_productivity")
    if current is not None and _productivity_frontier_key(candidate_score) >= (
        float(current["score"].get("setup_time_min", 0) or 0),
        float(current["score"].get("setups", 0) or 0),
        float(current["score"].get("earliness_avg_days", 0) or 0),
    ):
        return

    trace["best_rejected_productivity"] = {
        **decision,
        "not_applied_policy": (
            "Preserves physical and delivery trust, but is not applied because "
            "it leaves the accepted productivity/earliness frontier."
        ),
    }


def _reconcile_productivity_frontier_miss(trace: dict, final: ScheduleResult) -> None:
    """Drop stale near-misses once a later accepted candidate dominates them."""

    frontier = trace.get("best_rejected_productivity")
    if not frontier:
        return

    frontier_score = frontier.get("score") or {}
    final_score = final.score or {}
    if _has_setup_productivity_gain(frontier_score, final_score):
        return

    trace["superseded_rejected_productivity"] = {
        **frontier,
        "superseded_by": trace.get("best_candidate"),
        "superseded_reason": (
            "No remaining setup-time or setup-count gain versus the accepted plan."
        ),
    }
    trace["best_rejected_productivity"] = None


def _has_setup_productivity_gain(candidate_score: dict, reference_score: dict) -> bool:
    return (
        _setup_minutes(candidate_score) < _setup_minutes(reference_score)
        or float(candidate_score.get("setups", 0) or 0)
        < float(reference_score.get("setups", 0) or 0)
    )


def _append_local_repair_decision(chain: dict | None, decision: dict | None) -> dict | None:
    if decision is None:
        return chain
    if chain is None:
        return decision

    cursor = chain
    while isinstance(cursor.get("follow_up"), dict):
        cursor = cursor["follow_up"]
    cursor["follow_up"] = decision
    return chain


def _summarize_candidate_search_trace(trace: dict) -> None:
    decision_class_counts: dict[str, int] = {}
    local_repair_counts: dict[str, dict[str, int]] = {}

    for decision in trace.get("decisions") or []:
        decision_class = str(decision.get("decision_class") or "unknown")
        decision_class_counts[decision_class] = decision_class_counts.get(decision_class, 0) + 1

        repair = decision.get("local_repair")
        while isinstance(repair, dict):
            name = str(repair.get("name") or "unknown")
            repair_decision = str(repair.get("decision") or "unknown")
            bucket = local_repair_counts.setdefault(name, {})
            bucket[repair_decision] = bucket.get(repair_decision, 0) + 1
            repair = repair.get("follow_up")

    trace["decision_class_counts"] = decision_class_counts
    trace["local_repair_counts"] = local_repair_counts


def _summarize_non_applied_productivity(trace: dict, final: ScheduleResult) -> None:
    final_score = final.score or {}
    trace["trusted_productivity_frontier"] = _trusted_productivity_frontier(
        trace,
        final_score,
    )
    trace["near_applicable_productivity_frontier"] = _near_applicable_productivity_frontier(
        trace,
        final_score,
    )
    best: dict | None = None
    best_key: tuple[float, float, float] | None = None

    for decision in trace.get("decisions") or []:
        if decision.get("name") == trace.get("best_candidate"):
            continue
        score = decision.get("score") or {}
        if not _is_fully_trusted_score(score):
            continue
        if not _has_setup_productivity_gain(score, final_score):
            continue
        key = _productivity_frontier_key(score)
        if best_key is None or key < best_key:
            best_key = key
            best = decision

    if best is None:
        trace["best_non_applied_productivity"] = None
        return

    score = best.get("score") or {}
    trace["best_non_applied_productivity"] = {
        **best,
        "not_applied_policy": _non_applied_productivity_policy(score, final_score),
        **_earliness_approval_metadata(score, final_score),
    }


def _trusted_productivity_frontier(trace: dict, final_score: dict) -> list[dict]:
    frontier: list[dict] = []
    seen: set[tuple[float, float, float, float]] = set()

    for decision in trace.get("decisions") or []:
        score = decision.get("score") or {}
        if not _is_fully_trusted_score(score):
            continue
        is_final_candidate = decision.get("name") == trace.get("best_candidate")
        if not is_final_candidate and not _has_setup_productivity_gain(
            score,
            final_score,
        ):
            continue
        signature = (
            float(score.get("setups", 0) or 0),
            _setup_minutes(score),
            float(score.get("earliness_avg_days", 0.0) or 0.0),
            float(score.get("planning_penalty", 0.0) or 0.0),
        )
        if signature in seen:
            continue
        seen.add(signature)
        approval_metadata = _earliness_approval_metadata(score, final_score)
        frontier.append(
            {
                "name": decision.get("name"),
                "decision": decision.get("decision"),
                "decision_class": decision.get("decision_class"),
                "reason": decision.get("reason"),
                "score": score,
                "delta_vs_final": _score_delta(score, final_score),
                "productivity_metrics": _productivity_delta_metrics(final_score, score),
                "requires_approval": _earliness_excess(score)
                > _earliness_excess(final_score),
                "approval_reason": (
                    "earliness_above_policy"
                    if _earliness_excess(score) > _earliness_excess(final_score)
                    else None
                ),
                **approval_metadata,
            }
        )

    frontier.sort(
        key=lambda item: (
            item["productivity_metrics"].get("setup_minutes_saved", 0.0) <= 0,
            _productivity_frontier_key(item.get("score") or {}),
        )
    )
    frontier = _pareto_productivity_frontier(frontier)
    return frontier[:8]


def _near_applicable_productivity_frontier(trace: dict, final_score: dict) -> list[dict]:
    """Trusted productivity candidates ranked by smallest remaining approval gap."""

    frontier: list[dict] = []
    seen: set[tuple[float, float, float, float]] = set()
    for decision in trace.get("decisions") or []:
        score = decision.get("score") or {}
        if not _is_fully_trusted_score(score):
            continue
        if not _has_setup_productivity_gain(score, final_score):
            continue
        signature = (
            float(score.get("setups", 0) or 0),
            _setup_minutes(score),
            float(score.get("earliness_avg_days", 0.0) or 0.0),
            float(score.get("planning_penalty", 0.0) or 0.0),
        )
        if signature in seen:
            continue
        seen.add(signature)
        approval_metadata = _earliness_approval_metadata(score, final_score)
        frontier.append(
            {
                "name": decision.get("name"),
                "decision": decision.get("decision"),
                "decision_class": decision.get("decision_class"),
                "reason": decision.get("reason"),
                "score": score,
                "delta_vs_final": _score_delta(score, final_score),
                "productivity_metrics": _productivity_delta_metrics(final_score, score),
                "earliness_excess_days": approval_metadata["approval_gap_days"],
                "remaining_approval_gap": "earliness_envelope",
                **approval_metadata,
            }
        )

    frontier.sort(
        key=lambda item: (
            float(item.get("earliness_excess_days", 999.0) or 999.0),
            -float(item["productivity_metrics"].get("setup_minutes_saved", 0.0) or 0.0),
            float((item.get("score") or {}).get("setups", 0) or 0),
        )
    )
    frontier = _pareto_productivity_frontier(frontier)
    return frontier[:5]


def _pareto_productivity_frontier(items: list[dict]) -> list[dict]:
    """Drop trusted productivity candidates that are strictly dominated."""

    return [
        item
        for idx, item in enumerate(items)
        if not any(
            _dominates_productivity_frontier(other, item)
            for other_idx, other in enumerate(items)
            if other_idx != idx
        )
    ]


def _dominates_productivity_frontier(left: dict, right: dict) -> bool:
    left_score = _productivity_frontier_item_score(left)
    right_score = _productivity_frontier_item_score(right)
    left_values = _productivity_frontier_axes(left_score)
    right_values = _productivity_frontier_axes(right_score)
    return all(left <= right for left, right in zip(left_values, right_values)) and any(
        left < right for left, right in zip(left_values, right_values)
    )


def _productivity_frontier_item_score(item: dict) -> dict:
    return item.get("score") or item.get("after_target") or {}


def _productivity_frontier_axes(score: dict) -> tuple[float, float, float, float]:
    return (
        _setup_minutes(score),
        float(score.get("setups", 0) or 0),
        float(score.get("earliness_avg_days", 0.0) or 0.0),
        float(score.get("planning_penalty", 0.0) or 0.0),
    )


def _non_applied_productivity_policy(score: dict, final_score: dict) -> str:
    if _earliness_excess(score) > _earliness_excess(final_score):
        return (
            "Preserves hard and delivery gates with fewer setups, but requires "
            "business approval for extra early stock."
        )
    return (
        "Preserves hard and delivery gates with fewer setups, but was superseded "
        "by the accepted trust-rank frontier."
    )


def _delivery_repair_triage(
    candidate: ScheduleResult,
    incumbent: ScheduleResult,
) -> dict:
    score = candidate.score or {}
    if _hard_violation_count(score) > 0:
        return {
            "name": "delivery_left_shift_repair",
            "decision": "not_applicable",
            "reason": "candidate already violates hard gates",
        }
    if not _delivery_regresses(score, incumbent.score or {}):
        return {
            "name": "delivery_left_shift_repair",
            "decision": "not_applicable",
            "reason": "candidate has no delivery regression versus incumbent",
        }
    if not _has_setup_productivity_gain(score, incumbent.score or {}):
        return {
            "name": "delivery_left_shift_repair",
            "decision": "not_applicable",
            "reason": "candidate has no setup productivity gain",
        }
    reasons = _delivery_repair_skip_reasons(score)
    if reasons:
        return {
            "name": "delivery_left_shift_repair",
            "decision": "skipped",
            "reason": "; ".join(reasons),
            "score": _score_snapshot(score),
        }
    return {
        "name": "delivery_left_shift_repair",
        "decision": "attempt",
        "reason": "near delivery miss with setup productivity gain",
    }


def _delivery_repair_skip_reasons(score: dict) -> list[str]:
    reasons: list[str] = []
    tardy_count = int(score.get("tardy_count", 0) or 0)
    otd_d_failures = int(score.get("otd_d_failures", 0) or 0)
    total_tardiness = float(score.get("total_tardiness", 0.0) or 0.0)
    max_tardiness = float(score.get("max_tardiness", 0.0) or 0.0)
    otd = float(score.get("otd", 0.0) or 0.0)
    otd_d = float(score.get("otd_d", 0.0) or 0.0)

    if tardy_count > DELIVERY_REPAIR_MAX_TARDY_COUNT:
        reasons.append(
            f"tardy_count {tardy_count} > {DELIVERY_REPAIR_MAX_TARDY_COUNT}"
        )
    if otd_d_failures > DELIVERY_REPAIR_MAX_OTD_D_FAILURES:
        reasons.append(
            f"otd_d_failures {otd_d_failures} > {DELIVERY_REPAIR_MAX_OTD_D_FAILURES}"
        )
    if otd < DELIVERY_REPAIR_MIN_OTD:
        reasons.append(f"OTD {_format_metric(otd)} < {_format_metric(DELIVERY_REPAIR_MIN_OTD)}")
    if otd_d < DELIVERY_REPAIR_MIN_OTD_D:
        reasons.append(
            f"OTD-D {_format_metric(otd_d)} < {_format_metric(DELIVERY_REPAIR_MIN_OTD_D)}"
        )
    if total_tardiness > DELIVERY_REPAIR_MAX_TOTAL_TARDINESS:
        reasons.append(
            f"total_tardiness {_format_metric(total_tardiness)} > "
            f"{_format_metric(DELIVERY_REPAIR_MAX_TOTAL_TARDINESS)}"
        )
    if max_tardiness > DELIVERY_REPAIR_MAX_TARDINESS:
        reasons.append(
            f"max_tardiness {_format_metric(max_tardiness)} > "
            f"{_format_metric(DELIVERY_REPAIR_MAX_TARDINESS)}"
        )
    return reasons


def _try_delivery_left_shift_repair(
    incumbent: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
) -> tuple[ScheduleResult, dict | None]:
    """Pull tardy runs earlier in a bounded LNS repair.

    The repair is intentionally local: it does not change sequencing, lot sizing,
    machine assignment, or setup count. It only tries trusted day-level left
    shifts for late runs and machine suffixes, accepting moves that improve the
    feasibility-first trust rank while preserving all hard physical gates.
    """

    if not incumbent.segments or _hard_violation_count(incumbent.score or {}) > 0:
        return incumbent, None
    if _is_fully_trusted_score(incumbent.score or {}):
        return incumbent, None

    beam: list[tuple[tuple[float, ...], list[str], ScheduleResult]] = [
        (_trust_rank(incumbent.score or {}), [], incumbent)
    ]
    best = beam[0]
    seen = {_segment_signature(incumbent.segments)}

    for _depth in range(2):
        candidates: list[tuple[tuple[float, ...], list[str], ScheduleResult]] = []
        for _rank, moves, result in beam:
            for move, trial_segments in _delivery_left_shift_neighbors(
                result,
                engine_data,
                config,
            ):
                signature = _segment_signature(trial_segments)
                if signature in seen:
                    continue
                seen.add(signature)
                trial_score = _score_repaired_segments(
                    trial_segments,
                    result,
                    engine_data,
                    config,
                )
                if trial_score is None:
                    continue
                trial_rank = _trust_rank(trial_score)
                if trial_rank >= _trust_rank(result.score or {}):
                    continue
                trial = _clone_with_segments(result, trial_segments, trial_score)
                candidates.append((trial_rank, [*moves, move], trial))
        if not candidates:
            break
        candidates.sort(key=lambda item: (item[0], len(item[1]), item[1]))
        beam = candidates[:6]
        if beam[0][0] < best[0]:
            best = beam[0]
        if _is_fully_trusted_score(best[2].score or {}):
            break

    if best[2] is incumbent:
        return incumbent, {
            "name": "delivery_left_shift_repair",
            "decision": "rejected",
            "reason": "no hard-gate-safe delivery improvement found",
        }

    best_score = best[2].score or {}
    return best[2], {
        "name": "delivery_left_shift_repair",
        "decision": "accepted",
        "reason": "reduced delivery violations by pulling late runs earlier",
        "moves": best[1],
        "score": _score_snapshot(best_score),
        "delta_vs_incumbent": _score_delta(best_score, incumbent.score or {}),
    }


def _try_final_jit_timing_polish(
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
    max_segments: int = 0,
) -> tuple[ScheduleResult, dict | None]:
    """Final trusted timing polish for stock-early reduction.

    Candidate search optimizes the setup frontier first. This final polish gives
    a fully trusted plan one last bounded chance to move safe runs closer to EDD
    without changing setup count, lot sizing, sequencing, or hard-gate status.
    """

    if not incumbent.segments or not _is_fully_trusted_score(incumbent.score or {}):
        return incumbent, None
    if max_segments > 0 and len(incumbent.segments) > max_segments:
        return incumbent, {
            "name": "final_jit_timing_polish",
            "decision": "skipped",
            "reason": (
                f"plan has {len(incumbent.segments)} segments > "
                f"budget {max_segments}"
            ),
            "score": _score_snapshot(incumbent.score or {}),
        }

    polished, beam_decision = _try_beam_delay_earliness_repair(
        incumbent,
        baseline,
        engine_data,
        config,
    )
    if polished is incumbent or beam_decision is None:
        return incumbent, {
            "name": "final_jit_timing_polish",
            "decision": "rejected",
            "reason": "no hard-gate-safe timing improvement found",
            "score": _score_snapshot(incumbent.score or {}),
        }

    score = polished.score or {}
    return polished, {
        "name": "final_jit_timing_polish",
        "decision": "accepted",
        "reason": "reduced earliness after setup frontier selection",
        "method": beam_decision.get("name"),
        "moves": beam_decision.get("moves", []),
        "search_stats": beam_decision.get("search_stats", {}),
        "score": _score_snapshot(score),
        "delta_vs_incumbent": _score_delta(score, incumbent.score or {}),
        "delta_vs_baseline": _score_delta(score, baseline.score or {}),
    }


def _delivery_left_shift_neighbors(
    result: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
) -> list[tuple[str, list[Segment]]]:
    rows = _tardy_run_rows(result, config)
    if not rows:
        return []

    all_rows = _machine_run_rows(result.segments, config)
    neighbors: list[tuple[str, list[Segment]]] = []
    for row in rows[:12]:
        run_id = str(row["run_id"])
        machine_id = str(row["machine_id"])
        start_abs = float(row["start_abs"])
        delay_days = max(1, int(row["delay_days"]))
        move_sets: list[tuple[str, set[str]]] = [(f"run={run_id}", {run_id})]
        suffix = {
            str(other["run_id"])
            for other in all_rows
            if other["machine_id"] == machine_id
            and float(other["start_abs"]) >= start_abs - 0.01
        }
        if len(suffix) > 1:
            move_sets.append((f"machine_suffix={machine_id},from={run_id}", suffix))

        for label, run_ids in move_sets:
            for delta_days in range(1, min(4, delay_days + 2) + 1):
                trial_segments = _shift_run_days(
                    result.segments,
                    run_ids,
                    -delta_days,
                    engine_data,
                )
                move = f"{label},delta_workdays=-{delta_days}"
                neighbors.append((move, trial_segments))
    return neighbors


def _tardy_run_rows(
    result: ScheduleResult,
    config: FactoryConfig,
) -> list[dict[str, object]]:
    lot_edd = {lot.id: lot.edd for lot in result.lots}
    lot_completion: dict[str, int] = {}
    for seg in result.segments:
        if seg.setup_min > 0 and seg.qty == 0:
            continue
        lot_completion[seg.lot_id] = max(lot_completion.get(seg.lot_id, -999), seg.day_idx)

    delay_by_run: dict[str, int] = defaultdict(int)
    for seg in result.segments:
        edd = lot_edd.get(seg.lot_id, seg.edd)
        delay_by_run[seg.run_id] = max(
            delay_by_run[seg.run_id],
            max(0, lot_completion.get(seg.lot_id, seg.day_idx) - edd),
        )

    rows: list[dict[str, object]] = []
    for row in _machine_run_rows(result.segments, config):
        run_id = str(row["run_id"])
        delay_days = max(int(row["delay_days"]), delay_by_run.get(run_id, 0))
        if delay_days <= 0:
            continue
        rows.append({**row, "delay_days": delay_days})

    return sorted(
        rows,
        key=lambda item: (
            -int(item["delay_days"]),
            float(item["start_abs"]),
            str(item["run_id"]),
        ),
    )


def _try_global_delay_earliness_repair(
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
) -> tuple[ScheduleResult, dict | None]:
    """Delay a safe suffix of runs to reduce stock-early days.

    This is a tiny LNS repair: preserve the run order and shift whole suffixes by
    full workdays. It never creates the applied plan directly unless the full
    trust rank improves and physical/delivery gates still pass.
    """

    if not incumbent.segments or not _is_fully_trusted_score(incumbent.score or {}):
        return incumbent, None

    best_result = incumbent
    best_decision: dict | None = None
    run_rows = _run_timing_rows(incumbent.segments, config)
    if len(run_rows) < 2:
        return _try_single_run_earliness_fallback(
            incumbent,
            baseline,
            engine_data,
            config,
            reason="not enough run rows for suffix timing repair",
        )

    for cut_abs in _global_delay_cut_points(run_rows):
        affected_run_ids = {
            row["run_id"] for row in run_rows if row["start_abs"] >= cut_abs - 0.01
        }
        if not affected_run_ids:
            continue
        for delta_days in (1, 2, 3):
            trial_segments = _shift_run_days(
                incumbent.segments,
                affected_run_ids,
                delta_days,
                engine_data,
            )
            if _touches_global_holiday(trial_segments, engine_data):
                continue
            try:
                assert_plan_valid(trial_segments, engine_data, config)
            except PlanValidationError:
                continue
            trial_score = compute_score(trial_segments, incumbent.lots, engine_data, config=config)
            _apply_score_policy_to_score(trial_score, config)
            if "buffer_days" in (incumbent.score or {}):
                trial_score["buffer_days"] = incumbent.score.get("buffer_days", 0)
            trial = ScheduleResult(
                segments=trial_segments,
                lots=incumbent.lots,
                score=trial_score,
                time_ms=incumbent.time_ms,
                warnings=list(incumbent.warnings),
                operator_alerts=incumbent.operator_alerts,
                audit_trail=incumbent.audit_trail,
                study=incumbent.study,
                journal=incumbent.journal,
                machine_runs=incumbent.machine_runs,
                gate_report=incumbent.gate_report,
            )
            if not _is_better_candidate(trial, best_result):
                continue
            if not _preserves_trust(trial, baseline):
                continue
            best_result = trial
            best_decision = {
                "name": "global_suffix_earliness_repair",
                "decision": "accepted",
                "reason": "trust-rank improvement",
                "cut_abs_min": round(cut_abs, 2),
                "delta_days": delta_days,
                "affected_runs": len(affected_run_ids),
                "score": _score_snapshot(trial_score),
                "delta_vs_incumbent": _score_delta(trial_score, incumbent.score or {}),
                "delta_vs_baseline": _score_delta(trial_score, baseline.score or {}),
            }

    if best_decision is not None:
        if _earliness_excess(best_result.score or {}) > 0:
            beam_result, beam_decision = _try_beam_delay_earliness_repair(
                best_result,
                baseline,
                engine_data,
                config,
            )
            if beam_result is not best_result and beam_decision is not None:
                best_decision["follow_up"] = beam_decision
                return beam_result, best_decision
        return best_result, best_decision

    return _try_single_run_earliness_fallback(
        incumbent,
        baseline,
        engine_data,
        config,
        reason="no trust-rank improvement found",
    )


def _try_single_run_earliness_fallback(
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
    *,
    reason: str,
) -> tuple[ScheduleResult, dict | None]:
    decision = {
        "name": "global_suffix_earliness_repair",
        "decision": "rejected",
        "reason": reason,
        "score": _score_snapshot(incumbent.score or {}),
    }
    if _earliness_excess(incumbent.score or {}) <= 0:
        return incumbent, decision

    beam_result, beam_decision = _try_beam_delay_earliness_repair(
        incumbent,
        baseline,
        engine_data,
        config,
    )
    if beam_result is incumbent or beam_decision is None:
        return incumbent, decision

    decision["follow_up"] = beam_decision
    return beam_result, decision


def _try_beam_delay_earliness_repair(
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
) -> tuple[ScheduleResult, dict | None]:
    """Small beam search over single-run right shifts after suffix timing repair."""

    if not incumbent.segments or not _is_fully_trusted_score(incumbent.score or {}):
        return incumbent, None

    beam: list[tuple[float, float, list[str], ScheduleResult]] = [
        (
            float(incumbent.score.get("earliness_avg_days", 0.0) or 0.0),
            float(incumbent.score.get("planning_penalty", 0.0) or 0.0),
            [],
            incumbent,
        )
    ]
    best = beam[0]
    seen = {_segment_signature(incumbent.segments)}
    max_depth = 2
    beam_width = 6
    search_stats = {
        "max_depth": max_depth,
        "beam_width": beam_width,
        "generated_neighbors": 0,
        "unique_neighbors": 0,
        "valid_neighbors": 0,
        "trusted_improvements": 0,
    }

    for _depth in range(max_depth):
        candidates: list[tuple[float, float, list[str], ScheduleResult]] = []
        for _earliness, _penalty, moves, result in beam:
            for move, trial_segments in _single_run_delay_neighbors(
                result.segments,
                engine_data,
                config,
            ):
                search_stats["generated_neighbors"] += 1
                signature = _segment_signature(trial_segments)
                if signature in seen:
                    continue
                seen.add(signature)
                search_stats["unique_neighbors"] += 1
                trial_score = _score_repaired_segments(
                    trial_segments,
                    result,
                    engine_data,
                    config,
                )
                if trial_score is None:
                    continue
                search_stats["valid_neighbors"] += 1
                trial = _clone_with_segments(result, trial_segments, trial_score)
                if not _is_better_candidate(trial, result):
                    continue
                if not _preserves_trust(trial, baseline):
                    continue
                search_stats["trusted_improvements"] += 1
                candidates.append(
                    (
                        float(trial_score.get("earliness_avg_days", 0.0) or 0.0),
                        float(trial_score.get("planning_penalty", 0.0) or 0.0),
                        [*moves, move],
                        trial,
                    )
                )
        if not candidates:
            break
        candidates.sort(key=lambda item: (item[0], item[1], len(item[2]), item[2]))
        beam = candidates[:beam_width]
        if beam[0][:3] < best[:3]:
            best = beam[0]
        if _earliness_excess(best[3].score or {}) <= 0:
            break

    if best[3] is incumbent:
        return incumbent, None

    best_score = best[3].score or {}
    return best[3], {
        "name": "beam_single_run_earliness_repair",
        "decision": "accepted",
        "reason": "trust-rank improvement",
        "moves": best[2],
        "score": _score_snapshot(best_score),
        "delta_vs_incumbent": _score_delta(best_score, incumbent.score or {}),
        "delta_vs_baseline": _score_delta(best_score, baseline.score or {}),
        "search_stats": search_stats,
    }


def _single_run_delay_neighbors(
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig,
) -> list[tuple[str, list[Segment]]]:
    neighbors: list[tuple[str, list[Segment]]] = []
    for row in sorted(
        _run_timing_rows(segments, config),
        key=lambda item: (
            -float(item["gap_days"]),
            float(item["start_abs"]),
            str(item["run_id"]),
        ),
    )[:24]:
        gap_days = int(row["gap_days"])
        if gap_days <= 0:
            continue
        run_id = str(row["run_id"])
        for delta_days in range(1, min(8, gap_days) + 1):
            trial_segments = _shift_run_days(segments, {run_id}, delta_days, engine_data)
            move = f"run={run_id},delta_workdays={delta_days}"
            neighbors.append((move, trial_segments))
    return neighbors


def _score_repaired_segments(
    segments: list[Segment],
    reference: ScheduleResult,
    engine_data: EngineData,
    config: FactoryConfig,
) -> dict | None:
    if _touches_global_holiday(segments, engine_data):
        return None
    try:
        assert_plan_valid(segments, engine_data, config)
    except PlanValidationError:
        return None
    score = compute_score(segments, reference.lots, engine_data, config=config)
    _apply_score_policy_to_score(score, config)
    if "buffer_days" in (reference.score or {}):
        score["buffer_days"] = reference.score.get("buffer_days", 0)
    return score


def _clone_with_segments(
    reference: ScheduleResult,
    segments: list[Segment],
    score: dict,
) -> ScheduleResult:
    return ScheduleResult(
        segments=segments,
        lots=reference.lots,
        score=score,
        time_ms=reference.time_ms,
        warnings=list(reference.warnings),
        operator_alerts=reference.operator_alerts,
        audit_trail=reference.audit_trail,
        study=reference.study,
        journal=reference.journal,
        machine_runs=reference.machine_runs,
        gate_report=reference.gate_report,
    )


def _segment_signature(segments: list[Segment]) -> tuple[tuple[str, str, int, int, int], ...]:
    return tuple(
        sorted(
            (seg.run_id, seg.lot_id, seg.day_idx, seg.start_min, seg.end_min)
            for seg in segments
        )
    )


def _run_timing_rows(segments: list[Segment], config: FactoryConfig) -> list[dict[str, object]]:
    return [
        {
            "run_id": row["run_id"],
            "start_abs": row["start_abs"],
            "gap_days": max(0, int(row["edd"]) - int(row["last_day"])),
        }
        for row in _machine_run_rows(segments, config)
    ]


def _machine_run_rows(segments: list[Segment], config: FactoryConfig) -> list[dict[str, object]]:
    by_run: dict[str, list[Segment]] = defaultdict(list)
    for seg in segments:
        by_run[seg.run_id].append(seg)

    rows: list[dict[str, object]] = []
    for run_id, run_segments in by_run.items():
        start_abs = min(segment_abs(seg, config)[0] for seg in run_segments)
        last_day = max(seg.day_idx for seg in run_segments)
        edd = max(seg.edd for seg in run_segments)
        rows.append(
            {
                "run_id": run_id,
                "machine_id": run_segments[0].machine_id,
                "start_abs": start_abs,
                "last_day": last_day,
                "edd": edd,
                "delay_days": max(0, last_day - edd),
            }
        )
    return sorted(rows, key=lambda row: float(row["start_abs"]))


def _global_delay_cut_points(run_rows: list[dict[str, object]]) -> list[float]:
    candidates: list[float] = []
    if not run_rows:
        return candidates

    for q in (0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        idx = min(len(run_rows) - 1, max(0, int(len(run_rows) * q)))
        candidates.append(float(run_rows[idx]["start_abs"]))

    for row in sorted(run_rows, key=lambda item: float(item["gap_days"]), reverse=True)[:24]:
        candidates.append(float(row["start_abs"]))

    unique: list[float] = []
    for cut_abs in candidates:
        if all(abs(cut_abs - existing) > 1.0 for existing in unique):
            unique.append(cut_abs)
    return unique[:40]


def _shift_run_days(
    segments: list[Segment],
    run_ids: set[str],
    delta_days: int,
    engine_data: EngineData,
) -> list[Segment]:
    shifted = copy.deepcopy(segments)
    for seg in shifted:
        if seg.run_id in run_ids:
            if delta_days >= 0:
                seg.day_idx = _add_workdays(seg.day_idx, delta_days, engine_data)
            else:
                seg.day_idx = _subtract_workdays(
                    seg.day_idx,
                    abs(delta_days),
                    engine_data,
                )
    return shifted


def _add_workdays(day_idx: int, delta_days: int, engine_data: EngineData) -> int:
    holidays = set(getattr(engine_data, "holidays", []) or [])
    current = day_idx
    moved = 0
    while moved < delta_days:
        current += 1
        if current not in holidays:
            moved += 1
    return current


def _subtract_workdays(day_idx: int, delta_days: int, engine_data: EngineData) -> int:
    holidays = set(getattr(engine_data, "holidays", []) or [])
    current = day_idx
    moved = 0
    while moved < delta_days:
        current -= 1
        if current not in holidays:
            moved += 1
    return current


def _touches_global_holiday(segments: list[Segment], engine_data: EngineData) -> bool:
    holidays = set(getattr(engine_data, "holidays", []) or [])
    if not holidays:
        return False
    return any(seg.day_idx in holidays for seg in segments if seg.end_min > seg.start_min)


def _is_fully_trusted_score(score: dict) -> bool:
    if _hard_violation_count(score) > 0:
        return False
    if float(score.get("otd", 0.0) or 0.0) < 100.0:
        return False
    if float(score.get("otd_d", 0.0) or 0.0) < 100.0:
        return False
    return all(float(score.get(key, 0.0) or 0.0) <= 0.0 for key in TRUST_DELIVERY_KEYS)


def _productivity_frontier_key(score: dict) -> tuple[float, float, float]:
    return (
        _setup_minutes(score),
        float(score.get("setups", 0) or 0),
        float(score.get("earliness_avg_days", 0.0) or 0.0),
    )


@contextmanager
def _quiet_advisory_solver_logs():
    """Keep rejected shadow/advisory candidates out of operator-facing logs."""

    noisy_loggers = (
        logging.getLogger("backend.scheduler.scheduler"),
        logging.getLogger("backend.cpo.cpsat_polish"),
    )
    previous_levels = [
        (candidate_logger, candidate_logger.level) for candidate_logger in noisy_loggers
    ]
    try:
        for candidate_logger in noisy_loggers:
            if candidate_logger.getEffectiveLevel() < logging.ERROR:
                candidate_logger.setLevel(logging.ERROR)
        yield
    finally:
        for candidate_logger, previous_level in previous_levels:
            candidate_logger.setLevel(previous_level)


def _candidate_configs(
    config: FactoryConfig,
    mode: str,
    engine_data: EngineData,
) -> list[tuple[str, FactoryConfig, dict[str, object], list[str] | None]]:
    """Build conservative CPO v4 shadow variants.

    These are not user-facing config changes. They are bounded experiments that
    let the solver mature incrementally while the trust gates decide acceptance.
    """

    variants: list[tuple[str, dict[str, object]]] = [
        (
            "delivery_focus",
            {
                "campaign_window": min(config.campaign_window, 8),
                "edd_swap_tolerance": min(config.edd_swap_tolerance, 3),
                "lst_safety_buffer": max(config.lst_safety_buffer, 3),
                "urgency_threshold": min(config.urgency_threshold, 3),
            },
        ),
        (
            "jit_tighter",
            {
                "jit_buffer_pct": min(config.jit_buffer_pct, 0.02),
                "jit_earliness_target": min(config.jit_earliness_target, 4.5),
                "lst_safety_buffer": max(config.lst_safety_buffer, 3),
            },
        ),
        (
            "jit_release_slack",
            {
                "jit_buffer_pct": max(config.jit_buffer_pct, 0.08),
                "jit_earliness_target": max(config.jit_earliness_target, 6.5),
            },
        ),
        (
            "compact_idle",
            {
                "compact_enabled": True,
            },
        ),
        (
            "vns_block_relocate_probe",
            {
                "vns_block_moves_enabled": True,
            },
        ),
        (
            "campaign_merge_frontier",
            {
                "max_edd_gap": max(config.max_edd_gap, 14),
                "max_edd_span": max(config.max_edd_span, 40),
                "campaign_window": max(config.campaign_window, 18),
                "edd_swap_tolerance": max(config.edd_swap_tolerance, 12),
                "jit_buffer_pct": min(config.jit_buffer_pct, 0.04),
                "jit_earliness_target": max(config.jit_earliness_target, 7.1),
            },
        ),
    ]

    if mode in {"deep", "max"}:
        variants.append(
            (
                "setup_campaign_guarded",
                {
                    "campaign_window": max(config.campaign_window, 25),
                    "edd_swap_tolerance": max(config.edd_swap_tolerance, 8),
                },
            )
        )

    out: list[tuple[str, FactoryConfig, dict[str, object], list[str] | None]] = []
    seen: set[tuple[tuple[str, object], ...]] = set()
    for name, overrides in variants:
        candidate = copy.deepcopy(config)
        changes: dict[str, object] = {}
        for key, value in overrides.items():
            if getattr(candidate, key) != value:
                setattr(candidate, key, value)
                changes[key] = value
        if not changes:
            continue
        signature = tuple(sorted(changes.items()))
        if signature in seen:
            continue
        seen.add(signature)
        out.append((name, candidate, changes, None))

    for name, crew_priority in _crew_priority_candidates(engine_data):
        signature = (("crew_priority", tuple(crew_priority)),)
        if signature in seen:
            continue
        seen.add(signature)
        out.append(
            (
                name,
                copy.deepcopy(config),
                {"crew_priority": " > ".join(crew_priority)},
                crew_priority,
            )
        )

    for name, changes, crew_priority in _combined_candidate_configs(config, engine_data):
        signature = tuple(sorted(changes.items()))
        if signature in seen:
            continue
        seen.add(signature)
        candidate = copy.deepcopy(config)
        for key, value in changes.items():
            if hasattr(candidate, key):
                setattr(candidate, key, value)
        out.append((name, candidate, changes, crew_priority))
    return sorted(out, key=lambda item: _candidate_sort_key(item[0], item[2], item[3]))


def _crew_priority_candidates(engine_data: EngineData) -> list[tuple[str, list[str]]]:
    """Small setup-crew priority experiments for one-crew APS repair.

    These priorities are intentionally candidates, not assumptions. They are
    useful when JIT creates good delivery windows that then compete for the
    single setup crew. The trust rank decides whether any priority is accepted.
    """

    machine_ids = [machine.id for machine in engine_data.machines]
    if len(machine_ids) < 2:
        return []

    preferred_orders = [
        (
            "setup_priority_prm019_medias",
            ["PRM019", "PRM042", "PRM031", "PRM043", "PRM039"],
        ),
        (
            "setup_priority_medias_prm019",
            ["PRM042", "PRM019", "PRM031", "PRM043", "PRM039"],
        ),
        (
            "setup_priority_prm019_prm043_medias",
            ["PRM019", "PRM043", "PRM042", "PRM039", "PRM031"],
        ),
        (
            "setup_priority_prm019_prm043_prm039",
            ["PRM019", "PRM043", "PRM039", "PRM031", "PRM042"],
        ),
    ]

    out: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, ...]] = set()

    def add_priority(name: str, priority: list[str]) -> None:
        if len(priority) != len(machine_ids):
            return
        signature = tuple(priority)
        if signature in seen:
            return
        seen.add(signature)
        out.append((name, priority))

    for name, preferred in preferred_orders:
        if not any(machine_id in machine_ids for machine_id in preferred):
            continue
        priority = _priority_from_preferred(machine_ids, preferred)
        add_priority(name, priority)

    medias_first = [
        machine.id
        for machine in engine_data.machines
        if machine.group.lower() in {"medias", "médias"}
    ]
    if medias_first and len(medias_first) < len(machine_ids):
        medias_first.extend(
            machine.id for machine in engine_data.machines if machine.id not in medias_first
        )
        add_priority("setup_priority_medias_first", medias_first)

    for name, priority in _data_driven_crew_priorities(engine_data):
        add_priority(name, priority)

    return out


def _priority_from_preferred(machine_ids: list[str], preferred: list[str]) -> list[str]:
    priority = [machine_id for machine_id in preferred if machine_id in machine_ids]
    priority.extend(machine_id for machine_id in machine_ids if machine_id not in priority)
    return priority


def _data_driven_crew_priorities(engine_data: EngineData) -> list[tuple[str, list[str]]]:
    """Derive setup-crew priority candidates from demand and setup pressure."""

    machine_ids = [machine.id for machine in engine_data.machines]
    if len(machine_ids) < 2:
        return []

    features = _machine_pressure_features(engine_data)
    setup_pressure = sorted(
        machine_ids,
        key=lambda machine_id: (
            -features[machine_id]["setup_pressure"],
            -features[machine_id]["workload_min"],
            features[machine_id]["first_due"],
            machine_id,
        ),
    )
    delivery_pressure = sorted(
        machine_ids,
        key=lambda machine_id: (
            -features[machine_id]["delivery_pressure"],
            features[machine_id]["first_due"],
            -features[machine_id]["workload_min"],
            machine_id,
        ),
    )

    return [
        ("setup_priority_setup_pressure", setup_pressure),
        ("setup_priority_delivery_pressure", delivery_pressure),
    ]


def _machine_pressure_features(engine_data: EngineData) -> dict[str, dict[str, float]]:
    features = {
        machine.id: {
            "workload_min": 0.0,
            "setup_pressure": 0.0,
            "delivery_pressure": 0.0,
            "first_due": float(engine_data.n_days + 1),
        }
        for machine in engine_data.machines
    }

    for op in engine_data.ops:
        if op.m not in features:
            continue
        demand_by_day = [max(0, qty) for qty in op.d[: engine_data.n_days]]
        total_demand = float(sum(demand_by_day))
        if total_demand <= 0:
            continue

        first_due = next(
            (float(day_idx) for day_idx, qty in enumerate(demand_by_day) if qty > 0),
            float(engine_data.n_days + 1),
        )
        pieces_per_hour = max(float(op.pH or 0.0) * max(float(op.oee or 0.0), 0.01), 0.01)
        workload_min = total_demand / pieces_per_hour * 60.0
        setup_min = max(float(op.sH or 0.0), 0.0) * 60.0
        delivery_pressure = sum(
            float(qty) / (float(day_idx) + 1.0)
            for day_idx, qty in enumerate(demand_by_day)
            if qty > 0
        )

        machine_features = features[op.m]
        machine_features["workload_min"] += workload_min
        machine_features["setup_pressure"] += setup_min
        machine_features["delivery_pressure"] += delivery_pressure
        machine_features["first_due"] = min(machine_features["first_due"], first_due)

    return features


def _combined_candidate_configs(
    config: FactoryConfig,
    engine_data: EngineData,
) -> list[tuple[str, dict[str, object], list[str]]]:
    """Build bounded combination candidates from proven-safe building blocks."""

    out: list[tuple[str, dict[str, object], list[str]]] = []
    for priority_name, crew_priority in _crew_priority_candidates(engine_data):
        out.append(
            (
                f"jit_release_slack_with_{priority_name}",
                {
                    "jit_buffer_pct": max(config.jit_buffer_pct, 0.08),
                    "jit_earliness_target": max(config.jit_earliness_target, 6.5),
                    "crew_priority": " > ".join(crew_priority),
                },
                crew_priority,
            )
        )
        out.append(
            (
                f"setup_campaign_with_{priority_name}",
                {
                    "campaign_window": max(config.campaign_window, 25),
                    "edd_swap_tolerance": max(config.edd_swap_tolerance, 8),
                    "crew_priority": " > ".join(crew_priority),
                },
                crew_priority,
            )
        )
        out.append(
            (
                f"setup_time_focus_with_{priority_name}",
                {
                    "campaign_window": max(config.campaign_window, 18),
                    "edd_swap_tolerance": max(config.edd_swap_tolerance, 12),
                    "jit_buffer_pct": max(config.jit_buffer_pct, 0.10),
                    "jit_earliness_target": max(config.jit_earliness_target, 6.8),
                    "crew_priority": " > ".join(crew_priority),
                },
                crew_priority,
            )
        )
        out.append(
            (
                f"productivity_frontier_with_{priority_name}",
                {
                    "campaign_window": max(config.campaign_window, 18),
                    "edd_swap_tolerance": max(config.edd_swap_tolerance, 12),
                    "jit_buffer_pct": min(config.jit_buffer_pct, 0.04),
                    "jit_earliness_target": max(config.jit_earliness_target, 7.1),
                    "crew_priority": " > ".join(crew_priority),
                },
                crew_priority,
            )
        )
    return out


def _candidate_sort_key(
    name: str,
    changes: dict[str, object],
    crew_priority: list[str] | None,
) -> tuple[int, int, str]:
    """Order candidates so bounded search evaluates high-value moves first."""

    has_crew_priority = crew_priority is not None
    changes_campaign = "campaign_window" in changes or "edd_swap_tolerance" in changes
    changes_jit = "jit_buffer_pct" in changes or "jit_earliness_target" in changes

    if has_crew_priority and name.startswith("setup_campaign_with_"):
        bucket = 0
    elif has_crew_priority and name.startswith("setup_time_focus_with_"):
        bucket = 1
    elif has_crew_priority and name.startswith("productivity_frontier_with_"):
        bucket = 2
    elif has_crew_priority and changes_jit:
        bucket = 3
    elif name.startswith("setup_priority_"):
        bucket = 4
    elif changes_campaign:
        bucket = 5
    elif changes_jit:
        bucket = 6
    elif name == "delivery_focus":
        bucket = 7
    elif name == "compact_idle":
        bucket = 9
    else:
        bucket = 8

    return (bucket, len(changes), name)


def _attach_solver_trace(result: ScheduleResult, trace: dict) -> None:
    if result.gate_report is None:
        result.gate_report = {}
    _append_non_applied_productivity_proposal(result.gate_report, trace)
    result.gate_report["solver_trace"] = trace


def _append_non_applied_productivity_proposal(gate_report: dict, trace: dict) -> None:
    proposal = _non_applied_productivity_proposal(trace)
    if proposal is None:
        return
    proposals = gate_report.setdefault("proposals", [])
    if any(item.get("id") == proposal["id"] for item in proposals):
        return
    proposals.append(proposal)


def _non_applied_productivity_proposal(trace: dict) -> dict | None:
    candidate = (trace.get("candidate_search") or {}).get("best_non_applied_productivity")
    if not isinstance(candidate, dict):
        return None
    candidate_score = candidate.get("score") or {}
    final_score = trace.get("final") or {}
    if not candidate_score or not final_score:
        return None

    before = _proposal_productivity_metrics(final_score)
    after = _proposal_productivity_metrics(candidate_score)
    productivity_metrics = _productivity_delta_metrics(final_score, candidate_score)
    approval_metadata = _earliness_approval_metadata(candidate_score, final_score)
    setup_saved = int(productivity_metrics["setup_count_saved"])
    setup_minutes_saved = float(productivity_metrics["setup_minutes_saved"])
    earliness_delta = float(productivity_metrics["earliness_delta_days"])
    if setup_saved <= 0 and setup_minutes_saved <= 0:
        return None

    candidate_name = str(candidate.get("name") or "non_applied_productivity")
    near_frontier = (
        (trace.get("candidate_search") or {}).get("near_applicable_productivity_frontier")
        or []
    )
    approval_options = _productivity_approval_options(
        trace,
        final_score,
        candidate,
    )
    affected_lots, affected_skus = _proposal_entities_from_frontier(trace)
    return {
        "id": f"{candidate_name}_proposal",
        "type": "campaign_merge",
        "description": "Proposta nao aplicada: juntar campanhas para reduzir setups.",
        "expected_impact": (
            f"Poupa {setup_saved} setups e {setup_minutes_saved:.0f} min de setup; "
            f"aumenta stock cedo em {earliness_delta:.1f} dias."
        ),
        "before": before,
        "after_target": after,
        "productivity_metrics": productivity_metrics,
        "earliness_pressure": candidate.get("earliness_pressure"),
        "near_applicable_frontier": near_frontier[:3],
        "approval_options": approval_options,
        "approval_blockers": _proposal_approval_blockers(candidate),
        "suggested_actions": _proposal_suggested_actions(candidate, candidate_score),
        "solver_next_steps": _proposal_solver_next_steps(
            productivity_metrics,
            candidate,
        ),
        "affected_lots": affected_lots,
        "affected_skus": affected_skus,
        "affected_machines": _proposal_machines_from_frontier(trace),
        "requires_validation": True,
        "requires_approval": True,
        "approval_reason": "earliness_above_policy",
        "approval_action": "approve_productivity_earliness_ceiling",
        **approval_metadata,
        "source_candidate": candidate_name,
        "not_applied_policy": candidate.get("not_applied_policy"),
        "rejection_reasons": [
            "stock cedo acima do envelope aprovado",
            "OTD/OTD-D abaixo de 100 apos validacao",
            "cria overlap de setup crew",
            "cria conflito de ferramenta",
            "cria violacao de capacidade",
        ],
    }


def _proposal_solver_next_steps(productivity_metrics: dict, candidate: dict) -> list[dict]:
    setup_saved = int(productivity_metrics.get("setup_count_saved", 0) or 0)
    earliness_delta = float(productivity_metrics.get("earliness_delta_days", 0.0) or 0.0)
    blockers = _proposal_approval_blockers(candidate, limit=3)
    if setup_saved <= 0 or earliness_delta <= 0 or not blockers:
        return []

    targets = [_proposal_action_target(blocker) for blocker in blockers]
    return [
        {
            "step": "lns_split_repair",
            "description": (
                "Executar LNS local: dividir apenas campanhas que geram stock cedo "
                "e reparar entrega antes de aceitar a produtividade."
            ),
            "targets": targets,
            "objective": "reduzir earliness mantendo a maior parte dos setups poupados",
            "validation_order": [
                "hard_gates",
                "delivery_gate",
                "earliness_policy",
                "productivity_gain",
            ],
            "reject_if": [
                "tardy_count > 0",
                "otd < 100",
                "otd_d < 100",
                "setup_crew_overlaps > 0",
                "tool_conflicts > 0",
                "day_cap_violations > 0",
            ],
            "fallback": "manter plano atual plenamente confiavel",
        },
        {
            "step": "capacity_guard",
            "description": (
                "Se o split reduzir stock cedo mas criar atraso, testar horas extra, "
                "subcontrato ou maquina alternativa antes de propor aplicacao."
            ),
            "targets": targets,
            "objective": "recuperar OTD/OTD-D sem propor segunda equipa de setup",
            "validation_order": [
                "capacity_action",
                "hard_gates",
                "delivery_gate",
                "productivity_gain",
            ],
            "reject_if": [
                "tardy_count > 0",
                "otd_d < 100",
                "hard_violations > 0",
            ],
            "fallback": "marcar inviavel nas condicoes atuais",
        },
    ]


def _productivity_approval_options(
    trace: dict,
    final_score: dict,
    primary_candidate: dict,
) -> list[dict]:
    search = trace.get("candidate_search") or {}
    candidates: list[dict] = []
    candidates.extend(search.get("near_applicable_productivity_frontier") or [])
    candidates.append(primary_candidate)

    options: list[dict] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        score = item.get("score") or {}
        if not name or name in seen:
            continue
        if not _is_fully_trusted_score(score):
            continue
        if not _has_setup_productivity_gain(score, final_score):
            continue
        seen.add(name)
        metrics = _productivity_delta_metrics(final_score, score)
        approval_metadata = _earliness_approval_metadata(score, final_score)
        options.append(
            {
                "id": f"{name}_approval_option",
                "source_candidate": name,
                "is_primary_target": name == str(primary_candidate.get("name") or ""),
                "decision_class": item.get("decision_class"),
                "reason": item.get("reason"),
                "before": _proposal_productivity_metrics(final_score),
                "after_target": _proposal_productivity_metrics(score),
                "productivity_metrics": metrics,
                "hard_gate_passed": _hard_violation_count(score) == 0,
                "delivery_gate_passed": not _delivery_regresses(score, final_score),
                "status": "requires_business_approval",
                "approval_action": "approve_productivity_earliness_ceiling",
                **approval_metadata,
            }
        )

    options = _pareto_productivity_frontier(options)
    options.sort(
        key=lambda item: (
            float(item.get("required_earliness_ceiling_days", 999.0) or 999.0),
            -float(
                (item.get("productivity_metrics") or {}).get(
                    "setup_minutes_saved",
                    0.0,
                )
                or 0.0
            ),
            float((item.get("after_target") or {}).get("setups", 999.0) or 999.0),
        )
    )
    return options[:4]


def _proposal_approval_blockers(candidate: dict, limit: int = 5) -> list[dict]:
    pressure = candidate.get("earliness_pressure")
    if not isinstance(pressure, dict):
        return []
    approval_metadata = _earliness_approval_metadata(candidate.get("score") or {})
    top_runs = pressure.get("top_runs") or []
    blockers: list[dict] = []
    for idx, run in enumerate(top_runs):
        if not isinstance(run, dict):
            continue
        gap_days = int(run.get("gap_days") or 0)
        if gap_days <= 0:
            continue
        lot_ids = [str(item) for item in run.get("lot_ids") or []][:8]
        skus = [str(item) for item in run.get("skus") or []][:8]
        machine_id = str(run.get("machine_id") or "")
        tool_id = str(run.get("tool_id") or "")
        blockers.append(
            {
                "id": f"early_stock_run_{idx + 1}",
                "reason": "stock_cedo_acima_politica",
                "severity": "high" if gap_days >= 14 else "medium",
                "run_id": str(run.get("run_id") or ""),
                "machine_id": machine_id,
                "tool_id": tool_id,
                "first_day_idx": run.get("first_day_idx"),
                "last_day_idx": run.get("last_day_idx"),
                "edd_min": run.get("edd_min"),
                "edd_max": run.get("edd_max"),
                "gap_days": gap_days,
                **approval_metadata,
                "setup_min": run.get("setup_min"),
                "prod_min": run.get("prod_min"),
                "lot_ids": lot_ids,
                "skus": skus,
            }
        )
        if len(blockers) >= limit:
            break
    return blockers


def _proposal_suggested_actions(candidate: dict, candidate_score: dict) -> list[dict]:
    blockers = _proposal_approval_blockers(candidate, limit=3)
    actions: list[dict] = []
    for blocker in blockers:
        target = _proposal_action_target(blocker)
        lot_count = len(blocker.get("lot_ids") or [])
        sku = (blocker.get("skus") or [""])[0]
        machine_id = str(blocker.get("machine_id") or "")
        tool_id = str(blocker.get("tool_id") or "")
        if lot_count > 1:
            actions.append(
                {
                    "action_type": "adjust_sequence",
                    "operation": "split_campaign",
                    "description": (
                        "Separar a campanha em lotes cedo/tarde para reduzir stock cedo, "
                        "mantendo a validacao de setups simultaneos, ferramenta, "
                        "capacidade e entrega."
                    ),
                    "target": target,
                    "expected_effect": "reduzir earliness sem esconder setups adicionais",
                    "requires_validation": True,
                }
            )
        if sku:
            actions.append(
                {
                    "action_type": "subcontract",
                    "operation": "subcontract_sku",
                    "description": (
                        f"Simular subcontrato de {sku} se a divisao da campanha criar atraso."
                    ),
                    "target": {**target, "sku": sku},
                    "expected_effect": "proteger OTD/OTD-D quando a sequencia fisica fica inviavel",
                    "requires_validation": True,
                }
            )
        if machine_id:
            actions.append(
                {
                    "action_type": "move_machine",
                    "operation": "move_to_alternative_machine",
                    "description": (
                        f"Testar maquina alternativa para {tool_id} em vez de {machine_id}."
                    ),
                    "target": target,
                    "expected_effect": "libertar a janela que obriga producao demasiado cedo",
                    "requires_validation": True,
                }
            )
        if len(actions) >= 5:
            break

    bottleneck = str(candidate_score.get("bottleneck_machine") or "")
    if bottleneck and len(actions) < 5:
        actions.append(
            {
                "action_type": "overtime",
                "operation": "add_overtime",
                "description": (
                    f"Simular horas extra em {bottleneck} para permitir sequencia mais JIT."
                ),
                "target": {"machine_id": bottleneck},
                "expected_effect": "criar folga de capacidade antes de aceitar mais setups",
                "requires_validation": True,
            }
        )
    return actions[:5]


def _proposal_action_target(blocker: dict) -> dict:
    return {
        "run_id": blocker.get("run_id"),
        "machine_id": blocker.get("machine_id"),
        "tool_id": blocker.get("tool_id"),
        "lot_ids": list(blocker.get("lot_ids") or []),
        "skus": list(blocker.get("skus") or []),
        "gap_days": blocker.get("gap_days"),
    }


def _proposal_entities_from_frontier(trace: dict) -> tuple[list[str], list[str]]:
    campaigns = _proposal_campaigns_from_frontier(trace)
    lot_ids: list[str] = []
    skus: list[str] = []
    for campaign in campaigns:
        for lot_id in campaign.get("lot_ids") or []:
            lot_ids.append(str(lot_id))
        for sku in campaign.get("skus") or []:
            skus.append(str(sku))
    return _unique(lot_ids)[:12], _unique(skus)[:12]


def _proposal_productivity_metrics(score: dict) -> dict:
    keys = (
        "otd",
        "otd_d",
        "tardy_count",
        "otd_d_failures",
        "setups",
        "setup_time_min",
        "earliness_avg_days",
        "planning_penalty",
        "hard_violations",
        "setup_crew_overlaps",
        "tool_conflicts",
        "day_cap_violations",
        "idle_capacity_min",
        "work_time_min",
        "machine_work_min",
        "bottleneck_machine",
    )
    return {key: score[key] for key in keys if key in score}


def _productivity_delta_metrics(before: dict, after: dict) -> dict:
    setup_minutes_saved = round(
        float(before.get("setup_time_min", 0.0) or 0.0)
        - float(after.get("setup_time_min", 0.0) or 0.0),
        1,
    )
    setup_count_saved = int(before.get("setups", 0) or 0) - int(
        after.get("setups", 0) or 0
    )
    work_minutes_released = round(
        float(before.get("work_time_min", 0.0) or 0.0)
        - float(after.get("work_time_min", 0.0) or 0.0),
        1,
    )
    idle_capacity_delta = round(
        float(after.get("idle_capacity_min", 0.0) or 0.0)
        - float(before.get("idle_capacity_min", 0.0) or 0.0),
        1,
    )
    earliness_delta = round(
        float(after.get("earliness_avg_days", 0.0) or 0.0)
        - float(before.get("earliness_avg_days", 0.0) or 0.0),
        1,
    )
    planning_penalty_delta = round(
        float(after.get("planning_penalty", 0.0) or 0.0)
        - float(before.get("planning_penalty", 0.0) or 0.0),
        1,
    )
    bottleneck = str(before.get("bottleneck_machine") or "")
    capacity_released_on_bottleneck = 0.0
    before_work = before.get("machine_work_min") or {}
    after_work = after.get("machine_work_min") or {}
    if bottleneck and isinstance(before_work, dict) and isinstance(after_work, dict):
        capacity_released_on_bottleneck = round(
            float(before_work.get(bottleneck, 0.0) or 0.0)
            - float(after_work.get(bottleneck, 0.0) or 0.0),
            1,
        )

    return {
        "setup_count_saved": setup_count_saved,
        "setup_minutes_saved": setup_minutes_saved,
        "work_minutes_released": work_minutes_released,
        "capacity_released_on_bottleneck_min": capacity_released_on_bottleneck,
        "idle_capacity_delta_min": idle_capacity_delta,
        "earliness_delta_days": earliness_delta,
        "planning_penalty_delta": planning_penalty_delta,
        "productivity_gain_min": max(0.0, setup_minutes_saved),
    }


def _proposal_machines_from_frontier(trace: dict) -> list[str]:
    machines: list[str] = []
    for campaign in _proposal_campaigns_from_frontier(trace):
        machine_id = campaign.get("machine_id") if isinstance(campaign, dict) else None
        if machine_id:
            machines.append(str(machine_id))
    return _unique(machines)[:8]


def _proposal_campaigns_from_frontier(trace: dict) -> list[dict]:
    campaigns = (
        ((trace.get("setup_frontier") or {}).get("final") or {}).get("top_split_campaigns")
        or []
    )
    return [campaign for campaign in campaigns if isinstance(campaign, dict)]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _build_solver_trace(
    *,
    mode: str,
    cfg: dict,
    baseline: ScheduleResult,
    final: ScheduleResult,
    elapsed_ms: float,
    final_source: str,
    candidate_search_trace: dict | None = None,
    local_repair_decisions: list[dict] | None = None,
    cp_sat_decisions: list[dict] | None = None,
) -> dict:
    baseline_score = baseline.score or {}
    final_score = final.score or {}
    baseline_setup_frontier = _setup_frontier_report(baseline)
    final_setup_frontier = _setup_frontier_report(final)
    return {
        "version": "cpo_v4_trust_loop",
        "mode": mode,
        "time_ms": round(elapsed_ms, 1),
        "final_source": final_source,
        "baseline": _score_snapshot(baseline_score),
        "final": _score_snapshot(final_score),
        "delta_vs_baseline": _score_delta(final_score, baseline_score),
        "setup_frontier": {
            "baseline": baseline_setup_frontier,
            "final": final_setup_frontier,
            "delta": _setup_frontier_delta(
                baseline_setup_frontier,
                final_setup_frontier,
            ),
        },
        "earliness_pressure": {
            "baseline": _earliness_pressure_report(baseline),
            "final": _earliness_pressure_report(final),
            "delta_vs_baseline": _score_delta(final_score, baseline_score),
        },
        "candidate_search": candidate_search_trace
        or {
            "mode": mode,
            "budget": int(cfg.get("candidate_budget", 0) or 0),
            "total_candidates": 0,
            "evaluated": 0,
            "accepted": 0,
            "rejected": 0,
            "errored": 0,
            "skipped_by_budget": 0,
            "delivery_repairs_skipped": 0,
            "frontier_exhausted": True,
            "coverage_pct": 100.0,
            "best_candidate": None,
            "best_rejected_productivity": None,
            "best_non_applied_productivity": None,
            "trusted_productivity_frontier": [],
            "near_applicable_productivity_frontier": [],
            "decision_class_counts": {},
            "local_repair_counts": {},
            "decisions": [],
        },
        "cp_sat": {
            "enabled": bool(cfg.get("cp_sat")),
            "time_per_machine_s": float(cfg.get("cp_sat_time_per_machine", 0.0) or 0.0),
            "decisions": cp_sat_decisions or [],
        },
        "local_repairs": {
            "decisions": local_repair_decisions or [],
        },
        "acceptance_policy": {
            "setup_crews": 1,
            "hard_gates": list(HARD_GATE_KEYS),
            "delivery_regression_keys": ["otd", "otd_d", *TRUST_DELIVERY_KEYS],
            "productivity_earliness_ceiling_days": float(
                final_score.get(
                    "productivity_earliness_ceiling_days",
                    PRODUCTIVITY_EARLINESS_CEILING_DAYS,
                )
                or PRODUCTIVITY_EARLINESS_CEILING_DAYS
            ),
            "rule": (
                "accept only strict trust-rank improvements with no hard "
                "or delivery regression"
            ),
        },
    }


def _setup_frontier_report(result: ScheduleResult) -> dict:
    score = result.score or {}
    setup_count = int(score.get("setups", 0) or 0)
    setup_time_min = float(score.get("setup_time_min", 0.0) or 0.0)

    run_pairs: dict[str, tuple[str, str]] = {}
    run_setup_min: dict[str, float] = defaultdict(float)
    run_details: dict[str, dict] = {}

    for seg in result.segments:
        if seg.end_min <= seg.start_min:
            continue
        start_abs, end_abs = segment_abs(seg)
        run_id = str(seg.run_id)
        pair = (str(seg.machine_id), str(seg.tool_id))
        run_pairs.setdefault(run_id, pair)
        run_setup_min[run_id] = max(run_setup_min[run_id], float(seg.setup_min or 0.0))
        detail = run_details.setdefault(
            run_id,
            {
                "run_id": run_id,
                "machine_id": str(seg.machine_id),
                "tool_id": str(seg.tool_id),
                "start_abs": start_abs,
                "end_abs": end_abs,
                "first_day_idx": int(seg.day_idx),
                "last_day_idx": int(seg.day_idx),
                "setup_min": 0.0,
                "edd_min": int(seg.edd) if seg.edd else None,
                "edd_max": int(seg.edd) if seg.edd else None,
                "lot_ids": set(),
                "skus": set(),
            },
        )
        detail["start_abs"] = min(float(detail["start_abs"]), start_abs)
        detail["end_abs"] = max(float(detail["end_abs"]), end_abs)
        detail["first_day_idx"] = min(int(detail["first_day_idx"]), int(seg.day_idx))
        detail["last_day_idx"] = max(int(detail["last_day_idx"]), int(seg.day_idx))
        detail["setup_min"] = max(float(detail["setup_min"]), float(seg.setup_min or 0.0))
        if seg.edd:
            edd = int(seg.edd)
            detail["edd_min"] = (
                edd if detail["edd_min"] is None else min(detail["edd_min"], edd)
            )
            detail["edd_max"] = (
                edd if detail["edd_max"] is None else max(detail["edd_max"], edd)
            )
        if seg.lot_id:
            detail["lot_ids"].add(str(seg.lot_id))
        if seg.sku:
            detail["skus"].add(str(seg.sku))

    setup_run_pairs = {
        run_id: pair
        for run_id, pair in run_pairs.items()
        if run_setup_min.get(run_id, 0.0) > 0.0
    }
    pair_runs: dict[tuple[str, str], set[str]] = defaultdict(set)
    tool_runs: dict[str, set[str]] = defaultdict(set)
    for run_id, pair in setup_run_pairs.items():
        pair_runs[pair].add(run_id)
        tool_runs[pair[1]].add(run_id)

    fixed_assignment_lb = len(pair_runs)
    tool_only_lb = len(tool_runs)
    observed_run_count = len(setup_run_pairs)
    if setup_count <= 0:
        setup_count = observed_run_count
    if setup_time_min <= 0:
        setup_time_min = round(sum(run_setup_min.values()), 1)

    split_campaigns = []
    for (machine_id, tool_id), run_ids in pair_runs.items():
        run_count = len(run_ids)
        if run_count <= 1:
            continue
        details = [
            run_details[run_id]
            for run_id in run_ids
            if run_id in run_details
        ]
        first_day_idx = min((int(item["first_day_idx"]) for item in details), default=None)
        last_day_idx = max((int(item["last_day_idx"]) for item in details), default=None)
        setup_min = round(sum(run_setup_min.get(run_id, 0.0) for run_id in run_ids), 1)
        split_campaigns.append(
            {
                "machine_id": machine_id,
                "tool_id": tool_id,
                "run_count": run_count,
                "excess_runs": run_count - 1,
                "setup_time_min": setup_min,
                "first_day_idx": first_day_idx,
                "last_day_idx": last_day_idx,
                "campaign_span_days": (
                    (last_day_idx - first_day_idx + 1)
                    if first_day_idx is not None and last_day_idx is not None
                    else None
                ),
                "lot_ids": _campaign_unique_values(details, "lot_ids")[:12],
                "skus": _campaign_unique_values(details, "skus")[:12],
                "runs": _campaign_run_summaries(details),
                "run_detail_truncated": len(details) > 6,
            }
        )
    split_campaigns.sort(
        key=lambda item: (
            -int(item["excess_runs"]),
            -float(item["setup_time_min"]),
            str(item["machine_id"]),
            str(item["tool_id"]),
        )
    )

    return {
        "setups": setup_count,
        "setup_time_min": round(setup_time_min, 1),
        "observed_run_count": observed_run_count,
        "fixed_assignment_lower_bound": fixed_assignment_lb,
        "tool_only_lower_bound": tool_only_lb,
        "excess_vs_fixed_assignment_lb": max(0, setup_count - fixed_assignment_lb),
        "excess_vs_tool_only_lb": max(0, setup_count - tool_only_lb),
        "split_campaign_count": len(split_campaigns),
        "top_split_campaigns": split_campaigns[:8],
    }


def _campaign_unique_values(details: list[dict], key: str) -> list[str]:
    values: list[str] = []
    for detail in sorted(details, key=_campaign_detail_sort_key):
        for value in detail.get(key) or []:
            values.append(str(value))
    return _unique(values)


def _earliness_pressure_report(result: ScheduleResult, limit: int = 8) -> dict:
    """Explain which runs contribute most to average earliness."""

    by_run: dict[str, list[Segment]] = defaultdict(list)
    for seg in result.segments:
        if seg.end_min > seg.start_min:
            by_run[str(seg.run_id)].append(seg)

    rows: list[dict] = []
    for run_id, segments in by_run.items():
        first_start = min(segment_abs(seg)[0] for seg in segments)
        first_day = min(int(seg.day_idx) for seg in segments)
        last_day = max(int(seg.day_idx) for seg in segments)
        edds = [int(seg.edd) for seg in segments if seg.edd]
        edd_min = min(edds) if edds else last_day
        edd_max = max(edds) if edds else last_day
        gap_days = max(0, edd_max - last_day)
        rows.append(
            {
                "run_id": run_id,
                "machine_id": str(segments[0].machine_id),
                "tool_id": str(segments[0].tool_id),
                "first_day_idx": first_day,
                "last_day_idx": last_day,
                "edd_min": edd_min,
                "edd_max": edd_max,
                "gap_days": gap_days,
                "setup_min": round(
                    sum(float(seg.setup_min or 0.0) for seg in segments),
                    1,
                ),
                "prod_min": round(
                    sum(float(seg.prod_min or 0.0) for seg in segments),
                    1,
                ),
                "lot_ids": _unique([str(seg.lot_id) for seg in segments if seg.lot_id])[
                    :8
                ],
                "skus": _unique([str(seg.sku) for seg in segments if seg.sku])[:8],
                "_first_start": first_start,
            }
        )

    rows.sort(
        key=lambda item: (
            -int(item["gap_days"]),
            -float(item["prod_min"]),
            -float(item["setup_min"]),
            float(item["_first_start"]),
            str(item["run_id"]),
        )
    )
    for row in rows:
        row.pop("_first_start", None)

    gap_rows = [row for row in rows if int(row["gap_days"]) > 0]
    return {
        "earliness_avg_days": (result.score or {}).get("earliness_avg_days"),
        "run_count": len(rows),
        "runs_with_gap": len(gap_rows),
        "total_gap_days": sum(int(row["gap_days"]) for row in rows),
        "top_runs": gap_rows[:limit],
    }


def _campaign_run_summaries(details: list[dict]) -> list[dict]:
    summaries: list[dict] = []
    for detail in sorted(details, key=_campaign_detail_sort_key)[:6]:
        summaries.append(
            {
                "run_id": detail.get("run_id"),
                "first_day_idx": detail.get("first_day_idx"),
                "last_day_idx": detail.get("last_day_idx"),
                "setup_min": round(float(detail.get("setup_min") or 0.0), 1),
                "edd_min": detail.get("edd_min"),
                "edd_max": detail.get("edd_max"),
                "lot_ids": sorted(str(item) for item in detail.get("lot_ids") or [])[:6],
                "skus": sorted(str(item) for item in detail.get("skus") or [])[:6],
            }
        )
    return summaries


def _campaign_detail_sort_key(detail: dict) -> tuple[float, str]:
    return (float(detail.get("start_abs") or 0.0), str(detail.get("run_id") or ""))


def _setup_frontier_delta(baseline: dict, final: dict) -> dict:
    setup_count_saved = int(baseline.get("setups", 0) or 0) - int(
        final.get("setups", 0) or 0
    )
    setup_minutes_saved = float(baseline.get("setup_time_min", 0.0) or 0.0) - float(
        final.get("setup_time_min", 0.0) or 0.0
    )
    fixed_excess_reduced = int(
        baseline.get("excess_vs_fixed_assignment_lb", 0) or 0
    ) - int(final.get("excess_vs_fixed_assignment_lb", 0) or 0)
    split_campaigns_reduced = int(baseline.get("split_campaign_count", 0) or 0) - int(
        final.get("split_campaign_count", 0) or 0
    )
    return {
        "setup_count_saved": setup_count_saved,
        "setup_minutes_saved": round(setup_minutes_saved, 1),
        "fixed_assignment_excess_reduced": fixed_excess_reduced,
        "split_campaigns_reduced": split_campaigns_reduced,
    }


def _candidate_decision(
    name: str,
    decision: str,
    reason: str,
    changes: dict[str, object],
    crew_priority: list[str] | None,
    candidate: ScheduleResult,
    incumbent: ScheduleResult,
    baseline: ScheduleResult,
    local_repair: dict | None = None,
) -> dict:
    score = candidate.score or {}
    payload = {
        "name": name,
        "decision": decision,
        "decision_class": _candidate_decision_class(
            decision,
            candidate.score or {},
            incumbent.score or {},
        ),
        "reason": reason,
        "changes": _jsonable_changes(changes),
        "crew_priority": list(crew_priority or []),
        "score": _score_snapshot(score),
        "delta_vs_incumbent": _score_delta(score, incumbent.score or {}),
        "delta_vs_baseline": _score_delta(score, baseline.score or {}),
        "earliness_pressure": _earliness_pressure_report(candidate),
    }
    if decision != "accepted":
        blocking_metrics = _candidate_blocking_metrics(score, incumbent.score or {})
        if blocking_metrics:
            payload["blocking_metrics"] = blocking_metrics
            payload["next_actions"] = _candidate_next_actions(
                str(payload["decision_class"]),
                blocking_metrics,
            )
    if local_repair is not None:
        payload["local_repair"] = _jsonable(local_repair)
    return payload


def _candidate_error_decision(
    name: str,
    changes: dict[str, object],
    crew_priority: list[str] | None,
    exc: Exception,
) -> dict:
    return {
        "name": name,
        "decision": "errored",
        "decision_class": "error",
        "reason": str(exc),
        "error_type": type(exc).__name__,
        "changes": _jsonable_changes(changes),
        "crew_priority": list(crew_priority or []),
    }


def _candidate_decision_class(
    decision: str,
    candidate_score: dict,
    reference_score: dict,
) -> str:
    if decision == "accepted":
        return "accepted"
    if _hard_violation_count(candidate_score) > 0:
        return "hard_gate"
    if _delivery_regresses(candidate_score, reference_score):
        return "delivery_gate"
    if _earliness_excess(candidate_score) > _earliness_excess(reference_score):
        return "earliness_envelope"
    if _has_setup_productivity_gain(candidate_score, reference_score):
        return "productivity_frontier"
    return "score_frontier"


def _candidate_blocking_metrics(
    candidate_score: dict,
    reference_score: dict,
) -> list[dict]:
    blockers: list[dict] = []

    for key in HARD_GATE_KEYS:
        value = int(candidate_score.get(key, 0) or 0)
        if value > 0:
            blockers.append(
                {
                    "gate": "hard",
                    "metric": key,
                    "value": value,
                    "required": 0,
                }
            )

    otd = float(candidate_score.get("otd", 0.0) or 0.0)
    required_otd = max(100.0, float(reference_score.get("otd", 0.0) or 0.0))
    if otd < required_otd:
        blockers.append(
            {
                "gate": "delivery",
                "metric": "otd",
                "value": round(otd, 3),
                "required": round(required_otd, 3),
            }
        )

    otd_d = float(candidate_score.get("otd_d", 0.0) or 0.0)
    required_otd_d = max(100.0, float(reference_score.get("otd_d", 0.0) or 0.0))
    if otd_d < required_otd_d:
        blockers.append(
            {
                "gate": "delivery",
                "metric": "otd_d",
                "value": round(otd_d, 3),
                "required": round(required_otd_d, 3),
            }
        )

    for key in TRUST_DELIVERY_KEYS:
        value = float(candidate_score.get(key, 0.0) or 0.0)
        reference = float(reference_score.get(key, 0.0) or 0.0)
        required = min(reference, 0.0)
        if value > reference or value > 0.0:
            blockers.append(
                {
                    "gate": "delivery",
                    "metric": key,
                    "value": _jsonable(round(value, 3)),
                    "required": _jsonable(round(required, 3)),
                    "reference": _jsonable(round(reference, 3)),
                }
            )

    earliness = float(candidate_score.get("earliness_avg_days", 0.0) or 0.0)
    if _earliness_excess(candidate_score) > _earliness_excess(reference_score):
        approval_metadata = _earliness_approval_metadata(candidate_score, reference_score)
        blockers.append(
            {
                "gate": "earliness_envelope",
                "metric": "earliness_avg_days",
                "value": round(earliness, 3),
                "required": approval_metadata["current_earliness_ceiling_days"],
                **approval_metadata,
            }
        )

    return blockers


def _candidate_next_actions(decision_class: str, blocking_metrics: list[dict]) -> list[dict]:
    metrics = {str(item.get("metric")) for item in blocking_metrics}
    gates = {str(item.get("gate")) for item in blocking_metrics}
    actions: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(action_type: str, operation: str, description: str) -> None:
        key = (action_type, operation)
        if key in seen:
            return
        seen.add(key)
        actions.append(
            {
                "action_type": action_type,
                "operation": operation,
                "description": description,
                "requires_validation": True,
            }
        )

    if "setup_crew_overlaps" in metrics:
        add(
            "adjust_sequence",
            "serialise_setups",
            "Serializar setups e revalidar com uma unica equipa de setup.",
        )
        add(
            "advance_lot",
            "advance_before_setup_peak",
            "Antecipar lotes que criam pico de setup para uma janela livre.",
        )

    if {"machine_overlaps", "tool_conflicts"} & metrics:
        add(
            "move_machine",
            "move_to_alternative_machine",
            "Testar maquina alternativa validada pela ferramenta.",
        )
        add(
            "adjust_sequence",
            "resequencing",
            "Reordenar a janela local para remover conflito fisico.",
        )

    if {
        "day_cap_violations",
        "blocked_machine_segments",
        "blocked_tool_segments",
        "ghost_segments",
    } & metrics:
        add(
            "advance_lot",
            "advance_before_blocked_or_full_day",
            "Mover carga para uma janela anterior com capacidade e recurso livre.",
        )

    if decision_class == "delivery_gate" or "delivery" in gates:
        add(
            "overtime",
            "add_overtime",
            "Simular horas extra na maquina gargalo antes de aceitar o candidato.",
        )
        add(
            "subcontract",
            "subcontract_late_sku",
            "Simular subcontrato para SKUs que ficam atrasados apos a reparacao.",
        )
        add(
            "move_machine",
            "move_to_alternative_machine",
            "Testar maquina alternativa para recuperar OTD/OTD-D.",
        )

    if decision_class == "earliness_envelope" or "earliness_envelope" in gates:
        add(
            "adjust_sequence",
            "split_campaign",
            "Dividir apenas campanhas que geram stock cedo excessivo.",
        )

    return actions[:5]


def _score_snapshot(score: dict) -> dict:
    return {key: _jsonable(score[key]) for key in SCORE_SNAPSHOT_KEYS if key in score}


def _score_delta(score: dict, reference: dict) -> dict:
    delta: dict[str, int | float] = {}
    for key in DELTA_SCORE_KEYS:
        if key not in score and key not in reference:
            continue
        current = score.get(key, 0) or 0
        previous = reference.get(key, 0) or 0
        if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
            continue
        diff = round(float(current) - float(previous), 3)
        if diff == 0:
            continue
        delta[key] = int(diff) if diff.is_integer() else diff
    return delta


def _jsonable_changes(changes: dict[str, object]) -> dict[str, object]:
    return {key: _jsonable(value) for key, value in sorted(changes.items())}


def _jsonable(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    return str(value)


def _preserves_trust(candidate: ScheduleResult, reference: ScheduleResult) -> bool:
    """True when candidate does not regress physical or delivery trust metrics."""

    c_score = candidate.score or {}
    r_score = reference.score or {}
    if _hard_violation_count(c_score) > 0:
        return False
    if _hard_violation_count(c_score) > _hard_violation_count(r_score):
        return False
    return not _delivery_regresses(c_score, r_score)


def _delivery_regresses(candidate_score: dict, reference_score: dict) -> bool:
    if _hard_violation_count(candidate_score) > _hard_violation_count(reference_score):
        return True
    if float(candidate_score.get("otd", 0.0) or 0.0) < float(
        reference_score.get("otd", 0.0) or 0.0
    ):
        return True
    if float(candidate_score.get("otd_d", 0.0) or 0.0) < float(
        reference_score.get("otd_d", 0.0) or 0.0
    ):
        return True
    for key in TRUST_DELIVERY_KEYS:
        if float(candidate_score.get(key, 0.0) or 0.0) > float(
            reference_score.get(key, 0.0) or 0.0
        ):
            return True
    return False


def _is_better_candidate(candidate: ScheduleResult, reference: ScheduleResult) -> bool:
    if not _preserves_trust(candidate, reference):
        return False
    return _trust_rank(candidate.score or {}) < _trust_rank(reference.score or {})


def _trust_rank(score: dict) -> tuple[float, ...]:
    """Feasibility-first rank: physics, delivery, then productivity."""

    return (
        float(_hard_violation_count(score)),
        float(score.get("tardy_count", 0) or 0),
        float(score.get("otd_d_failures", 0) or 0),
        -float(score.get("otd", 0.0) or 0.0),
        -float(score.get("otd_d", 0.0) or 0.0),
        float(score.get("total_tardiness", 0.0) or 0.0),
        float(score.get("max_tardiness", 0.0) or 0.0),
        _earliness_excess(score),
        _setup_minutes(score),
        float(score.get("setups", 0) or 0),
        float(score.get("planning_penalty", 0.0) or 0.0),
        float(score.get("earliness_avg_days", 0.0) or 0.0),
        _fitness_cost(score),
    )


def _earliness_excess(score: dict) -> float:
    earliness = float(score.get("earliness_avg_days", 0.0) or 0.0)
    ceiling = _earliness_ceiling(score)
    return max(0.0, earliness - ceiling)


def _earliness_ceiling(score: dict | None) -> float:
    score = score or {}
    return float(
        score.get(
            "productivity_earliness_ceiling_days",
            PRODUCTIVITY_EARLINESS_CEILING_DAYS,
        )
        or PRODUCTIVITY_EARLINESS_CEILING_DAYS
    )


def _earliness_approval_metadata(score: dict, reference_score: dict | None = None) -> dict:
    current_ceiling = _earliness_ceiling(
        score
        if "productivity_earliness_ceiling_days" in (score or {})
        else reference_score
    )
    earliness = float((score or {}).get("earliness_avg_days", 0.0) or 0.0)
    required_ceiling = max(current_ceiling, earliness)
    approval_gap = max(0.0, required_ceiling - current_ceiling)
    return {
        "approval_parameter": "productivity_earliness_ceiling_days",
        "current_earliness_ceiling_days": round(current_ceiling, 3),
        "required_earliness_ceiling_days": round(required_ceiling, 3),
        "approval_gap_days": round(approval_gap, 3),
    }


def _apply_score_policy(result: ScheduleResult, config: FactoryConfig) -> ScheduleResult:
    if result.score is not None:
        _apply_score_policy_to_score(result.score, config)
    return result


def _apply_score_policy_to_score(score: dict, config: FactoryConfig) -> None:
    score["productivity_earliness_ceiling_days"] = float(
        getattr(
            config,
            "productivity_earliness_ceiling_days",
            PRODUCTIVITY_EARLINESS_CEILING_DAYS,
        )
        or PRODUCTIVITY_EARLINESS_CEILING_DAYS
    )


def _strip_score_policy(result: ScheduleResult) -> ScheduleResult:
    if result.score is not None:
        result.score.pop("productivity_earliness_ceiling_days", None)
    return result


def _setup_minutes(score: dict) -> float:
    setup_time = float(score.get("setup_time_min", 0.0) or 0.0)
    if setup_time > 0:
        return setup_time
    return float(score.get("setups", 0) or 0) * 30.0


def _hard_violation_count(score: dict) -> int:
    aggregate = int(score.get("hard_violations") or 0)
    explicit = sum(int(score.get(key, 0) or 0) for key in HARD_GATE_KEYS)
    return max(aggregate, explicit)


def _candidate_rejection_reason(candidate: ScheduleResult, reference: ScheduleResult) -> str:
    regressions = _trust_regression_reasons(candidate.score or {}, reference.score or {})
    if regressions:
        return "; ".join(regressions[:3])
    if _trust_rank(candidate.score or {}) >= _trust_rank(reference.score or {}):
        return _score_frontier_reason(candidate.score or {}, reference.score or {})
    return "not accepted"


def _trust_regression_reasons(candidate_score: dict, reference_score: dict) -> list[str]:
    reasons: list[str] = []
    c_hard = _hard_violation_count(candidate_score)
    r_hard = _hard_violation_count(reference_score)
    if c_hard > 0:
        hard_metrics = [
            f"{key}={int(candidate_score.get(key, 0) or 0)}"
            for key in HARD_GATE_KEYS
            if int(candidate_score.get(key, 0) or 0) > 0
        ]
        detail = ", ".join(hard_metrics) if hard_metrics else f"hard_violations={c_hard}"
        reasons.append(f"hard gate violations: {detail}")
    elif c_hard > r_hard:
        reasons.append(f"hard_violations {c_hard} > {r_hard}")

    c_otd = float(candidate_score.get("otd", 0.0) or 0.0)
    r_otd = float(reference_score.get("otd", 0.0) or 0.0)
    if c_otd < r_otd:
        reasons.append(f"OTD {_format_metric(c_otd)} < {_format_metric(r_otd)}")

    c_otd_d = float(candidate_score.get("otd_d", 0.0) or 0.0)
    r_otd_d = float(reference_score.get("otd_d", 0.0) or 0.0)
    if c_otd_d < r_otd_d:
        reasons.append(f"OTD-D {_format_metric(c_otd_d)} < {_format_metric(r_otd_d)}")

    for key in TRUST_DELIVERY_KEYS:
        current = float(candidate_score.get(key, 0.0) or 0.0)
        previous = float(reference_score.get(key, 0.0) or 0.0)
        if current > previous:
            reasons.append(f"{key} {_format_metric(current)} > {_format_metric(previous)}")
    return reasons


def _score_frontier_reason(candidate_score: dict, reference_score: dict) -> str:
    c_excess = _earliness_excess(candidate_score)
    r_excess = _earliness_excess(reference_score)
    if c_excess > r_excess:
        return (
            "earliness envelope "
            f"{_format_metric(c_excess)}d > {_format_metric(r_excess)}d"
        )
    c_setup_min = _setup_minutes(candidate_score)
    r_setup_min = _setup_minutes(reference_score)
    if c_setup_min >= r_setup_min:
        return f"setup minutes {_format_metric(c_setup_min)} >= {_format_metric(r_setup_min)}"
    c_cost = _fitness_cost(candidate_score)
    r_cost = _fitness_cost(reference_score)
    if c_cost >= r_cost:
        return f"fitness cost {_format_metric(c_cost)} >= {_format_metric(r_cost)}"
    return "no score-frontier improvement"


def _format_metric(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _summarize_score(score: dict) -> str:
    return (
        f"OTD={float(score.get('otd', 0.0) or 0.0):.1f}%, "
        f"OTD-D={float(score.get('otd_d', 0.0) or 0.0):.1f}%, "
        f"tardy={int(score.get('tardy_count', 0) or 0)}, "
        f"setups={int(score.get('setups', 0) or 0)}, "
        f"earliness={float(score.get('earliness_avg_days', 0.0) or 0.0):.1f}d"
    )


def _format_changes(changes: dict[str, object]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(changes.items()))


def _build_local_machine_runs(
    engine_data: EngineData,
    config: FactoryConfig,
) -> dict[str, list]:
    """Build deterministic local windows for CP-SAT polish."""

    lots = create_lots(engine_data, config=config)
    runs = create_tool_runs(lots, config=config)
    return assign_machines(runs, engine_data, config=config)


def offline_ga_optimize(
    engine_data: EngineData,
    mode: str = "normal",
    config: FactoryConfig | None = None,
    seed: int | None = 42,
) -> ScheduleResult:
    """Offline GA/MAP-Elites experiment path.

    This is intentionally separate from `optimize()` so production planning stays
    proposal-based and gate-first. Use it for parameter studies, never direct
    plan application.
    """

    if config is None:
        config = FactoryConfig()
    if mode not in {"normal", "deep", "max"}:
        raise ValueError("offline_ga_optimize supports normal/deep/max only")

    ga_cfg = {
        "normal": {
            "pop_size": 20,
            "max_gen": 30,
            "time_budget": 15.0,
            "use_surrogate": False,
            "use_archive": True,
        },
        "deep": {
            "pop_size": 40,
            "max_gen": 100,
            "time_budget": 120.0,
            "use_surrogate": True,
            "use_archive": True,
        },
        "max": {
            "pop_size": 60,
            "max_gen": 300,
            "time_budget": 300.0,
            "use_surrogate": True,
            "use_archive": True,
        },
    }[mode]

    baseline = schedule_all(engine_data, config=config)
    lots = create_lots(engine_data, config=config)
    runs = create_tool_runs(lots, config=config)
    machine_runs = assign_machines(runs, engine_data, config=config)
    baseline_chrom = Chromosome.from_baseline(runs, machine_runs, config=config)

    rng = random.Random(seed)
    pipeline = CachedPipeline(engine_data, config)
    result = _ga_search(
        pipeline=pipeline,
        baseline_chrom=baseline_chrom,
        baseline_result=baseline,
        pop_size=ga_cfg["pop_size"],
        max_gen=ga_cfg["max_gen"],
        time_budget=ga_cfg["time_budget"],
        use_surrogate=ga_cfg["use_surrogate"],
        use_archive=ga_cfg["use_archive"],
        rng=rng,
    )
    assert_plan_valid(result.segments, engine_data, config)
    result.gate_report = build_gate_report(
        result.segments,
        result.lots,
        result.score,
        engine_data,
        config,
    )
    return result


def _fitness_cost(score: dict) -> float:
    """Compute cost from score. Lower is better.

    Feasibility-first: infeasible solutions get a large penalty.
    Earliness is heavily penalized above 6.5d (SOFT constraint threshold).
    """
    tardy = score.get("tardy_count", 0)
    otd_d_fail = score.get("otd_d_failures", 0)
    day_cap_fail = score.get("day_cap_violations", 0)
    hard_violations = score.get("hard_violations", 0)

    if tardy > 0 or otd_d_fail > 0 or day_cap_fail > 0 or hard_violations > 0:
        # Infeasible: large penalty proportional to violations
        return (
            10000.0
            + tardy * 100.0
            + otd_d_fail * 50.0
            + day_cap_fail * 200.0
            + hard_violations * 500.0
        )

    earliness = score.get("earliness_avg_days", 10.0)

    # Earliness penalty: quadratic above config threshold (default 5.5d)
    earl_threshold = score.get("_earliness_target", 5.5)
    earl_cost = earliness * 0.50
    if earliness > earl_threshold:
        earl_cost += (earliness - earl_threshold) ** 2 * 5.0

    # Setup cost: weighted by machine utilisation (bottleneck setups cost more)
    weighted_setup = score.get("weighted_setup_cost", 0.0)
    if weighted_setup > 0:
        setup_cost = weighted_setup * 0.015
    else:
        # Fallback: flat count (backward compat with non-CPO scores)
        setup_cost = score.get("setups", 200) * 0.20

    return earl_cost + setup_cost + score.get("planning_penalty", 0.0)


def _ga_search(
    pipeline: CachedPipeline,
    baseline_chrom: Chromosome,
    baseline_result: ScheduleResult,
    pop_size: int,
    max_gen: int,
    time_budget: float,
    use_surrogate: bool,
    use_archive: bool,
    rng: random.Random,
) -> ScheduleResult:
    """Core GA loop."""

    baseline_cost = _fitness_cost(baseline_result.score)
    best_cost = baseline_cost
    best_result = baseline_result

    # Initialize components
    op_names = list(OPERATORS.keys())
    frrmab = FRRMAB(op_names)
    archive = MAPElitesArchive() if use_archive else None
    one_fifth = OneFifthRule()
    surrogate = SurrogateModel() if use_surrogate else None

    # Insert baseline into archive
    if archive:
        archive.try_insert(baseline_chrom, baseline_result.score, baseline_cost)

    # Initial population: baseline + random mutations
    population: list[tuple[Chromosome, float]] = [(baseline_chrom, baseline_cost)]
    for _ in range(pop_size - 1):
        child = baseline_chrom.clone()
        # Apply 1-3 random mutations
        n_muts = rng.randint(1, 3)
        for _ in range(n_muts):
            op_name = rng.choice(op_names)
            op_fn = OPERATORS[op_name]
            child = op_fn(child, rng)
        population.append((child, float("inf")))  # unevaluated

    # Evaluate initial population
    for i, (chrom, cost) in enumerate(population):
        if cost == float("inf"):
            result = pipeline.evaluate(chrom)
            cost = _fitness_cost(result.score)
            population[i] = (chrom, cost)

            if surrogate:
                surrogate.add_sample(chrom, cost)
            if archive:
                archive.try_insert(chrom, result.score, cost)

            if cost < best_cost and result.score.get("tardy_count", 1) == 0:
                best_cost = cost
                best_result = result

    # Train surrogate on initial evals
    if surrogate and len(pipeline._fitness_cache) >= surrogate.min_samples:
        surrogate.train()

    t0 = time.perf_counter()
    stagnation_count = 0
    max_stagnation = max(10, max_gen // 5)  # escape after 10+ gens without improvement

    for gen in range(max_gen):
        if time.perf_counter() - t0 > time_budget:
            break
        if stagnation_count >= max_stagnation:
            logger.info("GA early stop: %d generations without improvement", stagnation_count)
            break

        gen_improved = 0

        for _ in range(pop_size):
            if time.perf_counter() - t0 > time_budget:
                break

            # Select operator (OneFifthRule: force strong mutation when stagnating)
            # Only activate after warmup (at least 2 full generations)
            if (
                one_fifth.rate < 0.15
                and len(one_fifth.history) >= one_fifth.history.maxlen
                and gen >= 2
            ):
                op_name = "mutate_strong"
            else:
                op_name = frrmab.select(rng)
            op_fn = OPERATORS[op_name]

            # Select parent(s)
            parent = tournament_select(population, k=3, rng=rng)

            # Apply operator
            child = op_fn(parent, rng)

            # Crossover: 30% chance
            if rng.random() < 0.30 and len(population) >= 2:
                parent2 = tournament_select(population, k=3, rng=rng)
                child = crossover_uniform(child, parent2, rng)

            # Check fitness cache
            h = child.compute_hash()
            if h in pipeline._fitness_cache:
                score, result = pipeline._fitness_cache[h]
                cost = _fitness_cost(score)
                pipeline.cache_hits += 1
            else:
                # Surrogate pre-screening
                if surrogate and surrogate.is_trained:
                    if not surrogate.should_evaluate(child, best_cost, threshold=1.5):
                        frrmab.update(op_name, 0.0)
                        continue

                # Full evaluation
                result = pipeline.evaluate(child)
                score = result.score
                cost = _fitness_cost(score)

                if surrogate:
                    surrogate.add_sample(child, cost)

            # Archive insertion
            if archive:
                archive.try_insert(child, score, cost)

            # FRRMAB reward
            improvement = max(0, best_cost - cost) / max(best_cost, 0.01)
            frrmab.update(op_name, improvement)

            # Track best
            improved = False
            if cost < best_cost and score.get("tardy_count", 1) == 0:
                best_cost = cost
                best_result = result
                improved = True
                gen_improved += 1

            one_fifth.record(improved)

            # Add to population
            population.append((child, cost))

        # Survivor selection: keep best pop_size
        population.sort(key=lambda x: x[1])
        population = population[:pop_size]

        # Track stagnation
        if gen_improved > 0:
            stagnation_count = 0
        else:
            stagnation_count += 1

        # Re-train surrogate periodically
        if surrogate and gen % 10 == 9:
            surrogate.train()

        if gen % 5 == 0:
            logger.debug(
                "Gen %d: best_cost=%.2f, evals=%d, cache_hits=%d, archive=%d",
                gen,
                best_cost,
                pipeline.eval_count,
                pipeline.cache_hits,
                archive.size() if archive else 0,
            )

    # Final: check archive for best
    if archive:
        archive_best = archive.best()
        if archive_best and archive_best.cost < best_cost:
            # Re-evaluate to get fresh result
            result = pipeline.evaluate(archive_best.chrom)
            if result.score.get("tardy_count", 0) == 0 and _fitness_cost(result.score) < best_cost:
                best_result = result

    logger.info(
        "GA done: %d evals, %d cache hits, %d generations",
        pipeline.eval_count,
        pipeline.cache_hits,
        min(max_gen, int(time.perf_counter() - t0)),
    )

    return best_result

"""Offline GA / MAP-Elites tuning experiment, outside the operational path.

Moved out of ``optimizer.py`` (plano-solver-2026-10-02 §6, phase 5): nothing
in the operational planner calls it. ``optimize()`` never runs a GA; this
module is kept for offline parameter experiments only.
"""

from __future__ import annotations

import logging
import random
import time

from backend.config.types import FactoryConfig
from backend.cpo.cached_pipeline import CachedPipeline
from backend.cpo.chromosome import OPERATORS, Chromosome, crossover_uniform
from backend.cpo.optimizer import _normalize_operational_result, _schedule_all_bounded
from backend.cpo.population import FRRMAB, MAPElitesArchive, OneFifthRule, tournament_select
from backend.cpo.surrogate import SurrogateModel
from backend.scheduler.dispatch import assign_machines
from backend.scheduler.gates import build_gate_report
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import ScheduleResult
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData

logger = logging.getLogger(__name__)


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

    baseline = _schedule_all_bounded(engine_data, config=config)
    lots = create_lots(engine_data, config=config)
    runs = create_tool_runs(
        lots,
        config=config,
        release_holidays=calendar_holidays(
            engine_data,
            -14,
            engine_data.n_days + 30,
        ),
    )
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
    result = _normalize_operational_result(
        result,
        engine_data,
        config,
    )
    assert_plan_valid(result.segments, engine_data, config, lots=result.lots)
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
    early_window_fail = score.get("early_window_violations", 0)
    dispatch_misses = score.get("subcontract_dispatch_misses", 0)
    dispatch_late = score.get("subcontract_dispatch_late_workdays", 0)

    if (
        tardy > 0
        or dispatch_misses > 0
        or otd_d_fail > 0
        or day_cap_fail > 0
        or hard_violations > 0
        or early_window_fail > 0
    ):
        # Infeasible: large penalty proportional to violations
        return (
            10000.0
            + tardy * 100.0
            + dispatch_misses * 150.0
            + dispatch_late * 25.0
            + otd_d_fail * 50.0
            + day_cap_fail * 200.0
            + hard_violations * 500.0
            + early_window_fail * 500.0
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

    latest_gap_cost = float(score.get("latest_start_gap_avg_min", 0.0) or 0.0) / 60.0
    return latest_gap_cost + earl_cost + setup_cost + score.get("planning_penalty", 0.0)

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

            if (
                cost < best_cost
                and result.score.get("tardy_count", 1) == 0
                and result.score.get("subcontract_dispatch_misses", 0) == 0
            ):
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
            if (
                cost < best_cost
                and score.get("tardy_count", 1) == 0
                and score.get("subcontract_dispatch_misses", 0) == 0
            ):
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
            if (
                result.score.get("tardy_count", 0) == 0
                and result.score.get("subcontract_dispatch_misses", 0) == 0
                and _fitness_cost(result.score) < best_cost
            ):
                best_result = result

    logger.info(
        "GA done: %d evals, %d cache hits, %d generations",
        pipeline.eval_count,
        pipeline.cache_hits,
        min(max_gen, int(time.perf_counter() - t0)),
    )

    return best_result

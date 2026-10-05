"""Compare the improvement cycle with the independent oracle (plan §8.2)."""

from __future__ import annotations

import random

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.improvement import anticipation_key, improve_plan
from backend.scheduler.priority import lot_priority_key
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, EOp, MachineInfo
from tests.oracle import DAY, Job, best_schedule, worst_order_schedule

WORKDAYS = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
SETUP_HOURS = (0.5, 1.0, 1.25)


def _instance(seed: int):
    rng = random.Random(seed)
    machines = ["M1", "M2"][: rng.choice([1, 2])]
    n_jobs = rng.choice([2, 3, 4])
    tools = [f"T{index}" for index in range(rng.choice([1, 2, n_jobs]))]
    ops, lots, jobs = [], [], {}
    for index in range(n_jobs):
        tool = rng.choice(tools)
        reference = f"{tool}-REF{rng.choice([0, 0, 1])}"
        eligible = tuple(rng.sample(machines, rng.choice([1, len(machines)])))
        qty = rng.choice([100, 300, 600, 900])
        setup_hours = rng.choice(SETUP_HOURS)
        due = rng.choice([2, 3, 4])
        release = rng.choice([0, 0, 1])
        op = EOp(
            id=f"OP{index}", sku=reference, client="C", designation=reference,
            m=eligible[0], t=tool, pH=100.0, sH=setup_hours, operators=1, eco_lot=0,
            alt=eligible[1] if len(eligible) > 1 else None, stk=0, backlog=0,
            d=[qty if day == due else 0 for day in range(len(WORKDAYS))], oee=1.0, wip=0,
        )
        lot = Lot(
            id=f"L{index}", op_id=op.id, sku=reference, tool_id=tool, machine_id=eligible[0],
            alt_machine_id=op.alt, qty=qty, prod_min=qty * 0.6, setup_min=setup_hours * 60,
            edd=due, is_twin=False, delivery_day=due, production_due_day=due,
            material_release_day=release,
        )
        ops.append(op)
        lots.append(lot)
        jobs[lot.id] = Job(lot.id, tool, reference, eligible, int(setup_hours * 60),
                           int(qty * 0.6), release, lot_priority_key(lot))
    data = EngineData(
        ops=ops, machines=[MachineInfo(m, "Grandes", 1020) for m in machines],
        twin_groups=[], client_demands={}, workdays=WORKDAYS, n_days=len(WORKDAYS),
    )
    config = FactoryConfig()
    config.machines = {m: MachineConfig(id=m, group="Grandes", oee=1.0) for m in machines}
    return data, config, lots, jobs


def _segments(placements, lots) -> list[Segment]:
    by_id = {lot.id: lot for lot in lots}
    rows = []
    for placement in placements:
        lot = by_id[placement.job]
        pieces = [("setup", s, e) for s, e in placement.setup]
        pieces += [("prod", s, e) for s, e in placement.production]
        split = []
        for kind, start, end in pieces:
            day = start // DAY
            boundary = day * DAY + 930
            if start < boundary < end:
                split += [(kind, start, boundary), (kind, boundary, end)]
            else:
                split.append((kind, start, end))
        produced, total_prod = 0, sum(e - s for k, s, e in split if k == "prod")
        prod_seen = 0
        for index, (kind, start, end) in enumerate(split):
            day, start_min = divmod(start, DAY)
            minutes = end - start
            if kind == "prod":
                prod_seen += minutes
                qty = round(lot.qty * prod_seen / total_prod) - produced
                produced += qty
            else:
                qty = 0
            rows.append(Segment(
                lot_id=lot.id, run_id=f"R-{lot.id}", machine_id=placement.machine,
                tool_id=lot.tool_id, day_idx=day, start_min=start_min,
                end_min=start_min + minutes, shift="A" if start_min < 930 else "B", qty=qty,
                prod_min=float(minutes if kind == "prod" else 0),
                setup_min=float(minutes if kind == "setup" else 0), sku=lot.sku, edd=lot.edd,
                lot_qty=lot.qty, run_qty=lot.qty, run_setup_min=lot.setup_min, run_lot_count=1,
                delivery_day=lot.delivery_day, production_due_day=lot.production_due_day,
                is_continuation=index > 0,
            ))
    return rows


SEEDS = range(40)


@pytest.mark.parametrize("seed", SEEDS)
def test_oracle_physics_is_accepted_by_the_validator(seed):
    data, config, lots, jobs = _instance(seed)
    _key, best = best_schedule(jobs)
    assert not validate_plan(_segments(best, lots), data, config, lots=lots)


def _gap(seed):
    data, config, lots, jobs = _instance(seed)
    oracle_key, _best = best_schedule(jobs)
    start = _segments(worst_order_schedule(jobs), lots)
    assert not validate_plan(start, data, config, lots=lots)
    improved, improved_lots, _report = improve_plan(start, lots, data, config, time_budget_s=20)
    assert not validate_plan(improved, data, config, lots=improved_lots)
    result = anticipation_key(improved, improved_lots)
    return result, oracle_key


@pytest.mark.parametrize("seed", SEEDS)
def test_cycle_never_beats_the_oracle_and_stays_valid(seed):
    result, oracle_key = _gap(seed)
    assert result >= oracle_key


# Known gap: the local CP-SAT model ignores retained mounts, so a 4-run
# reorder that keeps a successor's mount is not found (plan §12.1).
KNOWN_GAPS = {27}


@pytest.mark.parametrize("seed", SEEDS)
def test_no_oracle_schedule_is_preferred_to_the_cycle_result(seed):
    """Decisions of 03/10 (setup window) and 05/10 (anticipation tolerance):
    under the canonical preference, no schedule enumerated by the oracle is
    better than the plan the cycle returns."""
    from backend.scheduler.policy import anticipation_better

    from tests.oracle import all_vectors

    if seed in KNOWN_GAPS:
        pytest.xfail("N4 does not model retained mounts")
    data, config, lots, jobs = _instance(seed)
    start = _segments(worst_order_schedule(jobs), lots)
    improved, improved_lots, _report = improve_plan(start, lots, data, config, time_budget_s=20)
    result = anticipation_key(improved, improved_lots)
    better = [v for v in all_vectors(jobs, split_setup=False) if anticipation_better(v, result)]
    assert not better, better[0]

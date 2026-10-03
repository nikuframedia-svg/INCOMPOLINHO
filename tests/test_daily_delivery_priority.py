"""Delivery decisions must respect the date of an actual stock shortage."""

from backend.config.types import FactoryConfig
from backend.replan.jobs import _valid_delivery_floor
from backend.scheduler.priority import (
    delivery_improves,
    delivery_not_worse,
    delivery_priority_key,
)
from backend.scheduler.scoring import _compute_otd_d
from backend.scheduler.types import ScheduleResult
from backend.types import EOp, EngineData, MachineInfo


def _data() -> EngineData:
    return EngineData(
        ops=[EOp(
            id="urgent", sku="SKU", client="C", designation="SKU",
            m="M1", t="T1", pH=100, sH=0, operators=1, eco_lot=0,
            alt=None, stk=0, backlog=0, d=[100, 0, 100], oee=1, wip=0,
        )],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[], client_demands={}, workdays=[], n_days=3,
    )


def test_daily_shortfall_records_the_first_unmet_delivery():
    metrics = _compute_otd_d([], [], _data(), set())

    assert metrics["otd_d_daily_shortfall_qty"] == [100, 0, 200]
    assert metrics["otd_d_failures"] == 2


def test_day_zero_delivery_ranks_first_but_cannot_worsen_existing_lot_commitments():
    day_zero_covered = {
        "otd": 93.1, "otd_d": 98.7, "tardy_count": 14,
        "otd_d_failures": 9, "otd_d_daily_shortfall_qty": [0, 500, 0],
    }
    day_zero_missed = {
        "otd": 96.0, "otd_d": 93.8, "tardy_count": 8,
        "otd_d_failures": 42, "otd_d_daily_shortfall_qty": [4344, 0, 0],
    }

    assert delivery_priority_key(day_zero_covered) < delivery_priority_key(day_zero_missed)
    assert not delivery_improves(day_zero_covered, day_zero_missed)
    assert not delivery_not_worse(day_zero_missed, day_zero_covered)


def test_day_zero_delivery_wins_when_existing_commitments_are_preserved():
    earlier = {
        "otd": 96, "otd_d": 99, "tardy_count": 8, "otd_d_failures": 3,
        "otd_d_daily_shortfall_qty": [0, 200, 0],
    }
    later = {
        "otd": 96, "otd_d": 99, "tardy_count": 8, "otd_d_failures": 3,
        "otd_d_daily_shortfall_qty": [100, 0, 0],
    }

    assert delivery_improves(earlier, later)


def test_shortfall_improvement_cannot_accept_incomplete_or_more_late_lots():
    reference = {
        "otd": 75, "otd_d": 75, "tardy_count": 1,
        "otd_d_failures": 1, "hard_violations": 0,
        "otd_d_daily_shortfall_qty": [100, 0],
    }
    more_late = {
        **reference, "tardy_count": 2,
        "otd_d_daily_shortfall_qty": [50, 0],
    }
    incomplete = {
        **reference, "hard_violations": 1,
        "otd_d_daily_shortfall_qty": [50, 0],
    }

    assert not delivery_not_worse(more_late, reference)
    assert not delivery_not_worse(incomplete, reference)


def test_explicit_customer_priority_remains_before_daily_shortfall():
    protected = {
        "otd": 90, "otd_d": 90, "priority_tardy_count": 0,
        "otd_d_daily_shortfall_qty": [100, 0],
    }
    unprotected = {
        "otd": 90, "otd_d": 90, "priority_tardy_count": 1,
        "otd_d_daily_shortfall_qty": [0, 0],
    }

    assert delivery_improves(protected, unprotected)


def test_old_snapshot_score_uses_existing_metrics_until_recomputed():
    legacy = {"otd": 95, "otd_d": 95, "tardy_count": 2}
    new = {
        "otd": 90, "otd_d": 90, "tardy_count": 3,
        "otd_d_daily_shortfall_qty": [0, 0],
    }

    assert not delivery_not_worse(new, legacy)


def test_zero_shortfall_has_same_rank_with_or_without_new_metric():
    old = {"otd": 100, "otd_d": 100, "tardy_count": 0}
    new = {**old, "otd_d_daily_shortfall_qty": [0, 0, 0]}

    assert delivery_priority_key(old) == delivery_priority_key(new)


def test_valid_original_plan_remains_a_delivery_floor_without_compaction():
    data = EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=1,
    )
    result = ScheduleResult(
        segments=[], lots=[], score={"otd": 0}, time_ms=0,
        warnings=[], operator_alerts=[],
    )

    floor = _valid_delivery_floor(result, data, FactoryConfig())

    assert floor is not result
    assert floor.score["otd"] == 100.0
    assert floor.score["otd_d_daily_shortfall_qty"] == [0]

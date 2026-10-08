import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.global_jit import materialise_fixed_run
from backend.scheduler.improvement import physical_setups, production_windows
from backend.scheduler.priority_normalization import (
    classify_priority_order_anomalies,
    repair_priority_inversions,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ToolRun
from backend.types import EngineData, MachineInfo


DAY_CAPACITY = 1020


def _lot(
    lot_id: str,
    tool_id: str,
    sku: str,
    *,
    due: int,
    prod_min: int,
    setup_min: int,
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=lot_id,
        tool_id=tool_id,
        machine_id="M1",
        alt_machine_id=None,
        qty=prod_min,
        prod_min=float(prod_min),
        setup_min=float(setup_min),
        edd=due,
        is_twin=False,
        sku=sku,
        original_edd=due,
        delivery_day=due,
        production_due_day=due,
        material_release_day=0,
    )


def _run(run_id: str, lot: Lot, setup_min: int) -> ToolRun:
    return ToolRun(
        id=run_id,
        tool_id=lot.tool_id,
        machine_id="M1",
        alt_machine_id=None,
        lots=[lot],
        setup_min=float(setup_min),
        total_prod_min=lot.prod_min,
        total_min=float(setup_min) + lot.prod_min,
        edd=lot.edd,
        production_due_day=lot.production_due_day,
    )


def _case(*, urgent_due: int):
    config = FactoryConfig(
        machines={"M1": MachineConfig("M1", "Grandes")},
        setup_crews_by_group={"Grandes": 1},
    )
    data = EngineData(
        ops=[],
        machines=[MachineInfo("M1", "Grandes", DAY_CAPACITY)],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-01-{day:02d}" for day in range(5, 15)],
        n_days=10,
        holidays=[],
    )
    working_days = [day for day in range(data.n_days) if day not in {5, 6}]
    mounted = _lot(
        "MOUNTED",
        "VUL115",
        "VUL-SKU",
        due=0,
        prod_min=120,
        setup_min=60,
    )
    deferred = _lot(
        "DEFERRED",
        "VUL115",
        "VUL-SKU",
        due=7,
        prod_min=30,
        setup_min=60,
    )
    urgent = _lot(
        "URGENT",
        "JDE002",
        "JDE-SKU",
        due=urgent_due,
        prod_min=890,
        setup_min=60,
    )
    segments = [
        *materialise_fixed_run(
            _run("RUN-MOUNTED", mounted, 60),
            "M1",
            0,
            working_days,
            config,
        ),
        *materialise_fixed_run(
            _run("RUN-DEFERRED", deferred, 0),
            "M1",
            2 * DAY_CAPACITY,
            working_days,
            config,
        ),
        *materialise_fixed_run(
            _run("RUN-URGENT", urgent, 60),
            "M1",
            2 * DAY_CAPACITY + 30,
            working_days,
            config,
        ),
    ]
    return segments, [mounted, deferred, urgent], data, config


def _score(segments, lots, data, config):
    return compute_score(
        segments,
        lots,
        data,
        config=config,
        include_operational_audit=False,
    )


@pytest.mark.parametrize("urgent_due", [0, 2])
def test_earlier_urgent_start_is_applied_even_with_an_extra_setup(urgent_due):
    """Decision of 02/10/2026 (AGENTS.md §1.5): interrupting the retained
    campaign costs one more setup but starts URGENT two days earlier and keeps
    every order. It is applied, with or without a delivery gain; it used to be
    a trade-off waiting for a human decision."""
    segments, lots, data, config = _case(urgent_due=urgent_due)
    before = _score(segments, lots, data, config)

    detail = classify_priority_order_anomalies(segments, lots, data, config)
    repaired = repair_priority_inversions(segments, lots, data, config)

    anomaly = next(
        item
        for item in detail
        if item["urgent_lot_id"] == "URGENT"
        and item["blocking_lot_id"] == "DEFERRED"
    )
    assert anomaly["verification_status"] == "permutable"
    assert physical_setups(repaired).count == physical_setups(segments).count + 1
    old, new = production_windows(segments), production_windows(repaired)
    assert new["URGENT"][0] < old["URGENT"][0]
    after = _score(repaired, lots, data, config)
    assert after["hard_violations"] == 0
    assert after["otd"] >= before["otd"] and after["otd_d"] >= before["otd_d"]
    assert after["tardy_count"] <= before["tardy_count"]

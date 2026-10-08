"""Plain order-level data in the gate report (encomendas a tempo, atrasadas)."""

from __future__ import annotations

import json

from backend.config.types import FactoryConfig
from backend.scheduler.gates import LATE_ORDER_DETAIL_LIMIT, build_gate_report
from backend.scheduler.improvement import order_service
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo

N_DAYS = 12


def _op(op_id: str, sku: str, demand: dict[int, int]) -> EOp:
    d = [0] * N_DAYS
    for day, qty in demand.items():
        d[day] += qty
    return EOp(
        id=op_id, sku=sku, client="CLI", designation=sku, m="M1", t=f"T-{sku}",
        pH=100.0, sH=0.5, operators=1, eco_lot=0, alt=None, stk=0,
        backlog=0, d=d, oee=0.66, wip=0,
    )


def _entry(sku: str, client: str, day: int, qty: int) -> ClientDemandEntry:
    return ClientDemandEntry(
        client=client, sku=sku, day_idx=day, date="", order_qty=qty, np_value=-qty,
    )


def _data(ops: list[EOp], demands: dict[str, list[ClientDemandEntry]]) -> EngineData:
    return EngineData(
        ops=ops,
        machines=[MachineInfo("M1", "Grandes", 1020)],
        twin_groups=[],
        client_demands=demands,
        workdays=[f"2026-10-{day + 1:02d}" for day in range(N_DAYS)],
        n_days=N_DAYS,
    )


def _lot(lot_id: str, op_id: str, sku: str, qty: int, edd: int) -> Lot:
    return Lot(
        id=lot_id, op_id=op_id, tool_id=f"T-{sku}", machine_id="M1",
        alt_machine_id=None, qty=qty, prod_min=60.0, setup_min=0.0, edd=edd,
        is_twin=False, sku=sku,
    )


def _seg(
    lot_id: str, sku: str, day: int, qty: int, start: int = 420, machine: str = "M1"
) -> Segment:
    return Segment(
        lot_id=lot_id, run_id=f"R-{lot_id}", machine_id=machine, tool_id=f"T-{sku}",
        day_idx=day, start_min=start, end_min=start + 60, shift="A", qty=qty,
        prod_min=60.0, setup_min=0.0, sku=sku,
    )


SCORE = {"otd": 50.0, "otd_d": 80.0, "tardy_count": 1}


def _scenario():
    """A on time, B two days late, C (past due, day 0) never fully covered."""

    data = _data(
        [_op("OP-A", "A", {4: 100}), _op("OP-B", "B", {3: 80}), _op("OP-C", "C", {0: 50, 6: 50})],
        {
            "A": [_entry("A", "X", 4, 100)],
            "B": [_entry("B", "Y", 3, 80)],
            "C": [_entry("C", "Z", 0, 50), _entry("C", "Z", 6, 50)],
        },
    )
    lots = [
        _lot("LA", "OP-A", "A", 100, 4),
        _lot("LB", "OP-B", "B", 80, 3),
        _lot("LC", "OP-C", "C", 70, 0),
    ]
    segments = [
        _seg("LA", "A", 2, 100),
        _seg("LB", "B", 5, 80),
        _seg("LC", "C", 7, 70, start=600),
    ]
    return segments, lots, data


def test_order_metrics_match_no_loss_order_service():
    segments, lots, data = _scenario()

    report = build_gate_report(segments, lots, dict(SCORE), data, FactoryConfig())

    service = order_service(segments, lots, data)
    late = [key for key, item in service.items() if item.tardiness > 0]
    metrics = report["metrics"]
    assert metrics["orders_total"] == len(service) == 4
    assert metrics["orders_late"] == len(late) == 3
    assert metrics["orders_on_time"] == 1
    assert metrics["order_otd"] == 25.0


def test_late_orders_detail_is_plain_and_sorted_with_never_covered_as_null():
    segments, lots, data = _scenario()

    report = build_gate_report(segments, lots, dict(SCORE), data, FactoryConfig())

    detail = report["late_order_detail"]
    json.dumps(report["late_order_detail"], allow_nan=False)
    assert detail == [
        # C day 6: only 20 of 50 ever produced -> never covered.
        {
            "client": "Z", "sku": "C", "machine_id": "M1", "order_qty": 50, "covered_qty": 0,
            "shortfall_qty": 50, "due_day": 6, "ready_day": None, "late_days": None,
        },
        # C day 0: already past due, covered on day 7.
        {
            "client": "Z", "sku": "C", "machine_id": "M1", "order_qty": 50, "covered_qty": 0,
            "shortfall_qty": 50, "due_day": 0, "ready_day": 7, "late_days": 7,
        },
        {
            "client": "Y", "sku": "B", "machine_id": "M1", "order_qty": 80, "covered_qty": 0,
            "shortfall_qty": 80, "due_day": 3, "ready_day": 5, "late_days": 2,
        },
    ]


def test_lot_based_delivery_fields_are_untouched():
    segments, lots, data = _scenario()
    score = dict(SCORE)

    report = build_gate_report(segments, lots, score, data, FactoryConfig())

    assert score == SCORE
    assert report["metrics"]["otd"] == 50.0
    assert report["metrics"]["tardy_count"] == 1
    assert "delivery_risk" in report["approval_reasons"]


def test_duplicate_orders_count_twice_and_list_is_capped():
    ops = [_op("OP-A", "A", {5: 10 * (LATE_ORDER_DETAIL_LIMIT + 5)})]
    entries = [_entry("A", "X", 5, 10) for _ in range(LATE_ORDER_DETAIL_LIMIT + 5)]
    data = _data(ops, {"A": entries})
    lots = [_lot("LA", "OP-A", "A", 10, 5)]

    report = build_gate_report(
        [_seg("LA", "A", 1, 10)], lots, dict(SCORE), data, FactoryConfig()
    )

    metrics = report["metrics"]
    assert metrics["orders_total"] == LATE_ORDER_DETAIL_LIMIT + 5
    assert metrics["orders_on_time"] == 1
    assert metrics["orders_late"] == LATE_ORDER_DETAIL_LIMIT + 4
    assert len(report["late_order_detail"]) == LATE_ORDER_DETAIL_LIMIT


def test_all_orders_on_time_and_report_without_data_still_builds():
    data = _data([_op("OP-A", "A", {4: 100})], {"A": [_entry("A", "X", 4, 100)]})
    lots = [_lot("LA", "OP-A", "A", 100, 4)]
    score = {"otd": 100.0, "otd_d": 100.0}

    report = build_gate_report([_seg("LA", "A", 2, 100)], lots, score, data, FactoryConfig())
    assert report["metrics"]["order_otd"] == 100.0
    assert report["metrics"]["orders_late"] == 0
    assert report["late_order_detail"] == []

    empty = build_gate_report([], [], score, None, FactoryConfig())
    assert "orders_total" not in empty["metrics"]
    assert empty["late_order_detail"] == []
    assert empty["long_production_detail"] == []


def test_long_production_reason_always_carries_its_detail_list():
    data = _data([_op("OP-A", "A", {9: 600})], {"A": [_entry("A", "X", 9, 600)]})
    lots = [_lot("LA", "OP-A", "A", 600, 9)]
    segments = [_seg("LA", "A", day, 100) for day in range(1, 7)]

    report = build_gate_report(
        segments, lots, {"otd": 100.0, "otd_d": 100.0}, data, FactoryConfig(max_run_days=4)
    )

    assert "long_production" in report["approval_reasons"]
    detail = report["long_production_detail"]
    assert isinstance(detail, list) and len(detail) == 1
    assert detail[0]["machine_id"] == "M1"
    assert detail[0]["sku"] == "A"
    assert detail[0]["workdays"] == 6
    assert detail[0]["limit_workdays"] == 4


def test_late_order_rows_name_the_machine_that_produces_the_order():
    """Main machine = most output up to the ready day; no output -> planned machine."""

    data = _data(
        [_op("OP-A", "A", {3: 100}), _op("OP-N", "N", {2: 40})],
        {"A": [_entry("A", "X", 3, 100)], "N": [_entry("N", "Y", 2, 40)]},
    )
    data.ops[1].m = "M3"
    lots = [_lot("LA1", "OP-A", "A", 30, 3), _lot("LA2", "OP-A", "A", 70, 3)]
    segments = [
        _seg("LA1", "A", 4, 30, machine="M1"),
        _seg("LA2", "A", 5, 70, machine="M2"),
        # After the ready day: must not decide the machine.
        _seg("LA1", "A", 9, 500, machine="M1"),
    ]

    report = build_gate_report(segments, lots, dict(SCORE), data, FactoryConfig())

    rows = {row["sku"]: row for row in report["late_order_detail"]}
    assert rows["A"]["ready_day"] == 5
    assert rows["A"]["machine_id"] == "M2"
    assert rows["N"]["ready_day"] is None
    assert rows["N"]["machine_id"] == "M3"

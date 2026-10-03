# Load modules that bind ``compute_score`` at import before any test patches it.
import backend.scheduler.transfer_consolidation  # noqa: F401
import copy
from collections import defaultdict
from dataclasses import replace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.operational_audit import _lower_priority_campaign_interruptions
from backend.scheduler.priority_normalization import repair_same_reference_interruptions
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, MachineInfo


def _case(*, twin=False):
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[], machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[],
        client_demands={}, workdays=[f"2026-09-{day:02d}" for day in range(14, 19)],
        n_days=5, holidays=[],
    )
    lots = [
        Lot(
            id=name, op_id="OP", tool_id="T1", machine_id="M1",
            alt_machine_id=None, qty=qty, prod_min=minutes, setup_min=30,
            edd=due, original_edd=due, sku="SKU", is_twin=twin,
            material_release_day=0,
            twin_outputs=[("OP", "SKU", qty), ("OP2", "SKU2", qty)] if twin else None,
        )
        for name, qty, minutes, due in [("URGENT", 107, 125, 2), ("LATER", 73, 90, 4)]
    ]
    segments = []
    for name, day, start, duration, setup, qty in [
        ("URGENT", 0, 420, 60, 30, 26),
        ("LATER", 1, 420, 90, 0, 73),
        ("URGENT", 1, 510, 40, 0, 34),
        ("URGENT", 1, 550, 55, 0, 47),
    ]:
        lot = next(lot for lot in lots if lot.id == name)
        segments.append(Segment(
            lot_id=name, run_id=f"RUN-{name}", machine_id="M1", tool_id="T1",
            day_idx=day, start_min=start, end_min=start + duration, shift="A",
            qty=qty, prod_min=duration - setup, setup_min=setup, sku="SKU",
            edd=lot.edd, original_edd=lot.original_edd, material_release_day=0,
            run_setup_min=30 if name == "URGENT" else 0,
            is_continuation=name == "URGENT" and day > 0,
            twin_outputs=[("OP", "SKU", qty), ("OP2", "SKU2", qty)] if twin else None,
        ))
    return segments, lots, data, config


def _totals(segments):
    result = defaultdict(float)
    for segment in segments:
        result[(segment.lot_id, "qty")] += segment.qty
        result[(segment.lot_id, "minutes")] += segment.prod_min
        result[(segment.lot_id, "setup")] += segment.setup_min
        for op, sku, qty in segment.twin_outputs or []:
            result[(segment.lot_id, op, sku)] += qty
    return dict(result)


def _occupied(segments):
    return {
        (s.machine_id, s.day_idx, minute)
        for s in segments for minute in range(s.start_min, s.end_min)
    }


@pytest.mark.parametrize("twin", [False, True])
def test_repairs_interrupted_reference_without_moving_setup_or_losing_output(twin):
    segments, lots, data, config = _case(twin=twin)
    original = copy.deepcopy(segments)
    assert_plan_valid(segments, data, config, lots=lots)
    assert len(_lower_priority_campaign_interruptions(segments, lots)) == 1

    result = repair_same_reference_interruptions(segments, lots, data, config)

    assert_plan_valid(result, data, config, lots=lots)
    assert _lower_priority_campaign_interruptions(result, lots) == []
    assert _totals(result) == _totals(segments)
    assert _occupied(result) == _occupied(segments)
    assert result[0] == segments[0]
    assert segments == original
    before = compute_score(segments, lots, data, config=config)
    after = compute_score(result, lots, data, config=config)
    assert after["otd"] >= before["otd"]
    assert after["otd_d"] >= before["otd_d"]
    assert repair_same_reference_interruptions(result, lots, data, config) == result


def test_does_not_reorder_across_a_new_setup():
    segments, lots, data, config = _case()
    segments[2] = replace(segments[2], setup_min=10, prod_min=30)
    assert repair_same_reference_interruptions(segments, lots, data, config) == segments


def test_repairs_multiple_independent_spans_in_one_pass():
    segments, lots, data, config = _case()
    second_lots = [replace(lot, id=lot.id + "2", op_id="OP2", tool_id="T2",
                           sku="SKU2") for lot in lots]
    second_segments = [
        replace(s, lot_id=s.lot_id + "2", run_id=s.run_id + "2", tool_id="T2",
                sku="SKU2", day_idx=s.day_idx + 2)
        for s in segments
    ]
    combined = segments + second_segments
    all_lots = lots + second_lots
    assert_plan_valid(combined, data, config, lots=all_lots)

    result = repair_same_reference_interruptions(combined, all_lots, data, config)

    assert _lower_priority_campaign_interruptions(result, all_lots) == []
    assert _totals(result) == _totals(combined)
    assert _occupied(result) == _occupied(combined)


def test_does_not_reorder_different_references_in_a_shared_setup_family():
    segments, lots, data, config = _case()
    lots[1] = replace(lots[1], op_id="OTHER", sku="OTHER", setup_family="SHARED")
    lots[0].setup_family = "SHARED"
    assert repair_same_reference_interruptions(segments, lots, data, config) == segments


@pytest.mark.parametrize("metric", ["otd", "otd_d"])
def test_independent_delivery_guards_reject_a_percentage_regression(monkeypatch, metric):
    segments, lots, data, config = _case()
    calls = 0

    def score(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"otd": 100, "otd_d": 100, metric: 99 if calls % 2 == 0 else 100}

    monkeypatch.setattr("backend.scheduler.scoring.compute_score", score)
    monkeypatch.setattr(
        "backend.scheduler.priority_normalization.delivery_not_worse", lambda *_args: True
    )
    assert repair_same_reference_interruptions(segments, lots, data, config) == segments


def test_repair_rejects_candidate_that_would_advance_production_before_release():
    source, lots, data, config = _case()
    for lot in lots:
        lot.setup_min = 0
    lots[0].material_release_day = 1
    segments = [
        replace(source[1], day_idx=0, start_min=420, end_min=510),
        replace(source[0], day_idx=1, start_min=420, end_min=545, prod_min=125,
                setup_min=0, run_setup_min=0, qty=107, material_release_day=1),
    ]
    assert_plan_valid(segments, data, config, lots=lots)
    assert repair_same_reference_interruptions(segments, lots, data, config) == segments

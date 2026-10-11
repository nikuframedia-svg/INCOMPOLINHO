"""Phase B4: validation work is shared, never changes the verdict.

B4.1: ``canonical.contract_lots`` memoises ``create_lots`` inside one planning
calculation. The entry is reused only for exactly equal lot-sizing inputs, so
results with the cache on (inside a planning scope) and off (outside) match.

B4.3: the protected-lot evaluation plan no longer deep-copies every candidate;
it copies only the segments the splice renames and never changes the
candidate itself.
"""

from __future__ import annotations

import copy
import gzip
import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.planning_control import planning_scope
from backend.plans import frozen
from backend.scheduler import canonical
from backend.scheduler.canonical import (
    contract_lots,
    preserved_lot_proofs,
    source_contract_violations,
)
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import CommittedSupply, EngineData, EOp, MachineInfo
from tests.test_delivery_views_agree import FIXTURES, OP_ID, START

ROOT = Path(__file__).resolve().parents[1]
REV121 = ROOT / "tests" / "fixtures" / "private" / "rev121.json.gz"


@pytest.fixture
def counted(monkeypatch):
    calls = []
    original = canonical.create_lots

    def counting(*args, **kwargs):
        calls.append(kwargs.get("quantity_material", True))
        return original(*args, **kwargs)

    monkeypatch.setattr(canonical, "create_lots", counting)
    return calls


def _violations_both_ways(segments, lots, data, config, **kwargs):
    off = source_contract_violations(segments, lots, data, config, **kwargs)
    with planning_scope(timeout_s=60.0):
        first = source_contract_violations(segments, lots, data, config, **kwargs)
        again = source_contract_violations(segments, lots, data, config, **kwargs)
    assert first == again == off
    return off


# ── B4.1: memoised canonical lots ────────────────────────────────────────


def test_contract_lots_equal_create_lots_and_are_reused_in_one_calculation(counted):
    _, _, data = FIXTURES["F5"]()
    config = FactoryConfig()
    with planning_scope(timeout_s=60.0):
        first = contract_lots(data, config)
        second = contract_lots(data, config)
    assert second is first
    assert first == create_lots(data, config)
    assert len(counted) == 1


def test_no_cache_outside_a_planning_calculation(counted):
    _, _, data = FIXTURES["F1"]()
    contract_lots(data, FactoryConfig())
    contract_lots(data, FactoryConfig())
    assert len(counted) == 2


@pytest.mark.parametrize("change", [
    "demand_in_place", "committed_supply", "holiday", "workday",
    "extra_workday", "config", "material_flag", "replaced_ops",
])
def test_any_lot_sizing_input_change_rebuilds(counted, change):
    _, _, data = FIXTURES["F5"]()
    config = FactoryConfig()
    with planning_scope(timeout_s=60.0):
        before = contract_lots(data, config)
        flag = True
        if change == "demand_in_place":
            data.ops[0].d[26] += 500
        elif change == "committed_supply":
            data.committed_supplies.append(CommittedSupply(
                OP_ID, "SKU", 1000, "", 0, "M1", "TOOL",
            ))
        elif change == "holiday":
            data.holidays.append(10)
        elif change == "workday":
            data.workdays[0] = "2026-08-30"
        elif change == "extra_workday":
            data.calendar_extra_workdays.append(-3)
        elif change == "config":
            config = replace(config, min_prod_min=config.min_prod_min + 5)
        elif change == "material_flag":
            flag = False
        elif change == "replaced_ops":
            data = copy.copy(data)
            data.ops = copy.deepcopy(data.ops)
            data.ops[0].pH = 750
        after = contract_lots(data, config, quantity_material=flag)
        assert after == create_lots(data, config, quantity_material=flag)
    assert len(counted) == 2
    assert after is not before


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_source_contract_identical_with_cache_on_and_off(name):
    segments, lots, data = FIXTURES[name]()
    config = FactoryConfig()
    # The view fixtures are not all material-valid; the verdict, whatever it
    # is, must not depend on the cache.
    _violations_both_ways(segments, lots, data, config)
    _violations_both_ways(segments, lots, data, config, require_current_material=True)
    # Too much production before the material of later deliveries is
    # released: the verdict and its details are the same with the cache.
    early = [replace(segment, day_idx=0) for segment in segments]
    found = _violations_both_ways(early, lots, data, config)
    assert any(item["field"] == "material_quantity" for item in found)
    resized = [replace(lots[0], qty=lots[0].qty + 1), *lots[1:]]
    assert _violations_both_ways(segments, resized, data, config)


def test_preserved_lot_credits_are_part_of_the_cache_identity(counted):
    segments, lots, data = FIXTURES["F2"]()
    config = FactoryConfig()
    plain = _violations_both_ways(segments, lots, data, config)
    preserved = copy.copy(data)
    preserved.preserved_lot_proofs = preserved_lot_proofs(segments, lots)
    credited = _violations_both_ways(segments, lots, preserved, config)
    assert plain == credited
    # The credited residual has different committed supplies, so it cannot
    # reuse the lots of the plain scenario (calls: off, on for each case).
    assert len(counted) == 4


@pytest.fixture(scope="module")
def rev121():
    if not REV121.exists():
        pytest.skip("private fixture rev121.json.gz absent")
    from backend.plans.serialize import assert_snapshot_integrity, deserialize_snapshot

    payload = json.loads(gzip.decompress(REV121.read_bytes()).decode("utf-8"))
    assert_snapshot_integrity(payload)
    restored = deserialize_snapshot(payload)
    return restored["engine_data"], restored["config"], restored["result"]


def test_rev121_validation_identical_with_cache_on_and_off(rev121):
    from backend.scheduler.canonical import result_validation_data
    from backend.scheduler.validation import validate_plan

    data, config, result = rev121
    view = result_validation_data(data, result)
    for kwargs in ({}, {"require_current_material": True}):
        assert _violations_both_ways(result.segments, result.lots, view, config, **kwargs) == []
    off = validate_plan(result.segments, view, config, lots=result.lots)
    with planning_scope(timeout_s=120.0):
        on = validate_plan(result.segments, view, config, lots=result.lots)
        on_again = validate_plan(result.segments, view, config, lots=result.lots)
    assert off == on == on_again
    # A broken plan reports the same violations either way.
    broken = copy.deepcopy(result.segments)
    first = min((s for s in broken if s.prod_min > 0), key=lambda s: (s.day_idx, s.start_min))
    first.qty += 10_000
    off = validate_plan(broken, view, config, lots=result.lots)
    with planning_scope(timeout_s=120.0):
        on = validate_plan(broken, view, config, lots=result.lots)
    assert off and off == on


# ── B4.3: the protected evaluation plan copies only what it renames ──────


def _frozen_case():
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    data = EngineData(
        ops=[EOp(
            id="OP1", sku="SKU1", client="C", designation="Part", m="M1", t="T1",
            pH=100, sH=.5, operators=2, eco_lot=0, alt=None, stk=0, backlog=0,
            d=[100, 0, 0, 0], oee=.66, wip=0,
        )],
        machines=[MachineInfo("M1", "Grandes", 1020)], twin_groups=[], client_demands={},
        workdays=["2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19"], n_days=4,
        holidays=[],
    )
    started = Lot("L1", "OP1", "T1", "M1", None, 100, 600, 30, 2, False, sku="SKU1")
    protected_segments = [
        Segment("L1", "R1", "M1", "T1", 0, 420, 510, "A", 10, 60, 30, sku="SKU1"),
    ]
    future = Lot("L2", "OP1", "T1", "M1", None, 50, 30, 30, 3, False, sku="SKU1")
    residual = [
        # Collides with the protected run id: the splice renames it.
        Segment("L2", "R1", "M1", "T1", 2, 420, 480, "A", 25, 30, 30, sku="SKU1"),
        Segment("L2", "R9", "M1", "T1", 3, 420, 480, "A", 25, 30, 30, sku="SKU1"),
    ]
    result = ScheduleResult(
        segments=[*protected_segments, *residual], lots=[started, future], score={},
        time_ms=0, warnings=[], operator_alerts=[],
    )
    return data, config, result, protected_segments, [started], residual, [future]


def _capture_evaluation_plan(monkeypatch, data, config, result, protected_segments,
                             protected_lots):
    captured = {}

    def improve_plan(segments, lots, *_args, evaluation_plan=None, **_kwargs):
        captured["evaluation_plan"] = evaluation_plan
        return segments, lots, {"moves_accepted": 0}

    monkeypatch.setattr("backend.scheduler.improvement.improve_plan", improve_plan)
    frozen.improve_preserving_protected_lots(
        result, data, copy.deepcopy(data), config, protected_segments, protected_lots,
        1, time_budget_s=5.0,
    )
    return captured["evaluation_plan"]


def test_protected_evaluation_plan_matches_the_deep_copy_splice(monkeypatch):
    data, config, result, protected_segments, protected_lots, residual, residual_lots = (
        _frozen_case()
    )
    evaluation_plan = _capture_evaluation_plan(
        monkeypatch, data, config, result, protected_segments, protected_lots,
    )
    before = copy.deepcopy((residual, residual_lots))
    segments, lots, view = evaluation_plan(residual, residual_lots)

    expected = copy.copy(result)
    expected.segments, expected.lots = copy.deepcopy(residual), copy.deepcopy(residual_lots)
    expected = frozen._splice_frozen_started_lots(
        expected, protected_segments, protected_lots,
    )
    assert segments == expected.segments
    assert lots == expected.lots
    assert view.preserved_lot_proofs == expected.preserved_lot_proofs
    # The candidate is unchanged; only the renamed segment was copied.
    assert (residual, residual_lots) == before
    assert {s.run_id for s in segments if s.lot_id == "L2"} == {"R1__replanned_1", "R9"}
    assert any(s is residual[1] for s in segments)
    assert not any(s is residual[0] for s in segments)


def test_nothing_protected_skips_the_copy(monkeypatch):
    data, config, result, *_ = _frozen_case()
    evaluation_plan = _capture_evaluation_plan(monkeypatch, data, config, result, [], [])
    segments, lots, view = evaluation_plan(result.segments, result.lots)
    assert segments is result.segments and lots is result.lots
    assert view == data  # the original inputs: no proofs to attach

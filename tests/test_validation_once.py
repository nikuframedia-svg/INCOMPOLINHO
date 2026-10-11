"""Phase B4: validation work is shared, never changes the verdict.

B4.1: ``canonical.contract_lots`` memoises ``create_lots`` inside one planning
calculation. The entry is reused only for exactly equal lot-sizing inputs, so
results with the cache on (inside a planning scope) and off (outside) match.

B4.2: ``validate_plan`` is memoised inside one planning calculation on the
exact content of the plan (every segment and lot field, in order), the
scenario and the configuration; ``compute_score(..., violations=)`` reuses a
verdict the caller already has. Results are identical with the memo on and
off, and the evaluator never validates a candidate a second time for its
score.

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
from backend.scheduler import validation
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.scheduler.validation import validate_plan, validation_counts
from backend.types import CommittedSupply, EngineData, EOp, MachineInfo
from tests.test_delivery_views_agree import FIXTURES, OP_ID

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
    assert _violations_both_ways(result.segments, result.lots, view, config) == []
    # Revision 121 was saved under material version 1 (twin cycles released
    # whole). Under the current contract (Fase B2) only its twin cycles break
    # their per-delivery windows, so it is a legacy plan to rebuild.
    from backend.scheduler.canonical import legacy_material_plan

    current = _violations_both_ways(
        result.segments, result.lots, view, config, require_current_material=True,
    )
    twins = {lot.id for lot in result.lots if lot.is_twin}
    assert current and {item["field"] for item in current} == {"material_quantity"}
    assert {item["lot_id"] for item in current} <= twins
    assert legacy_material_plan(result.lots, view, config)
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


# ── B4.2: each plan is validated once per calculation ───────────────────


def _overlapping(segments):
    """Same plan with the second productive block moved onto the first."""
    broken = copy.deepcopy(segments)
    productive = sorted((s for s in broken if s.prod_min > 0),
                        key=lambda s: (s.day_idx, s.start_min))
    first, second = productive[0], productive[1]
    second.day_idx, second.start_min = first.day_idx, first.start_min
    second.end_min = first.start_min + (second.end_min - second.start_min)
    second.machine_id = first.machine_id
    return broken


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_memo_is_transparent_and_validates_once(name):
    segments, lots, data = FIXTURES[name]()
    config = FactoryConfig()
    broken = _overlapping(segments)
    expected = [validate_plan(plan, data, config, lots=lots) for plan in (segments, broken)]
    assert expected[1], "the overlapping plan must be invalid"
    with planning_scope(timeout_s=60.0):
        for _ in range(3):
            got = [validate_plan(plan, data, config, lots=lots) for plan in (segments, broken)]
            assert got == expected
        assert validation_counts() == {"calls": 6, "validations": 2}
    # Outside a calculation there is no memo (and no counter).
    assert validation_counts() == {"calls": 0, "validations": 0}


def test_in_place_edit_after_validation_is_validated_again():
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    with planning_scope(timeout_s=60.0):
        clean = validate_plan(segments, data, config, lots=lots)
        overlapped = _overlapping(segments)
        # Same list and objects, edited in place to the overlapping plan.
        for segment, edited in zip(segments, overlapped):
            for field in ("day_idx", "start_min", "end_min", "machine_id"):
                setattr(segment, field, getattr(edited, field))
        after = validate_plan(segments, data, config, lots=lots)
        assert after == validation._validate_plan(segments, data, config, lots) != clean
        lots[0].qty += 1
        resized = validate_plan(segments, data, config, lots=lots)
        assert resized == validation._validate_plan(segments, data, config, lots) != after
        assert validation_counts()["validations"] == 3


def test_integer_and_float_minutes_never_share_an_entry():
    """Messages print the stored numbers: 420 and 420.0 are different texts."""
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    broken = _overlapping(segments)
    floats = copy.deepcopy(broken)
    for segment in floats:
        segment.start_min, segment.end_min = float(segment.start_min), float(segment.end_min)
    with planning_scope(timeout_s=60.0):
        as_int = validate_plan(broken, data, config, lots=lots)
        as_float = validate_plan(floats, data, config, lots=lots)
        assert validation_counts()["validations"] == 2
    assert as_int == validate_plan(broken, data, config, lots=lots)
    assert [str(item) for item in as_float] == [
        str(item) for item in validate_plan(floats, data, config, lots=lots)
    ]


def test_mutating_a_returned_verdict_never_changes_the_next_one():
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    broken = _overlapping(segments)
    expected = validate_plan(broken, data, config, lots=lots)
    with planning_scope(timeout_s=60.0):
        first = validate_plan(broken, data, config, lots=lots)
        first[0]["kind"] = "edited"
        first.clear()
        assert validate_plan(broken, data, config, lots=lots) == expected


@pytest.mark.parametrize("change", ["holiday", "machine_block", "proofs", "config"])
def test_scenario_and_config_are_part_of_the_identity(change):
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    with planning_scope(timeout_s=60.0):
        validate_plan(segments, data, config, lots=lots)
        if change == "holiday":
            data.holidays.append(min(s.day_idx for s in segments))
        elif change == "machine_block":
            data.machine_blocked_days = {"M1": {s.day_idx for s in segments}}
        elif change == "proofs":
            data = copy.copy(data)
            data.preserved_lot_proofs = preserved_lot_proofs(segments, lots)
        elif change == "config":
            config = replace(config, min_prod_min=config.min_prod_min + 5)
        changed = validate_plan(segments, data, config, lots=lots)
        assert validation_counts()["validations"] == 2
    assert changed == validate_plan(segments, data, config, lots=lots)


@pytest.mark.parametrize("field", ["output_milestones", "left_shift_blockers"])
def test_segment_explanation_fields_are_part_of_the_identity(field):
    """A frozen recalculation proves preserved lots over their whole segments.

    ``source_contract_violations`` fingerprints every field of a preserved
    lot's segments, explanation copies included, so changing only one of them
    can change the verdict. The memo must validate that plan again (review
    counterexample b3rev/cx/memo_proof.py).
    """
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    lots = copy.deepcopy(lots)
    lot = lots[0]
    lot.edd += 3  # preserved contract differs from today's source
    data = copy.copy(data)
    data.preserved_lot_proofs = preserved_lot_proofs(segments, lots)
    edited = copy.deepcopy(segments)
    segment = next(item for item in edited if item.lot_id == lot.id)
    if field == "output_milestones":
        segment.output_milestones = [{"note": "explanation copy changed"}]
    else:
        segment.left_shift_blockers = ["blocked_by_material_release"]
    direct = [
        validation._validate_plan(plan, data, config, lots)
        for plan in (segments, edited)
    ]
    assert direct[0] != direct[1], "the explanation field must change the proof"
    with planning_scope(timeout_s=60.0):
        got = [validate_plan(plan, data, config, lots=lots) for plan in (segments, edited)]
        assert validation_counts() == {"calls": 2, "validations": 2}
    assert got == direct


@pytest.mark.parametrize(
    "field, retype",
    [
        ("edd", float),
        ("is_continuation", int),
        ("run_qty", float),
        ("twin_outputs", "float_qty"),
    ],
)
def test_scalar_value_types_are_part_of_the_identity(field, retype):
    """``1`` and ``True``, ``5`` and ``5.0`` must not share a verdict.

    The preserved-lot proof (``schedule_fingerprint``, ``json.dumps``) tells
    them apart, so the true verdict can change. Review counterexample
    b3r2/rv/cx/memo_type.py: proven plan P1, a third plan replaces the
    per-lot proof cache, then P2 (P1 with one value of another type) must be
    validated again, never served P1's verdict.
    """
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    lots = copy.deepcopy(lots)
    lot = lots[0]
    lot.edd += 3  # preserved contract differs from today's source
    if retype == "float_qty":
        # P1 carries integer twin quantities; P2 the same numbers as floats.
        for item in segments:
            if item.lot_id == lot.id and not item.twin_outputs:
                item.twin_outputs = [(OP_ID, item.sku, int(item.qty))]
    data = copy.copy(data)
    data.preserved_lot_proofs = preserved_lot_proofs(segments, lots)
    retyped = copy.deepcopy(segments)
    segment = next(item for item in retyped if item.lot_id == lot.id)
    if retype == "float_qty":
        segment.twin_outputs = [
            (op, sku, float(qty)) for op, sku, qty in segment.twin_outputs
        ]
    else:
        setattr(segment, field, retype(getattr(segment, field)))
    other = copy.deepcopy(segments)
    next(item for item in other if item.lot_id == lot.id).output_milestones = [{"x": 1}]
    direct = validation._validate_plan(retyped, data, config, lots)
    assert direct != validation._validate_plan(segments, data, config, lots), (
        "the retyped value must change the preserved-lot proof"
    )
    with planning_scope(timeout_s=60.0):
        validate_plan(segments, data, config, lots=lots)
        validate_plan(other, data, config, lots=lots)
        got = validate_plan(retyped, data, config, lots=lots)
        assert validation_counts() == {"calls": 3, "validations": 3}
    assert got == direct


def test_lot_value_types_are_part_of_the_identity():
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    retyped = copy.deepcopy(lots)
    retyped[0].is_twin = int(retyped[0].is_twin)
    retyped[0].start_buffer_days = float(retyped[0].start_buffer_days)
    with planning_scope(timeout_s=60.0):
        validate_plan(segments, data, config, lots=lots)
        validate_plan(segments, data, config, lots=retyped)
        assert validation_counts() == {"calls": 2, "validations": 2}


def test_equal_explanation_fields_still_share_an_entry():
    segments, lots, data = FIXTURES["F5"]()
    config = FactoryConfig()
    data = copy.copy(data)
    data.preserved_lot_proofs = preserved_lot_proofs(segments, lots)
    with planning_scope(timeout_s=60.0):
        first = validate_plan(segments, data, config, lots=lots)
        again = validate_plan(copy.deepcopy(segments), data, config, lots=lots)
        assert validation_counts() == {"calls": 2, "validations": 1}
    assert first == again


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_score_with_precomputed_violations_is_the_same_score(name):
    segments, lots, data = FIXTURES[name]()
    config = FactoryConfig()
    for plan in (segments, _overlapping(segments)):
        violations = validate_plan(plan, data, config, lots=lots)
        for audit in (False, True):
            assert compute_score(
                plan, lots, data, config, include_operational_audit=audit,
                violations=violations,
            ) == compute_score(plan, lots, data, config, include_operational_audit=audit)


def test_score_with_precomputed_violations_does_not_validate(monkeypatch):
    segments, lots, data = FIXTURES["F5"]()
    violations = validate_plan(segments, data, FactoryConfig(), lots=lots)
    monkeypatch.setattr(
        validation, "_validate_plan",
        lambda *_a, **_k: pytest.fail("the score must reuse the given verdict"),
    )
    compute_score(segments, lots, data, FactoryConfig(), include_operational_audit=False,
                  violations=violations)


def test_improvement_validates_each_candidate_once_for_physics_and_score(monkeypatch):
    """The evaluator's score never re-validates the candidate it just checked."""
    from tests.test_anticipation_neighbourhood import _on_time_plan

    from backend.scheduler.improvement import improve_plan

    def run():
        segments, lots, data, config = _on_time_plan("A", "T1")
        return improve_plan(segments, lots, data, config)

    def comparable(outcome):
        segments, lots, report = outcome
        report = {key: value for key, value in report.items()
                  if key not in {"duration_ms", "allocation_cache"}}
        return segments, lots, report

    off = run()
    real = validation._validate_plan
    callers = []

    def spy(*args, **kwargs):
        import sys

        frame = sys._getframe(1)
        while frame.f_code.co_filename.endswith(("validation.py", "scoring.py")):
            frame = frame.f_back
        callers.append(frame.f_code.co_name)
        return real(*args, **kwargs)

    monkeypatch.setattr(validation, "_validate_plan", spy)
    with planning_scope(timeout_s=60.0):
        on = run()
        counts = validation_counts()
    assert comparable(on) == comparable(off)
    evaluated = on[2]["candidates_evaluated"]
    assert evaluated >= 1 and on[2]["moves_accepted"] == 1
    # Reference + every candidate: one physical validation each, no score one.
    assert callers.count("_physically_valid") <= evaluated + 1
    assert "_score_plan" not in callers
    assert counts["calls"] > counts["validations"] == len(callers)


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

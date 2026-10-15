"""Pins that no longer fit are released, never abort the plan (decisão de 15/10/2026).

At Incompol, on 15/10/2026, adding 07/12 as a holiday to revision 156 (five
lots pinned by hand on 02–04/12) was refused with «Plano inválido: 1
conflito.»: 43 940 pieces missing face à procura. The holiday had nothing to
do with it: every replan of that plan failed. A pinned lot that had not
started was frozen like history and credited as stock on day 0, so the
residual lot sizing used it for the first deliveries of its operation, sized
a lot with the pinned lot's id for the later ones and the splice dropped that
lot. A pinned lot is now a position (``ProtectedPlan.pinned``): credited on
the days of the deliveries it serves, dated by the current calendar, judged
against the current sizing.

Owner's decision: when a new input clashes with a lot pinned by hand, the
input is applied, the pin is released and the planner is told which lot and
why (``reconcile_manual_anchors``, the safety net of
``optimize_preserving_started_lots``); a candidate the validation refuses is
rejected, never aborts the optimiser (``retain``).
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backend.plans import frozen
from backend.plans.frozen import (
    RELEASED_ANCHOR_PREFIX,
    optimize_preserving_started_lots,
    reconcile_manual_anchors,
)
from backend.scheduler.canonical import result_validation_data
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import (
    PlanValidationError,
    demand_coverage_metrics,
    plan_anchor_violations,
    validate_plan,
)
from backend.types import PlanAnchor
from tests.snapshot_fixture import load_payload
from tests.test_quantity_campaigns import _config, _data, _op

LISBON = ZoneInfo("Europe/Lisbon")
# Before the first shift of the first day: nothing has started.
NOW = datetime(2026, 10, 7, 6, 0, tzinfo=LISBON)
EARLY, LATE, OTHER = "LOT_TA_M1_A_10", "LOT_TA_M1_A_24", "LOT_TB_M1_B_27"


def _plan():
    """A has two economic lots (deliveries on days 10 and 24); B is due on day 27."""
    data = _data([_op("A", "TA", {10: 600, 24: 600}, eco_lot=600), _op("B", "TB", {27: 600})])
    config = _config()
    return data, config, schedule_all(data, config=config)


def _anchor_at_its_place(data, result, lot_id):
    first = min(
        (s for s in result.segments if s.lot_id == lot_id and s.prod_min > 0),
        key=lambda s: (s.day_idx, s.start_min),
    )
    minute = int(first.start_min + first.setup_min)
    return PlanAnchor(
        lot_id, first.machine_id,
        f"{data.workdays[first.day_idx]}T{minute // 60:02d}:{minute % 60:02d}",
        "teste", "utilizador",
    )


def _rows(segments, lot_id):
    return sorted(
        (s.machine_id, s.day_idx, s.start_min, s.end_min, s.setup_min, s.qty)
        for s in segments if s.lot_id == lot_id
    )


def _released(warnings):
    return [w for w in warnings or [] if str(w).startswith(RELEASED_ANCHOR_PREFIX)]


# ── Root cause: a pinned lot is a position, not stock on day 0 ───────────────


def test_a_pinned_lot_is_credited_on_its_delivery_days_not_as_stock_on_day_0():
    """A_24 goes on with the tool A_10 mounted (no setup): A_10 is kept with
    it. Neither has started: both are positions, credited on their days."""
    data, config, result = _plan()
    data.plan_anchors = [_anchor_at_its_place(data, result, LATE)]

    protected = frozen._protected_plan(result, 0, data, config, now=NOW)
    assert protected.pinned == {EARLY, LATE}
    assert sorted(lot.id for lot in protected.lots) == [EARLY, LATE]

    snapshot = frozen._install_frozen_reservations(
        data, protected.segments, protected.lots, 0, config, protected.partial,
        pinned=protected.pinned,
    )
    try:
        supply = sorted((s.op_id, s.qty, s.available_day) for s in data.committed_supplies)
        assert supply == [("A", 600, 10), ("A", 600, 24)]
        # The residual sizes exactly the other lots of the complete sizing
        # (credited on day 0, the residual sized a lot "A_24" again).
        assert [lot.id for lot in create_lots(data, config)] == [OTHER]
    finally:
        frozen._restore_frozen_reservations(data, snapshot)


def test_a_pinned_lot_carries_no_preservation_proof():
    data, config, result = _plan()
    data.plan_anchors = [_anchor_at_its_place(data, result, LATE)]
    protected = frozen._protected_plan(result, 0, data, config, now=NOW)
    residual = copy.deepcopy(result)
    residual.segments = [s for s in residual.segments if s.lot_id != LATE]
    residual.lots = [lot for lot in residual.lots if lot.id != LATE]

    merged = frozen._splice_frozen_started_lots(
        residual, protected.segments, protected.lots, protected.partial, protected.pinned,
    )
    assert merged.preserved_lot_proofs == {}
    assert not validate_plan(
        merged.segments, result_validation_data(data, merged), config, lots=merged.lots,
    )


def _moved_plan():
    """A_24 moved by hand to day 21 at 07:00, after B: its own setup, pinned."""
    from backend.plans.manual_move import move_lot

    data, config, result = _plan()
    moved = move_lot(
        result.segments, result.lots, result.score, data, config,
        lot_id=LATE, target_day=21, target_start_min=420, now=NOW,
    )
    plan = copy.deepcopy(result)
    plan.segments, plan.lots = moved.segments, moved.lots
    data.plan_anchors = [_anchor_at_its_place(data, plan, LATE)]
    return data, config, plan


def test_a_replan_with_a_later_lot_pinned_keeps_every_lot_of_its_operation():
    """The synthetic twin of revision 156: credited as stock on day 0, the
    pinned A_24 covered the day-10 delivery, the residual sized a lot "A_24"
    for day 24, the splice dropped it and the plan lost 600 pieces
    (``source_missing_quantity``)."""
    data, config, plan = _moved_plan()
    assert next(s for s in _own_sorted(plan.segments, LATE)).setup_min > 0

    replanned = optimize_preserving_started_lots(data, config, plan, mode="quick", now=NOW)

    view = result_validation_data(data, replanned)
    assert not validate_plan(replanned.segments, view, config, lots=replanned.lots)
    assert demand_coverage_metrics(view, replanned.lots, config)["source_missing_qty"] == 0
    assert sorted(lot.id for lot in replanned.lots) == [EARLY, LATE, OTHER]
    assert _rows(replanned.segments, LATE) == _rows(plan.segments, LATE)
    assert [a.lot_id for a in data.plan_anchors] == [LATE]
    assert not _released(replanned.warnings)


def _own_sorted(segments, lot_id):
    return sorted((s for s in segments if s.lot_id == lot_id),
                  key=lambda s: (s.day_idx, s.start_min))


# ── Reconciliation before calculating ────────────────────────────────────────


def test_a_pin_on_a_machine_that_goes_down_that_day_is_released_with_a_notice():
    data, config, result = _plan()
    late, other = (_anchor_at_its_place(data, result, lot) for lot in (LATE, OTHER))
    data.plan_anchors = [late, other]
    day = min(s.day_idx for s in result.segments if s.lot_id == LATE)
    data.machine_blocked_intervals.setdefault("M1", []).append({
        "id": "avaria", "start_day": day, "start_min": 420, "end_day": day, "end_min": 600,
        "category": "Avaria", "reason": "teste",
    })

    notices = reconcile_manual_anchors(data, config, result, now=NOW)

    assert [a.lot_id for a in data.plan_anchors] == [OTHER]
    [notice] = notices
    when = f"{late.start_at[8:10]}/{late.start_at[5:7]} {late.start_at[11:16]}"
    assert notice.startswith(
        f"{RELEASED_ANCHOR_PREFIX} da Referência A · TA (M1), fixada para {when}: a M1 fica "
        f"indisponível no dia {data.workdays[day][8:10]}/{data.workdays[day][5:7]} "
        "das 07:00 às 10:00"
    )
    assert "LOT_" not in notice


def test_a_pin_still_possible_is_kept():
    data, config, result = _plan()
    data.plan_anchors = [_anchor_at_its_place(data, result, LATE)]
    assert reconcile_manual_anchors(data, config, result, now=NOW) == []
    assert [a.lot_id for a in data.plan_anchors] == [LATE]


def test_a_pin_on_a_day_that_is_no_longer_a_workday_is_released():
    data, config, result = _plan()
    data.plan_anchors = [_anchor_at_its_place(data, result, LATE)]
    day = min(s.day_idx for s in result.segments if s.lot_id == LATE)
    data.holidays = sorted({*data.holidays, day})

    [notice] = reconcile_manual_anchors(data, config, result, now=NOW)
    assert data.plan_anchors == []
    assert "deixou de ser dia de trabalho" in notice or "passou a feriado" in notice


def test_the_records_follow_the_released_anchors():
    from backend.plans.manual_edits import sync_manual_edits

    data, config, result = _plan()
    data.plan_anchors = [
        _anchor_at_its_place(data, result, LATE), _anchor_at_its_place(data, result, OTHER),
    ]
    state = SimpleNamespace(engine_data=data, manual_edits=[
        {"id": "e1", "lot_id": LATE}, {"id": "e2", "lot_id": OTHER},
    ])
    day = min(s.day_idx for s in result.segments if s.lot_id == LATE)
    data.machine_blocked_days.setdefault("M1", set()).add(day)

    reconcile_manual_anchors(data, config, result, now=NOW)
    sync_manual_edits(state)
    assert [edit["lot_id"] for edit in state.manual_edits] == [OTHER]


def test_released_pins_are_shown_as_plan_notices():
    from backend.api.data import _plan_notices

    data, config, result = _plan()
    notice = f"{RELEASED_ANCHOR_PREFIX} da Referência A · TA (M1), fixada para 30/10 08:00: x."
    notes = _plan_notices(result.segments, result.lots, data, config,
                          [notice, "Outra nota do cálculo."])
    assert notes[0] == notice
    assert "Outra nota do cálculo." not in notes
    # A later calculation does not inherit it.
    assert frozen.without_calculation_notes([notice, "Outra"]) == ["Outra"]


# ── retain(): a refused candidate is rejected, the optimiser goes on ─────────


def _dropping(result, lot_id):
    bad = copy.deepcopy(result)
    bad.segments = [s for s in bad.segments if s.lot_id != lot_id]
    bad.lots = [lot for lot in bad.lots if lot.id != lot_id]
    return bad


def test_retain_rejects_an_invalid_candidate_and_keeps_the_next_valid_one(caplog):
    from backend.planning_control import candidate_completed

    data, config, result = _plan()

    def optimizer(engine_data, **_kwargs):
        candidate_completed(_dropping(result, OTHER))
        return copy.deepcopy(result)

    with caplog.at_level(logging.INFO, logger="backend.plans.frozen"):
        replanned = optimize_preserving_started_lots(
            data, config, result, mode="quick", optimizer=optimizer, now=NOW,
        )
    assert sorted(lot.id for lot in replanned.lots) == [EARLY, LATE, OTHER]
    assert "Candidato completo rejeitado pela validação" in caplog.text
    assert "peça(s) em falta" in caplog.text


def test_no_valid_candidate_is_refused_with_its_conflicts():
    data, config, result = _plan()

    def optimizer(engine_data, **_kwargs):
        return _dropping(result, OTHER)

    with pytest.raises(PlanValidationError) as refused:
        optimize_preserving_started_lots(
            data, config, result, mode="quick", optimizer=optimizer, now=NOW,
        )
    assert any(v["kind"] == "source_missing_quantity" for v in refused.value.violations)


def test_the_safety_net_releases_the_pins_and_tries_once_more():
    """No valid plan with the pin and a conflict that names no lot: every pin
    is released, with a notice, and the calculation runs once more."""
    data, config, result = _plan()
    data.plan_anchors = [_anchor_at_its_place(data, result, LATE)]
    calls = []

    def optimizer(engine_data, **_kwargs):
        # The pinned lots are reserved (credited) in the residual data.
        calls.append(sorted(s.available_day for s in engine_data.committed_supplies))
        if len(calls) == 1:  # with the pin: a residual without B
            return _dropping(_dropping(result, LATE), OTHER)
        return copy.deepcopy(result)

    replanned = optimize_preserving_started_lots(
        data, config, result, mode="quick", optimizer=optimizer, now=NOW,
    )
    assert calls == [[10, 24], []]
    assert data.plan_anchors == []
    [notice] = _released(replanned.warnings)
    assert notice.startswith(f"{RELEASED_ANCHOR_PREFIX} da Referência A · TA (M1), fixada para ")
    assert "deixou de ter solução com o lote nesse sítio" in notice
    assert sorted(lot.id for lot in replanned.lots) == [EARLY, LATE, OTHER]


def test_the_safety_net_tries_only_once():
    data, config, result = _plan()
    data.plan_anchors = [_anchor_at_its_place(data, result, LATE)]
    calls = []

    def optimizer(engine_data, **_kwargs):
        calls.append(1)
        return _dropping(_dropping(result, LATE), OTHER)

    with pytest.raises(PlanValidationError):
        optimize_preserving_started_lots(
            data, config, result, mode="quick", optimizer=optimizer, now=NOW,
        )
    assert len(calls) == 2


# ── Real cases, Incompol 15/10/2026 (private snapshots) ─────────────────────

INCOMPOL_NOW = datetime(2026, 10, 15, 13, 31, tzinfo=LISBON)
JTE003_64 = "LOT_JTE003_PRM043_6800017267C.30_64"
JTE003_66 = "LOT_JTE003_PRM043_6800017267C.30_66"


def _rev156(*, holiday=None, outage=None):
    from backend.config.planning import synchronize_active_twin_groups
    from backend.plans.serialize import deserialize_snapshot
    from backend.transform.calendars import apply_calendars

    _, payload = load_payload("rev156")
    restored = deserialize_snapshot(payload)
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    if holiday:
        config.holidays.append(holiday)
    if outage:
        config.machine_unavailability = [*config.machine_unavailability, outage]
    synchronize_active_twin_groups(data, config.twins)
    apply_calendars(data, config)
    return data, config, result


def _assert_admissible(replanned, data, config):
    view = result_validation_data(data, replanned)
    assert not validate_plan(replanned.segments, view, config, lots=replanned.lots)
    assert not plan_anchor_violations(replanned.segments, data, config)
    metrics = replanned.gate_report["metrics"]
    assert metrics["lot_split_violations"] == 0
    assert metrics["source_missing_qty"] == 0
    assert replanned.gate_report["physical_gate_passed"]
    assert replanned.gate_report["coverage_gate_passed"]


def test_incompol_holiday_on_a_plan_with_pins_is_applied_and_keeps_the_pins():
    """Revision 156 + holiday 07/12 (refused on 15/10 with 43 940 pieces
    missing): applied, the five pins (02–04/12) stay where they were."""
    data, config, result = _rev156(holiday="2026-12-07")
    pinned = [anchor.lot_id for anchor in data.plan_anchors]
    assert len(pinned) == 5

    replanned = optimize_preserving_started_lots(
        data, config, result, audit=True, now=INCOMPOL_NOW,
    )

    _assert_admissible(replanned, data, config)
    assert [anchor.lot_id for anchor in data.plan_anchors] == pinned
    assert not _released(replanned.warnings)
    for lot_id in pinned:
        assert _rows(replanned.segments, lot_id) == _rows(result.segments, lot_id), lot_id


def test_incompol_outage_over_a_pin_releases_it_and_keeps_the_others():
    """Revision 156 + PRM043 down on 03/12 16:00–20:00, over JTE003 pinned at
    17:30 (and JTE003 pinned at 09:00 the next day, which goes on with its
    tool without a setup): both released with a notice, the other three kept."""
    outage = {
        "id": "teste-avaria", "resource": "PRM043", "start_at": "2026-12-03T16:00",
        "end_at": "2026-12-03T20:00", "category": "Avaria", "reason": "teste",
    }
    data, config, result = _rev156(outage=outage)
    before = [anchor.lot_id for anchor in data.plan_anchors]

    replanned = optimize_preserving_started_lots(
        data, config, result, audit=True, now=INCOMPOL_NOW,
    )

    _assert_admissible(replanned, data, config)
    kept = [anchor.lot_id for anchor in data.plan_anchors]
    assert kept == [lot_id for lot_id in before if lot_id not in {JTE003_64, JTE003_66}]
    for lot_id in kept:
        assert _rows(replanned.segments, lot_id) == _rows(result.segments, lot_id), lot_id
    notices = _released(replanned.warnings)
    assert len(notices) == 2
    assert all("Referência 6800017267C.30 · JTE003 (PRM043)" in notice for notice in notices)
    assert all("LOT_" not in notice for notice in notices)
    assert any(
        "fixada para 03/12 17:30: a PRM043 fica indisponível no dia 03/12" in notice
        for notice in notices
    )
    assert any("fixada para 04/12 09:00: seguia sem nova afinação" in n for n in notices)


def test_incompol_move_that_reorganises_around_earlier_pins_is_accepted():
    """Revision 154 (four lots pinned on 02–04/12): moving JTE001 to 07/12
    08:00 on PRM043 was refused, as was every move that needed the plan
    reorganised: the earlier pins were credited as stock on day 0 and the
    other lots of their operations (BFP125, JDE002, JTE003) failed the ISOP
    contract. Now accepted, with no late order and no split lot."""
    from backend.plans.manual_move import move_lot
    from backend.plans.serialize import deserialize_snapshot

    _, payload = load_payload("rev154")
    restored = deserialize_snapshot(payload)
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    day = [str(item)[:10] for item in data.workdays].index("2026-12-07")

    moved = move_lot(
        result.segments, result.lots, result.score, data, config,
        lot_id="LOT_JTE001_PRM043_6800016767A.10_57", target_day=day,
        target_machine="PRM043", target_start_min=480,
        now=datetime(2026, 10, 15, 13, 29, tzinfo=LISBON),
    )

    assert moved.gate_report["physical_gate_passed"]
    assert moved.gate_report["metrics"]["lot_split_violations"] == 0
    assert moved.score["tardy_count"] <= result.score["tardy_count"]
    assert not moved.delivery_warnings

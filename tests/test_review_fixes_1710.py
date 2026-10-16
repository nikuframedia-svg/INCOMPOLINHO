"""Review fixes of 17/10/2026 for the owner rule of 16/10/2026.

A started lot may change machine only when its machine became inactive or no
longer allowed; what it made stays as history; operations without an allowed
active machine are unmet demand with the notice «Sem máquina ativa».
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timezone

from backend.config.planning import NO_ACTIVE_MACHINE_PREFIX
from backend.plans import frozen
from backend.scheduler.canonical import result_validation_data, source_contract_violations
from tests.test_deactivate_machines import NOW, _lot_op, _op, _replan, _scenario, _snapshots, _valid


def _moved_off_m1():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", "M2", day=5)],
        {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5}},
    )
    moved_data, moved_config, moved, _warnings = _replan(
        data, config, baseline, {"machine_active": {"M1": False}},
    )
    assert {s.machine_id for s in moved.segments} == {"M1", "M2"}
    return data, config, baseline, moved_data, moved_config, moved


# ── #1: the source contract refuses a started lot moved off an allowed machine


def test_started_lot_moved_off_an_active_allowed_machine_breaks_the_source_contract():
    data, config, _baseline, moved_data, moved_config, moved = _moved_off_m1()
    # Judged where M1 is still active and allowed: the lot changed machine.
    view = result_validation_data(data, moved)
    violations = source_contract_violations(moved.segments, moved.lots, view, config)
    assert any(
        v["kind"] == "source_contract" and v["field"] == "machine_id" for v in violations
    ), violations
    # Where M1 is inactive the same plan stays valid.
    assert _valid(moved, moved_data, moved_config) == []


# ── #2: the commit guard refuses the same move ─────────────────────────────


def test_commit_guard_refuses_a_started_lot_moved_off_an_active_allowed_machine():
    data, config, baseline, moved_data, moved_config, moved = _moved_off_m1()
    [lot] = moved.lots
    # The candidate as it would be committed with M1 active and allowed.
    before, after = _snapshots(data, config, baseline, moved)
    assert frozen.historical_schedule_changes(before, after, now=NOW) == [lot.id]
    # With M1 deactivated (the candidate's own config) the move is accepted.
    before, after = _snapshots(moved_data, moved_config, baseline, moved)
    assert frozen.historical_schedule_changes(before, after, now=NOW) == []


def test_commit_guard_refuses_a_hand_moved_rest_on_the_alternative():
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", "M2", day=5)],
        {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5}},
    )
    [lot] = baseline.lots
    candidate = copy.deepcopy(baseline)
    later = [s for s in candidate.segments if (s.day_idx, s.start_min) > (1, 600)]
    assert later
    for segment in later:
        segment.machine_id = "M2"
    candidate.lots = [replace(candidate.lots[0], machine_id="M2")]
    before, after = _snapshots(data, config, baseline, candidate)
    assert frozen.historical_schedule_changes(before, after, now=NOW) == [lot.id]


# ── #3: the rest of a started lot may use the second allowed machine ───────


def test_rest_of_a_started_lot_uses_the_second_allowed_machine_when_the_first_is_full():
    data, config, baseline = _scenario(
        [
            _op("A", "M1", "T1", "M2", day=5),
            _op("X", "M1", "TX", day=5, qty=13000),
            _op("Z", "M3", "TZ", day=8, qty=200),
        ],
        {"T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5},
         "TX": {"primary": "M1", "setup_hours": 0.5},
         "TZ": {"primary": "M3", "setup_hours": 0.5}},
    )
    on_alt = [s for s in baseline.segments if _lot_op(baseline, s.lot_id) == "A"]
    assert {s.machine_id for s in on_alt} == {"M2"}, "fixture: A runs on its alternative"
    assert any(s.day_idx == 1 for s in on_alt)
    data, config, result, _warnings = _replan(
        data, config, baseline, {"tool_updates": {"T1": {"alt": "M3"}}},
    )
    assert _valid(result, data, config) == []
    rest = [
        s for s in result.segments
        if _lot_op(result, s.lot_id) == "A" and (s.day_idx, s.start_min) >= (1, 600)
    ]
    assert rest and {s.machine_id for s in rest} == {"M3"}
    assert max(s.day_idx for s in rest) <= 5  # A is due on day 5
    before, after = _snapshots(data, config, baseline, result)
    assert frozen.historical_schedule_changes(before, after, now=NOW) == []


# ── #4: a started lot that made nothing leaves the plan ────────────────────

SEVEN = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)  # 07:00 in Lisbon


def _setup_only_history(machine_active: bool):
    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", day=5), _op("B", "M2", "T2", day=8)],
        {"T1": {"primary": "M1"}, "T2": {"primary": "M2"}},
    )
    lot_a = next(lot for lot in baseline.lots if lot.op_id == "A")
    segments = [s for s in baseline.segments if s.lot_id == lot_a.id]
    others = [s for s in baseline.segments if s.lot_id != lot_a.id]
    first = min(segments, key=lambda s: (s.day_idx, s.start_min))
    setup = replace(
        first, day_idx=0, start_min=1410, end_min=1440, setup_min=30.0,
        prod_min=0.0, qty=0, twin_outputs=None, is_continuation=False,
    )
    # Production from day 1 at 420 with no setup of its own: the 30 minutes
    # the setup took move from the first segment to the last (same pieces).
    ordered = sorted(segments, key=lambda s: (s.day_idx, s.start_min))
    assert first.start_min == 420 and first.setup_min == 30
    rate = first.qty / first.prod_min
    shifted = []
    for segment in ordered:
        prod_min, end_min = segment.prod_min, segment.end_min
        if segment is first:
            prod_min += 30
        elif segment is ordered[-1]:
            prod_min, end_min = prod_min - 30, end_min - 30
        shifted.append(replace(
            segment, day_idx=segment.day_idx + 1, setup_min=0.0, end_min=end_min,
            prod_min=prod_min, qty=round(prod_min * rate), is_continuation=True,
        ))
    assert sum(s.qty for s in shifted) == lot_a.qty
    edited = copy.deepcopy(baseline)
    edited.segments = sorted(
        [*others, setup, *shifted], key=lambda s: (s.machine_id, s.day_idx, s.start_min),
    )
    updates = {} if machine_active else {"machine_active": {"M1": False}}
    config_copy, data_copy = copy.deepcopy(config), copy.deepcopy(data)
    from backend.api.replan import _apply_change, _sync_active_machines
    from backend.config.planning import apply_effective_planning_config

    for key, value in updates.items():
        _apply_change(key, value, config_copy, data_copy, config_copy.day_capacity_min)
    apply_effective_planning_config(data_copy, config_copy)
    warnings = _sync_active_machines(config_copy, data_copy)
    result = frozen.optimize_preserving_started_lots(
        data_copy, config_copy, copy.deepcopy(edited), mode="quick", now=SEVEN,
    )
    return data_copy, config_copy, edited, result, warnings, lot_a


def test_setup_only_started_lot_on_a_deactivated_machine_is_unmet_demand():
    data, config, edited, result, warnings, lot_a = _setup_only_history(False)
    assert _valid(result, data, config) == []
    assert any(w.startswith(NO_ACTIVE_MACHINE_PREFIX) for w in warnings)
    assert all(lot.op_id != "A" for lot in result.lots)
    assert not any(s.machine_id == "M1" for s in result.segments)
    before, after = _snapshots(data, config, edited, result)
    assert frozen.historical_schedule_changes(before, after, now=SEVEN) == []


def test_setup_only_started_lot_on_an_active_machine_keeps_its_size():
    data, config, edited, result, _warnings, lot_a = _setup_only_history(True)
    assert _valid(result, data, config) == []
    [kept] = [lot for lot in result.lots if lot.id == lot_a.id]
    assert kept.qty == lot_a.qty
    # Dropping it there would be a history change.
    dropped = copy.deepcopy(result)
    dropped.lots = [lot for lot in dropped.lots if lot.id != lot_a.id]
    dropped.segments = [s for s in dropped.segments if s.lot_id != lot_a.id]
    before, after = _snapshots(data, config, edited, dropped)
    assert lot_a.id in frozen.historical_schedule_changes(before, after, now=SEVEN)


# ── #5: only a deliberate planning refusal shows its own text ─────────────


def _run_job(monkeypatch, exc):
    from backend.replan import jobs

    data, config, baseline = _scenario(
        [_op("A", "M1", "T1", day=5)], {"T1": {"primary": "M1"}},
    )

    def refuse(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(jobs, "optimize_preserving_started_lots", refuse)
    monkeypatch.setattr(jobs, "optimize", refuse, raising=False)
    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    job = store.create("Teste", "fixture", 1)
    try:
        manager._run(
            job["id"], copy.deepcopy(data), copy.deepcopy(config), "fixture", 1,
            "Teste", {"id": "fixture"}, [], None, False, False, False,
        )
    finally:
        manager.executor.shutdown(wait=True)
    return store.get(job["id"])


def test_technical_value_error_with_accented_data_is_an_internal_error(monkeypatch):
    final = _run_job(monkeypatch, ValueError("could not convert string to float: 'Peças'"))
    assert final["code"] == "internal_error", final
    assert "Peças" not in str(final.get("causes"))


def test_planning_refusal_without_accents_shows_its_text(monkeypatch):
    from backend.scheduler.errors import PlanningRefusal

    final = _run_job(monkeypatch, PlanningRefusal("SKU desconhecido: X"))
    assert final["code"] == "refused", final
    assert "SKU desconhecido: X" in str(final.get("causes"))

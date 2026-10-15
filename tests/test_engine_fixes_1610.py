"""Engine fixes of 16/10/2026.

- One machine group per machine (``FactoryConfig.machine_group``), projected
  onto the engine list without duplicates.
- «Adicionar máquina MPR007» as Médias (15/10/2026 14:11:03Z, revision 163)
  was refused with «2 afinações em simultâneo para 1 equipa de afinação de
  Medias» between two setups of that morning, kept from the active plan:
  elapsed setups no longer reserve the crew, and reservations are never
  judged against each other.
- Pins released by a calculation the replan job discarded are still told.
- Manual moves do not inherit the notes of the previous calculation.
- «Soltar» with ``lot_ids=[]`` is refused; the stock shows the planned press.
"""

from __future__ import annotations

import copy
import time
from dataclasses import replace
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans import frozen
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, MachineInfo, PlanAnchor
from tests.test_frozen_planning import frozen_plan  # noqa: F401 - fixture
from tests.test_manual_move import manual_api_state  # noqa: F401 - fixture
from tests.test_replan_jobs import _late_active_plan, ready_replan  # noqa: F401 - fixture

# ── 1. One machine group ─────────────────────────────────────────────────────


def test_machine_group_is_the_configured_one_even_when_inactive():
    config = FactoryConfig(machines={
        "MPR007": MachineConfig("MPR007", "Medias", active=False),
        "PRM019": MachineConfig("PRM019", "Grandes"),
    })
    assert config.machine_group("MPR007") == "Medias"
    assert "MPR007" not in config.machine_groups
    assert config.machine_group("PRM042") == "Medias"  # legacy default
    assert config.machine_group("XPTO") == "Grandes"
    assert FactoryConfig().machine_group("PRM042") == "Medias"


def test_engine_machines_are_projected_from_the_config_without_duplicates():
    from backend.config.planning import apply_effective_planning_config

    config = FactoryConfig(machines={"MPR007": MachineConfig("MPR007", "Medias")})
    shared = MachineInfo("MPR007", "Grandes", 1020)
    data = EngineData(
        ops=[], machines=[shared, MachineInfo("MPR007", "Medias", 1020)],
        twin_groups=[], client_demands={}, workdays=[], n_days=0,
    )
    apply_effective_planning_config(data, config)
    assert [(m.id, m.group) for m in data.machines] == [("MPR007", "Medias")]
    assert shared.group == "Grandes"  # a shallow copy's object is left alone


# ── 2. Reserved setups are history ───────────────────────────────────────────


def _validation_data():
    return EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=5,
    )


def _reservation(index, machine, start, end):
    return {
        "id": f"frozen-prefix-{index}", "machine_id": machine, "tool_id": f"T{index}",
        "start_day": 0, "start_min": start, "end_day": 0, "end_min": end, "group": "Medias",
    }


def test_two_reservations_on_one_crew_are_not_a_conflict_but_still_block_new_setups():
    config = FactoryConfig(machines={
        "M1": MachineConfig("M1", "Medias"), "M2": MachineConfig("M2", "Medias"),
        "M3": MachineConfig("M3", "Medias"),
    })
    data = _validation_data()
    data.setup_crew_reservations = [
        _reservation(4, "M1", 480, 510), _reservation(5, "M2", 480, 540),
    ]
    assert not any(
        v["kind"] == "setup_crew_overlap" for v in validate_plan([], data, config)
    )
    new_setup = Segment("B", "RB", "M3", "TB", 0, 500, 600, "A", 10, 70, 30, sku="B")
    assert any(
        v["kind"] == "setup_crew_overlap" for v in validate_plan([new_setup], data, config)
    )


def test_today_the_crew_is_reserved_only_from_now(frozen_plan):  # noqa: F811
    data, config, baseline = frozen_plan
    snapshot = frozen._install_frozen_reservations(
        data, baseline.segments, baseline.lots, 1, config, now_min=440,
    )
    assert [(r["start_day"], r["start_min"], r["end_min"])
            for r in data.setup_crew_reservations] == [(1, 440, 450)]
    frozen._restore_frozen_reservations(data, snapshot)
    frozen._install_frozen_reservations(
        data, baseline.segments, baseline.lots, 1, config, now_min=460,
    )
    assert data.setup_crew_reservations == []


def test_reservation_only_load_is_capped_at_the_crew_capacity():
    from backend.scheduler.global_jit import _capped_profile

    assert _capped_profile([(0, 30), (0, 60), (90, 100)], 1) == [(0, 60, 1), (90, 100, 1)]
    assert _capped_profile([(0, 30), (10, 60)], 2) == [(0, 10, 1), (10, 30, 2), (30, 60, 1)]


def test_mpr007_added_as_medias_on_revision_163_is_not_refused(monkeypatch):
    """The 14:11:03Z job: MPR007 (6 operations in the ISOP, Grandes by the
    transform default) added as Médias, the existing engine entry regrouped as
    ``start_replan`` does. Refused before with a conflict made only of two
    setups of that morning (frozen-prefix-4, frozen-prefix-5)."""
    from backend import calendar as factory_calendar
    from backend.api.replan import _sync_active_machines
    from backend.config.loader import validate_config
    from backend.plans.serialize import deserialize_snapshot
    from backend.replan import jobs
    from tests.snapshot_fixture import load_payload

    _, payload = load_payload("rev163")
    now = datetime.fromisoformat("2026-10-15T14:11:03+00:00")
    monkeypatch.setattr(factory_calendar, "_wall_clock", lambda zone: now.astimezone(zone))
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, data = copy.deepcopy(restored["config"]), copy.deepcopy(restored["engine_data"])
    assert "MPR007" not in config.machines
    assert [m.group for m in data.machines if m.id == "MPR007"] == ["Grandes"]
    config.machines["MPR007"] = MachineConfig(id="MPR007", group="Medias", active=True)
    data.machines = [
        replace(m, group="Medias") if m.id == "MPR007" else m for m in data.machines
    ]
    assert validate_config(config, data) == []
    warnings = _sync_active_machines(config, data)

    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    dataset = restored["dataset_info"]
    job = store.create("Adicionar máquina MPR007", str(dataset["id"]), payload["plan_revision"])
    started = time.monotonic()
    try:
        manager._run(
            job["id"], data, config, str(dataset["id"]), payload["plan_revision"],
            "Adicionar máquina MPR007", copy.deepcopy(dataset), warnings,
            copy.deepcopy(payload), False, False, False,
        )
    finally:
        manager.executor.shutdown(wait=True)
    elapsed = time.monotonic() - started

    final = store.get(job["id"])
    assert "setup_crew_overlap" not in str(final.get("causes") or ""), final
    assert "afinações em simultâneo" not in str(final.get("error") or ""), final
    # The false conflict is gone. This ISOP (134 operations, 11 machines) sits
    # near the budget: on a loaded machine the job may still stop by time
    # (AGENTS §6), never with an invalid plan.
    assert final.get("code") != "invalid_plan", final
    assert final["status"] == "ready" or final.get("code") == "planning_timeout", final
    assert elapsed < jobs.REPLAN_TOTAL_BUDGET_S + 15


# ── 3. Replan budget ─────────────────────────────────────────────────────────


def test_replan_budget_is_80_seconds():
    from backend.replan import jobs

    assert jobs.REPLAN_TOTAL_BUDGET_S == 80.0


# ── 4. Pins released by a discarded calculation are told ─────────────────────


def test_the_ledger_remembers_pins_a_later_calculation_no_longer_sees():
    data = EngineData(
        ops=[], machines=[], twin_groups=[], client_demands={}, workdays=[], n_days=0,
    )
    data.plan_anchors = [PlanAnchor("L1", "M1", "2026-10-20T08:00"), PlanAnchor("L2", "M1",
                                                                              "2026-10-21T08:00")]
    lot = Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 0, False, sku="SKU1")
    assert frozen.released_anchor_notices_missing(data) == []
    with frozen.released_anchor_ledger():
        [notice] = frozen.release_anchors(data, [lot], {"L1": "a M1 fica indisponível"})
        assert frozen.release_anchors(data, [lot], {}) == []
        assert frozen.released_anchor_notices_missing(data) == [notice]
    assert frozen.released_anchor_notices_missing(data) == []


def test_a_pin_released_by_a_discarded_compaction_is_told(ready_replan, monkeypatch):  # noqa: F811
    from backend.plans.serialize import deserialize_snapshot, serialize_snapshot
    from backend.planning_control import planning_scope
    from backend.replan import jobs

    live, manager, _, result, _ = ready_replan
    _late, on_time = _late_active_plan(live, result)
    live.engine_data.plan_anchors = [PlanAnchor("L1", "M1", "2026-03-17T07:30")]
    monkeypatch.setattr(jobs, "_late_with_idle_capacity", lambda *_args: True)

    def compact(data, _config, plan, **_kwargs):
        frozen.release_anchors(data, plan.lots, {"L1": "a M1 fica indisponível"})
        raise ValueError("compaction rejected")

    monkeypatch.setattr(jobs, "compact_preserving_started_lots", compact)
    monkeypatch.setattr(
        jobs, "optimize_preserving_started_lots", lambda *_a, **_k: copy.deepcopy(on_time),
    )
    baseline = serialize_snapshot(live)
    job = manager.store.create("capacity released", "fixture", live.plan_revision)
    config = copy.deepcopy(live.config)
    config.operators[("Grandes", "A")] += 1
    with planning_scope(timeout_s=60.0, clock=lambda: 0.0):
        manager._run(
            job["id"], copy.deepcopy(live.engine_data), config,
            "fixture", live.plan_revision, "capacity released", copy.deepcopy(live.dataset_info),
            baseline_snapshot=baseline, reoptimize_relaxed_baseline=True,
        )
    current = manager.store.get(job["id"])
    assert current["status"] == "ready", current
    released = [w for w in current["warnings"] if w.startswith(frozen.RELEASED_ANCHOR_PREFIX)]
    assert len(released) == 1 and "a M1 fica indisponível" in released[0]
    candidate = deserialize_snapshot(manager.store.get_candidate(job["id"]))
    assert candidate["engine_data"].plan_anchors == []
    assert released[0] in candidate["result"].warnings


# ── 5–7. API ─────────────────────────────────────────────────────────────────


def test_a_manual_move_does_not_inherit_the_previous_calculation_notes(
    manual_api_state, monkeypatch,  # noqa: F811
):
    from backend.api.copilot import app
    from backend.copilot.state import state

    stale = f"{frozen.RELEASED_ANCHOR_PREFIX} da Referência X · T (M1), fixada para 03/12: x."
    state.warnings = [stale, "Tempo de melhoria esgotado: y.", "Nota do plano."]
    client = TestClient(app)
    body = {"lot_id": "LOT1", "target_day": 1, "target_machine": "M2"}
    preview = client.post("/api/data/plan/move-preview", json=body).json()
    applied = client.post("/api/data/plan/move-apply", json={
        **body, "candidate_id": preview["candidate_id"],
        "expected_revision": state.plan_revision, "confirm_delivery_risk": True,
        "reason": "Teste", "author": "pytest",
    })
    assert applied.status_code == 200, applied.text
    assert stale not in state.warnings
    assert not any(w.startswith("Tempo de melhoria esgotado") for w in state.warnings)
    assert "Nota do plano." in state.warnings


def test_release_with_an_empty_lot_list_is_refused(manual_api_state):  # noqa: F811
    from backend.api.copilot import app
    from backend.copilot.state import state

    state.engine_data.plan_anchors = [PlanAnchor("LOT1", "M1", "2026-03-17T07:30")]
    revision = state.plan_revision
    client = TestClient(app)
    empty = client.post("/api/data/manual-edits/release", json={
        "lot_ids": [], "expected_revision": revision,
    })
    assert empty.status_code == 400
    assert empty.json()["detail"] == (
        "lot_ids deve ter pelo menos um lote; omite-o para soltar todos."
    )
    assert state.plan_revision == revision
    assert [a.lot_id for a in state.engine_data.plan_anchors] == ["LOT1"]
    bad = client.post("/api/data/manual-edits/release", json={
        "lot_ids": [""], "expected_revision": revision,
    })
    assert bad.json()["detail"] == "lot_ids deve ser uma lista de lotes; omite-o para soltar todos."


def test_stock_shows_the_machines_the_plan_uses(manual_api_state, monkeypatch):  # noqa: F811
    from backend.api.copilot import app
    from backend.copilot.state import state

    assert state.stock_projections
    projection = state.stock_projections[0]
    op = next(op for op in state.engine_data.ops if op.id == projection.op_id)
    lot_ids = {lot.id for lot in state.lots if lot.op_id == op.id}
    planned = [s for s in state.segments if s.lot_id in lot_ids]
    assert planned and {s.machine_id for s in planned} == {op.m}
    later = replace(planned[-1], machine_id="MALT", day_idx=planned[-1].day_idx + 1)
    monkeypatch.setattr(state, "segments", [*state.segments, later])
    client = TestClient(app)

    row = next(r for r in client.get("/api/data/stock").json() if r["op_id"] == op.id)
    assert row["machines"] == [op.m, "MALT"]
    assert row["machine"] == f"{op.m} / MALT"
    detail = client.get(f"/api/data/stock/{projection.sku}").json()
    assert detail["machines"] == [op.m, "MALT"] and detail["machine"] == f"{op.m} / MALT"

    monkeypatch.setattr(state, "segments", [s for s in state.segments if s.lot_id not in lot_ids])
    row = next(r for r in client.get("/api/data/stock").json() if r["op_id"] == op.id)
    assert row["machines"] == [op.m] and row["machine"] == op.m


# ── 8. Lot label ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("tool", "expected"), [
    ("T1", "Referência SKU1 · T1 (M2)"), ("", "Referência SKU1 (M2)"),
])
def test_lot_label_names_the_tool_only_when_there_is_one(tool, expected):
    from backend.scheduler.validation import _lot_label

    lot = Lot("L1", "OP1", tool, "M1", None, 100, 60, 30, 0, False, sku="SKU1")
    assert _lot_label(lot, "M2") == expected

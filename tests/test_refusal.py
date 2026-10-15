"""One refusal format: concrete causes, never a bare count (decisão de 15/10/2026).

At Incompol, on 15/10/2026, moving JTE001 to 03/12 08:45 was refused with
«o plano reorganizado não cumpre as regras físicas ou de quantidade» and
adding 07/12 as a holiday with a browser alert «Plano inválido: 1 conflito.».
The validator had the conflicts in both cases; they were thrown away on the
way to the screen. Now every refusal carries ``causes`` (plain pt-PT), naming
the lots the planner pinned by hand.
"""

from __future__ import annotations

import ast
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from backend.plans.refusal import (
    MAX_CAUSES,
    causes_for_log,
    refusal_causes,
    refusal_detail,
    refusal_http,
)
from backend.scheduler.validation import PlanValidationError
from backend.types import PlanAnchor
from tests.snapshot_fixture import load_payload

ROOT = Path(__file__).resolve().parents[1]
LISBON = ZoneInfo("Europe/Lisbon")


def _data(anchors=()):
    return SimpleNamespace(
        plan_anchors=list(anchors),
        workdays=[f"2026-12-{day:02d}" for day in range(1, 11)],
        calendar_day_offset=0,
    )


def _lot(lot_id, sku, machine="PRM043"):
    return SimpleNamespace(id=lot_id, sku=sku, op_id=sku, twin_outputs=[], machine_id=machine)


def _overlap(lot_id="LOT_A", other="LOT_B", day=2):
    return {
        "kind": "machine_overlap", "message": "Máquina PRM043 com produções sobrepostas.",
        "lot_id": lot_id, "machine_id": "PRM043", "day_idx": day,
        "start_min": 525, "end_min": 990,
        "other": {"lot_id": other, "machine_id": "PRM043", "day_idx": day},
    }


def test_cause_says_where_and_when_with_the_reference_never_the_lot_id():
    lots = [_lot("LOT_A", "6800016767A.10"), _lot("LOT_B", "6800017267C.30")]
    [cause] = refusal_causes([_overlap()], _data(), lots=lots)
    assert cause.startswith("Máquina PRM043 com produções sobrepostas")
    assert "08:45–16:30" in cause
    assert "Referência 6800016767A.10 (PRM043)" in cause
    assert "LOT_" not in cause
    assert cause.endswith(".")


def test_cause_names_the_lot_pinned_by_hand_but_not_the_lot_being_moved():
    anchors = [
        PlanAnchor("LOT_A", "PRM043", "2026-12-03T08:45"),
        PlanAnchor("LOT_B", "PRM043", "2026-12-03T17:30"),
    ]
    lots = [_lot("LOT_A", "6800016767A.10"), _lot("LOT_B", "6800017267C.30")]
    [cause] = refusal_causes([_overlap()], _data(anchors), lots=lots, subject="LOT_A")
    assert "choca com a alteração manual da Referência 6800017267C.30 (PRM043)" in cause
    assert "fixada para 03/12 17:30" in cause
    assert "6800016767A.10 (PRM043) (fixada" not in cause


def test_physical_conflicts_come_before_bookkeeping_and_the_rest_is_counted():
    contract = {"kind": "source_contract", "message": "Contrato.", "lot_id": "LOT_X"}
    physical = [_overlap(day=day) for day in range(1, MAX_CAUSES + 3)]
    causes = refusal_causes([contract, *physical], _data())
    assert causes[0].startswith("Máquina PRM043")
    assert len(causes) == MAX_CAUSES + 1
    assert causes[-1] == "… e mais 3 conflitos."


def test_reservation_names_its_holder_lot():
    anchors = [PlanAnchor("LOT_B", "PRM043", "2026-12-04T09:00")]
    violation = {
        "kind": "machine_down", "message": "Máquina PRM043 indisponível entre 20:48 e 24:00.",
        "lot_id": "LOT_A", "day_idx": 2, "start_min": 1248, "end_min": 1430,
        "unavailability": {"lot_id": "LOT_B", "start_min": 1248, "end_min": 1440},
    }
    [cause] = refusal_causes([violation], _data(anchors), lots=[_lot("LOT_B", "X1")])
    assert "choca com a alteração manual da Referência X1 (PRM043)" in cause


def test_plan_validation_error_becomes_a_structured_http_refusal(monkeypatch):
    from backend.copilot.state import state

    monkeypatch.setattr(state, "engine_data", _data(), raising=False)
    monkeypatch.setattr(state, "lots", [], raising=False)
    refused = refusal_http(400, PlanValidationError([_overlap()]))
    assert refused.status_code == 400
    assert refused.detail["message"] == "Plano inválido: 1 conflito."
    assert refused.detail["code"] == "invalid_plan"
    assert refused.detail["causes"] and refused.detail["violations"]
    plain = refusal_http(400, ValueError("Data inválida."))
    assert plain.detail == "Data inválida."


def test_log_keeps_the_causes_not_only_the_count():
    line = causes_for_log(PlanValidationError([_overlap()]), _data())
    assert "Máquina PRM043 com produções sobrepostas" in line


def test_refusal_detail_keeps_causes_of_an_error_without_violations():
    error = ValueError("Não cabe.")
    error.causes = ["O lote precisa de 23,4 h seguidas."]
    assert refusal_detail(error)["causes"] == ["O lote precisa de 23,4 h seguidas."]


def test_master_data_refusal_reaches_the_api_with_its_causes():
    """Holidays, machines, tools, twins: the executor JSON keeps the causes."""
    from fastapi import HTTPException

    from backend.api.data import _exec_result

    with pytest.raises(HTTPException) as refused:
        _exec_result(json.dumps({
            "error": "Plano inválido: 1 conflito.", "code": "invalid_plan",
            "causes": ["Procura e lotes não reconciliam: 43940 peça(s) em falta."],
        }))
    assert refused.value.detail["causes"] == [
        "Procura e lotes não reconciliam: 43940 peça(s) em falta."
    ]
    with pytest.raises(HTTPException) as plain:
        _exec_result(json.dumps({"error": "Feriado 2026-12-07 já existe."}))
    assert plain.value.detail == "Feriado 2026-12-07 já existe."


def test_no_api_handler_turns_an_error_into_bare_text():
    """``HTTPException(4xx, str(exc))`` drops the conflicts; use ``refusal_http``."""
    offenders = []
    for path in [*(ROOT / "backend" / "api").glob("*.py"), ROOT / "backend/plans/transactions.py"]:
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HTTPException"):
                continue
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Call) and getattr(
                node.args[1].func, "id", "",
            ) == "str":
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


@pytest.mark.parametrize("inconclusive", [False, True])
def test_move_job_returns_the_causes(monkeypatch, inconclusive):
    import threading

    from backend.plans import manual_move_jobs
    from backend.plans.manual_move import ManualMoveError, ManualMoveInconclusive

    error_type = ManualMoveInconclusive if inconclusive else ManualMoveError

    def refuse(*_args, **_kwargs):
        raise error_type("Não é possível iniciar o lote.", causes=["Causa concreta."])

    monkeypatch.setattr(manual_move_jobs, "move_lot", refuse)
    manager = manual_move_jobs.ManualMoveJobManager()
    manager.jobs["j"] = {"id": "j", "status": "queued"}
    manager._run(
        "j", threading.Event(), [], [], {}, None, None,
        "LOT", 1, "PRM043", 480, "", "planeador",
    )
    job = manager.get("j")
    assert job["status"] == "failed"
    assert job["causes"] == ["Causa concreta."]
    manager.executor.shutdown(wait=False)


# ── Real cases, Incompol 15/10/2026 (private snapshots) ─────────────────────


def _snapshot(name):
    from backend.plans.serialize import deserialize_snapshot

    _, payload = load_payload(name)
    return deserialize_snapshot(payload)


def test_incompol_refused_move_says_it_clashes_with_earlier_manual_changes():
    """Revision 154: JTE001 to 03/12 08:45 on PRM043, with JTE003 pinned at
    17:30 that day and at 09:00 the next, and the BFP125 twin at 16:30."""
    from backend.plans.manual_move import ManualMoveError, move_lot

    restored = _snapshot("rev154")
    result = restored["result"]
    with pytest.raises(ManualMoveError) as refused:
        move_lot(
            result.segments, result.lots, result.score,
            restored["engine_data"], restored["config"],
            lot_id="LOT_JTE001_PRM043_6800016767A.10_57", target_day=51,
            target_machine="PRM043", target_start_min=525,
            now=datetime(2026, 10, 15, 13, 29, tzinfo=LISBON),
        )
    causes = refused.value.causes
    assert causes, refused.value
    assert any("choca com a alteração manual" in cause for cause in causes)
    assert any("6800017267C.30" in cause for cause in causes)
    assert not any("LOT_" in cause for cause in causes)


def test_incompol_refused_holiday_says_which_rule_failed():
    """Revision 156 (8 manual edits) + holiday 07/12: one conflict, now named."""
    from backend.config.planning import synchronize_active_twin_groups
    from backend.plans.frozen import optimize_preserving_started_lots
    from backend.transform.calendars import apply_calendars

    restored = _snapshot("rev156")
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    config.holidays.append("2026-12-07")
    synchronize_active_twin_groups(data, config.twins)
    apply_calendars(data, config)
    try:
        optimize_preserving_started_lots(
            data, config, result, audit=True,
            now=datetime(2026, 10, 15, 13, 31, tzinfo=LISBON),
        )
    except PlanValidationError as error:
        causes = refusal_causes(error.violations, data, lots=result.lots)
        assert causes and all(cause.endswith(".") for cause in causes)
        assert "Plano inválido" not in " ".join(causes)
    # Accepted is fine too: the holiday then no longer clashes (later steps).


def test_broken_pin_is_named_by_reference_and_never_clashes_with_itself():
    """Review of 15/10: a pin that no longer holds said «LOT_…» and «choca com»
    its own manual change."""
    from backend.scheduler.types import Segment
    from backend.scheduler.validation import plan_anchor_violations

    data = _data([PlanAnchor("LOT_A", "PRM043", "2026-12-03T17:30")])
    moved = Segment(
        lot_id="LOT_A", run_id="R", machine_id="PRM043", tool_id="T", day_idx=2,
        start_min=420, end_min=600, shift="A", qty=10, prod_min=180.0, setup_min=0.0,
    )
    violations = plan_anchor_violations([moved], data, None)
    assert violations and "LOT_" not in violations[0]["message"]
    [cause] = refusal_causes(violations, data, lots=[_lot("LOT_A", "6800017267C.30")])
    assert "LOT_" not in cause
    assert "Referência 6800017267C.30 (PRM043)" in cause
    assert "choca com" not in cause


def test_a_pinned_conflicting_lot_is_said_once_to_be_a_manual_change():
    anchors = [PlanAnchor("LOT_A", "PRM043", "2026-12-03T08:45")]
    [cause] = refusal_causes([_overlap()], _data(anchors), lots=[_lot("LOT_A", "X")])
    assert "este lote é uma alteração manual (fixado para 03/12 08:45)" in cause
    assert "choca com a alteração manual da Referência X" not in cause


def test_remainder_counts_only_distinct_causes():
    same = [_overlap(day=1)] * 4
    distinct = [_overlap(day=day) for day in range(2, MAX_CAUSES + 3)]
    causes = refusal_causes([*distinct, *same], _data())
    assert causes[-1] == "… e mais 2 conflitos."


def test_move_refusal_headline_names_the_reference_and_the_date():
    from backend.plans.manual_move import _inconclusive_move, _refused_move

    data = _data()
    lot = _lot("LOT_JTE001_PRM043_6800016767A.10_57", "6800016767A.10")
    refused = _refused_move(lot.id, 2, 525, "PRM043", data, "motivo.", lot=lot)
    assert str(refused).startswith(
        "Não é possível iniciar a Referência 6800016767A.10 (PRM043) no dia 2 (03/12), às 08:45"
    )
    inconclusive = _inconclusive_move(lot.id, 2, 525, "PRM043", lot=lot, data=data)
    assert "LOT_" not in str(refused) and "LOT_" not in str(inconclusive)


def test_blocked_application_carries_causes(monkeypatch):
    from backend.copilot.state import state
    from backend.scheduler.gates import ApplicationBlocked, application_refusal_detail

    monkeypatch.setattr(state, "engine_data", _data(), raising=False)
    monkeypatch.setattr(state, "lots", [], raising=False)
    blocked = ApplicationBlocked(
        "O candidato tem conflitos físicos.", {"violations": [_overlap()]},
    )
    detail = application_refusal_detail(blocked)
    assert detail["causes"] and detail["causes"][0].startswith("Máquina PRM043")

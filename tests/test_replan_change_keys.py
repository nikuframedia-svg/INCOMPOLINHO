"""One ``POST /replan-jobs`` carries every kind of configuration change."""

from __future__ import annotations

import asyncio
import copy

import pytest
from fastapi import HTTPException

from backend.api import replan as replan_api
from backend.config.types import FactoryConfig, MachineConfig
from backend.config.unavailability import add_unavailability_entry
from backend.copilot.state import CopilotState
from backend.replan.jobs import ReplanJobManager, ReplanJobStore
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import EOp, EngineData, MachineInfo


class _RecordingExecutor:
    def __init__(self) -> None:
        self.submissions: list[tuple] = []

    def submit(self, function, *args):
        self.submissions.append(args)

    def shutdown(self, wait: bool = True) -> None:
        return None


def _op(op_id: str, sku: str) -> EOp:
    return EOp(op_id, sku, "C", "Part", "M1", "T1", 100, 0.5, 1, 0, None, 100, 0, [100, 0], 1.0, 0)


@pytest.fixture
def live(tmp_path, monkeypatch):
    config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    config.holidays = ["2026-03-20"]
    config.extra_workdays = ["2026-03-22"]
    engine = EngineData(
        ops=[_op("OP1", "SKU1"), _op("OP2", "SKU2")],
        # M9 came from the ISOP and is not configured yet.
        machines=[MachineInfo("M1", "Grandes", 1020), MachineInfo("M9", "Grandes", 1020)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18"],
        n_days=2,
        holidays=[],
    )
    add_unavailability_entry(
        config,
        engine,
        {
            "id": "U1",
            "kind": "machine",
            "resource": "M1",
            "start_at": "2026-03-18T07:00",
            "end_at": "2026-03-18T10:00",
        },
    )
    result = ScheduleResult(
        segments=[Segment("L1", "R1", "M1", "T1", 0, 420, 510, "A", 100, 60, 30, sku="SKU1")],
        lots=[Lot("L1", "OP1", "T1", "M1", None, 100, 60, 30, 0, False, sku="SKU1")],
        score={"otd": 100.0, "otd_d": 100.0, "tardy_count": 0, "setups": 1},
        time_ms=0,
        warnings=[],
        operator_alerts=[],
        gate_report={"status": "applicable"},
    )
    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda self: None)
    state = CopilotState(
        engine_data=engine,
        config=config,
        dataset_info={"id": "fixture", "filename": "fixture.xlsx"},
    )
    state.update_schedule(result)
    state.default_config = copy.deepcopy(config)
    manager = ReplanJobManager(ReplanJobStore(tmp_path / "replan.db"))
    manager.executor.shutdown(wait=True)
    manager.executor = _RecordingExecutor()
    monkeypatch.setattr(replan_api, "state", state)
    monkeypatch.setattr(replan_api, "manager", manager)
    yield state, manager
    manager.store.conn.close()


def _start(live, updates: dict, **extra) -> dict:
    """Start one job and return what the manager received."""

    state, manager = live
    body = {"expected_revision": state.plan_revision, "config_updates": updates, **extra}
    response = asyncio.run(replan_api.start_replan(body))
    args = manager.executor.submissions[-1]
    return {
        "response": response,
        "engine": args[1],
        "config": args[2],
        "reason": args[5],
        "flags": args[9:12],
        "jobs": len(manager.executor.submissions),
    }


def _refused(live, updates: dict) -> HTTPException:
    with pytest.raises(HTTPException) as error:
        _start(live, updates)
    assert error.value.status_code == 400
    return error.value


def test_calendar_keys_change_the_candidate_config(live):
    job = _start(
        live,
        {
            "holiday_additions": ["2026-03-19"],
            "holiday_removals": ["2026-03-20"],
            "extra_day_additions": ["2026-03-21"],
            "extra_day_removals": ["2026-03-22"],
        },
    )
    assert job["config"].holidays == ["2026-03-19"]
    assert job["config"].extra_workdays == ["2026-03-21"]
    # The live configuration only changes when the job is applied.
    assert live[0].config.holidays == ["2026-03-20"]


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"holiday_additions": ["2026-03-20"]}, "Feriado 2026-03-20 já existe."),
        ({"holiday_removals": ["2026-03-25"]}, "Feriado 2026-03-25 não existe."),
        ({"holiday_additions": ["amanhã"]}, "A data amanhã deve usar o formato YYYY-MM-DD."),
        ({"extra_day_additions": ["2026-03-18"]}, "Só sábados ou domingos podem ser dias extra."),
        ({"extra_day_removals": ["2026-03-28"]}, "Dia de trabalho extra 2026-03-28 não existe."),
        ({"holiday_additions": "2026-03-19"}, "holiday_additions deve ser uma lista."),
    ],
)
def test_invalid_calendar_entries_are_refused_in_plain_words(live, updates, message):
    assert _refused(live, updates).detail == message


def test_twin_additions_change_only_the_config(live):
    job = _start(live, {"twin_additions": [{"tool_id": "T1", "sku_a": "SKU1", "sku_b": "SKU2"}]})
    assert job["config"].twins == {"T1": ["SKU1", "SKU2"]}
    assert job["reason"] == "Configuração: gémea T1"

    live[0].config.twins = {"T1": ["SKU1", "SKU2"]}
    job = _start(live, {"twin_removals": ["T1"]})
    assert job["config"].twins == {}


@pytest.mark.parametrize(
    ("twin", "message"),
    [
        ({"tool_id": "T1", "sku_a": "SKU1", "sku_b": "SKU1"}, "Uma gémea exige duas referências"),
        ({"tool_id": "T7", "sku_a": "SKU1", "sku_b": "SKU2"}, "Ferramenta T7 não existe."),
        ({"tool_id": "T1", "sku_a": "SKU1", "sku_b": "SKU5"}, "SKU5=0"),
        ({"tool_id": "T1", "sku_a": "SKU1"}, "Gémea inválida"),
    ],
)
def test_invalid_twins_are_refused(live, twin, message):
    assert message in _refused(live, {"twin_additions": [twin]}).detail


def test_removing_an_unknown_twin_is_refused(live):
    assert _refused(live, {"twin_removals": ["T1"]}).detail == "Twin para ferramenta T1 não existe."


def test_setup_overrides_operators_and_sku_planning(live):
    live[0].config.sku_planning_rules = {"SKU2": {"start_buffer_days": 2}}
    job = _start(
        live,
        {
            "setup_overrides": [{"sku": "SKU1", "machine": "M1", "hours": 1.5}],
            "operators": {"Grandes A": 3},
            "sku_planning": {"SKU1": {"eco_lot": 250}, "SKU2": None},
        },
    )
    config = job["config"]
    assert config.setup_overrides == [{"sku": "SKU1", "machine": "M1", "hours": 1.5}]
    assert config.operators[("Grandes", "A")] == 3
    assert config.sku_planning_rules == {"SKU1": {"eco_lot": 250}}
    # The planning rules reach the engine data the job plans with.
    ops = {op.sku: op for op in job["engine"].ops}
    assert ops["SKU1"].eco_lot == 250
    assert ops["SKU2"].start_buffer_days == 0


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"setup_overrides": [{"sku": "SKU1", "machine": "M1"}]}, "hours deve ser um número."),
        ({"setup_overrides": [{"sku": "", "machine": "M1", "hours": 1}]}, "sku e machine"),
        ({"operators": {"Grandes A": -1}}, "Operadores inválidos para Grandes A: deve ser >= 0"),
        ({"operators": {"Medias A": 2}}, "Grupo desconhecido para Medias A: Medias"),
        ({"operators": {"Grandes C": 2}}, "Turno desconhecido para Grandes C: C"),
        ({"sku_planning": {"SKU9": {"eco_lot": 10}}}, "SKU SKU9 não encontrado."),
        ({"sku_planning": {"SKU1": {"eco_lot": -5}}}, "SKU1"),
    ],
)
def test_invalid_edits_are_refused(live, updates, message):
    assert message in _refused(live, updates).detail


def test_subcontracts_use_the_put_body(live):
    job = _start(
        live,
        {
            "subcontracts": {
                "companies": [{"id": "C1", "name": "Sub", "lead_time_workdays": 3}],
                "sku_subcontracts": {"SKU1": {"enabled": True, "company_id": "C1"}},
            }
        },
    )
    assert job["config"].subcontract_skus == ["SKU1"]
    assert [company["id"] for company in job["config"].subcontract_companies] == ["C1"]
    assert {op.sku: op.is_subcontracted for op in job["engine"].ops} == {
        "SKU1": True,
        "SKU2": False,
    }

    error = _refused(
        live,
        {"subcontracts": {"sku_subcontracts": {"SKU1": {"enabled": True, "company_id": "X"}}}},
    )
    assert error.detail == "SKU1: empresa de subcontratação desconhecida: X."


def test_preset_then_config_params(live):
    job = _start(
        live,
        {
            # The individual parameter wins over the preset, whatever the key order.
            "config_params": {"max_edd_gap": 7, "vns_enabled": "false", "max_run_days": 3},
            "preset": "min_setups",
        },
    )
    config = job["config"]
    assert config.campaign_window == 30
    assert config.max_edd_gap == 7
    assert config.vns_enabled is False


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"preset": "rapido"}, "Preset desconhecido"),
        ({"config_params": {"inventado": 1}}, "Parâmetro desconhecido: config_params.inventado"),
        ({"config_params": {"eco_lot_mode": "x"}}, "eco_lot_mode deve ser 'hard' ou 'soft'"),
        ({"config_params": {"setup_crews": 2}}, "setup_crews global foi substituído"),
        ({"inventado": 1}, "Parâmetro desconhecido: inventado"),
    ],
)
def test_invalid_parameters_are_refused(live, updates, message):
    assert message in _refused(live, updates).detail


def test_mixed_request_creates_one_full_replan(live):
    job = _start(
        live,
        {
            # Listed before the machine it names: processed after it.
            "unavailability_additions": [
                {
                    "kind": "machine",
                    "resource": "M2",
                    "start_at": "2026-03-17T07:00",
                    "end_at": "2026-03-17T09:00",
                }
            ],
            "setup_crews_by_group": {"Grandes": 2, "Medias": 1},
            "twin_additions": [{"tool_id": "T1", "sku_a": "SKU1", "sku_b": "SKU2"}],
            "holiday_additions": ["2026-03-19"],
            "machine_additions": [
                {"id": "M2", "group": "Grandes"},
                {"id": "M3", "group": "Medias"},
            ],
        },
    )
    assert job["jobs"] == 1
    assert job["response"]["status"] == "queued"
    config = job["config"]
    assert {"M2", "M3"} <= set(config.machines)
    assert config.holidays == ["2026-03-20", "2026-03-19"]
    assert config.twins == {"T1": ["SKU1", "SKU2"]}
    assert config.setup_crews_by_group["Grandes"] == 2
    assert [entry["resource"] for entry in config.machine_unavailability] == ["M1", "M2"]
    assert job["flags"] == (False, False, False)
    assert job["reason"] == (
        "Configuração: 2 máquinas, equipas de setup, gémea T1, 1 feriado, 1 indisponibilidade"
    )


def test_unavailability_removal_alone_reoptimises_but_not_with_other_changes(live):
    alone = _start(live, {"unavailability_removals": ["U1"]})
    assert alone["flags"] == (False, False, True)

    mixed = _start(
        live,
        {
            "unavailability_removals": ["U1"],
            "machine_additions": [{"id": "M2", "group": "Grandes"}],
        },
    )
    assert mixed["jobs"] == 2
    assert mixed["flags"] == (False, False, False)


def test_adding_a_machine_already_imported_updates_it(live):
    job = _start(live, {"machine_additions": [{"id": "M9", "group": "Medias"}]})
    machines = [machine for machine in job["engine"].machines if machine.id == "M9"]
    assert len(machines) == 1
    assert machines[0].group == "Medias"
    assert job["config"].machines["M9"].group == "Medias"

    assert _refused(
        live, {"machine_additions": [{"id": "M1", "group": "Grandes"}]}
    ).detail == "Máquina M1 já existe."


def test_explicit_reason_is_kept(live):
    job = _start(live, {"holiday_additions": ["2026-03-19"]}, reason="Fecho da fábrica")
    assert job["reason"] == "Fecho da fábrica"
    assert _start(live, {"holiday_additions": ["2026-03-23"]})["reason"] == (
        "Configuração: 1 feriado"
    )

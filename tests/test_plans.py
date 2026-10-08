"""Persistent plan snapshots: store, serialization, restore and REST API."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.api.copilot import app
from backend.api.data import _ensure_result_applicable
from backend.analytics.late_delivery import analyze_late_deliveries
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import CopilotState, state
from backend.plans.restore import restore_plan_into_state
from backend.plans.serialize import SNAPSHOT_VERSION, deserialize_snapshot, serialize_snapshot
from backend.plans.store import PlansStore
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.types import EngineData, EOp, MachineInfo, TwinGroup


def _config() -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
    config.tools = {"T1": {"primary": "M1", "setup_hours": 0.5}}
    return config


def _engine() -> EngineData:
    return EngineData(
        ops=[
            EOp(
                id="OP1",
                sku="SKU1",
                client="CLIENTE",
                designation="Peça",
                m="M1",
                t="T1",
                pH=100,
                sH=0.5,
                operators=1,
                eco_lot=0,
                alt=None,
                stk=100,
                backlog=0,
                d=[100, 0],
                oee=1.0,
                wip=0,
            )
        ],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-17", "2026-03-18"],
        n_days=2,
        holidays=[],
        machine_blocked_days={"M1": {1}},
        tool_blocked_days={"T1": {1}},
    )


def _result() -> ScheduleResult:
    lot = Lot(
        id="LOT1",
        op_id="OP1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=0,
        is_twin=False,
        twin_outputs=None,
    )
    segment = Segment(
        lot_id="LOT1",
        run_id="RUN1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=420,
        end_min=510,
        shift="A",
        qty=100,
        prod_min=60,
        setup_min=30,
        edd=0,
        sku="SKU1",
        twin_outputs=None,
    )
    return ScheduleResult(
        segments=[segment],
        lots=[lot],
        score={
            "otd": 100.0,
            "otd_d": 100.0,
            "otd_d_failures": 0,
            "tardy_count": 0,
            "setups": 1,
            "earliness_avg_days": 0.0,
            "early_window_violations": 0,
        },
        time_ms=1,
        warnings=[],
        operator_alerts=[],
        gate_report={"status": "applicable"},
    )


def _loaded_state() -> CopilotState:
    loaded = CopilotState(engine_data=_engine(), config=_config())
    loaded.dataset_info = {
        "id": "dataset-1",
        "filename": "isop.xlsx",
        "uploaded_at": "2026-03-17T10:00:00+00:00",
        "n_ops": 1,
        "n_segments": 1,
        "trust_score": 100,
        "trust_gate": "full_auto",
        "otd": 100,
        "tardy_count": 0,
    }
    loaded.update_schedule(_result())
    return loaded


def _state_with_incompatible_twin() -> CopilotState:
    source = _loaded_state()
    first = source.engine_data.ops[0]
    first.eco_lot = 100
    first.eco_lot_effective = 100
    second = copy.deepcopy(first)
    second.id = "OP2"
    second.sku = "SKU2"
    second.eco_lot = 200
    second.eco_lot_effective = 200
    second.d = [0, 0]
    second.stk = 0
    source.engine_data.ops.append(second)
    source.engine_data.twin_groups = [
        TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1=first.id,
            op_id_2=second.id,
            sku_1=first.sku,
            sku_2=second.sku,
            eco_lot_1=100,
            eco_lot_2=200,
        )
    ]
    source.config.twins = {"T1": ["SKU1", "SKU2"]}
    source.dataset_info["n_ops"] = 2
    return source


def test_snapshot_round_trip_restores_sets_and_tuples():
    loaded = _loaded_state()

    restored = deserialize_snapshot(serialize_snapshot(loaded))

    assert restored["engine_data"].machine_blocked_days == {"M1": {1}}
    assert restored["engine_data"].tool_blocked_days == {"T1": {1}}
    assert restored["result"].segments[0].twin_outputs is None
    assert restored["result"].score["otd"] == 100.0
    assert restored["config"].machines["M1"].group == "Grandes"
    assert restored["config"].operators[("Grandes", "A")] == 6


def test_restore_reapplies_active_availability_mutations_to_engine_timeline():
    source = _loaded_state()
    source.lots[0].is_twin = False
    source.lots[0].twin_outputs = None
    source.segments[0].twin_outputs = None
    source.engine_data.machine_blocked_days = {}
    source.engine_data.tool_blocked_days = {}
    source.engine_data.operator_blocked_intervals = []
    source.active_mutations = [
        {
            "type": "machine_down",
            "params": {"machine_id": "M1", "start": 1, "end": 1},
        },
        {
            "type": "tool_down",
            "params": {"tool_id": "T1", "start": 1, "end": 1},
        },
        {
            "type": "operator_shortage",
            "params": {
                "group": "Grandes",
                "shift": "A",
                "start": 1,
                "end": 1,
                "count": 1,
            },
        },
    ]
    target = CopilotState(config=_config())
    plan = {
        "id": "availability-snapshot",
        "name": "Plano com indisponibilidades",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Validar reposição de indisponibilidades",
        approval_author="pytest",
    )

    assert target.engine_data.machine_blocked_days == {"M1": {1}}
    assert target.engine_data.tool_blocked_days == {"T1": {1}}
    assert [
        (
            block["group"],
            block["shift"],
            block["start_day"],
            block["count"],
        )
        for block in target.engine_data.operator_blocked_intervals
    ] == [("Grandes", "A", 1, 1)]
    assert target.active_mutations == source.active_mutations


def test_restore_rejects_incompatible_active_twin_eco_lots_transactionally():
    source = _state_with_incompatible_twin()
    plan = {
        "id": "incompatible-twins",
        "name": "Gémeas incompatíveis",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }
    target = _loaded_state()
    target.config.twins = {"T1": ["SKU1", "SKU2"]}
    previous_revision = target.plan_revision

    with pytest.raises(ValueError, match=r"T1: SKU1=100, SKU2=200"):
        restore_plan_into_state(plan, target)

    assert target.plan_revision == previous_revision
    assert target.engine_data.ops[0].sku == "SKU1"


def test_restore_requires_explicit_recalculation_when_config_deactivates_snapshot_twin(
    monkeypatch,
):
    source = _state_with_incompatible_twin()
    plan = {
        "id": "inactive-snapshot-twin",
        "name": "Gémea entretanto desativada",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }
    target = _loaded_state()
    target.config.twins = {}
    called = {}

    def fake_optimize(engine_data, **kwargs):
        called["twin_groups"] = copy.deepcopy(engine_data.twin_groups)
        called["kwargs"] = kwargs
        return _result()

    monkeypatch.setattr("backend.cpo.optimizer.optimize", fake_optimize)

    # Never recalculated silently (plan-melhoria §6.6, §7.4).
    with pytest.raises(ValueError, match="recalculo explicito"):
        restore_plan_into_state(
            plan,
            target,
            approve_exceptions=True,
            approval_reason="Aplicar classificação atual de gémeas",
            approval_author="pytest",
        )
    assert called == {}

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Aplicar classificação atual de gémeas",
        approval_author="pytest",
        recalculate=True,
    )

    assert called["twin_groups"] == []
    assert called["kwargs"]["mode"] == "quick"
    assert target.config.twins == {}
    assert target.engine_data.twin_groups == []
    assert any("configuração de peças gémeas mudou" in item for item in target.warnings)


def test_restore_allows_inactive_factory_twin_catalog_entries():
    source = _loaded_state()
    source.config.twins = {
        "OLD_TOOL": ["OLD_SKU_1", "OLD_SKU_2"],
        "T1": ["SKU1", "SKU_NOT_IN_THIS_ISOP"],
    }
    source.engine_data.twin_groups = []
    plan = {
        "id": "inactive-twin-catalog",
        "name": "Catálogo fabril com pares inativos",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }
    target = _loaded_state()
    target.config.twins = copy.deepcopy(source.config.twins)

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Validar catálogo fabril inativo",
        approval_author="pytest",
    )

    assert target.config.twins == source.config.twins
    assert target.engine_data.twin_groups == []
    assert target.segments


def test_snapshot_rejects_tampered_engine_payload():
    payload = serialize_snapshot(_loaded_state())
    payload["engine_data"]["ops"][0]["sku"] = "ALTERADO"

    with pytest.raises(ValueError, match="fingerprint dos dados do motor"):
        deserialize_snapshot(payload)


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("segments", lambda payload: payload["segments"][0].update(machine_id="M_FAKE")),
        ("lots", lambda payload: payload["lots"][0].update(qty=1)),
        ("score", lambda payload: payload["score"].update(otd=0)),
        ("gate_report", lambda payload: payload["gate_report"].update(status="forjado")),
        (
            "active_mutations",
            lambda payload: payload["active_mutations"].append(
                {"type": "rush_order", "params": {"sku": "SKU1", "qty": 999}}
            ),
        ),
    ],
)
def test_snapshot_rejects_tampered_plan_content(field, mutate):
    payload = serialize_snapshot(_loaded_state())
    mutate(payload)

    with pytest.raises(ValueError, match="fingerprint do conteúdo do plano"):
        deserialize_snapshot(payload)


def test_snapshot_rejects_stale_dataset_operation_count():
    payload = serialize_snapshot(_loaded_state())
    payload["dataset_info"]["n_ops"] = 88

    with pytest.raises(ValueError, match="metadados indicam 88 operações"):
        deserialize_snapshot(payload)


def test_v1_snapshot_is_migrated_and_lot_sku_is_normalized():
    payload = serialize_snapshot(_loaded_state())
    payload["version"] = 1
    payload.pop("model_version")
    payload.pop("plan_revision")
    payload.pop("approvals")
    payload.pop("fingerprints")
    payload["lots"][0].pop("sku", None)

    restored = deserialize_snapshot(payload)

    assert restored["migrated_from_version"] == 1
    assert restored["plan_revision"] == 0
    assert restored["approvals"] == []
    assert restored["result"].lots[0].sku == "SKU1"


def test_failed_restore_does_not_change_live_config_or_revision():
    source = _loaded_state()
    source.config.name = "Configuração do snapshot"
    # Genuine refusal: the snapshot delivers the day-0 order one day late, so
    # the delivery gate requires explicit approval and none is given.
    source.engine_data.ops[0].stk = 0
    source.engine_data.machine_blocked_days = {}
    source.engine_data.tool_blocked_days = {}
    source.segments[0].day_idx = 1
    payload = serialize_snapshot(source)
    target = _loaded_state()
    target.config.name = "Configuração em produção"
    original_engine = target.engine_data
    original_revision = target.plan_revision
    original_segments = copy.deepcopy(target.segments)
    plan = {
        "id": "snapshot-1",
        "name": "Plano atrasado sem aprovação",
        "origin": "isop.xlsx",
        "payload": copy.deepcopy(payload),
    }

    with pytest.raises(ValueError, match="aprovação explícita: delivery_risk"):
        restore_plan_into_state(
            plan,
            target,
            expected_revision=original_revision,
        )

    assert target.config.name == "Configuração em produção"
    assert target.engine_data is original_engine
    assert target.plan_revision == original_revision
    assert target.segments == original_segments


def test_startup_restore_keeps_the_current_persisted_factory_config():
    source = _loaded_state()
    source.config.name = "Configuração antiga do plano"
    source.config.sku_planning_rules = {}
    target = _loaded_state()
    target.config.name = "Configuração atual guardada"
    target.config.sku_planning_rules = {"TP042173-0040-2": {"planning_priority": 100}}
    plan = {
        "id": "snapshot-old-config",
        "name": "Plano anterior",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Reposição automática no arranque",
        approval_author="pytest",
        prefer_current_config=True,
    )

    assert target.config.name == "Configuração atual guardada"
    assert target.config.sku_planning_rules == {"TP042173-0040-2": {"planning_priority": 100}}


def test_startup_restore_keeps_exact_active_plan_when_new_diagnostics_block(monkeypatch):
    source = _loaded_state()
    target = _loaded_state()
    plan = {
        "id": "active-plan",
        "name": "Plano ativo",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }
    blocked = {
        "status": "blocked",
        "apply_decision": "blocked",
        "physical_gate_passed": True,
        "coverage_gate_passed": True,
        "jit_window_gate_passed": True,
        "operational_gate_passed": False,
        "metrics": {},
    }
    monkeypatch.setattr(
        "backend.plans.restore.build_gate_report", lambda *_args, **_kwargs: blocked
    )

    restored = restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        prefer_current_config=True,
        preserve_exact=True,
        recover_existing=True,
    )

    assert restored["plan_revision"] >= source.plan_revision
    assert target.gate_report["apply_decision"] == "blocked"
    assert target.segments == source.segments


def test_restore_does_not_reoptimize_a_canonical_snapshot():
    source = _loaded_state()
    source.config.machine_unavailability = [
        {
            "id": "stop-1",
            "resource": "M1",
            "start_at": "2026-03-17T07:00:00+00:00",
            "end_at": "2026-03-17T10:00:00+00:00",
            "category": "Manutenção",
            "reason": "Teste",
        }
    ]
    source.segments[0].start_min = 600
    source.segments[0].end_min = 690
    plan = {
        "id": "snapshot-exact",
        "name": "Plano canónico",
        "origin": "isop.xlsx",
        "payload": serialize_snapshot(source),
    }
    target = CopilotState(config=_config())

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Repor plano exato",
        approval_author="pytest",
    )

    assert [(segment.start_min, segment.end_min) for segment in target.segments] == [(600, 690)]


def test_restore_reoptimizes_stale_planning_policy_only_on_explicit_request(monkeypatch):
    source = _loaded_state()
    payload = serialize_snapshot(source)
    payload["planning_policy_version"] = "legacy-expedition-release"
    plan = {
        "id": "snapshot-old-policy",
        "name": "Plano com política anterior",
        "origin": "isop.xlsx",
        "payload": payload,
    }
    target = CopilotState(config=_config())
    called = {}

    def fake_optimize(engine_data, **kwargs):
        called["engine_data"] = engine_data
        called["kwargs"] = kwargs
        return _result()

    monkeypatch.setattr("backend.cpo.optimizer.optimize", fake_optimize)

    with pytest.raises(ValueError, match="recalculo explicito"):
        restore_plan_into_state(
            plan,
            target,
            approve_exceptions=True,
            approval_reason="Migrar política de datas",
            approval_author="pytest",
        )
    assert called == {}

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Migrar política de datas",
        approval_author="pytest",
        recalculate=True,
    )

    assert called["engine_data"] is not None
    assert called["kwargs"]["mode"] == "quick"
    assert any("modelo de planeamento anterior" in item for item in target.warnings)


def test_store_crud_and_auto_pruning(tmp_path: Path):
    store = PlansStore(tmp_path / "plans.db")
    payload = serialize_snapshot(_loaded_state())
    try:
        user = store.save(
            name="Aprovado",
            source="user",
            origin="isop.xlsx",
            note="Distribuir",
            payload=payload,
            score={"otd": 100, "otd_d": 100, "tardy_count": 0, "setups": 1},
            gate_report={"status": "applicable"},
            is_auto=False,
        )
        for index in range(4):
            store.save(
                name=f"Auto {index}",
                source="auto",
                origin="isop.xlsx",
                note="",
                payload=payload,
                score={},
                gate_report=None,
                is_auto=True,
            )

        assert store.get(user["id"])["payload"]["version"] == SNAPSHOT_VERSION
        assert store.prune_auto(keep=2) == 2
        listed = store.list()
        assert sum(plan["is_auto"] for plan in listed) == 2
        assert any(plan["id"] == user["id"] for plan in listed)
        assert store.delete(user["id"]) is True
        assert store.delete(user["id"]) is False
    finally:
        store.close()


def test_store_skips_inconsistent_latest_plan(tmp_path: Path):
    store = PlansStore(tmp_path / "plans.db")
    payload = serialize_snapshot(_loaded_state())
    try:
        valid = store.save(
            name="Plano válido",
            source="auto",
            origin="isop.xlsx",
            note="",
            payload=payload,
            score={"otd": 100},
            gate_report={"status": "applicable"},
            is_auto=True,
        )
        invalid = copy.deepcopy(payload)
        invalid["dataset_info"]["n_ops"] = 93
        with store._lock:
            store._conn.execute(
                """
                INSERT INTO plans (
                    id, name, source, origin, note, is_auto, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "invalid-latest",
                    "Plano incoerente",
                    "auto",
                    "isop.xlsx",
                    "",
                    1,
                    json.dumps(invalid),
                ),
            )
            store._conn.commit()

        assert store.latest()["id"] == valid["id"]
        with pytest.raises(ValueError, match="Snapshot inconsistente"):
            store.save(
                name="Não guardar",
                source="auto",
                origin="isop.xlsx",
                note="",
                payload=invalid,
                score={},
                gate_report=None,
                is_auto=True,
            )
    finally:
        store.close()


def test_late_delivery_report_uses_customer_delivery_not_internal_deadline():
    loaded = _loaded_state()
    loaded.engine_data.machine_blocked_days = {}
    loaded.engine_data.tool_blocked_days = {}
    lot = loaded.lots[0]
    lot.edd = 0
    lot.internal_deadline = 0
    lot.delivery_day = 1
    loaded.segments[0].day_idx = 1

    report = analyze_late_deliveries(
        loaded.segments,
        loaded.lots,
        loaded.engine_data,
        loaded.config,
    )

    assert report.tardy_count == 0


def test_late_delivery_lead_time_capacity_includes_deadline_day():
    loaded = _loaded_state()
    loaded.engine_data.machine_blocked_days = {}
    loaded.engine_data.tool_blocked_days = {}
    lot = loaded.lots[0]
    segment = loaded.segments[0]
    lot.edd = 0
    lot.internal_deadline = 0
    lot.delivery_day = 0
    lot.prod_min = 1_020
    lot.setup_min = 0
    segment.day_idx = 1
    segment.prod_min = 1_020
    segment.setup_min = 0

    report = analyze_late_deliveries(
        loaded.segments,
        loaded.lots,
        loaded.engine_data,
        loaded.config,
    )

    assert report.tardy_count == 1
    assert report.analyses[0].root_cause != "lead_time"


def test_late_delivery_lead_time_includes_setup_minutes():
    loaded = _loaded_state()
    loaded.engine_data.machine_blocked_days = {}
    loaded.engine_data.tool_blocked_days = {}
    lot = loaded.lots[0]
    segment = loaded.segments[0]
    lot.edd = 0
    lot.internal_deadline = 0
    lot.delivery_day = 0
    lot.prod_min = 1_000
    lot.setup_min = 30
    segment.day_idx = 1
    segment.prod_min = 1_000
    segment.setup_min = 30

    report = analyze_late_deliveries(
        loaded.segments,
        loaded.lots,
        loaded.engine_data,
        loaded.config,
    )

    analysis = report.analyses[0]
    assert analysis.root_cause == "lead_time"
    assert analysis.capacity_gap_min == 10


def test_late_delivery_report_uses_the_controlling_twin_output():
    loaded = _loaded_state()
    loaded.engine_data.machine_blocked_days = {}
    loaded.engine_data.tool_blocked_days = {}
    lot = loaded.lots[0]
    segment = loaded.segments[0]
    lot.op_id = "OPA"
    lot.sku = "A"
    lot.twin_outputs = [("OPA", "A", 100), ("OPB", "B", 100)]
    lot.output_milestones = [
        {
            "op_id": "OPA",
            "sku": "A",
            "qty": 100,
            "is_subcontracted": False,
            "subcontract_lead_time_days": 0,
            "customer_delivery_day": 10,
            "production_due_day": 10,
            "subcontract_dispatch_day": None,
        },
        {
            "op_id": "OPB",
            "sku": "B",
            "qty": 100,
            "is_subcontracted": True,
            "subcontract_lead_time_days": 5,
            "customer_delivery_day": 8,
            "production_due_day": 3,
            "subcontract_dispatch_day": 3,
        },
    ]
    segment.sku = "A"
    segment.twin_outputs = list(lot.twin_outputs)
    segment.day_idx = 4

    report = analyze_late_deliveries(
        loaded.segments,
        loaded.lots,
        loaded.engine_data,
        loaded.config,
    )

    assert report.tardy_count == 1
    assert report.analyses[0].op_id == "OPB"
    assert report.analyses[0].sku == "B"
    assert report.analyses[0].edd == 8
    assert report.analyses[0].production_due_day == 3
    assert report.analyses[0].subcontract_dispatch_day == 3


def test_blocked_plan_is_never_persisted_automatically_or_manually(tmp_path: Path):
    loaded = _loaded_state()
    store = PlansStore(tmp_path / "plans.db")
    loaded.plans_store = store
    blocked = _result()
    blocked.gate_report = {
        "status": "jit_window_blocked",
        "apply_decision": "blocked",
    }

    try:
        loaded.update_schedule(blocked, plan_source="load", plan_note="Diagnóstico JIT")

        assert store.list() == []
        with pytest.raises(ValueError, match="plano bloqueado"):
            loaded.persist_current_plan(
                name="Não guardar",
                source="user",
                is_auto=False,
            )
    finally:
        store.close()


def test_schedule_update_can_require_a_durable_snapshot():
    loaded = _loaded_state()

    class _FailingStore:
        def save(self, **_kwargs):
            raise OSError("disco indisponível")

    loaded.plans_store = _FailingStore()

    with pytest.raises(OSError, match="disco indisponível"):
        loaded.update_schedule(
            _result(),
            plan_source="auto",
            require_persistence=True,
        )


def test_saved_scenario_is_never_the_automatic_startup_plan(tmp_path: Path):
    store = PlansStore(tmp_path / "plans.db")
    payload = serialize_snapshot(_loaded_state())
    try:
        production = store.save(
            name="Produção",
            source="auto",
            origin="isop.xlsx",
            note="",
            payload=payload,
            score={},
            gate_report={"status": "applicable"},
            is_auto=True,
        )
        scenario = store.save(
            name="What-if",
            source="scenario",
            origin="isop.xlsx",
            note="",
            payload=payload,
            score={},
            gate_report={"status": "best_effort"},
            is_auto=False,
        )
        assert store.latest()["id"] == production["id"]
        assert store.latest(include_scenarios=True)["id"] == scenario["id"]
    finally:
        store.close()


def test_restore_recomputes_gate_and_dataset(tmp_path: Path):
    loaded = _loaded_state()
    store = PlansStore(tmp_path / "plans.db")
    try:
        saved = store.save(
            name="Plano manhã",
            source="user",
            origin="isop.xlsx",
            note="",
            payload=serialize_snapshot(loaded),
            score=loaded.score,
            gate_report=loaded.gate_report,
            is_auto=False,
        )
        plan = store.get(saved["id"])
        loaded.score = {"otd": 0}
        loaded.engine_data = None

        response = restore_plan_into_state(
            plan,
            loaded,
            approve_exceptions=True,
            approval_reason="Repor plano validado no teste",
            approval_author="pytest",
        )

        assert loaded.score["otd"] == 100.0
        # Robustness is information only: a clean plan restores without approval.
        assert loaded.gate_report["status"] == "applicable"
        assert loaded.gate_report["apply_decision"] == "auto_applicable"
        assert "robustness_not_evaluated" not in loaded.gate_report["approval_reasons"]
        assert loaded.dataset_info["id"] == f"plan_{saved['id']}"
        assert response["dataset"]["filename"] == "isop.xlsx"
    finally:
        store.close()


def test_restore_keeps_setup_start_gaps_of_old_snapshots_as_saved():
    source = _loaded_state()
    first = source.segments[0]
    first.start_min = 431
    first.end_min = 930
    first.setup_min = 30
    first.prod_min = 469
    first.qty = 94
    first.twin_outputs = None
    continuation = copy.deepcopy(first)
    continuation.start_min = 930
    continuation.end_min = 960
    continuation.setup_min = 0
    continuation.prod_min = 30
    continuation.qty = 6
    continuation.is_continuation = True
    source.segments = [first, continuation]
    source.lots[0].prod_min = 499
    source.engine_data.ops[0].pH = 100 * 60 / 499
    source.lots[0].setup_min = 30
    source.lots[0].is_twin = False
    source.lots[0].twin_outputs = None
    payload = serialize_snapshot(source)
    target = CopilotState(config=_config())
    plan = {
        "id": "snapshot-gap",
        "name": "Plano antigo com buraco",
        "origin": "isop.xlsx",
        "payload": copy.deepcopy(payload),
    }

    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Validar normalização de snapshot antigo",
        approval_author="pytest",
    )

    # No hidden normalization: the saved times are restored exactly and any
    # gap is a diagnostic of the recomputed gate, fixed only by recalculation.
    assert [(s.start_min, s.end_min) for s in target.segments] == [(431, 930), (930, 960)]


def test_legacy_detached_setup_is_diagnosed_and_fixed_only_by_explicit_recalculation(
    monkeypatch,
):
    source = _loaded_state()
    source.engine_data.machine_blocked_days = {}
    source.engine_data.tool_blocked_days = {}
    source.lots[0].delivery_day = 8  # First permitted production day is day 1.
    detached_setup = Segment(
        lot_id="LOT1",
        run_id="RUN1",
        machine_id="M1",
        tool_id="T1",
        day_idx=0,
        start_min=700,
        end_min=730,
        shift="A",
        qty=0,
        prod_min=0,
        setup_min=30,
        edd=1,
        sku="SKU1",
    )
    production = copy.deepcopy(source.segments[0])
    production.day_idx = 1
    production.start_min = 420
    production.end_min = 480
    production.setup_min = 0
    production.prod_min = 60
    source.segments = [detached_setup, production]
    payload = serialize_snapshot(source)
    target = CopilotState(config=_config())
    plan = {
        "id": "snapshot-detached-setup",
        "name": "Plano antigo com setup destacado",
        "origin": "isop.xlsx",
        "payload": copy.deepcopy(payload),
    }

    with pytest.raises(ValueError, match="conflitos físicos"):
        restore_plan_into_state(
            plan,
            target,
            approve_exceptions=True,
            approval_reason="Validar normalização de setup destacado",
            approval_author="pytest",
        )
    assert target.segments == []

    called = {}

    def fake_optimize(engine_data, **kwargs):
        called["kwargs"] = kwargs
        return _result()

    monkeypatch.setattr("backend.cpo.optimizer.optimize", fake_optimize)
    restore_plan_into_state(
        plan,
        target,
        approve_exceptions=True,
        approval_reason="Recalcular snapshot antigo",
        approval_author="pytest",
        recalculate=True,
    )
    assert called["kwargs"]["mode"] == "quick"
    assert any("recalculado a pedido" in item for item in target.warnings)


def test_startup_rebuilds_jit_blocked_snapshot_but_manual_restore_rejects_it():
    source = _loaded_state()
    source.engine_data.workdays = [f"2026-03-{day:02d}" for day in range(16, 31)]
    source.engine_data.n_days = len(source.engine_data.workdays)
    source.engine_data.machine_blocked_days = {}
    source.engine_data.tool_blocked_days = {}
    source.lots[0].delivery_day = 12
    source.lots[0].edd = 12
    source.segments[0].day_idx = 0
    source.segments[0].edd = 12
    payload = serialize_snapshot(source)
    plan = {
        "id": "snapshot-jit-blocked",
        "name": "Plano antigo fora da janela JIT",
        "origin": "isop.xlsx",
        "payload": copy.deepcopy(payload),
    }

    with pytest.raises(ValueError, match="bloqueado"):
        restore_plan_into_state(plan, CopilotState(config=_config()))

    recovered = CopilotState(config=_config())
    response = restore_plan_into_state(
        plan,
        recovered,
        approve_exceptions=True,
        approval_reason="Reposição automática do último plano guardado",
        approval_author="pytest",
        recover_jit_blocked=True,
    )

    assert response["gate_report"]["jit_window_gate_passed"] is True
    assert response["gate_report"]["coverage_gate_passed"] is True
    assert recovered.score["early_window_violations"] == 0
    assert any("janela de material" in warning for warning in recovered.warnings)


def test_operational_disruption_never_overrides_the_hard_jit_release_gate():
    result = SimpleNamespace(
        gate_report={
            "apply_decision": "blocked",
            "physical_gate_passed": True,
            "coverage_gate_passed": True,
            "jit_window_gate_passed": False,
            "status": "jit_window_blocked",
            "approval_reasons": ["jit_window_blocked"],
            "metrics": {"early_window_violations": 1},
        }
    )

    with pytest.raises(HTTPException) as error:
        _ensure_result_applicable(
            result,
            {
                "_allow_operational_disruption": True,
                "approve_exceptions": True,
                "approval_reason": "não deve contornar a libertação de material",
                "approval_author": "pytest",
            },
        )

    assert error.value.status_code == 409
    assert "janela JIT" in str(error.value.detail["message"])


@pytest.fixture
def plans_api_state(tmp_path: Path):
    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    temp_store = PlansStore(tmp_path / "plans-api.db")
    loaded = _loaded_state()
    for key in state.__dataclass_fields__:
        setattr(state, key, getattr(loaded, key))
    state.plans_store = temp_store
    yield
    temp_store.close()
    for key, value in previous.items():
        setattr(state, key, value)


def test_plans_api_save_list_restore_delete(plans_api_state):
    client = TestClient(app)

    created = client.post("/api/data/plans", json={"name": "Plano aprovado", "note": "Turno A"})
    assert created.status_code == 200
    plan_id = created.json()["plan"]["id"]

    listed = client.get("/api/data/plans")
    assert listed.status_code == 200
    assert listed.json()["plans"][0]["name"] == "Plano aprovado"

    state.score = {"otd": 0.0}
    restored = client.post(
        f"/api/data/plans/{plan_id}/restore",
        json={
            "expected_revision": state.plan_revision,
            "approve_exceptions": True,
            "approval_reason": "Repor snapshot no teste",
            "approval_author": "pytest",
        },
    )
    assert restored.status_code == 200, restored.text
    assert state.score["otd"] == 100.0
    # Robustness is information only: a clean plan restores without approval.
    assert restored.json()["gate_report"]["status"] == "applicable"
    assert restored.json()["gate_report"]["requires_approval"] is False

    deleted = client.delete(f"/api/data/plans/{plan_id}")
    assert deleted.status_code == 200
    assert client.delete(f"/api/data/plans/{plan_id}").status_code == 404

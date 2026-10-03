"""Tests for Audit Trail — Spec 07."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from backend.audit import (
    AuditLogger,
    AuditStore,
    AuditTrail,
    compute_counterfactual,
    compute_diff,
)
from backend.audit.templates import TEMPLATES, render_decision
from backend.audit.types import Alternative, DecisionRecord
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.types import Segment
from backend.types import EngineData, EOp, MachineInfo


# --- Fixtures ---


def _eop(
    op_id: str = "T1_M1_SKU1",
    sku: str = "SKU1",
    machine: str = "M1",
    tool: str = "T1",
    d: list[int] | None = None,
    pH: float = 100.0,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client="CLIENT",
        designation="Test",
        m=machine,
        t=tool,
        pH=pH,
        sH=sH,
        operators=1,
        eco_lot=0,
        alt=alt,
        stk=0,
        backlog=0,
        d=d or [0, 500, 0, 300, 0],
        oee=oee,
        wip=0,
    )


def _engine(
    ops: list[EOp] | None = None,
    n_days: int = 10,
) -> EngineData:
    if ops is None:
        ops = [_eop()]
    machine_ids = list({op.m for op in ops})
    if ops and any(op.alt for op in ops):
        for op in ops:
            if op.alt and op.alt not in machine_ids:
                machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{i + 5:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=[],
    )


def _seg(
    lot_id: str = "L1",
    machine: str = "M1",
    tool: str = "T1",
    day: int = 0,
    start: int = 420,
    end: int = 720,
    qty: int = 200,
    prod_min: float = 300.0,
    setup_min: float = 30.0,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id="R1",
        machine_id=machine,
        tool_id=tool,
        day_idx=day,
        start_min=start,
        end_min=end,
        shift="A",
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
    )


# --- Logger Tests ---


class TestAuditLogger:
    def test_log_assign_records_decision(self):
        logger = AuditLogger()
        logger.log_assign(
            "run_BFP079",
            "BFP079",
            "PRM031",
            [("PRM031", 350), ("PRM039", 520)],
            "assign_load_balance",
        )
        assert len(logger.decisions) == 1
        assert logger.decisions[0].chosen == "PRM031"
        assert logger.decisions[0].phase == "assign"

    def test_log_assign_no_alt(self):
        logger = AuditLogger()
        logger.log_assign(
            "run_BFP079",
            "BFP079",
            "PRM031",
            [("PRM031", 350)],
            "assign_no_alt",
        )
        assert len(logger.decisions) == 1
        assert logger.decisions[0].binding_constraint == "ONLY_OPTION"

    def test_log_assign_alternatives_captured(self):
        logger = AuditLogger()
        logger.log_assign(
            "run_BFP079",
            "BFP079",
            "PRM031",
            [("PRM031", 350), ("PRM039", 520)],
            "assign_load_balance",
        )
        assert len(logger.decisions[0].alternatives) == 1
        assert logger.decisions[0].alternatives[0].value == "PRM039"

    def test_log_sequence(self):
        logger = AuditLogger()
        logger.log_sequence("PRM031", "sequence_campaign", 3)
        assert len(logger.decisions) == 1
        assert logger.decisions[0].phase == "sequence"

    def test_log_sequence_zero_moves_skipped(self):
        logger = AuditLogger()
        logger.log_sequence("PRM031", "sequence_campaign", 0)
        assert len(logger.decisions) == 0

    def test_log_gate(self):
        logger = AuditLogger()
        logger.log_gate("run1", 5100.0, 8160.0, 10, "gate_jit")
        assert len(logger.decisions) == 1
        assert logger.decisions[0].phase == "jit"

    def test_log_split(self):
        logger = AuditLogger()
        logger.log_split("run1", "infeasible", 3, 2, total_min=6000, capacity=5100)
        assert len(logger.decisions) == 1
        assert logger.decisions[0].action == "split_run"

    def test_get_trail(self):
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        logger.log_gate("r1", 1020.0, 2040.0, 5, "gate_jit")
        trail = logger.get_trail("test123")
        assert isinstance(trail, AuditTrail)
        assert trail.total_decisions == 2
        assert trail.phases["assign"] == 1
        assert trail.phases["jit"] == 1

    def test_decision_ids_sequential(self):
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        logger.log_assign("r2", "T2", "M2", [("M2", 200)], "assign_no_alt")
        assert logger.decisions[0].id == "D0000"
        assert logger.decisions[1].id == "D0001"


# --- Template Tests ---


class TestTemplates:
    def test_all_templates_have_content(self):
        assert len(TEMPLATES) >= 10

    def test_assign_template_renders(self):
        record = DecisionRecord(
            id="D0000",
            phase="assign",
            subject_id="run_BFP079",
            subject_type="run",
            action="assign_machine",
            chosen="PRM031",
            rule="assign_load_balance",
            binding_constraint="LOAD_BALANCE",
            alternatives=[Alternative("PRM039", 520, "LOAD_BALANCE", "Carga 520min")],
            state_snapshot={"chosen_load": 350, "alt_load": 520, "tool_id": "BFP079", "edd": 0},
            explanation_pt="",
            timestamp_ms=0.1,
        )
        text = render_decision(record)
        assert "PRM031" in text
        assert "350" in text

    def test_unknown_rule_fallback(self):
        record = DecisionRecord(
            id="D0000",
            phase="assign",
            subject_id="run1",
            subject_type="run",
            action="test",
            chosen="X",
            rule="UNKNOWN_RULE",
            binding_constraint="NONE",
            alternatives=[],
            state_snapshot={},
            explanation_pt="",
            timestamp_ms=0.0,
        )
        text = render_decision(record)
        assert "assign" in text
        assert "X" in text

    def test_explanation_in_portuguese(self):
        logger = AuditLogger()
        logger.log_assign(
            "run_BFP079",
            "BFP079",
            "PRM031",
            [("PRM031", 350), ("PRM039", 520)],
            "assign_load_balance",
        )
        exp = logger.decisions[0].explanation_pt
        assert "carga" in exp.lower() or "atribuído" in exp.lower()


# --- Integration Tests ---


class TestScheduleAllAudit:
    def test_audit_false_no_trail(self):
        engine = _engine()
        result = schedule_all(engine)
        assert result.audit_trail is None

    def test_audit_true_has_trail(self):
        engine = _engine()
        result = schedule_all(engine, audit=True)
        assert result.audit_trail is not None
        assert result.audit_trail.total_decisions > 0

    def test_audit_decisions_include_assign(self):
        engine = _engine()
        result = schedule_all(engine, audit=True)
        phases = {d.phase for d in result.audit_trail.decisions}
        assert "assign" in phases

    def test_audit_with_alt_machine(self):
        """Runs with alt machines should log load-balance decisions."""
        ops = [
            _eop(op_id="T1_M1_SKU1", machine="M1", tool="T1", alt="M2"),
            _eop(op_id="T2_M2_SKU2", sku="SKU2", machine="M2", tool="T2"),
        ]
        engine = _engine(ops=ops)
        result = schedule_all(engine, audit=True)
        assign_decisions = [d for d in result.audit_trail.decisions if d.phase == "assign"]
        assert len(assign_decisions) >= 2

    def test_audit_no_performance_regression(self):
        """Audit overhead should be < 100ms."""
        engine = _engine()

        t0 = time.perf_counter()
        schedule_all(engine)
        base_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        schedule_all(engine, audit=True)
        audit_ms = (time.perf_counter() - t0) * 1000

        overhead = audit_ms - base_ms
        assert overhead < 100

    def test_score_unchanged_with_audit(self):
        """Audit should not affect schedule output."""
        engine = _engine()
        result_no_audit = schedule_all(engine)
        result_audit = schedule_all(engine, audit=True)
        assert result_no_audit.score == result_audit.score


# --- Diff Tests ---


class TestDiff:
    def test_identical_schedules(self):
        segs = [_seg(lot_id="L1", day=0), _seg(lot_id="L2", day=1)]
        diff = compute_diff(segs, segs, {}, {})
        assert len(diff.changes) == 0
        assert diff.summary == "Sem alterações"

    def test_machine_change_detected(self):
        old = [_seg(lot_id="L1", machine="M1", day=0)]
        new = [_seg(lot_id="L1", machine="M2", day=0)]
        diff = compute_diff(old, new, {}, {})
        types = {c.change_type for c in diff.changes}
        assert "MOVED" in types

    def test_added_removed_detected(self):
        old = [_seg(lot_id="L1", day=0), _seg(lot_id="L2", day=1)]
        new = [_seg(lot_id="L1", day=0), _seg(lot_id="L3", day=2)]
        diff = compute_diff(old, new, {}, {})
        types = {c.change_type for c in diff.changes}
        assert "ADDED" in types
        assert "REMOVED" in types

    def test_retimed_detected(self):
        old = [_seg(lot_id="L1", machine="M1", day=0)]
        new = [_seg(lot_id="L1", machine="M1", day=3)]
        diff = compute_diff(old, new, {}, {})
        types = {c.change_type for c in diff.changes}
        assert "RETIMED" in types

    def test_summary_in_portuguese(self):
        old = [_seg(lot_id="L1", day=0)]
        new = [_seg(lot_id="L2", day=1)]
        diff = compute_diff(old, new, {}, {})
        assert "novos" in diff.summary or "removidos" in diff.summary


# --- Store Tests ---


class TestAuditStore:
    def test_save_load_roundtrip(self):
        store = AuditStore(db_path=":memory:")
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        trail = logger.get_trail("test_schedule")
        store.save_trail(trail, {"otd": 100}, "test.xlsx")
        loaded = store.load_decisions("test_schedule")
        assert len(loaded) == 1
        assert loaded[0]["chosen"] == "M1"
        store.close()

    def test_list_schedules(self):
        store = AuditStore(db_path=":memory:")
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        trail = logger.get_trail("sched1")
        store.save_trail(trail, {"otd": 100})
        schedules = store.list_schedules()
        assert len(schedules) == 1
        assert schedules[0]["id"] == "sched1"
        assert schedules[0]["n_decisions"] == 1
        store.close()

    def test_filter_by_subject(self):
        store = AuditStore(db_path=":memory:")
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        logger.log_assign("r2", "T2", "M2", [("M2", 200)], "assign_no_alt")
        trail = logger.get_trail("sched")
        store.save_trail(trail, {})
        loaded = store.load_decisions("sched", subject_id="r1")
        assert len(loaded) == 1
        assert loaded[0]["subject_id"] == "r1"
        store.close()

    def test_store_can_be_reused_from_a_worker_thread(self):
        store = AuditStore(db_path=":memory:")
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        trail = logger.get_trail("threaded")

        with ThreadPoolExecutor(max_workers=1) as executor:
            saved_id = executor.submit(store.save_trail, trail, {"otd": 100}).result()
            loaded = executor.submit(store.load_decisions, saved_id).result()

        assert len(loaded) == 1
        assert loaded[0]["chosen"] == "M1"
        store.close()

    def test_resaving_schedule_replaces_decisions(self):
        store = AuditStore(db_path=":memory:")
        logger = AuditLogger()
        logger.log_assign("r1", "T1", "M1", [("M1", 100)], "assign_no_alt")
        trail = logger.get_trail("same-schedule")

        store.save_trail(trail, {"otd": 100})
        store.save_trail(trail, {"otd": 100})

        assert len(store.load_decisions("same-schedule")) == 1
        store.close()


# --- Counterfactual Tests ---


class TestCounterfactual:
    def test_force_machine(self):
        ops = [
            _eop(
                op_id="T1_M1_SKU1",
                machine="M1",
                tool="T1",
                alt="M2",
                d=[0, 500, 0, 300, 0, 0, 0, 0, 0, 0],
            ),
        ]
        engine = _engine(ops=ops)
        result = schedule_all(engine)
        cf = compute_counterfactual(
            "force_machine",
            {"tool_id": "T1", "to_machine": "M2"},
            engine,
            result.score,
        )
        assert cf.delta is not None
        assert cf.explanation_pt != ""
        assert cf.time_ms > 0
        assert cf.question == "E se T1 estivesse na M2?"

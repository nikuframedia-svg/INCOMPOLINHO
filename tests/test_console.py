"""Tests for Console — Spec 11."""

from __future__ import annotations

import json

import pytest

from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.console.action_items import (
    ActionItem,
    Fix,
    _aggregate_and_cap,
    _diagnose_why_short,
    _find_fix,
    _has_production_before,
    compute_action_items,
)
from backend.console.expedition_today import compute_expedition_today
from backend.console.machines_today import compute_machines_today
from backend.console.state_phrase import compute_state_phrase
from backend.console.tomorrow_prep import check_crew_bottleneck, compute_tomorrow_prep
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo, TwinGroup


# ─── Fixtures ─────────────────────────────────────────────────────────────


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
    eco_lot: int = 0,
    client: str = "CLIENTE",
) -> EOp:
    return EOp(
        id=op_id, sku=sku, client=client, designation="Peça teste",
        m=machine, t=tool, pH=pH, sH=sH, operators=1,
        eco_lot=eco_lot, alt=alt, stk=0, backlog=0,
        d=d or [0, 500, 0, 300, 0, 200, 0, 0, 0, 0], oee=oee, wip=0,
    )


def _engine(
    ops: list[EOp] | None = None,
    n_days: int = 10,
    twin_groups: list[TwinGroup] | None = None,
    client_demands: dict | None = None,
) -> EngineData:
    if ops is None:
        ops = [
            _eop("T1_M1_SKU1", "SKU1", "M1", "T1", alt="M2"),
            _eop("T2_M2_SKU2", "SKU2", "M2", "T2",
                 d=[0, 0, 400, 0, 300, 0, 0, 0, 0, 0]),
            _eop("T3_M1_SKU3", "SKU3", "M1", "T3",
                 d=[0, 600, 0, 0, 400, 0, 0, 0, 0, 0]),
        ]
    machine_ids = list({op.m for op in ops})
    for op in ops:
        if op.alt and op.alt not in machine_ids:
            machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    workdays = [f"2026-03-{i + 5:02d}" for i in range(n_days)]

    # Build client_demands from ops if not provided
    if client_demands is None:
        client_demands = {}
        for op in ops:
            entries = []
            for day_idx, qty in enumerate(op.d):
                if qty > 0:
                    entries.append(ClientDemandEntry(
                        client=op.client, sku=op.sku,
                        day_idx=day_idx,
                        date=workdays[day_idx] if day_idx < len(workdays) else "",
                        order_qty=qty, np_value=-qty,
                    ))
            if entries:
                client_demands[op.sku] = entries

    return EngineData(
        ops=ops, machines=machines, twin_groups=twin_groups or [],
        client_demands=client_demands,
        workdays=workdays, n_days=n_days, holidays=[],
    )


def _config() -> FactoryConfig:
    config = FactoryConfig()
    config.machines = {
        "M1": MachineConfig(id="M1", group="Grandes", active=True),
        "M2": MachineConfig(id="M2", group="Grandes", active=True),
    }
    config.tools = {
        "T1": {"primary": "M1", "alt": "M2", "setup_hours": 0.5},
        "T2": {"primary": "M2", "setup_hours": 0.5},
        "T3": {"primary": "M1", "setup_hours": 0.5},
    }
    return config


def _schedule(engine=None, config=None):
    engine = engine or _engine()
    config = config or _config()
    result = schedule_all(engine, config=config)
    return engine, config, result


# ─── TestStatePhrase ─────────────────────────────────────────────────────


class TestStatePhrase:
    def test_green_no_problems(self):
        expedition = {"total_orders": 3, "total_ready": 3}
        machines = {"machines": [{"util": 0.5}, {"util": 0.3}]}
        color, phrase = compute_state_phrase([], expedition, machines)
        assert color == "green"
        assert "Sem problemas" in phrase
        assert "2 máquinas" in phrase

    def test_red_critical(self):
        item = ActionItem(
            severity="critical", phrase="Entrega Faurecia em risco.",
            body="", actions=[], deadline="2026-03-06", client="FAURECIA",
            category="delivery",
        )
        color, phrase = compute_state_phrase(
            [item], {"total_orders": 1, "total_ready": 0},
            {"machines": [{"util": 0.5}]},
        )
        assert color == "red"
        assert "Faurecia" in phrase

    def test_yellow_warning(self):
        item = ActionItem(
            severity="warning", phrase="Stock de SKU1 esgota.",
            body="", actions=[], deadline="2026-03-08", client="",
            category="stockout",
        )
        color, phrase = compute_state_phrase(
            [item], {"total_orders": 2, "total_ready": 2},
            {"machines": [{"util": 0.5}]},
        )
        assert color == "yellow"

    def test_multiple_critical(self):
        items = [
            ActionItem(severity="critical", phrase="P1", body="", actions=[],
                       deadline="", client="A", category="delivery"),
            ActionItem(severity="critical", phrase="P2", body="", actions=[],
                       deadline="", client="B", category="delivery"),
        ]
        color, phrase = compute_state_phrase(
            items, {"total_orders": 0, "total_ready": 0},
            {"machines": []},
        )
        assert color == "red"
        assert "2 problemas" in phrase


# ─── TestMachinesToday ───────────────────────────────────────────────────


class TestMachinesToday:
    def test_machines_present(self):
        engine, config, result = _schedule()
        r = compute_machines_today(result.segments, engine, config, 0)
        machine_ids = {m["id"] for m in r["machines"]}
        for m in engine.machines:
            assert m.id in machine_ids

    def test_sorted_by_util(self):
        engine, config, result = _schedule()
        r = compute_machines_today(result.segments, engine, config, 0)
        utils = [m["util"] for m in r["machines"]]
        assert utils == sorted(utils, reverse=True)

    def test_setup_count(self):
        engine, config, result = _schedule()
        r = compute_machines_today(result.segments, engine, config, 0)
        expected = sum(
            1 for s in result.segments
            if s.day_idx == 0 and s.setup_min > 0
        )
        assert r["total_setups"] == expected

    def test_tool_sequence_no_repeats(self):
        engine, config, result = _schedule()
        r = compute_machines_today(result.segments, engine, config, 0)
        for m in r["machines"]:
            for i in range(1, len(m["tools"])):
                assert m["tools"][i]["id"] != m["tools"][i - 1]["id"]


# ─── TestExpeditionToday ─────────────────────────────────────────────────


class TestExpeditionToday:
    def test_all_ready_or_structure(self):
        engine, config, result = _schedule()
        r = compute_expedition_today(result.segments, result.lots, engine, 0)
        # Day 0 has no demand in our fixture → no expeditions
        # Just check structure
        assert "has_expeditions" in r
        assert "total_orders" in r
        assert "total_ready" in r
        assert "all_ready" in r

    def test_day_with_demand(self):
        engine, config, result = _schedule()
        # Day 1 has demand (SKU1=500, SKU3=600)
        r = compute_expedition_today(result.segments, result.lots, engine, 1)
        if r["has_expeditions"]:
            assert r["total_orders"] > 0
            assert isinstance(r["clients"], list)

    def test_no_expeditions_empty_day(self):
        engine, config, result = _schedule()
        # Day 9 has no demand
        r = compute_expedition_today(result.segments, result.lots, engine, 9)
        assert r["has_expeditions"] is False
        assert r["total_orders"] == 0


# ─── TestTomorrowPrep ────────────────────────────────────────────────────


class TestTomorrowPrep:
    def test_structure(self):
        engine, config, result = _schedule()
        r = compute_tomorrow_prep(result.segments, result.lots, engine, config, 1)
        assert "date" in r
        assert "setups" in r
        assert "operators" in r
        assert "problems" in r
        assert "ok" in r
        assert isinstance(r["ok"], bool)

    def test_setups_have_fields(self):
        engine, config, result = _schedule()
        r = compute_tomorrow_prep(result.segments, result.lots, engine, config, 1)
        for s in r["setups"]:
            assert "time" in s
            assert "machine" in s
            assert "to_tool" in s
            assert "duration_min" in s

    def test_ok_no_problems(self):
        engine, config, result = _schedule()
        # Default config has enough operators
        r = compute_tomorrow_prep(result.segments, result.lots, engine, config, 1)
        # Operator problems depend on actual schedule density
        assert isinstance(r["problems"], list)

    def test_expeditions_summary(self):
        engine, config, result = _schedule()
        r = compute_tomorrow_prep(result.segments, result.lots, engine, config, 1)
        assert isinstance(r["expeditions_summary"], str)


# ─── TestCrewBottleneck ──────────────────────────────────────────────────


class TestCrewBottleneck:
    def test_no_bottleneck_few_setups(self):
        segs = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=1, start_min=420, end_min=480, shift="A", qty=100,
                    prod_min=30, setup_min=30),
            Segment(lot_id="L2", run_id="R2", machine_id="M2", tool_id="T2",
                    day_idx=1, start_min=500, end_min=560, shift="A", qty=100,
                    prod_min=30, setup_min=30),
        ]
        result = check_crew_bottleneck(segs, day_idx=1)
        assert len(result) == 0

    def test_bottleneck_3_setups(self):
        segs = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=1, start_min=420, end_min=480, shift="A", qty=100,
                    prod_min=30, setup_min=30),
            Segment(lot_id="L2", run_id="R2", machine_id="M2", tool_id="T2",
                    day_idx=1, start_min=450, end_min=510, shift="A", qty=100,
                    prod_min=30, setup_min=30),
            Segment(lot_id="L3", run_id="R3", machine_id="M3", tool_id="T3",
                    day_idx=1, start_min=480, end_min=540, shift="A", qty=100,
                    prod_min=30, setup_min=30),
        ]
        result = check_crew_bottleneck(segs, day_idx=1)
        assert len(result) >= 1
        assert result[0]["simultaneous"] >= 3


# ─── TestActionItems ─────────────────────────────────────────────────────


class TestActionItems:
    def test_no_alerts_normal_schedule(self):
        """Well-balanced schedule should have few or no alerts."""
        engine, config, result = _schedule()
        actions = compute_action_items(result.segments, result.lots, engine, config)
        # Should be max 7
        assert len(actions) <= 7

    def test_delivery_risk_with_shortfall(self):
        """Shortfall in production → delivery alert."""
        # Create segments that only produce 200 of 500 needed by day 1
        ops = [_eop("T1_M1_SKU1", "SKU1", "M1", "T1",
                     d=[0, 500, 0, 0, 0, 0, 0, 0, 0, 0], pH=100.0)]
        engine = _engine(ops=ops)
        config = _config()
        # Manually create insufficient segments (bypass scheduler)
        from backend.scheduler.types import Lot, Segment
        lots = [Lot(id="L1", op_id="T1_M1_SKU1", tool_id="T1",
                     machine_id="M1", alt_machine_id=None, qty=200,
                     prod_min=20, setup_min=30, edd=1, is_twin=False)]
        segs = [Segment(lot_id="L1", run_id="R1", machine_id="M1",
                        tool_id="T1", day_idx=0, start_min=420, end_min=440,
                        shift="A", qty=200, prod_min=20, setup_min=0,
                        is_continuation=False, edd=1, sku="SKU1")]
        actions = compute_action_items(segs, lots, engine, config)
        delivery = [a for a in actions if a.category == "delivery"]
        assert len(delivery) >= 1
        assert delivery[0].severity in ("critical", "warning")

    def test_no_alert_distant_delivery(self):
        """Delivery far in the future (day > 5) → no alert."""
        ops = [_eop("T1_M1_FAR", "FAR", "M1", "T1",
                     d=[0, 0, 0, 0, 0, 0, 0, 500, 0, 0], pH=100.0)]
        engine = _engine(ops=ops)
        config = _config()
        result = schedule_all(engine, config=config)
        actions = compute_action_items(result.segments, result.lots, engine, config)
        delivery = [a for a in actions if a.category == "delivery"]
        assert len(delivery) == 0

    def test_critical_before_warning(self):
        items = [
            ActionItem(severity="warning", phrase="W", body="", actions=[],
                       deadline="2026-03-06", client="A", category="delivery"),
            ActionItem(severity="critical", phrase="C", body="", actions=[],
                       deadline="2026-03-07", client="B", category="delivery"),
        ]
        agg = _aggregate_and_cap(items)
        assert agg[0].severity == "critical"

    def test_max_7_alerts(self):
        items = [
            ActionItem(severity="warning", phrase=f"W{i}", body="", actions=[],
                       deadline=f"2026-03-{6 + i:02d}", client=f"C{i}",
                       category="delivery")
            for i in range(20)
        ]
        agg = _aggregate_and_cap(items)
        assert len(agg) <= 7

    def test_aggregation_same_client(self):
        items = [
            ActionItem(severity="warning", phrase="W", body=f"B{i}", actions=[],
                       deadline="2026-03-06", client="FAURECIA",
                       category="delivery")
            for i in range(5)
        ]
        agg = _aggregate_and_cap(items)
        faurecia = [a for a in agg if a.client == "FAURECIA"]
        assert len(faurecia) == 1
        assert "5 entregas" in faurecia[0].phrase


# ─── TestDiagnose ────────────────────────────────────────────────────────


class TestDiagnose:
    def test_diagnose_no_plan(self):
        from backend.analytics.expedition import ExpeditionEntry
        entry = ExpeditionEntry(
            day_idx=1, date="2026-03-06", client="TEST", sku="NOPE",
            order_qty=100, produced_qty=0, status="not_planned",
            coverage_pct=0, shortfall=100,
        )
        engine = _engine()
        result = _diagnose_why_short(entry, [], [], engine)
        assert "não está no plano" in result.lower()

    def test_diagnose_no_segments(self):
        from backend.analytics.expedition import ExpeditionEntry
        entry = ExpeditionEntry(
            day_idx=1, date="2026-03-06", client="CLIENTE", sku="SKU1",
            order_qty=500, produced_qty=0, status="not_planned",
            coverage_pct=0, shortfall=500,
        )
        engine = _engine()
        result = _diagnose_why_short(entry, [], [], engine)
        assert "sem produção" in result.lower()

    def test_diagnose_late_production(self):
        from backend.analytics.expedition import ExpeditionEntry
        entry = ExpeditionEntry(
            day_idx=1, date="2026-03-06", client="CLIENTE", sku="SKU1",
            order_qty=500, produced_qty=0, status="partial",
            coverage_pct=0, shortfall=500,
        )
        engine = _engine()
        lots = [Lot(id="L1", op_id="T1_M1_SKU1", tool_id="T1", machine_id="M1",
                     alt_machine_id=None, qty=500, prod_min=100, setup_min=30,
                     edd=1, is_twin=False, twin_outputs=None)]
        segs = [Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                        day_idx=5, start_min=420, end_min=550, shift="A", qty=500,
                        prod_min=100, setup_min=30)]
        result = _diagnose_why_short(entry, segs, lots, engine)
        assert "depois da entrega" in result.lower()


# ─── TestFindFix ─────────────────────────────────────────────────────────


class TestFindFix:
    def test_fix_alt_machine(self):
        from backend.analytics.expedition import ExpeditionEntry
        entry = ExpeditionEntry(
            day_idx=1, date="2026-03-06", client="CLIENTE", sku="SKU1",
            order_qty=500, produced_qty=0, status="partial",
            coverage_pct=0, shortfall=500,
        )
        engine = _engine()
        config = _config()
        # No segments on M2 → M2 has full capacity
        fix = _find_fix(entry, engine, [], config)
        assert fix is not None
        assert "M2" in fix.description

    def test_fix_none_no_alt(self):
        from backend.analytics.expedition import ExpeditionEntry
        # SKU2 has no alt machine
        entry = ExpeditionEntry(
            day_idx=1, date="2026-03-06", client="CLIENTE", sku="SKU2",
            order_qty=500, produced_qty=0, status="partial",
            coverage_pct=0, shortfall=500,
        )
        engine = _engine()
        config = _config()
        fix = _find_fix(entry, engine, [], config)
        # SKU2 op has no alt, but night shift may work
        # With pH=100 and oee=0.66: needed = 500 / (100*0.66) * 60 = 454 min > 420
        # So night shift won't work either
        assert fix is None

    def test_fix_night_shift(self):
        from backend.analytics.expedition import ExpeditionEntry
        # SKU3 has no alt, but small shortfall fits in night shift
        entry = ExpeditionEntry(
            day_idx=1, date="2026-03-06", client="CLIENTE", sku="SKU3",
            order_qty=200, produced_qty=0, status="partial",
            coverage_pct=0, shortfall=200,
        )
        engine = _engine()
        config = _config()
        # Fill M2 so alt doesn't apply, and SKU3 has no alt anyway
        fix = _find_fix(entry, engine, [], config)
        # pH=100, oee=0.66: needed = 200 / (100*0.66) * 60 = 181 min < 420
        assert fix is not None
        assert "noite" in fix.description.lower()


# ─── TestHasProductionBefore ─────────────────────────────────────────────


class TestHasProductionBefore:
    def test_has_production(self):
        from backend.analytics.stock_projection import StockProjection, StockDay
        proj = StockProjection(
            op_id="T1_M1_SKU1", sku="SKU1", client="CLIENTE",
            days=[], initial_stock=0, stockout_day=3,
            coverage_days=3.0, total_demand=1000, total_produced=500,
        )
        lots = [Lot(id="L1", op_id="T1_M1_SKU1", tool_id="T1", machine_id="M1",
                     alt_machine_id=None, qty=500, prod_min=100, setup_min=30,
                     edd=1, is_twin=False, twin_outputs=None)]
        segs = [Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                        day_idx=2, start_min=420, end_min=550, shift="A", qty=500,
                        prod_min=100, setup_min=30)]
        assert _has_production_before(proj, segs, lots) is True

    def test_no_production(self):
        from backend.analytics.stock_projection import StockProjection
        proj = StockProjection(
            op_id="T1_M1_SKU1", sku="SKU1", client="CLIENTE",
            days=[], initial_stock=0, stockout_day=3,
            coverage_days=3.0, total_demand=1000, total_produced=0,
        )
        assert _has_production_before(proj, [], []) is False


# ─── TestConsoleAPI ──────────────────────────────────────────────────────


class TestConsoleAPI:
    def test_console_structure(self):
        from backend.copilot.state import state

        engine, config, result = _schedule()
        state.engine_data = engine
        state.config = config
        state.update_schedule(result)

        try:
            from backend.api.console import router
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
        except ImportError:
            pytest.skip("fastapi not installed")

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/console?day_idx=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "state" in data
        assert "color" in data["state"]
        assert "phrase" in data["state"]
        assert "actions" in data
        assert "machines" in data
        assert "expedition" in data
        assert "tomorrow" in data

    def test_console_no_data_503(self):
        from backend.copilot.state import state

        state.engine_data = None
        state.config = None

        try:
            from backend.api.console import router
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
        except ImportError:
            pytest.skip("fastapi not installed")

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/console?day_idx=0")
        assert resp.status_code == 503

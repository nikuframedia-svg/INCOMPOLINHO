"""Tests for backend/scheduler/window.py — Fase 1.3 materials-window policy."""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.gates import build_gate_report
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.types import Lot
from backend.scheduler.window import (
    compute_lot_floor,
    compute_window_gates,
    effective_earliness_target,
)
from backend.types import EngineData, EOp, MachineInfo


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
        d=d or [0] * 12,
        oee=oee,
        wip=0,
    )


def _engine(ops: list[EOp], n_days: int = 12, holidays: list[int] | None = None) -> EngineData:
    machine_ids: list[str] = []
    for op in ops:
        if op.m not in machine_ids:
            machine_ids.append(op.m)
        if op.alt and op.alt not in machine_ids:
            machine_ids.append(op.alt)
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{i + 2:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=holidays or [],
    )


def _lot(lot_id: str = "L1", edd: int = 8, prod_min: float = 300.0) -> Lot:
    return Lot(
        id=lot_id,
        op_id="T1_M1_SKU1",
        tool_id="T1",
        machine_id="M1",
        alt_machine_id=None,
        qty=100,
        prod_min=prod_min,
        setup_min=30.0,
        edd=edd,
        is_twin=False,
    )


class TestFloorArithmetic:
    def test_floor_simple(self):
        assert compute_lot_floor(_lot(edd=8), set(), 5) == 3

    def test_floor_skips_holidays(self):
        # Holidays at 5 and 6 → need 2 extra days back
        assert compute_lot_floor(_lot(edd=8), {5, 6}, 5) == 1

    def test_floor_clamps_at_zero(self):
        assert compute_lot_floor(_lot(edd=3), set(), 5) == 0

    def test_lot_bigger_than_window_yields(self):
        """A lot needing more days than the window keeps a feasible start."""
        config = FactoryConfig(earliness_policy="window", material_release_days=2)
        # 3 full days of production → latest feasible start = edd − 3 < edd − 2
        big = _lot(edd=8, prod_min=3 * 1020.0)
        run_gates, lot_floors = compute_window_gates(
            {"M1": [_run_of(big)]}, set(), config
        )
        # Floor must be edd − 3 (feasible), not edd − 2 (window)
        assert lot_floors[big.id] <= (8 - 3) * 1020.0


def _run_of(lot: Lot):
    from backend.scheduler.types import ToolRun

    return ToolRun(
        id=f"run_{lot.id}",
        tool_id=lot.tool_id,
        machine_id=lot.machine_id,
        alt_machine_id=None,
        lots=[lot],
        setup_min=lot.setup_min,
        total_prod_min=lot.prod_min,
        total_min=lot.setup_min + lot.prod_min,
        edd=lot.edd,
    )


class TestWindowPolicy:
    def test_jit_policy_unchanged(self):
        """Default policy (jit) produces the same plan as before the change."""
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 500, 0, 300, 0, 0, 0])]
        r_default = schedule_all(_engine(ops))
        r_explicit = schedule_all(_engine(ops), config=FactoryConfig(earliness_policy="jit"))
        assert r_default.score == r_explicit.score

    def test_window_starts_at_floor_not_before(self):
        """Production starts as early as possible but never before edd − N."""
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0])]  # demand at day 8
        config = FactoryConfig(earliness_policy="window", material_release_days=5)
        result = schedule_all(_engine(ops), config=config)

        assert result.score["otd"] == 100.0
        assert result.score["tardy_count"] == 0
        prod_days = [s.day_idx for s in result.segments if s.qty > 0]
        assert prod_days, "expected production segments"
        # Floor = 8 − 5 = 3: earliest-in-window means starting AT day 3
        assert min(prod_days) == 3
        assert result.score["early_window_violations"] == 0

    def test_window_earlier_than_jit(self):
        """Window policy produces earlier than JIT (its whole purpose)."""
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0])]
        r_jit = schedule_all(_engine(ops), config=FactoryConfig(earliness_policy="jit"))
        r_win = schedule_all(
            _engine(ops),
            config=FactoryConfig(earliness_policy="window", material_release_days=5),
        )
        jit_start = min(s.day_idx for s in r_jit.segments if s.qty > 0)
        win_start = min(s.day_idx for s in r_win.segments if s.qty > 0)
        assert win_start <= jit_start
        assert win_start == 3

    def test_window_respects_holidays(self):
        """Floor is measured in workdays: holidays push it earlier."""
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0])]
        config = FactoryConfig(earliness_policy="window", material_release_days=5)
        result = schedule_all(_engine(ops, holidays=[5, 6]), config=config)
        assert result.score["otd"] == 100.0
        prod_days = [s.day_idx for s in result.segments if s.qty > 0]
        # Floor with holidays {5,6}: 8−5 workdays → day 1
        assert min(prod_days) == 1
        assert 5 not in prod_days and 6 not in prod_days

    def test_window_keeps_otd_on_tight_demand(self):
        """Demand at day 1 (inside window width) still delivers on time."""
        ops = [_eop(d=[0, 800, 0, 0, 0, 0, 500, 0, 0, 0, 0, 0])]
        config = FactoryConfig(earliness_policy="window", material_release_days=5)
        result = schedule_all(_engine(ops), config=config)
        assert result.score["otd"] == 100.0
        assert result.score["otd_d"] == 100.0
        assert result.score["tardy_count"] == 0


class TestWindowMetricsAndGates:
    def _early_plan(self, enforcement: str):
        """ASAP plan (no phase-4 timing) under window policy → violations."""
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 0, 0, 500, 0, 0, 0])]
        engine = _engine(ops)
        config = FactoryConfig(
            earliness_policy="window",
            material_release_days=5,
            early_window_enforcement=enforcement,
            jit_enabled=False,  # baseline ASAP → starts day 0, floor is 3
        )
        result = schedule_all(engine, config=config)
        return result, engine, config

    def test_soft_counts_but_does_not_gate(self):
        result, engine, config = self._early_plan("soft")
        assert result.score["early_window_violations"] > 0
        report = build_gate_report(
            result.segments, result.lots, result.score, engine, config
        )
        assert report["material_gate_passed"] is True
        assert report["status"] == "applicable"

    def test_hard_gates_to_infeasible_conditions(self):
        result, engine, config = self._early_plan("hard")
        report = build_gate_report(
            result.segments, result.lots, result.score, engine, config
        )
        assert report["material_gate_passed"] is False
        assert report["status"] == "infeasible_current_conditions"
        assert report["hard_gate_passed"] is True  # never invalid_physics

    def test_jit_policy_has_zero_window_metrics(self):
        ops = [_eop(d=[0, 0, 0, 0, 0, 0, 500, 0, 0, 0, 0, 0])]
        result = schedule_all(_engine(ops), config=FactoryConfig())
        assert result.score["early_window_violations"] == 0


class TestEarlinessTarget:
    def test_target_recalibrated_under_window(self):
        c = FactoryConfig(
            earliness_policy="window", material_release_days=5, jit_earliness_target=5.5
        )
        assert effective_earliness_target(c) == 7.5

    def test_target_unchanged_under_jit(self):
        c = FactoryConfig(earliness_policy="jit", jit_earliness_target=5.5)
        assert effective_earliness_target(c) == 5.5

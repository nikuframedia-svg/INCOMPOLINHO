"""Tests for Risk Assessment — Spec 06."""

from __future__ import annotations

import time

from backend.config.types import FactoryConfig, MachineConfig
from backend.risk import compute_risk, RiskResult
from backend.risk.heatmap import compute_heatmap
from backend.risk.slack_analytics import (
    compute_health_score,
    compute_lot_risks,
    compute_machine_risks,
)
from backend.risk.surrogate import extract_features, predict_risk
from backend.risk.types import LotRisk, MachineRisk
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.types import Lot, Segment
from backend.types import EngineData, EOp, MachineInfo


# --- Fixtures ---

WORKDAYS = ["2026-03-05", "2026-03-06", "2026-03-07", "2026-03-10", "2026-03-11"]


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
    operators: int = 1,
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
        operators=operators,
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
    n_days: int = 5,
) -> EngineData:
    if ops is None:
        ops = [_eop()]
    machine_ids = list({op.m for op in ops})
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands={},
        workdays=WORKDAYS[:n_days],
        n_days=n_days,
        holidays=[],
    )


def _lot(
    lot_id: str = "L1",
    op_id: str = "T1_M1_SKU1",
    tool: str = "T1",
    machine: str = "M1",
    edd: int = 4,
    qty: int = 500,
    prod_min: float = 300.0,
    setup_min: float = 30.0,
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=op_id,
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=None,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=edd,
        is_twin=False,
    )


def _seg(
    lot_id: str = "L1",
    machine: str = "M1",
    tool: str = "T1",
    sku: str = "SKU1",
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
        sku=sku,
    )


# --- Tier 1: Lot Risks ---


class TestLotRisks:
    def test_large_slack_is_low_risk(self):
        """Lot completing well before EDD → low risk."""
        engine = _engine()
        lots = [_lot(edd=4)]
        segs = [_seg(day=0)]  # completes day 0, edd=4 → slack=4

        risks = compute_lot_risks(segs, lots, engine)
        assert len(risks) == 1
        assert risks[0].risk_level == "low"
        assert risks[0].slack_days == 4
        assert risks[0].risk_score < 0.5

    def test_zero_slack_is_critical(self):
        """Lot completing on EDD → critical."""
        engine = _engine()
        lots = [_lot(edd=2)]
        segs = [_seg(day=2)]  # completes day 2, edd=2 → slack=0

        risks = compute_lot_risks(segs, lots, engine)
        assert risks[0].risk_level == "critical"
        assert risks[0].slack_days == 0
        # Zero slack alone proves nothing about which resource is short.
        assert risks[0].binding_constraint == "none"
        assert risks[0].cause is None
        assert risks[0].status == "at_limit"

    def test_negative_slack_is_critical(self):
        """Lot completing after EDD → critical with negative slack."""
        engine = _engine()
        lots = [_lot(edd=1)]
        segs = [_seg(day=3)]  # completes day 3, edd=1 → slack=-2

        risks = compute_lot_risks(segs, lots, engine)
        assert risks[0].risk_level == "critical"
        assert risks[0].slack_days == -2

    def test_one_day_slack_is_high(self):
        """Lot with 1 day slack → high risk."""
        engine = _engine()
        lots = [_lot(edd=3)]
        segs = [_seg(day=2)]  # slack=1

        risks = compute_lot_risks(segs, lots, engine)
        assert risks[0].risk_level == "high"
        assert risks[0].binding_constraint == "none"
        assert risks[0].cause is None
        assert risks[0].status == "short_slack"

    def test_risk_score_between_0_and_1(self):
        """Risk score is bounded [0, 1]."""
        engine = _engine()
        lots = [_lot(edd=0), _lot(lot_id="L2", edd=20, prod_min=10.0)]
        segs = [_seg(day=2, lot_id="L1"), _seg(day=0, lot_id="L2")]

        risks = compute_lot_risks(segs, lots, engine)
        for r in risks:
            assert 0.0 <= r.risk_score <= 1.0

    def test_binding_constraint_identifies_jit_exception(self):
        engine = _engine(n_days=5)
        lots = [_lot(edd=10)]
        lots[0].delivery_day = 10
        segs = [_seg(day=0)]

        risks = compute_lot_risks(segs, lots, engine, FactoryConfig())

        assert risks[0].binding_constraint == "jit_exception"

    def test_binding_constraint_identifies_long_consecutive_run(self):
        engine = _engine(n_days=6)
        lots = [_lot(edd=10)]
        lots[0].delivery_day = 4
        segs = [
            _seg(day=day, start=420, end=480, prod_min=60, setup_min=0)
            for day in range(5)
        ]

        risks = compute_lot_risks(segs, lots, engine, FactoryConfig(max_run_days=4))

        assert risks[0].binding_constraint == "long_run"

    def test_binding_constraint_identifies_operator_capacity(self):
        engine = _engine(ops=[_eop(operators=2)], n_days=5)
        lots = [_lot(edd=4)]
        lots[0].delivery_day = 4
        segs = [_seg(day=0, setup_min=0)]
        config = FactoryConfig()
        config.machines = {"M1": MachineConfig(id="M1", group="Grandes")}
        config.operators[("Grandes", "A")] = 1

        risks = compute_lot_risks(segs, lots, engine, config)

        assert risks[0].binding_constraint == "operator"

    def test_binding_constraint_identifies_setup_overlap(self):
        engine = _engine(
            ops=[
                _eop(op_id="OP1", sku="SKU1", machine="M1", tool="T1"),
                _eop(op_id="OP2", sku="SKU2", machine="M2", tool="T2"),
            ],
            n_days=5,
        )
        lots = [
            _lot("L1", op_id="OP1", tool="T1", machine="M1", edd=4),
            _lot("L2", op_id="OP2", tool="T2", machine="M2", edd=4),
        ]
        for lot in lots:
            lot.delivery_day = 4
        segs = [
            _seg(lot_id="L1", machine="M1", tool="T1", setup_min=30),
            _seg(lot_id="L2", machine="M2", tool="T2", sku="SKU2", setup_min=30),
        ]
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes"),
            "M2": MachineConfig(id="M2", group="Grandes"),
        }

        risks = compute_lot_risks(segs, lots, engine, config)

        assert {risk.binding_constraint for risk in risks} == {"setup"}

    def test_binding_constraint_identifies_calendar_block(self):
        engine = _engine(n_days=5)
        engine.machine_blocked_days = {"M1": {0}}
        lots = [_lot(edd=4)]
        lots[0].delivery_day = 4
        segs = [_seg(day=0, setup_min=0)]

        risks = compute_lot_risks(segs, lots, engine, FactoryConfig())

        assert risks[0].binding_constraint == "calendar"


# --- Tier 1: Machine Risks ---


class TestMachineRisks:
    def test_utilization_computed(self):
        """Machine utilization from segments."""
        engine = _engine()
        lots = [_lot()]
        segs = [_seg(prod_min=500.0, setup_min=30.0)]
        lot_risks = compute_lot_risks(segs, lots, engine)

        machine_risks = compute_machine_risks(segs, lot_risks, engine)
        assert len(machine_risks) == 1
        assert machine_risks[0].machine_id == "M1"
        # 530 min on day 0 / 1020 = ~0.520
        assert 0.4 < machine_risks[0].peak_utilization < 0.6

    def test_critical_lot_count(self):
        """Counts lots with critical/high risk on each machine."""
        engine = _engine()
        lots = [_lot(edd=0)]  # will be critical
        segs = [_seg(day=1)]

        lot_risks = compute_lot_risks(segs, lots, engine)
        machine_risks = compute_machine_risks(segs, lot_risks, engine)
        assert machine_risks[0].critical_lot_count >= 1


# --- Tier 1: Health Score ---


class TestHealthScore:
    def test_health_in_range(self):
        """Health score is 0-100."""
        lot_risks = [
            LotRisk("L1", "SKU1", "M1", 4, 0, 4, 4080.0, 0.1, "low", "none"),
            LotRisk("L2", "SKU2", "M1", 3, 3, 0, 0.0, 1.0, "critical", "capacity"),
        ]
        machine_risks = [
            MachineRisk("M1", 0.85, 0.50, 1, 0.0),
        ]

        score = compute_health_score(lot_risks, machine_risks)
        assert 0 <= score <= 100

    def test_all_safe_high_score(self):
        """All low-risk lots → high health score."""
        lot_risks = [
            LotRisk("L1", "SKU1", "M1", 10, 0, 10, 10200.0, 0.0, "low", "none"),
        ]
        machine_risks = [
            MachineRisk("M1", 0.30, 0.20, 0, 0.0),
        ]

        score = compute_health_score(lot_risks, machine_risks)
        assert score >= 70

    def test_all_critical_low_score(self):
        """All critical lots → low health score."""
        lot_risks = [
            LotRisk("L1", "SKU1", "M1", 0, 2, -2, -2040.0, 1.0, "critical", "capacity"),
        ]
        machine_risks = [
            MachineRisk("M1", 0.99, 0.90, 1, 0.0),
        ]

        score = compute_health_score(lot_risks, machine_risks)
        assert score <= 30


# --- Tier 1: Heatmap ---


class TestHeatmap:
    def test_heatmap_dimensions(self):
        """Heatmap = n_machines × n_days cells."""
        engine = _engine(n_days=3)
        lots = [_lot()]
        segs = [_seg(day=0)]
        lot_risks = compute_lot_risks(segs, lots, engine)

        cells = compute_heatmap(segs, lot_risks, engine)
        assert len(cells) == 1 * 3  # 1 machine × 3 days

    def test_heatmap_levels(self):
        """Cells have valid risk levels."""
        engine = _engine(n_days=2)
        lots = [_lot()]
        segs = [_seg(day=0)]
        lot_risks = compute_lot_risks(segs, lots, engine)

        cells = compute_heatmap(segs, lot_risks, engine)
        for cell in cells:
            assert cell.risk_level in ("low", "medium", "high", "critical")

    def test_heatmap_high_util_is_critical(self):
        """Day with >95% utilization → critical."""
        engine = _engine(n_days=1)
        lots = [_lot()]
        segs = [_seg(day=0, prod_min=980.0, setup_min=30.0)]  # >1020 → util > 0.99
        lot_risks = compute_lot_risks(segs, lots, engine)

        cells = compute_heatmap(segs, lot_risks, engine)
        assert cells[0].risk_level == "critical"
        assert cells[0].load_min == 1010.0
        assert cells[0].capacity_min == 1020.0


# --- Tier 2: Surrogate ---


class TestSurrogate:
    def test_extract_features_length(self):
        """Feature vector has exactly 10 elements."""
        engine = _engine()
        lot_risks = [
            LotRisk("L1", "SKU1", "M1", 4, 0, 4, 4080.0, 0.1, "low", "none"),
        ]
        machine_risks = [
            MachineRisk("M1", 0.50, 0.30, 0, 0.0),
        ]

        features = extract_features(lot_risks, machine_risks, engine)
        assert len(features) == 10

    def test_predict_returns_none_untrained(self):
        """predict_risk returns None when no model file exists."""
        features = [0.0] * 10
        result = predict_risk(features)
        assert result is None


# --- Integration: compute_risk ---


class TestComputeRisk:
    def test_returns_risk_result(self):
        """compute_risk returns a valid RiskResult."""
        engine = _engine()
        lots = [_lot()]
        segs = [_seg(day=0)]

        result = compute_risk(segs, lots, engine)
        assert isinstance(result, RiskResult)
        assert 0 <= result.health_score <= 100
        assert len(result.lot_risks) == 1
        assert len(result.machine_risks) == 1
        assert result.critical_count >= 0
        assert len(result.top_risks) <= 5
        assert result.bottleneck != ""

    def test_mc_cache_populated(self):
        """Monte Carlo cache populates Tier 3 fields."""
        engine = _engine()
        lots = [_lot()]
        segs = [_seg(day=0)]
        mc = {
            "otd_p50": 98.5,
            "otd_p80": 95.0,
            "otd_p95": 88.0,
            "tardy_mean": 1.2,
            "n_samples": 500,
        }

        result = compute_risk(segs, lots, engine, mc_cache=mc)
        assert result.mc_otd_p50 == 98.5
        assert result.mc_otd_p80 == 95.0
        assert result.mc_otd_p95 == 88.0
        assert result.mc_tardy_expected == 1.2
        assert result.mc_runs == 500

    def test_no_mc_cache_is_none(self):
        """Without MC cache, Tier 3 fields are None."""
        engine = _engine()
        lots = [_lot()]
        segs = [_seg(day=0)]

        result = compute_risk(segs, lots, engine)
        assert result.mc_otd_p50 is None
        assert result.mc_runs is None

    def test_performance_under_200ms(self):
        """compute_risk completes in <200ms for small input."""
        ops = [_eop(op_id=f"T{i}_M1_SKU{i}", sku=f"SKU{i}", tool=f"T{i}") for i in range(10)]
        engine = _engine(ops=ops, n_days=20)
        lots = [
            _lot(lot_id=f"L{i}", op_id=f"T{i}_M1_SKU{i}", tool=f"T{i}", edd=i + 5)
            for i in range(10)
        ]
        segs = [_seg(lot_id=f"L{i}", tool=f"T{i}", day=i % 5) for i in range(10)]

        t0 = time.perf_counter()
        result = compute_risk(segs, lots, engine)
        elapsed = (time.perf_counter() - t0) * 1000

        assert elapsed < 200
        assert isinstance(result, RiskResult)

    def test_empty_schedule(self):
        """compute_risk handles empty segments/lots gracefully."""
        engine = _engine()
        result = compute_risk([], [], engine)
        assert isinstance(result, RiskResult)
        assert result.health_score >= 0
        assert result.lot_risks == []

    def test_top_risks_late_first_then_nearest_date(self):
        """Late lots first, then the nearest due day; lots with room are hidden."""
        engine = _engine()
        lots = [
            _lot(lot_id="L1", edd=10),
            _lot(lot_id="L2", edd=1),
            _lot(lot_id="L3", edd=0),
        ]
        segs = [
            _seg(lot_id="L1", day=0),
            _seg(lot_id="L2", day=0),
            _seg(lot_id="L3", day=1),
        ]

        result = compute_risk(segs, lots, engine)
        assert [r.lot_id for r in result.top_risks] == ["L3", "L2"]
        assert [r.status for r in result.top_risks] == ["late", "short_slack"]

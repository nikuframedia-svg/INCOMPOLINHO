"""Tests for analytics — Spec 03: Stock Projection, CTP, Expedition."""

from __future__ import annotations

import pytest

from backend.analytics import (
    build_production_by_op,
    compute_ctp,
    compute_expedition,
    compute_order_tracking,
    compute_stock_projections,
)
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.constants import DAY_CAP
from backend.scheduler.types import Lot, Segment
from backend.types import ClientDemandEntry, EngineData, EOp, MachineInfo

WORKDAYS = [
    "2026-03-05",
    "2026-03-06",
    "2026-03-07",
    "2026-03-10",
    "2026-03-11",
    "2026-03-12",
]


# --- Fixtures ---


def _eop(
    op_id: str = "op1",
    sku: str = "SKU1",
    machine: str = "M1",
    tool: str = "T1",
    d: list[int] | None = None,
    pH: float = 100.0,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
    client: str = "CLIENT",
) -> EOp:
    return EOp(
        id=op_id,
        sku=sku,
        client=client,
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
    n_days: int = 5,
    client_demands: dict | None = None,
    holidays: list[int] | None = None,
) -> EngineData:
    if ops is None:
        ops = [_eop()]
    machine_ids = list({machine for op in ops for machine in (op.m, op.alt) if machine})
    machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=[],
        client_demands=client_demands or {},
        workdays=WORKDAYS[:n_days],
        n_days=n_days,
        holidays=holidays or [],
    )


def _lot(
    lot_id: str = "L1",
    op_id: str = "op1",
    tool_id: str = "T1",
    machine_id: str = "M1",
    qty: int = 500,
    prod_min: float = 100.0,
    setup_min: float = 30.0,
    edd: int = 3,
    is_twin: bool = False,
    twin_outputs: list[tuple[str, str, int]] | None = None,
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=op_id,
        tool_id=tool_id,
        machine_id=machine_id,
        alt_machine_id=None,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=edd,
        is_twin=is_twin,
        twin_outputs=twin_outputs,
    )


def _seg(
    lot_id: str = "L1",
    run_id: str = "R1",
    machine: str = "M1",
    tool: str = "T1",
    day: int = 0,
    qty: int = 500,
    prod_min: float = 100.0,
    setup_min: float = 30.0,
    sku: str = "SKU1",
    twin_outputs: list[tuple[str, str, int]] | None = None,
) -> Segment:
    return Segment(
        lot_id=lot_id,
        run_id=run_id,
        machine_id=machine,
        tool_id=tool,
        day_idx=day,
        start_min=420,
        end_min=520,
        shift="A",
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=3,
        sku=sku,
        twin_outputs=twin_outputs,
    )


# ═══ BUILD PRODUCTION BY OP ═══


class TestBuildProductionByOp:
    def test_basic(self):
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=1000)]
        prod = build_production_by_op(segs, lots)
        assert prod["op1"][0] == 1000

    def test_twin_outputs(self):
        lots = [
            _lot(op_id="op1", is_twin=True, twin_outputs=[("op1", "A", 500), ("op2", "B", 300)])
        ]
        segs = [_seg(day=0, qty=500, twin_outputs=[("op1", "A", 500), ("op2", "B", 300)])]
        prod = build_production_by_op(segs, lots)
        assert prod["op1"][0] == 500
        assert prod["op2"][0] == 300

    def test_empty(self):
        prod = build_production_by_op([], [])
        assert len(prod) == 0


# ═══ STOCK PROJECTION ═══


class TestStockProjection:
    def test_basic(self):
        """Stock = produced - demand."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=1000)]
        engine = _engine(ops=[_eop(d=[800, 0, 0, 0, 0])])

        projs = compute_stock_projections(segs, lots, engine)
        assert len(projs) == 1
        assert projs[0].days[0].stock == 1000 - 800  # 200

    def test_twin(self):
        """Twin segment credits both ops."""
        lots = [
            _lot(op_id="op1", is_twin=True, twin_outputs=[("op1", "A", 5000), ("op2", "B", 5000)])
        ]
        segs = [_seg(day=0, qty=5000, twin_outputs=[("op1", "A", 5000), ("op2", "B", 5000)])]
        engine = _engine(
            ops=[
                _eop(op_id="op1", sku="A", d=[3000, 0, 0, 0, 0]),
                _eop(op_id="op2", sku="B", d=[2000, 0, 0, 0, 0]),
            ]
        )

        projs = compute_stock_projections(segs, lots, engine)
        p1 = next(p for p in projs if p.op_id == "op1")
        p2 = next(p for p in projs if p.op_id == "op2")
        assert p1.days[0].stock == 5000 - 3000  # 2000
        assert p2.days[0].stock == 5000 - 2000  # 3000

    def test_stockout_detected(self):
        """Demand before production → stockout_day set."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=3, qty=500)]
        engine = _engine(ops=[_eop(d=[0, 500, 0, 0, 0])])

        projs = compute_stock_projections(segs, lots, engine)
        assert projs[0].stockout_day == 1

    def test_no_demand_no_stockout(self):
        """Zero demand → no stockout."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=500)]
        engine = _engine(ops=[_eop(d=[0, 0, 0, 0, 0])])

        projs = compute_stock_projections(segs, lots, engine)
        assert projs[0].stockout_day is None
        assert projs[0].coverage_days == 5.0

    def test_coverage_days(self):
        """Coverage = days before first stockout."""
        lots = [_lot(op_id="op1")]
        segs = []  # no production
        engine = _engine(ops=[_eop(d=[0, 0, 100, 0, 0])])

        projs = compute_stock_projections(segs, lots, engine)
        assert projs[0].stockout_day == 2
        assert projs[0].coverage_days == 2.0

    def test_initial_stock_not_in_formula(self):
        """Initial stock NOT added to projection (NP already deducts it)."""
        lots = [_lot(op_id="op1")]
        segs = []  # no production
        # stk=200, demand=500 on day 1
        op = EOp(
            id="op1",
            sku="SKU1",
            client="C",
            designation="T",
            m="M1",
            t="T1",
            pH=100.0,
            sH=0.5,
            operators=1,
            eco_lot=0,
            alt=None,
            stk=200,
            backlog=0,
            d=[0, 500, 0, 0, 0],
            oee=0.66,
            wip=0,
        )
        engine = _engine(ops=[op])

        projs = compute_stock_projections(segs, lots, engine)
        assert projs[0].initial_stock == 200  # stored but not in formula
        assert projs[0].days[0].stock == 0  # day 0: 0 - 0 = 0
        assert projs[0].days[1].stock == -500  # day 1: 0 - 500 = -500

    def test_buffer_days(self):
        """Buffer production creates visible entries with is_buffer=True."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=-1, qty=300), _seg(day=1, qty=200)]
        engine = _engine(ops=[_eop(d=[0, 500, 0, 0, 0])])

        projs = compute_stock_projections(segs, lots, engine, buffer_days=2)
        # First 2 entries are buffer days
        assert projs[0].days[0].is_buffer is True  # day -2
        assert projs[0].days[0].day_idx == -2
        assert projs[0].days[0].produced == 0
        assert projs[0].days[1].is_buffer is True  # day -1
        assert projs[0].days[1].day_idx == -1
        assert projs[0].days[1].produced == 300
        assert projs[0].days[1].stock == 300  # 300 produced, 0 demand
        # Regular days follow
        assert projs[0].days[2].is_buffer is False  # day 0
        assert projs[0].days[2].stock == 300  # carry from buffer
        assert projs[0].days[3].stock == 300 + 200 - 500  # day 1: +200 prod, -500 demand = 0

    def test_buffer_zero(self):
        """buffer_days=0 produces same result as before."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=1000)]
        engine = _engine(ops=[_eop(d=[800, 0, 0, 0, 0])])

        projs = compute_stock_projections(segs, lots, engine, buffer_days=0)
        assert len(projs[0].days) == 5  # no buffer entries
        assert projs[0].days[0].stock == 200  # 1000 - 800


# ═══ CTP ═══


class TestCTP:
    def test_feasible_primary(self):
        """Empty schedule, plenty of capacity → feasible."""
        engine = _engine(ops=[_eop()])
        result = compute_ctp("SKU1", 500, 4, [], engine)
        assert result.feasible is True
        assert result.machine == "M1"
        assert result.latest_day is not None
        assert result.latest_day <= 4

    def test_feasible_alt(self):
        """Primary full, alt has capacity."""
        engine = _engine(ops=[_eop(alt="M2")], n_days=5)
        # Fill primary completely
        segs = [
            _seg(machine="M1", tool="T2", day=d, prod_min=DAY_CAP, setup_min=0)
            for d in range(5)
        ]
        result = compute_ctp("SKU1", 500, 4, segs, engine)
        assert result.feasible is True
        assert result.machine == "M2"

    def test_infeasible(self):
        """Both machines full → not feasible."""
        engine = _engine(ops=[_eop(alt="M2")], n_days=3)
        segs = [_seg(machine="M1", day=d, prod_min=DAY_CAP, setup_min=0) for d in range(3)] + [
            _seg(machine="M2", day=d, prod_min=DAY_CAP, setup_min=0) for d in range(3)
        ]
        result = compute_ctp("SKU1", 500, 2, segs, engine)
        assert result.feasible is False

    def test_sku_not_found(self):
        engine = _engine(ops=[])
        result = compute_ctp("NONEXIST", 100, 3, [], engine)
        assert result.feasible is False
        assert "não encontrado" in result.reason

    def test_ph_zero(self):
        engine = _engine(ops=[_eop(pH=0)])
        result = compute_ctp("SKU1", 100, 3, [], engine)
        assert result.feasible is False
        assert "pH" in result.reason

    def test_holidays_skipped(self):
        """Holidays don't count as available capacity."""
        engine = _engine(ops=[_eop()], n_days=5, holidays=[3, 4])
        # Fill days 0-2 completely
        segs = [_seg(machine="M1", day=d, prod_min=DAY_CAP, setup_min=0) for d in range(3)]
        # Days 3,4 are holidays → no free capacity anywhere
        result = compute_ctp("SKU1", 500, 4, segs, engine)
        assert result.feasible is False

    def test_full_machine_block_is_not_promised(self):
        engine = _engine(ops=[_eop()], n_days=1)
        engine.machine_blocked_days = {"M1": {0}}

        result = compute_ctp("SKU1", 100, 0, [], engine)

        assert result.feasible is False

    def test_full_tool_block_is_not_promised(self):
        engine = _engine(ops=[_eop()], n_days=1)
        engine.tool_blocked_days = {"T1": {0}}

        result = compute_ctp("SKU1", 100, 0, [], engine)

        assert result.feasible is False

    def test_machine_and_tool_capacity_must_overlap_in_time(self):
        engine = _engine(ops=[_eop(pH=100, sH=0.5, oee=1)], n_days=1)
        engine.machine_blocked_intervals = {
            "M1": [
                {
                    "start_day": 0,
                    "start_min": 420,
                    "end_day": 0,
                    "end_min": 930,
                }
            ]
        }
        engine.tool_blocked_intervals = {
            "T1": [
                {
                    "start_day": 0,
                    "start_min": 930,
                    "end_day": 0,
                    "end_min": 1440,
                }
            ]
        }

        result = compute_ctp("SKU1", 100, 0, [], engine, FactoryConfig())

        assert result.feasible is False

    def test_inactive_machine_is_not_promised(self):
        engine = _engine(ops=[_eop()], n_days=1)
        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes", active=False)}
        )

        result = compute_ctp("SKU1", 100, 0, [], engine, config)

        assert result.feasible is False

    def test_operator_absence_is_not_promised(self):
        engine = _engine(ops=[_eop()], n_days=1)
        engine.operator_blocked_intervals = [
            {
                "group": "Grandes",
                "shift": "A",
                "start_day": 0,
                "start_min": 420,
                "end_min": 930,
                "count": 6,
            },
            {
                "group": "Grandes",
                "shift": "B",
                "start_day": 0,
                "start_min": 930,
                "end_min": 1440,
                "count": 5,
            },
        ]

        result = compute_ctp("SKU1", 100, 0, [], engine, FactoryConfig())

        assert result.feasible is False

    def test_setup_crew_exhaustion_is_not_promised(self):
        engine = _engine(ops=[_eop()], n_days=1)
        engine.machines.append(MachineInfo("M2", "Grandes", DAY_CAP))
        setup_on_other_resources = _seg(
            machine="M2", tool="T2", day=0, prod_min=0, setup_min=DAY_CAP
        )

        result = compute_ctp(
            "SKU1", 100, 0, [setup_on_other_resources], engine, FactoryConfig()
        )

        assert result.feasible is False

    def test_machine_oee_and_setup_override_change_required_minutes(self):
        engine = _engine(ops=[_eop(pH=100, sH=0.5, oee=0.9)], n_days=1)
        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes", oee=0.5)},
            setup_overrides=[{"sku": "SKU1", "machine": "M1", "hours": 2}],
        )

        result = compute_ctp("SKU1", 100, 0, [], engine, config)

        assert result.feasible is True
        assert result.required_min == 240.0

    def test_duplicate_sku_is_rejected_as_ambiguous(self):
        engine = _engine(
            ops=[
                _eop(op_id="op1", sku="SKU1", machine="M1", tool="T1"),
                _eop(op_id="op2", sku="SKU1", machine="M2", tool="T2"),
            ],
            n_days=1,
        )

        result = compute_ctp("SKU1", 100, 0, [], engine)

        assert result.feasible is False
        assert "ambíguo" in (result.reason or "")


# ═══ EXPEDITION ═══


class TestExpedition:
    def test_ready(self):
        """Production before demand day → ready."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=1000)]
        engine = _engine(
            ops=[_eop(d=[0, 0, 800, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="FAUR",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=800,
                        np_value=-800,
                    ),
                ]
            },
        )
        exp = compute_expedition(segs, lots, engine)
        assert len(exp.days) == 1
        assert exp.days[0].entries[0].status == "ready"

    def test_partial(self):
        """Partial production → partial status."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=500)]
        engine = _engine(
            ops=[_eop(d=[0, 0, 800, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="FAUR",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=800,
                        np_value=-800,
                    ),
                ]
            },
        )
        exp = compute_expedition(segs, lots, engine)
        assert exp.days[0].entries[0].status == "partial"
        assert exp.days[0].entries[0].shortfall == 300

    @pytest.mark.parametrize("reverse_ops", [False, True])
    def test_legacy_duplicate_sku_aggregates_every_route(self, reverse_ops):
        ops = [
            _eop(op_id="op1", sku="SKU1", machine="M1", tool="T1"),
            _eop(op_id="op2", sku="SKU1", machine="M2", tool="T2"),
        ]
        if reverse_ops:
            ops.reverse()
        lots = [
            _lot(lot_id="L1", op_id="op1", machine_id="M1", tool_id="T1", qty=300),
            _lot(lot_id="L2", op_id="op2", machine_id="M2", tool_id="T2", qty=300),
        ]
        segs = [
            _seg(lot_id="L1", run_id="R1", machine="M1", tool="T1", qty=300),
            _seg(lot_id="L2", run_id="R2", machine="M2", tool="T2", qty=300),
        ]
        engine = _engine(
            ops=ops,
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    )
                ]
            },
        )

        entry = compute_expedition(segs, lots, engine).days[0].entries[0]

        assert entry.produced_qty == 600
        assert entry.status == "ready"

    def test_multi_client(self):
        """Two clients for same SKU → separate entries."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=20000)]
        engine = _engine(
            ops=[_eop(d=[0, 0, 15000, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="FAURECIA",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=10000,
                        np_value=-10000,
                    ),
                    ClientDemandEntry(
                        client="FAUR-SIEGE",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=5000,
                        np_value=-5000,
                    ),
                ]
            },
        )
        exp = compute_expedition(segs, lots, engine)
        assert len(exp.days) == 1
        assert len(exp.days[0].entries) == 2
        assert all(e.status == "ready" for e in exp.days[0].entries)

    def test_no_demand(self):
        """No client demands → empty expedition."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=500)]
        engine = _engine(ops=[_eop(d=[0, 0, 0, 0, 0])], client_demands={})
        exp = compute_expedition(segs, lots, engine)
        assert len(exp.days) == 0

    def test_fill_rate(self):
        """Fill rate = ready / total * 100."""
        lots = [_lot(op_id="op1")]
        segs = [_seg(day=0, qty=500)]
        engine = _engine(
            ops=[_eop(d=[0, 800, 500, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=800,
                        np_value=-800,
                    ),
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=500,
                        np_value=-500,
                    ),
                ]
            },
        )
        exp = compute_expedition(segs, lots, engine)
        # Day 1: produced=500, cum_demand=800 → partial
        # Day 2: produced=500, cum_demand=1300 → partial
        assert exp.fill_rate < 100.0
        assert exp.at_risk_count >= 1


# ═══ ORDER TRACKING ═══


class TestOrderTracking:
    def test_covers_all_demands(self):
        """Every ClientDemandEntry gets an OrderTracking."""
        lots = [_lot(op_id="op1", qty=1000, edd=1)]
        segs = [_seg(day=0, qty=1000)]
        engine = _engine(
            ops=[_eop(d=[0, 500, 300, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    ),
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=300,
                        np_value=-300,
                    ),
                ]
            },
        )
        result = compute_order_tracking(segs, lots, engine)
        total_tracked = sum(len(c.orders) for c in result)
        assert total_tracked == 2

    def test_surplus_source(self):
        """Order covered by eco lot surplus → source='surplus'."""
        # Lot of 1000 covers demand of 500 + surplus of 500 covers 2nd demand of 300
        lots = [_lot(op_id="op1", qty=1000, edd=1)]
        segs = [_seg(day=0, qty=1000)]
        engine = _engine(
            ops=[_eop(d=[0, 500, 300, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    ),
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=2,
                        date="2026-03-07",
                        order_qty=300,
                        np_value=-300,
                    ),
                ]
            },
        )
        result = compute_order_tracking(segs, lots, engine)
        orders = result[0].orders
        assert orders[0].source == "production"
        assert orders[1].source == "surplus"
        assert orders[1].surplus_used == 300

    def test_demand_uses_every_contributing_lot_and_latest_ready_day(self):
        """A demand spanning several lots is ready only when the last lot is ready."""
        lots = [
            _lot(lot_id=f"L{i}", qty=14_000, edd=34)
            for i in range(1, 6)
        ]
        segs = [
            _seg(
                lot_id=lot.id,
                run_id=f"R{i}",
                day=day,
                qty=14_000,
            )
            for i, (lot, day) in enumerate(
                zip(lots, [30, 31, 32, 33, 40], strict=True),
                start=1,
            )
        ]
        engine = _engine(
            ops=[_eop(d=[0] * 5)],
            n_days=5,
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=34,
                        date="2026-10-12",
                        order_qty=70_000,
                        np_value=-70_000,
                    )
                ]
            },
        )

        client_orders = compute_order_tracking(segs, lots, engine)[0]
        order = client_orders.orders[0]

        assert order.allocated_qty == 70_000
        assert order.shortfall_qty == 0
        assert order.lot_ids == ["L1", "L2", "L3", "L4", "L5"]
        assert order.production_run_ids == ["R1", "R2", "R3", "R4", "R5"]
        assert order.production_qty == 70_000
        assert order.factory_ready_day == 40
        assert order.customer_ready_day == 40
        assert order.status == "planned"
        assert client_orders.total_ready == 0

    def test_partial_multi_lot_coverage_is_not_ready(self):
        lots = [
            _lot(lot_id="L1", qty=14_000, edd=34),
            _lot(lot_id="L2", qty=14_000, edd=34),
        ]
        segs = [
            _seg(lot_id="L1", run_id="R1", day=30, qty=14_000),
            _seg(lot_id="L2", run_id="R2", day=31, qty=14_000),
        ]
        engine = _engine(
            ops=[_eop(d=[0] * 5)],
            n_days=5,
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=34,
                        date="2026-10-12",
                        order_qty=70_000,
                        np_value=-70_000,
                    )
                ]
            },
        )

        client_orders = compute_order_tracking(segs, lots, engine)[0]
        order = client_orders.orders[0]

        assert order.allocated_qty == 28_000
        assert order.shortfall_qty == 42_000
        assert order.status == "partial"
        assert order.ready_day is None
        assert client_orders.total_ready == 0

    def test_surplus_is_not_counted_twice_across_demands(self):
        lots = [_lot(qty=1_000, edd=1)]
        segs = [_seg(day=0, qty=1_000)]
        demands = [
            ClientDemandEntry(
                client="C1",
                sku="SKU1",
                day_idx=1,
                date="2026-03-06",
                order_qty=500,
                np_value=-500,
            ),
            ClientDemandEntry(
                client="C1",
                sku="SKU1",
                day_idx=2,
                date="2026-03-07",
                order_qty=800,
                np_value=-800,
            ),
        ]
        engine = _engine(
            ops=[_eop(d=[0, 500, 800, 0, 0])],
            client_demands={"SKU1": demands},
        )

        orders = compute_order_tracking(segs, lots, engine)[0].orders

        assert orders[0].allocated_qty == 500
        assert orders[1].allocated_qty == 500
        assert orders[1].shortfall_qty == 300
        assert orders[1].source == "surplus"
        assert orders[1].status == "partial"

    def test_not_planned(self):
        """Demand with no lot → source='not_planned'."""
        engine = _engine(
            ops=[_eop(d=[0, 500, 0, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    ),
                ]
            },
        )
        result = compute_order_tracking([], [], engine)
        assert result[0].orders[0].source == "not_planned"
        assert result[0].orders[0].status == "not_planned"

    def test_legacy_duplicate_sku_finds_lots_from_every_route(self):
        ops = [
            _eop(op_id="op2", sku="SKU1", machine="M2", tool="T2"),
            _eop(op_id="op1", sku="SKU1", machine="M1", tool="T1"),
        ]
        lots = [
            _lot(
                lot_id="L2",
                op_id="op2",
                machine_id="M2",
                tool_id="T2",
                qty=500,
                edd=1,
            )
        ]
        segs = [
            _seg(
                lot_id="L2",
                run_id="R2",
                machine="M2",
                tool="T2",
                qty=500,
            )
        ]
        engine = _engine(
            ops=ops,
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    )
                ]
            },
        )

        order = compute_order_tracking(segs, lots, engine)[0].orders[0]

        assert order.source == "production"
        assert order.lot_id == "L2"
        assert order.production_machine == "M2"

    def test_reason_not_empty(self):
        """All orders have non-empty reason."""
        lots = [_lot(op_id="op1", qty=1000, edd=1)]
        segs = [_seg(day=0, qty=1000)]
        engine = _engine(
            ops=[_eop(d=[0, 500, 0, 0, 0])],
            client_demands={
                "SKU1": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU1",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    ),
                ]
            },
        )
        result = compute_order_tracking(segs, lots, engine)
        for client in result:
            for order in client.orders:
                assert order.reason, f"Empty reason for {order.sku} day {order.delivery_day}"

    def test_twin_tracking(self):
        """Twin lots credit correct SKU."""
        twin_lot = _lot(
            lot_id="LT1",
            op_id="op1",
            qty=500,
            edd=1,
            is_twin=True,
            twin_outputs=[("op1", "SKU-A", 500), ("op2", "SKU-B", 300)],
        )
        segs = [
            _seg(
                lot_id="LT1",
                day=0,
                qty=500,
                twin_outputs=[("op1", "SKU-A", 500), ("op2", "SKU-B", 300)],
            )
        ]
        engine = _engine(
            ops=[
                _eop(op_id="op1", sku="SKU-A", d=[0, 500, 0, 0, 0]),
                _eop(op_id="op2", sku="SKU-B", d=[0, 300, 0, 0, 0]),
            ],
            client_demands={
                "SKU-A": [
                    ClientDemandEntry(
                        client="C1",
                        sku="SKU-A",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=500,
                        np_value=-500,
                    )
                ],
                "SKU-B": [
                    ClientDemandEntry(
                        client="C2",
                        sku="SKU-B",
                        day_idx=1,
                        date="2026-03-06",
                        order_qty=300,
                        np_value=-300,
                    )
                ],
            },
        )
        result = compute_order_tracking(segs, [twin_lot], engine)
        # C1 gets SKU-A, C2 gets SKU-B
        c1 = next(c for c in result if c.client == "C1")
        c2 = next(c for c in result if c.client == "C2")
        assert c1.orders[0].sku == "SKU-A"
        assert c1.orders[0].source == "production"
        assert c2.orders[0].sku == "SKU-B"
        assert c2.orders[0].source == "production"

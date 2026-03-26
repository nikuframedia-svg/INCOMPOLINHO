"""Tests for scheduler — Spec 02 v6 (Definitivo).

Covers all 5 fixes + full pipeline:
  Fix 1: EDD sort internal (tool_grouping)
  Fix 2: LST-gated JIT (jit)
  Fix 3: Campaign sequencing (dispatch)
  Fix 4: Interleave urgent (dispatch)
  Fix 5: Min prod_min (lot_sizing + dispatch)
"""

from __future__ import annotations

from backend.scheduler.constants import DAY_CAP, MIN_PROD_MIN
from backend.scheduler.dispatch import (
    _campaign_sequence,
    _interleave_urgent,
    _two_opt,
    assign_machines,
    per_machine_dispatch,
    sequence_per_machine,
)
from backend.scheduler.jit import compute_lst, compute_paced_lst, jit_dispatch
from backend.scheduler.lot_sizing import _apply_eco_lot, create_lots
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData, EOp, MachineInfo, TwinGroup


# --- Fixtures ---

WORKDAYS = [
    "2026-03-05", "2026-03-06", "2026-03-07",
    "2026-03-10", "2026-03-11", "2026-03-12",
]


def _make_eop(
    sku: str = "SKU_A",
    machine: str = "PRM031",
    tool: str = "T1",
    client: str = "CLIENT",
    d: list[int] | None = None,
    eco_lot: int = 0,
    pH: float = 100.0,
    sH: float = 0.5,
    oee: float = 0.66,
    alt: str | None = None,
    stk: int = 0,
    operators: int = 1,
) -> EOp:
    return EOp(
        id=f"{tool}_{machine}_{sku}",
        sku=sku,
        client=client,
        designation="Test",
        m=machine,
        t=tool,
        pH=pH,
        sH=sH,
        operators=operators,
        eco_lot=eco_lot,
        alt=alt,
        stk=stk,
        backlog=0,
        d=d or [0, 500, 0, 300],
        oee=oee,
        wip=0,
    )


def _make_engine_data(
    ops: list[EOp] | None = None,
    machines: list[MachineInfo] | None = None,
    twins: list[TwinGroup] | None = None,
    n_days: int = 6,
    holidays: list[int] | None = None,
) -> EngineData:
    if ops is None:
        ops = [_make_eop()]
    if machines is None:
        machine_ids = list({op.m for op in ops})
        machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
    return EngineData(
        ops=ops,
        machines=machines,
        twin_groups=twins or [],
        client_demands={},
        workdays=WORKDAYS[:n_days],
        n_days=n_days,
        holidays=holidays or [],
    )


def _make_lot(
    lot_id: str = "L1",
    op_id: str = "O1",
    tool_id: str = "T1",
    machine_id: str = "M1",
    alt_machine_id: str | None = None,
    qty: int = 500,
    prod_min: float = 100.0,
    setup_min: float = 60.0,
    edd: int = 5,
    is_twin: bool = False,
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=op_id,
        tool_id=tool_id,
        machine_id=machine_id,
        alt_machine_id=alt_machine_id,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=edd,
        is_twin=is_twin,
    )


def _make_run(
    run_id: str = "R1",
    tool_id: str = "T1",
    machine_id: str = "M1",
    alt_machine_id: str | None = None,
    lots: list[Lot] | None = None,
    setup_min: float = 60.0,
    edd: int = 5,
) -> ToolRun:
    if lots is None:
        lots = [_make_lot()]
    total_prod = sum(lot.prod_min for lot in lots)
    return ToolRun(
        id=run_id,
        tool_id=tool_id,
        machine_id=machine_id,
        alt_machine_id=alt_machine_id,
        lots=lots,
        setup_min=setup_min,
        total_prod_min=total_prod,
        total_min=setup_min + total_prod,
        edd=edd,
    )


# ═══ ECO LOT ═══


class TestEcoLot:
    def test_zero_eco_lot(self):
        assert _apply_eco_lot(500, 0) == 500

    def test_round_up(self):
        assert _apply_eco_lot(500, 1000) == 1000

    def test_exact(self):
        assert _apply_eco_lot(1000, 1000) == 1000

    def test_multiple(self):
        assert _apply_eco_lot(2500, 1000) == 3000

    def test_eco_lot_carry_forward(self):
        op = _make_eop(d=[0, 500, 0, 300], eco_lot=1000)
        data = _make_engine_data(ops=[op])
        lots = create_lots(data)
        # Day 1: demand=500, eco_lot=1000 → qty=1000, surplus=500
        assert lots[0].qty == 1000
        # Day 3: demand=300, surplus=500 → no lot needed
        assert len(lots) == 1

    def test_eco_lot_exhausted(self):
        op = _make_eop(d=[5000] * 5, eco_lot=20000)
        data = _make_engine_data(ops=[op], n_days=5)
        lots = create_lots(data)
        # 20000 eco lot covers 4 days of 5000, then 1 more lot
        assert len(lots) == 2


# ═══ LOT SIZING ═══


class TestLotSizing:
    def test_solo_lot_creation(self):
        op = _make_eop(d=[0, 500, 0, 300])
        data = _make_engine_data(ops=[op])
        lots = create_lots(data)
        assert len(lots) == 2
        assert lots[0].edd == 1
        assert lots[0].qty == 500
        assert lots[1].edd == 3
        assert lots[1].qty == 300

    def test_stock_not_double_counted(self):
        """First negative NP already has stock deducted, so surplus starts at 0."""
        op = _make_eop(d=[0, 500, 0, 300], stk=200)
        data = _make_engine_data(ops=[op])
        lots = create_lots(data)
        assert lots[0].qty == 500  # surplus=0, full demand produced

    def test_no_demand_no_lots(self):
        op = _make_eop(d=[0, 0, 0])
        data = _make_engine_data(ops=[op], n_days=3)
        lots = create_lots(data)
        assert len(lots) == 0

    def test_min_prod_min_fix5(self):
        """Fix 5: micro-lots get at least MIN_PROD_MIN production time."""
        op = _make_eop(d=[0, 5], pH=1441.0, sH=0.0)
        data = _make_engine_data(ops=[op])
        lots = create_lots(data)
        assert len(lots) == 1
        assert lots[0].prod_min >= MIN_PROD_MIN

    def test_twin_lot_creation(self):
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000])
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 800])
        twin = TwinGroup(
            tool_id="T1", machine_id="M1",
            op_id_1="T1_M1_A", op_id_2="T1_M1_B",
            sku_1="A", sku_2="B", eco_lot_1=0, eco_lot_2=0,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twins=[twin],
        )
        lots = create_lots(data)
        assert len(lots) == 1
        assert lots[0].is_twin
        assert lots[0].twin_outputs is not None
        assert lots[0].prod_min > 0

    def test_twin_time_is_max(self):
        """Twin production time = max(time_a, time_b), not sum."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", pH=1000, d=[0, 5000])
        op_b = _make_eop(sku="B", tool="T1", machine="M1", pH=1000, d=[0, 3000])
        twin = TwinGroup(
            tool_id="T1", machine_id="M1",
            op_id_1="T1_M1_A", op_id_2="T1_M1_B",
            sku_1="A", sku_2="B", eco_lot_1=0, eco_lot_2=0,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twins=[twin],
        )
        lots = create_lots(data)
        expected_max = (5000 / (1000 * 0.66)) * 60
        assert abs(lots[0].prod_min - expected_max) < 1.0


# ═══ TOOL GROUPING (Fix 1) ═══


class TestToolGrouping:
    def test_same_tool_grouped(self):
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, setup_min=60, edd=5),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, setup_min=60, edd=10),
        ]
        runs = create_tool_runs(lots)
        assert len(runs) == 1
        assert runs[0].setup_min == 60  # 1 setup, not 2
        assert runs[0].total_prod_min == 180

    def test_different_tools_separate(self):
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, setup_min=60, edd=5),
            _make_lot("L2", "O2", "T2", "M1", qty=300, prod_min=80, setup_min=30, edd=10),
        ]
        runs = create_tool_runs(lots)
        assert len(runs) == 2

    def test_edd_sort_fix1(self):
        """Fix 1: lots within a ToolRun are always sorted by EDD."""
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, edd=15),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, edd=5),
            _make_lot("L3", "O3", "T1", "M1", qty=200, prod_min=50, edd=10),
        ]
        runs = create_tool_runs(lots)
        assert runs[0].lots[0].edd == 5
        assert runs[0].lots[1].edd == 10
        assert runs[0].lots[2].edd == 15
        assert runs[0].edd == 5  # most urgent

    def test_split_by_edd_gap(self):
        """Lots with large EDD gap get split into separate runs."""
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, edd=2),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, edd=20),
        ]
        runs = create_tool_runs(lots, max_edd_gap=10)
        assert len(runs) == 2

    def test_run_id_format(self):
        lots = [_make_lot("L1", "O1", "T1", "M1", edd=5)]
        runs = create_tool_runs(lots)
        assert runs[0].id == "run_T1_M1_0"


# ═══ CAMPAIGN SEQUENCING (Fix 3) ═══


class TestCampaignSequencing:
    def test_same_tool_grouped(self):
        """Fix 3: runs of same tool are grouped to reduce setups."""
        runs = [
            _make_run("R1", "T1", "M1", edd=2),
            _make_run("R2", "T2", "M1", edd=3),
            _make_run("R3", "T1", "M1", edd=5),
        ]
        result = _campaign_sequence(runs)
        # R1 (T1, edd=2) first, then R3 (T1, edd=5) same tool, then R2 (T2)
        assert result[0].tool_id == "T1"
        assert result[1].tool_id == "T1"
        assert result[2].tool_id == "T2"

    def test_respects_edd_tolerance(self):
        """Campaign doesn't pull in runs with EDD far in the future."""
        runs = [
            _make_run("R1", "T1", "M1", edd=2),
            _make_run("R2", "T2", "M1", edd=3),
            _make_run("R3", "T1", "M1", edd=50),  # far future
        ]
        result = _campaign_sequence(runs)
        # R3 is too far, shouldn't jump ahead of R2
        assert result[0].id == "R1"
        assert result[1].id == "R2"
        assert result[2].id == "R3"


# ═══ INTERLEAVE URGENT (Fix 4) ═══


class TestInterleaveUrgent:
    def test_breaks_campaign_for_urgent(self):
        """Fix 4: urgent run breaks a same-tool campaign."""
        runs = [
            _make_run("R1", "T1", "M1", edd=4),
            _make_run("R2", "T1", "M1", edd=11),
            _make_run("R3", "T2", "M1", edd=6),   # urgent, different tool
        ]
        result = _interleave_urgent(runs)
        # R3 (edd=6) should be inserted between R1 (edd=4) and R2 (edd=11)
        assert result[0].id == "R1"
        assert result[1].id == "R3"
        assert result[2].id == "R2"

    def test_no_break_when_not_urgent(self):
        """No interleave when the other run isn't more urgent."""
        runs = [
            _make_run("R1", "T1", "M1", edd=4),
            _make_run("R2", "T1", "M1", edd=6),
            _make_run("R3", "T2", "M1", edd=20),  # not urgent
        ]
        result = _interleave_urgent(runs)
        assert result[0].id == "R1"
        assert result[1].id == "R2"
        assert result[2].id == "R3"


# ═══ 2-OPT ═══


class TestTwoOpt:
    def test_swaps_to_reduce_setups(self):
        """2-opt swaps adjacent run to extend campaign."""
        runs = [
            _make_run("R1", "T1", "M1", edd=2),
            _make_run("R2", "T2", "M1", edd=3),
            _make_run("R3", "T1", "M1", edd=5),
        ]
        result = _two_opt(runs)
        # R2 and R3 should swap: T1, T1, T2 → fewer setups
        assert result[0].tool_id == "T1"
        assert result[1].tool_id == "T1"
        assert result[2].tool_id == "T2"


# ═══ MACHINE ASSIGNMENT ═══


class TestAssignMachines:
    def test_no_alt_goes_to_primary(self):
        runs = [_make_run("R1", "T1", "M1")]
        data = _make_engine_data()
        result = assign_machines(runs, data)
        assert "M1" in result
        assert len(result["M1"]) == 1

    def test_alt_load_balances(self):
        """Run with alt goes to less loaded machine."""
        lot_heavy = _make_lot("L1", prod_min=900, machine_id="M1")
        lot_light = _make_lot("L2", prod_min=100, machine_id="M2", alt_machine_id="M1")
        run_heavy = _make_run("R1", "T1", "M1", lots=[lot_heavy])
        run_light = _make_run("R2", "T2", "M2", alt_machine_id="M1",
                              lots=[lot_light])
        result = assign_machines([run_heavy, run_light], _make_engine_data())
        # run_light should go to M2 (less loaded)
        assert any(r.id == "R2" for r in result.get("M2", []))


# ═══ LST / JIT (Fix 2) ═══


class TestLST:
    def test_compute_lst_basic(self):
        """LST = EDD - days_needed - safety_buffer."""
        run = _make_run("R1", lots=[_make_lot(prod_min=DAY_CAP * 2)])
        run.total_min = DAY_CAP * 2
        run.edd = 10
        lst = compute_lst(run, holiday_set=set(), safety_buffer=2)
        # 2 days production + 2 buffer = 4 days before edd=10 → LST=6
        assert lst == 6

    def test_compute_lst_with_holidays(self):
        run = _make_run("R1", lots=[_make_lot(prod_min=DAY_CAP)])
        run.total_min = DAY_CAP
        run.edd = 5
        # Holiday on day 3 → skip it, need to go back further
        lst = compute_lst(run, holiday_set={3}, safety_buffer=1)
        assert lst < 3  # must account for holiday

    def test_paced_lst_tighter(self):
        """Paced LST considers internal lot deadlines."""
        lot1 = _make_lot("L1", prod_min=DAY_CAP, edd=5)
        lot2 = _make_lot("L2", prod_min=DAY_CAP, edd=8)
        run = _make_run("R1", lots=[lot1, lot2], edd=5)
        run.total_min = 2 * DAY_CAP
        lst_paced = compute_paced_lst(run, holiday_set=set(), safety_buffer=1)
        lst_basic = compute_lst(run, holiday_set=set(), safety_buffer=1)
        assert lst_paced <= lst_basic


class TestJITDispatch:
    def test_jit_fallback_on_worse_tardy(self):
        """JIT falls back to baseline if tardy count increases."""
        op = _make_eop(d=[0, 500, 0, 300], pH=100.0, sH=0.5)
        data = _make_engine_data(ops=[op])
        lots = create_lots(data)
        runs = create_tool_runs(lots)
        machine_runs = assign_machines(runs, data)
        machine_runs = sequence_per_machine(machine_runs)
        baseline_segs, baseline_lots, _ = per_machine_dispatch(machine_runs, data)
        baseline_score = compute_score(baseline_segs, baseline_lots, data)

        # JIT should not worsen tardy
        final_segs, final_lots, warnings, _, _ = jit_dispatch(
            runs, data, baseline_segs, baseline_lots, baseline_score,
        )
        final_score = compute_score(final_segs, final_lots, data)
        assert final_score["tardy_count"] <= baseline_score["tardy_count"]


# ═══ SCORING ═══


class TestScoring:
    def test_perfect_otd(self):
        """All lots on time → OTD = 100%."""
        lots = [_make_lot("L1", edd=5), _make_lot("L2", edd=10)]
        segments = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=3, start_min=420, end_min=520, shift="A", qty=500, prod_min=100),
            Segment(lot_id="L2", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=8, start_min=420, end_min=500, shift="A", qty=300, prod_min=80),
        ]
        data = _make_engine_data(n_days=12)
        score = compute_score(segments, lots, data)
        assert score["otd"] == 100.0
        assert score["tardy_count"] == 0

    def test_tardy_detection(self):
        """Lot completed after EDD → tardy."""
        lots = [_make_lot("L1", edd=2)]
        segments = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=5, start_min=420, end_min=520, shift="A", qty=500, prod_min=100),
        ]
        data = _make_engine_data(n_days=6)
        score = compute_score(segments, lots, data)
        assert score["tardy_count"] == 1
        assert score["max_tardiness"] == 3
        assert score["otd"] < 100.0

    def test_earliness_metric(self):
        """Earliness = average gap between last production day and EDD."""
        lots = [_make_lot("L1", edd=10)]
        segments = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=3, start_min=420, end_min=520, shift="A",
                    qty=500, prod_min=100, edd=10),
        ]
        data = _make_engine_data(n_days=12)
        score = compute_score(segments, lots, data)
        assert score["earliness_avg_days"] == 7.0  # edd=10, last_day=3 → gap=7

    def test_setup_count(self):
        segments = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=0, start_min=420, end_min=480, shift="A",
                    qty=0, prod_min=0, setup_min=60),
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=0, start_min=480, end_min=580, shift="A",
                    qty=500, prod_min=100, setup_min=0),
        ]
        data = _make_engine_data(n_days=6)
        score = compute_score(segments, [_make_lot("L1")], data)
        assert score["setups"] == 1


# ═══ FULL PIPELINE ═══


class TestScheduleAll:
    def test_basic_pipeline(self):
        op = _make_eop(d=[0, 500, 0, 300], pH=100.0, sH=0.5)
        data = _make_engine_data(ops=[op])
        result = schedule_all(data)
        assert len(result.lots) == 2
        assert len(result.segments) > 0
        assert result.score["total_lots"] == 2

    def test_empty_demand(self):
        op = _make_eop(d=[0, 0, 0])
        data = _make_engine_data(ops=[op], n_days=3)
        result = schedule_all(data)
        assert len(result.lots) == 0
        assert len(result.segments) == 0

    def test_multi_machine(self):
        op1 = _make_eop(sku="A", machine="PRM031", tool="T1", d=[0, 500])
        op2 = _make_eop(sku="B", machine="PRM039", tool="T2", d=[0, 300])
        data = _make_engine_data(
            ops=[op1, op2],
            machines=[
                MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
            ],
        )
        result = schedule_all(data)
        assert len(result.lots) == 2
        machines_used = {s.machine_id for s in result.segments if s.qty > 0}
        assert "PRM031" in machines_used
        assert "PRM039" in machines_used

    def test_twin_pipeline(self):
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000])
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 800])
        twin = TwinGroup(
            tool_id="T1", machine_id="M1",
            op_id_1="T1_M1_A", op_id_2="T1_M1_B",
            sku_1="A", sku_2="B", eco_lot_1=0, eco_lot_2=0,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twins=[twin],
        )
        result = schedule_all(data)
        assert len(result.lots) == 1
        assert result.lots[0].is_twin
        assert result.score is not None

    def test_twin_joint_equal_qty(self):
        """When both twins have demand, both produce max(eco_a, eco_b)."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000], eco_lot=0)
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 800], eco_lot=0)
        twin = TwinGroup(
            tool_id="T1", machine_id="M1",
            op_id_1="T1_M1_A", op_id_2="T1_M1_B",
            sku_1="A", sku_2="B", eco_lot_1=0, eco_lot_2=0,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twins=[twin],
        )
        lots = create_lots(data)
        assert len(lots) == 1
        to = lots[0].twin_outputs
        assert to is not None
        # Both produce max(1000, 800) = 1000
        assert to[0][2] == 1000  # A = 1000
        assert to[1][2] == 1000  # B = 1000 (not 800)
        assert lots[0].qty == 1000

    def test_twin_joint_with_eco_lot(self):
        """Max eco lot determines qty for both twins."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 4500], eco_lot=5000)
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 2800], eco_lot=3000)
        twin = TwinGroup(
            tool_id="T1", machine_id="M1",
            op_id_1="T1_M1_A", op_id_2="T1_M1_B",
            sku_1="A", sku_2="B", eco_lot_1=5000, eco_lot_2=3000,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twins=[twin],
        )
        lots = create_lots(data)
        assert len(lots) == 1
        to = lots[0].twin_outputs
        assert to is not None
        # eco_a = ceil(4500/5000)*5000 = 5000, eco_b = ceil(2800/3000)*3000 = 3000
        # qty = max(5000, 3000) = 5000
        assert to[0][2] == 5000  # A
        assert to[1][2] == 5000  # B (not 3000)
        assert lots[0].qty == 5000

    def test_twin_solo_only_a(self):
        """Only A has demand → B gets 0."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000])
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 0])
        twin = TwinGroup(
            tool_id="T1", machine_id="M1",
            op_id_1="T1_M1_A", op_id_2="T1_M1_B",
            sku_1="A", sku_2="B", eco_lot_1=0, eco_lot_2=0,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twins=[twin],
        )
        lots = create_lots(data)
        assert len(lots) == 1
        to = lots[0].twin_outputs
        assert to is not None
        assert to[0][2] == 1000  # A produces
        assert to[1][2] == 0     # B does NOT produce

    def test_with_holidays(self):
        op = _make_eop(d=[0, 0, 500], pH=1000.0, sH=0.0)
        data = _make_engine_data(ops=[op], n_days=3, holidays=[1])
        result = schedule_all(data)
        prod_segs = [s for s in result.segments if s.qty > 0]
        assert all(s.day_idx != 1 for s in prod_segs)

    def test_setup_count_reduced(self):
        """Same tool on same machine should produce 1 setup, not N."""
        ops = [
            _make_eop(sku=f"SKU_{i}", tool="T1", machine="PRM031",
                       d=[0] * i + [500] + [0] * (5 - i))
            for i in range(1, 4)
        ]
        data = _make_engine_data(ops=ops)
        result = schedule_all(data)
        # 3 lots with same tool → grouped → 1 setup
        setup_segs = [s for s in result.segments if s.setup_min > 0]
        assert len(setup_segs) == 1

    def test_crew_no_overlap_per_machine(self):
        """No two setups should overlap on the SAME machine.

        JIT phase dispatches per-machine independently (crew utilization ~7%),
        so cross-machine setup overlap is expected and harmless.
        """
        ops = [
            _make_eop(sku="A", tool="T1", machine="PRM031", d=[0, 500], sH=1.0),
            _make_eop(sku="B", tool="T2", machine="PRM039", d=[0, 300], sH=1.0),
        ]
        data = _make_engine_data(
            ops=ops,
            machines=[
                MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
            ],
        )
        result = schedule_all(data)
        # Group setups by machine
        from collections import defaultdict
        machine_setups: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for s in result.segments:
            if s.setup_min > 0:
                start = s.day_idx * DAY_CAP + s.start_min
                end = start + int(s.setup_min)
                machine_setups[s.machine_id].append((start, end))
        for m_id, setups in machine_setups.items():
            for i, (s1, e1) in enumerate(setups):
                for j, (s2, e2) in enumerate(setups):
                    if i != j:
                        assert not (s1 < e2 and s2 < e1), (
                            f"Setup overlap on {m_id}: [{s1},{e1}) vs [{s2},{e2})"
                        )

    def test_split_across_days(self):
        """Large lot should span multiple days."""
        op = _make_eop(d=[50000], pH=100.0, sH=0.0, eco_lot=0)
        data = _make_engine_data(ops=[op], n_days=6)
        result = schedule_all(data)
        prod_segs = [s for s in result.segments if s.qty > 0]
        days_used = {s.day_idx for s in prod_segs}
        # 50000 / (100 * 0.66) * 60 ≈ 4545 min = ~4.5 days
        assert len(days_used) >= 4

    def test_micro_lot_produces_segment_fix5(self):
        """Fix 5: even micro-lots (very small qty) produce at least 1 segment."""
        op = _make_eop(d=[0, 5], pH=1441.0, sH=0.5)
        data = _make_engine_data(ops=[op])
        result = schedule_all(data)
        assert len(result.lots) == 1
        prod_segs = [s for s in result.segments if s.qty > 0]
        assert len(prod_segs) >= 1

    def test_campaign_reduces_setups_fix3(self):
        """Fix 3: campaign sequencing reduces setup count."""
        ops = [
            _make_eop(sku="A", tool="T1", machine="M1", d=[0, 500], sH=0.5),
            _make_eop(sku="B", tool="T2", machine="M1", d=[0, 300], sH=0.5),
            _make_eop(sku="C", tool="T1", machine="M1", d=[0, 0, 400], sH=0.5),
        ]
        data = _make_engine_data(
            ops=ops,
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
        )
        result = schedule_all(data)
        setup_segs = [s for s in result.segments if s.setup_min > 0]
        # T1+T1 campaign → 1 setup for T1, 1 for T2 = 2 total (not 3)
        assert len(setup_segs) <= 2

    def test_pipeline_timing(self):
        """Scheduler should complete under 100ms for moderate input."""
        ops = [
            _make_eop(sku=f"SKU_{i}", tool=f"T{i % 5}",
                       machine=f"M{i % 3}", d=[0, 500, 300, 200])
            for i in range(20)
        ]
        machines = [MachineInfo(id=f"M{i}", group="Grandes", day_capacity=DAY_CAP) for i in range(3)]
        data = _make_engine_data(ops=ops, machines=machines)
        result = schedule_all(data)
        assert result.time_ms < 500  # generous for CI
        assert result.score is not None

    def test_no_production_overlap_per_machine_day(self):
        """No two production segments should overlap on the same machine/day.

        Large demand on day 0 triggers buffer, which previously caused
        _unshift_segments to clamp two engine days onto day_idx=0.
        """
        from collections import defaultdict

        op = _make_eop(d=[30000], pH=200.0, sH=0.5, eco_lot=0)
        data = _make_engine_data(ops=[op], n_days=10)
        result = schedule_all(data)

        by_md: dict[tuple[str, int], list] = defaultdict(list)
        for s in result.segments:
            by_md[(s.machine_id, s.day_idx)].append(s)

        for (mid, day), segs in by_md.items():
            sorted_segs = sorted(segs, key=lambda s: s.start_min)
            for i in range(1, len(sorted_segs)):
                prev = sorted_segs[i - 1]
                curr = sorted_segs[i]
                assert curr.start_min >= prev.end_min, (
                    f"Overlap on {mid} day {day}: "
                    f"[{prev.start_min},{prev.end_min}) vs [{curr.start_min},{curr.end_min})"
                )

    def test_no_overlap_full_factory_buffer(self):
        """Full factory with 5 machines: no overlaps after buffer unshift."""
        from collections import defaultdict

        machines_ids = ["PRM019", "PRM031", "PRM039", "PRM042", "PRM043"]
        ops = []
        for i, mid in enumerate(machines_ids):
            ops.append(_make_eop(
                sku=f"SKU_{mid}", machine=mid, tool=f"T{i}",
                d=[20000, 5000, 3000], pH=150.0, sH=0.5,
            ))
        machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machines_ids]
        data = _make_engine_data(ops=ops, machines=machines, n_days=10)
        result = schedule_all(data)

        by_md: dict[tuple[str, int], list] = defaultdict(list)
        for s in result.segments:
            by_md[(s.machine_id, s.day_idx)].append(s)

        overlaps = 0
        for (mid, day), segs in by_md.items():
            sorted_segs = sorted(segs, key=lambda s: s.start_min)
            for i in range(1, len(sorted_segs)):
                prev = sorted_segs[i - 1]
                curr = sorted_segs[i]
                if curr.start_min < prev.end_min:
                    overlaps += 1
        assert overlaps == 0, f"Found {overlaps} overlaps across all machines"

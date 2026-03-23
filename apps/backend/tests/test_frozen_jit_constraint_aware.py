"""Frozen invariant tests — JIT Constraint-Aware Right-Shift.

These tests FREEZE the following logic and MUST NEVER be weakened:

1. JIT is DEFAULT ON — schedule_all() applies _jit_right_shift unless disableJIT=True
2. Blocks shift RIGHT toward EDD (latest possible day)
3. OTD-D = 0 after JIT (cumProd >= cumDemand at every demand day)
4. Capacity respected (blocks skip days at DAY_CAP)
5. ToolTimeline respected (tool on 1 machine at a time)
6. CalcoTimeline respected (calco on 1 machine at a time)
7. SetupCrew respected (max 1 setup at a time)
8. Latest-EDD-first processing (proper reordering)
9. Twin blocks use most restrictive constraint across outputs
10. Production conservation (total qty unchanged by JIT)
11. unbook() methods on all 3 constraint classes

DO NOT MODIFY THESE TESTS. If they fail, the code is broken.
"""

from __future__ import annotations

from src.domain.scheduler.overflow_router import compute_otd_delivery_failures
from src.domain.scheduler.scheduler import _jit_right_shift, schedule_all
from src.domain.scheduling.constraints import CalcoTimeline, SetupCrew, ToolTimeline
from src.domain.scheduling.types import (
    Block,
    EMachine,
    EngineData,
    EOp,
    ETool,
    TwinGroup,
    TwinOutput,
)

# ── Helpers ──


def _make_engine_data(
    ops: list[EOp],
    tools: list[ETool],
    machines: list[EMachine] | None = None,
    twin_groups: list[TwinGroup] | None = None,
    n_days: int = 20,
) -> EngineData:
    """Build minimal EngineData."""
    if machines is None:
        machine_ids = list({op.m for op in ops})
        machines = [EMachine(id=mid, area="grandes") for mid in machine_ids]

    tool_map = {t.id: t for t in tools}
    workdays = [True] * n_days

    return EngineData(
        machines=machines,
        tools=tools,
        ops=ops,
        tool_map=tool_map,
        workdays=workdays,
        n_days=n_days,
        twin_groups=twin_groups or [],
        order_based=True,
    )


def _make_block(
    op_id: str = "OP1",
    tool_id: str = "T1",
    machine_id: str = "M1",
    day_idx: int = 0,
    edd_day: int | None = 10,
    qty: int = 100,
    prod_min: int = 60,
    setup_min: int = 30,
    start_min: int = 420,
    end_min: int = 480,
    setup_s: int | None = None,
    setup_e: int | None = None,
    outputs: list[TwinOutput] | None = None,
) -> Block:
    return Block(
        op_id=op_id,
        tool_id=tool_id,
        machine_id=machine_id,
        day_idx=day_idx,
        edd_day=edd_day,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        start_min=start_min,
        end_min=end_min,
        setup_s=setup_s,
        setup_e=setup_e,
        type="ok",
        outputs=outputs,
    )


# ═══════════════════════════════════════════════════════════
# TEST 1: Basic shift — block moves toward its EDD
# ═══════════════════════════════════════════════════════════


class TestBasicShift:
    def test_block_shifts_to_edd(self):
        """A block at day 0 with EDD=10 and no demand constraints should shift to day 10."""
        op = EOp(
            id="OP1",
            t="T1",
            m="M1",
            sku="SKU1",
            nm="Op1",
            d=[0] * 20,  # no demand at all → no OTD-D constraint
            pH=1000,
        )
        op.d[15] = 100  # demand at day 15 (after EDD)

        block = _make_block(
            day_idx=0,
            edd_day=10,
            qty=100,
            prod_min=60,
            setup_min=0,
            start_min=420,
            end_min=480,
        )

        ed = _make_engine_data(
            ops=[op],
            tools=[ETool(id="T1", m="M1", sH=0, pH=1000, op=1, oee=0.66)],
            n_days=20,
        )

        result = _jit_right_shift([block], ed)
        # Block should have shifted from day 0 toward day 10
        assert result[0].day_idx > 0, "Block should shift right from day 0"
        assert result[0].day_idx <= 10, "Block should not shift past EDD"


# ═══════════════════════════════════════════════════════════
# TEST 2: OTD-D preservation — block cannot shift past demand day
# ═══════════════════════════════════════════════════════════


class TestOtdDPreservation:
    def test_block_respects_demand_day(self):
        """Block cannot shift past a day where cumProd would drop below cumDemand."""
        op = EOp(
            id="OP1",
            t="T1",
            m="M1",
            sku="SKU1",
            nm="Op1",
            d=[0] * 20,
            pH=1000,
        )
        op.d[3] = 100  # demand of 100 at day 3

        block = _make_block(
            day_idx=0,
            edd_day=10,
            qty=100,
            prod_min=60,
            setup_min=0,
            start_min=420,
            end_min=480,
        )

        ed = _make_engine_data(
            ops=[op],
            tools=[ETool(id="T1", m="M1", sH=0, pH=1000, op=1, oee=0.66)],
            n_days=20,
        )

        result = _jit_right_shift([block], ed)
        # Block produces 100 pcs, demand of 100 at day 3
        # Cannot shift past day 3 or cumProd < cumDemand at day 3
        assert result[0].day_idx <= 3


# ═══════════════════════════════════════════════════════════
# TEST 3: Capacity check — block cannot exceed DAY_CAP
# ═══════════════════════════════════════════════════════════


class TestCapacityRespected:
    def test_block_skips_full_days(self):
        """Block cannot shift to a day that's already at capacity."""
        op = EOp(
            id="OP1",
            t="T1",
            m="M1",
            sku="SKU1",
            nm="Op1",
            d=[0] * 20,
            pH=1000,
        )
        op.d[15] = 100  # demand far in the future

        # Main block to shift
        block = _make_block(
            op_id="OP1",
            day_idx=0,
            edd_day=10,
            qty=100,
            prod_min=60,
            setup_min=0,
            start_min=420,
            end_min=480,
        )

        # Filler block on day 10 that uses 1000 min (nearly full)
        filler = _make_block(
            op_id="OP_FILLER",
            tool_id="T2",
            day_idx=10,
            edd_day=10,
            qty=500,
            prod_min=1000,
            setup_min=0,
            start_min=420,
            end_min=1420,
        )

        op_filler = EOp(
            id="OP_FILLER",
            t="T2",
            m="M1",
            sku="SKU2",
            nm="Filler",
            d=[0] * 20,
            pH=1000,
        )

        ed = _make_engine_data(
            ops=[op, op_filler],
            tools=[
                ETool(id="T1", m="M1", sH=0, pH=1000, op=1, oee=0.66),
                ETool(id="T2", m="M1", sH=0, pH=1000, op=1, oee=0.66),
            ],
            n_days=20,
        )

        result = _jit_right_shift([block, filler], ed)
        # Day 10 has 1000 min used, adding 60 would exceed 1020
        # Block should shift to day 9 or less
        shifted = [b for b in result if b.op_id == "OP1"][0]
        assert shifted.day_idx < 10, "Block should not go to full day"


# ═══════════════════════════════════════════════════════════
# TEST 4: ToolTimeline — tool on another machine blocks shift
# ═══════════════════════════════════════════════════════════


class TestToolTimelineRespected:
    def test_tool_conflict_prevents_shift(self):
        """Block cannot shift to day where its tool is booked on another machine."""
        op1 = EOp(
            id="OP1",
            t="T1",
            m="M1",
            sku="SKU1",
            nm="Op1",
            d=[0] * 20,
            pH=1000,
        )
        op1.d[15] = 100

        op2 = EOp(
            id="OP2",
            t="T1",
            m="M2",
            sku="SKU2",
            nm="Op2",
            d=[0] * 20,
            pH=1000,
        )

        # Block on M1 to shift
        block1 = _make_block(
            op_id="OP1",
            tool_id="T1",
            machine_id="M1",
            day_idx=0,
            edd_day=10,
            qty=100,
            prod_min=60,
            setup_min=0,
            start_min=420,
            end_min=480,
        )

        # Block on M2 using same tool T1 at day 10, same time window
        block2 = _make_block(
            op_id="OP2",
            tool_id="T1",
            machine_id="M2",
            day_idx=10,
            edd_day=10,
            qty=100,
            prod_min=60,
            setup_min=0,
            start_min=420,
            end_min=480,
        )

        ed = _make_engine_data(
            ops=[op1, op2],
            tools=[ETool(id="T1", m="M1", sH=0, pH=1000, op=1, oee=0.66)],
            machines=[
                EMachine(id="M1", area="grandes"),
                EMachine(id="M2", area="grandes"),
            ],
            n_days=20,
        )

        result = _jit_right_shift([block1, block2], ed)
        shifted = [b for b in result if b.op_id == "OP1"][0]
        # Tool T1 is on M2 at day 10 (same time window 420-480)
        # So OP1 on M1 cannot shift to day 10
        assert shifted.day_idx != 10 or shifted.machine_id != "M1", (
            "Block should not shift to day with tool conflict on another machine"
        )


# ═══════════════════════════════════════════════════════════
# TEST 5: Reorder on same machine — latest-EDD-first processing
# ═══════════════════════════════════════════════════════════


class TestReorderSameMachine:
    def test_latest_edd_gets_latest_day(self):
        """Processing latest-EDD first ensures each block lands near its EDD."""
        ops = []
        blocks_in = []
        # 3 blocks on same machine with different EDDs, all starting early
        for i, (edd, day) in enumerate([(5, 0), (8, 1), (12, 2)]):
            op_id = f"OP{i}"
            op = EOp(
                id=op_id,
                t=f"T{i}",
                m="M1",
                sku=f"SKU{i}",
                nm=f"Op{i}",
                d=[0] * 20,
                pH=1000,
            )
            op.d[edd] = 50  # demand at EDD day
            ops.append(op)

            block = _make_block(
                op_id=op_id,
                tool_id=f"T{i}",
                machine_id="M1",
                day_idx=day,
                edd_day=edd,
                qty=50,
                prod_min=60,
                setup_min=0,
                start_min=420,
                end_min=480,
            )
            blocks_in.append(block)

        tools = [ETool(id=f"T{i}", m="M1", sH=0, pH=1000, op=1, oee=0.66) for i in range(3)]

        ed = _make_engine_data(ops=ops, tools=tools, n_days=20)

        result = _jit_right_shift(blocks_in, ed)
        days = {b.op_id: b.day_idx for b in result}

        # OP2 (EDD=12) should be at a later day than OP1 (EDD=8)
        # and OP1 should be later than OP0 (EDD=5)
        assert days["OP2"] >= days["OP1"], "OP2 (EDD=12) should be >= OP1 (EDD=8)"
        assert days["OP1"] >= days["OP0"], "OP1 (EDD=8) should be >= OP0 (EDD=5)"

        # Each block should have shifted right from its original position
        assert days["OP2"] > 2, "OP2 should shift from day 2"


# ═══════════════════════════════════════════════════════════
# TEST 6: Twin blocks — most restrictive constraint
# ═══════════════════════════════════════════════════════════


class TestTwinMostRestrictive:
    def test_twin_uses_min_of_output_constraints(self):
        """Twin block shifts to min(max_day) across all twin outputs."""
        op_a = EOp(
            id="OP_A",
            t="T1",
            m="M1",
            sku="SKU_A",
            nm="A",
            d=[0] * 20,
            pH=1000,
        )
        op_a.d[5] = 100  # demand for A at day 5

        op_b = EOp(
            id="OP_B",
            t="T1",
            m="M1",
            sku="SKU_B",
            nm="B",
            d=[0] * 20,
            pH=1000,
        )
        op_b.d[10] = 100  # demand for B at day 10

        twin_block = _make_block(
            op_id="OP_A",
            tool_id="T1",
            machine_id="M1",
            day_idx=0,
            edd_day=10,
            qty=100,
            prod_min=60,
            setup_min=0,
            start_min=420,
            end_min=480,
            outputs=[
                TwinOutput(op_id="OP_A", sku="SKU_A", qty=100),
                TwinOutput(op_id="OP_B", sku="SKU_B", qty=100),
            ],
        )

        ed = _make_engine_data(
            ops=[op_a, op_b],
            tools=[ETool(id="T1", m="M1", sH=0, pH=1000, op=1, oee=0.66)],
            twin_groups=[
                TwinGroup(
                    op_id1="OP_A",
                    op_id2="OP_B",
                    sku1="SKU_A",
                    sku2="SKU_B",
                    machine="M1",
                    tool="T1",
                    pH=1000,
                    operators=1,
                )
            ],
            n_days=20,
        )

        result = _jit_right_shift([twin_block], ed)
        # A needs production by day 5, B by day 10
        # Most restrictive = day 5 (from OP_A)
        assert result[0].day_idx <= 5, (
            "Twin block should respect most restrictive output (OP_A demand at day 5)"
        )


# ═══════════════════════════════════════════════════════════
# TEST 7: Full pipeline — OTD-D remains 0 after JIT
# ═══════════════════════════════════════════════════════════


class TestFullPipelineOtdD:
    def test_otd_d_zero_with_jit(self):
        """Full schedule_all with JIT enabled produces 0 OTD-D failures."""
        machine_id = "M1"
        tool_id = "T1"
        n_days = 20
        pH = 1000

        d = [0] * n_days
        d[5] = 500
        d[10] = 300
        d[15] = 200

        op = EOp(id="OP1", t=tool_id, m=machine_id, sku="SKU1", nm="Op1", d=d, pH=pH)
        tool = ETool(id=tool_id, m=machine_id, sH=0.5, pH=pH, op=1, oee=0.66)

        ed = EngineData(
            machines=[EMachine(id=machine_id, area="grandes")],
            tools=[tool],
            ops=[op],
            tool_map={tool_id: tool},
            workdays=[True] * n_days,
            n_days=n_days,
            twin_groups=[],
            order_based=True,
        )

        # With JIT enabled
        result = schedule_all(ed, settings={"disableJIT": False})
        failures = compute_otd_delivery_failures(result.blocks, ed.ops)
        assert len(failures) == 0, f"OTD-D failures after JIT: {failures}"

    def test_otd_d_zero_with_twins_and_jit(self):
        """Full pipeline with twin pair + JIT produces 0 OTD-D failures."""
        machine_id = "M1"
        tool_id = "T1"
        n_days = 20
        pH = 1000

        d_a = [0] * n_days
        d_a[5] = 300
        d_a[12] = 200

        d_b = [0] * n_days
        d_b[5] = 500
        d_b[15] = 100

        ops = [
            EOp(id="OP_A", t=tool_id, m=machine_id, sku="SKU_A", nm="A", d=d_a, pH=pH),
            EOp(id="OP_B", t=tool_id, m=machine_id, sku="SKU_B", nm="B", d=d_b, pH=pH),
        ]
        tool = ETool(id=tool_id, m=machine_id, sH=0.5, pH=pH, op=1, oee=0.66)
        twin_group = TwinGroup(
            op_id1="OP_A",
            op_id2="OP_B",
            sku1="SKU_A",
            sku2="SKU_B",
            machine=machine_id,
            tool=tool_id,
            pH=pH,
            operators=1,
        )

        ed = EngineData(
            machines=[EMachine(id=machine_id, area="grandes")],
            tools=[tool],
            ops=ops,
            tool_map={tool_id: tool},
            workdays=[True] * n_days,
            n_days=n_days,
            twin_groups=[twin_group],
            order_based=True,
        )

        result = schedule_all(ed, settings={"disableJIT": False})
        failures = compute_otd_delivery_failures(result.blocks, ed.ops)
        assert len(failures) == 0, f"OTD-D failures with twins + JIT: {failures}"


# ═══════════════════════════════════════════════════════════
# FROZEN 8: JIT is DEFAULT ON
# ═══════════════════════════════════════════════════════════


class TestFrozenJitDefault:
    """JIT must be the system default — empty settings = JIT active."""

    def _make_ed(self) -> EngineData:
        n_days = 30
        d = [0] * n_days
        d[5] = 500
        d[15] = 300
        d[25] = 200
        op = EOp(id="OP1", t="T1", m="M1", sku="SKU1", nm="Op1", d=d, pH=1000)
        tool = ETool(id="T1", m="M1", sH=0.5, pH=1000, op=1, oee=0.66)
        return EngineData(
            machines=[EMachine(id="M1", area="grandes")],
            tools=[tool],
            ops=[op],
            tool_map={"T1": tool},
            workdays=[True] * n_days,
            n_days=n_days,
            twin_groups=[],
            order_based=True,
        )

    def test_jit_is_default_on(self):
        """schedule_all() with empty settings applies JIT (blocks shift right)."""
        ed = self._make_ed()
        result_default = schedule_all(ed, settings={})
        result_no_jit = schedule_all(ed, settings={"disableJIT": True})

        ok_default = [b for b in result_default.blocks if b.type == "ok"]
        ok_no_jit = [b for b in result_no_jit.blocks if b.type == "ok"]

        avg_default = sum(b.day_idx for b in ok_default) / max(len(ok_default), 1)
        avg_no_jit = sum(b.day_idx for b in ok_no_jit) / max(len(ok_no_jit), 1)

        assert avg_default > avg_no_jit, (
            f"Default must apply JIT: avg_day {avg_default:.1f} should be > ASAP {avg_no_jit:.1f}"
        )

    def test_jit_conserves_production(self):
        """JIT must not change total production quantity."""
        ed = self._make_ed()
        result_jit = schedule_all(ed, settings={"disableJIT": False})
        result_asap = schedule_all(ed, settings={"disableJIT": True})

        qty_jit = sum(b.qty for b in result_jit.blocks if b.type == "ok")
        qty_asap = sum(b.qty for b in result_asap.blocks if b.type == "ok")

        assert qty_jit == qty_asap, f"JIT must conserve production: {qty_jit} != {qty_asap}"

    def test_jit_blocks_closer_to_edd(self):
        """JIT blocks must be closer to their EDD than ASAP blocks."""
        ed = self._make_ed()
        result_jit = schedule_all(ed, settings={"disableJIT": False})
        result_asap = schedule_all(ed, settings={"disableJIT": True})

        def avg_edd_gap(blocks: list) -> float:
            gaps = [
                b.edd_day - b.day_idx for b in blocks if b.type == "ok" and b.edd_day is not None
            ]
            return sum(gaps) / max(len(gaps), 1)

        gap_jit = avg_edd_gap(result_jit.blocks)
        gap_asap = avg_edd_gap(result_asap.blocks)

        assert gap_jit < gap_asap, f"JIT gap to EDD ({gap_jit:.1f}) must be < ASAP ({gap_asap:.1f})"


# ═══════════════════════════════════════════════════════════
# FROZEN 9: Constraint unbook() methods exist
# ═══════════════════════════════════════════════════════════


class TestFrozenUnbookMethods:
    """All 3 constraint classes MUST have unbook() for JIT right-shift."""

    def test_tool_timeline_has_unbook(self):
        assert hasattr(ToolTimeline, "unbook"), "ToolTimeline.unbook() is required"
        tl = ToolTimeline()
        tl.book("T1", 0, 100, "M1")
        tl.unbook("T1", 0, 100, "M1")
        assert tl.is_available("T1", 0, 100, "M2"), "unbook must remove booking"

    def test_calco_timeline_has_unbook(self):
        assert hasattr(CalcoTimeline, "unbook"), "CalcoTimeline.unbook() is required"
        ct = CalcoTimeline()
        ct.book("C1", 0, 100, "M1")
        ct.unbook("C1", 0, 100, "M1")
        assert ct.is_available("C1", 0, 100), "unbook must remove booking"

    def test_setup_crew_has_unbook(self):
        assert hasattr(SetupCrew, "unbook"), "SetupCrew.unbook() is required"
        sc = SetupCrew()
        sc.book(0, 100, "M1")
        sc.unbook(0, 100, "M1")
        assert sc.find_next_available(0, 50, 200) == 0, "unbook must free slot"

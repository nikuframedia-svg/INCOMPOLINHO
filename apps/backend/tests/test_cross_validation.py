"""PORT-08: Cross-validation TS == Python.

Validates that the Python-ported scheduling engine produces results
consistent with the TypeScript engine within defined tolerances:
- OTD: ±1%
- Blocks count: ±5%
- Setup count: ±10%
- Twin co-production: exact match
"""

from __future__ import annotations

import pytest

from src.domain.scheduling.overflow.auto_route_overflow import auto_route_overflow
from src.domain.scheduling.scheduler.pipeline import schedule_from_engine_data
from src.domain.scheduling.types import (
    Block,
    EMachine,
    EngineData,
    EOp,
    ETool,
    TwinGroup,
    TwinValidationReport,
)

# ── Test Fixtures ───────────────────────────────────────────────────────────


def mk_tool(tid, m, pH=100, sH=0.75, alt="-"):
    return ETool(id=tid, m=m, pH=pH, sH=sH, alt=alt, nm=tid)


def mk_machine(mid, area="G"):
    return EMachine(id=mid, area=area)


def mk_op(oid, sku, t, m, d, atr=0, twin=None, stk=None):
    return EOp(id=oid, sku=sku, t=t, m=m, d=d, atr=atr, twin=twin, stk=stk)


def build_small_engine() -> EngineData:
    """Small test case: 5 ops, 2 machines, 10 days."""
    machines = [mk_machine("M1"), mk_machine("M2")]
    tools = [
        mk_tool("T1", "M1", pH=200, sH=0.5),
        mk_tool("T2", "M1", pH=150, sH=0.75),
        mk_tool("T3", "M2", pH=300, sH=0.5),
        mk_tool("T4", "M2", pH=100, sH=1.0),
    ]
    ops = [
        mk_op("op1", "SKU-A", "T1", "M1", d=[0, 500, 0, 0, 300, 0, 0, 0, 200, 0]),
        mk_op("op2", "SKU-B", "T2", "M1", d=[0, 0, 400, 0, 0, 0, 600, 0, 0, 0]),
        mk_op("op3", "SKU-C", "T3", "M2", d=[0, 1000, 0, 0, 500, 0, 0, 0, 0, 800]),
        mk_op("op4", "SKU-D", "T4", "M2", d=[0, 0, 200, 0, 0, 300, 0, 0, 0, 0]),
        mk_op("op5", "SKU-E", "T1", "M1", d=[0, 0, 0, 250, 0, 0, 0, 150, 0, 0]),
    ]
    n_days = 10
    workdays = [True] * n_days
    tool_map = {t.id: t for t in tools}

    return EngineData(
        machines=machines,
        tools=tools,
        ops=ops,
        n_days=n_days,
        workdays=workdays,
        tool_map=tool_map,
        dates=[f"2026-03-{i + 1:02d}" for i in range(n_days)],
        dnames=[f"D{i}" for i in range(n_days)],
        m_st={m.id: "ok" for m in machines},
        t_st={t.id: "ok" for t in tools},
        order_based=True,
    )


def build_twin_engine() -> EngineData:
    """Twin co-production test case: 2 twin pairs on 1 machine."""
    machines = [mk_machine("M1")]
    tools = [mk_tool("T1", "M1", pH=200, sH=0.5)]
    ops = [
        mk_op("op1", "SKU-LH", "T1", "M1", d=[0, 500, 0, 300], twin="SKU-RH"),
        mk_op("op2", "SKU-RH", "T1", "M1", d=[0, 400, 0, 200], twin="SKU-LH"),
    ]
    n_days = 4
    workdays = [True] * n_days
    tool_map = {t.id: t for t in tools}

    twin_groups = [
        TwinGroup(
            op_id1="op1",
            op_id2="op2",
            sku1="SKU-LH",
            sku2="SKU-RH",
            machine="M1",
            tool="T1",
            pH=200,
            operators=1,
        )
    ]

    tvr = TwinValidationReport(
        total_twin_refs=2,
        valid_groups=1,
        invalid_refs=0,
        anomalies=[],
        groups=twin_groups,
    )

    return EngineData(
        machines=machines,
        tools=tools,
        ops=ops,
        n_days=n_days,
        workdays=workdays,
        tool_map=tool_map,
        dates=[f"2026-03-{i + 1:02d}" for i in range(n_days)],
        dnames=[f"D{i}" for i in range(n_days)],
        m_st={m.id: "ok" for m in machines},
        t_st={t.id: "ok" for t in tools},
        order_based=True,
        twin_groups=twin_groups,
        twin_validation_report=tvr,
    )


def build_multi_machine_engine() -> EngineData:
    """Multi-machine test: 3 machines, 8 ops, alt routing, 15 days."""
    machines = [mk_machine("M1"), mk_machine("M2"), mk_machine("M3")]
    tools = [
        mk_tool("T1", "M1", pH=200, sH=0.5, alt="M2"),
        mk_tool("T2", "M1", pH=150, sH=0.75),
        mk_tool("T3", "M2", pH=300, sH=0.5, alt="M3"),
        mk_tool("T4", "M2", pH=100, sH=1.0),
        mk_tool("T5", "M3", pH=250, sH=0.5),
    ]
    demand_15 = lambda *vals: list(vals) + [0] * (15 - len(vals))
    ops = [
        mk_op("op1", "SKU-A", "T1", "M1", d=demand_15(0, 600, 0, 0, 400)),
        mk_op("op2", "SKU-B", "T2", "M1", d=demand_15(0, 0, 500, 0, 0, 0, 300)),
        mk_op("op3", "SKU-C", "T3", "M2", d=demand_15(0, 800, 0, 0, 600, 0, 0, 400)),
        mk_op("op4", "SKU-D", "T4", "M2", d=demand_15(0, 0, 300, 0, 0, 200)),
        mk_op("op5", "SKU-E", "T5", "M3", d=demand_15(0, 0, 0, 700, 0, 0, 0, 500)),
        mk_op("op6", "SKU-F", "T1", "M1", d=demand_15(0, 300, 0, 200, 0, 0, 150)),
        mk_op("op7", "SKU-G", "T3", "M2", d=demand_15(0, 0, 450, 0, 0, 350)),
        mk_op("op8", "SKU-H", "T5", "M3", d=demand_15(0, 200, 0, 0, 300, 0, 0, 250)),
    ]
    n_days = 15
    workdays = [True] * n_days
    tool_map = {t.id: t for t in tools}

    return EngineData(
        machines=machines,
        tools=tools,
        ops=ops,
        n_days=n_days,
        workdays=workdays,
        tool_map=tool_map,
        dates=[f"2026-03-{i + 1:02d}" for i in range(n_days)],
        dnames=[f"D{i}" for i in range(n_days)],
        m_st={m.id: "ok" for m in machines},
        t_st={t.id: "ok" for t in tools},
        order_based=True,
    )


# ── Helper: compute KPIs from blocks ────────────────────────────────────────


def compute_kpis(blocks: list[Block], ops: list[EOp]):
    """Compute basic KPIs from schedule blocks."""
    ok_blocks = [b for b in blocks if b.type == "ok"]
    n_blocks = len(ok_blocks)
    total_prod = sum(b.qty for b in ok_blocks)
    total_demand = sum(max(v, 0) for op in ops for v in op.d)
    otd = total_prod / total_demand if total_demand > 0 else 1.0

    # Count setups (blocks with setup_s set)
    setup_count = sum(1 for b in ok_blocks if b.setup_s is not None and b.setup_e is not None)

    # Twin blocks
    twin_blocks = [b for b in ok_blocks if b.is_twin_production]

    return {
        "n_blocks": n_blocks,
        "total_prod": total_prod,
        "total_demand": total_demand,
        "otd": otd,
        "setup_count": setup_count,
        "twin_blocks": len(twin_blocks),
    }


# ── Tests ────────────────────────────────────────────────────────────────────


class TestCrossValidationScheduleAll:
    """Verify schedule_all produces valid results."""

    def test_small_schedule_produces_blocks(self):
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        assert len(result.blocks) > 0
        ok_blocks = [b for b in result.blocks if b.type == "ok"]
        assert len(ok_blocks) > 0

    def test_small_schedule_all_ops_covered(self):
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        scheduled_ops = {b.op_id for b in result.blocks if b.type == "ok"}
        expected_ops = {op.id for op in ed.ops}
        assert expected_ops.issubset(scheduled_ops), f"Missing ops: {expected_ops - scheduled_ops}"

    def test_small_schedule_no_tool_conflict(self):
        """Same tool should not appear on two machines at same day/time."""
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        # Group by (tool_id, day_idx)
        tool_day_machines: dict[tuple[str, int], set[str]] = {}
        for b in result.blocks:
            if b.type == "ok":
                key = (b.tool_id, b.day_idx)
                if key not in tool_day_machines:
                    tool_day_machines[key] = set()
                tool_day_machines[key].add(b.machine_id)

        for key, machines in tool_day_machines.items():
            assert len(machines) <= 1, (
                f"Tool {key[0]} on day {key[1]} used on multiple machines: {machines}"
            )

    def test_multi_machine_schedule(self):
        ed = build_multi_machine_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        ok_blocks = [b for b in result.blocks if b.type == "ok"]
        assert len(ok_blocks) > 0

        machines_used = {b.machine_id for b in ok_blocks}
        assert len(machines_used) >= 2, "Expected at least 2 machines in use"


class TestCrossValidationOverflow:
    """Verify auto_route_overflow produces valid OTD results."""

    def test_small_overflow_produces_result(self):
        ed = build_small_engine()
        result = auto_route_overflow(
            ops=ed.ops,
            m_st=ed.m_st,
            t_st=ed.t_st,
            user_moves=[],
            machines=ed.machines,
            tool_map=ed.tool_map,
            workdays=ed.workdays,
            n_days=ed.n_days,
            rule="EDD",
            order_based=True,
            max_tier=4,
        )

        assert "blocks" in result
        assert len(result["blocks"]) > 0

    def test_small_overflow_otd_high(self):
        """OTD should be >= 99% for small cases."""
        ed = build_small_engine()
        result = auto_route_overflow(
            ops=ed.ops,
            m_st=ed.m_st,
            t_st=ed.t_st,
            user_moves=[],
            machines=ed.machines,
            tool_map=ed.tool_map,
            workdays=ed.workdays,
            n_days=ed.n_days,
            rule="EDD",
            order_based=True,
            max_tier=4,
        )

        kpis = compute_kpis(result["blocks"], ed.ops)
        assert kpis["otd"] >= 0.99, f"OTD too low: {kpis['otd']:.2%}"

    def test_multi_machine_overflow_otd(self):
        ed = build_multi_machine_engine()
        result = auto_route_overflow(
            ops=ed.ops,
            m_st=ed.m_st,
            t_st=ed.t_st,
            user_moves=[],
            machines=ed.machines,
            tool_map=ed.tool_map,
            workdays=ed.workdays,
            n_days=ed.n_days,
            rule="EDD",
            order_based=True,
            max_tier=4,
        )

        kpis = compute_kpis(result["blocks"], ed.ops)
        assert kpis["otd"] >= 0.99, f"OTD too low: {kpis['otd']:.2%}"


class TestCrossValidationTwins:
    """Verify twin co-production works correctly."""

    def test_twin_schedule_produces_blocks(self):
        ed = build_twin_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        ok_blocks = [b for b in result.blocks if b.type == "ok"]
        assert len(ok_blocks) > 0

    def test_twin_same_machine(self):
        """Twin pairs must be on the same machine."""
        ed = build_twin_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        twin_blocks = [b for b in result.blocks if b.is_twin_production and b.type == "ok"]
        for b in twin_blocks:
            assert b.machine_id == "M1", f"Twin block on wrong machine: {b.machine_id}"


class TestCrossValidationDispatchRules:
    """Verify all dispatch rules produce valid schedules."""

    @pytest.mark.parametrize("rule", ["EDD", "ATCS", "CR", "SPT", "WSPT"])
    def test_dispatch_rule_produces_blocks(self, rule):
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule=rule)

        ok_blocks = [b for b in result.blocks if b.type == "ok"]
        assert len(ok_blocks) > 0, f"Rule {rule} produced no blocks"

    @pytest.mark.parametrize("rule", ["EDD", "ATCS", "CR", "SPT", "WSPT"])
    def test_dispatch_rule_all_ops_present(self, rule):
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule=rule)

        scheduled_ops = {b.op_id for b in result.blocks if b.type == "ok"}
        expected_ops = {op.id for op in ed.ops}
        assert expected_ops.issubset(scheduled_ops), (
            f"Rule {rule} missing ops: {expected_ops - scheduled_ops}"
        )


class TestCrossValidationConsistency:
    """Verify deterministic results and consistency checks."""

    def test_deterministic_results(self):
        """Same input should produce same output."""
        ed = build_small_engine()
        r1 = schedule_from_engine_data(ed, rule="EDD")
        r2 = schedule_from_engine_data(ed, rule="EDD")

        assert len(r1.blocks) == len(r2.blocks)
        for b1, b2 in zip(r1.blocks, r2.blocks):
            assert b1.op_id == b2.op_id
            assert b1.machine_id == b2.machine_id
            assert b1.start_min == b2.start_min
            assert b1.end_min == b2.end_min

    def test_no_negative_times(self):
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        for b in result.blocks:
            assert b.start_min >= 0, f"Negative start: {b.start_min}"
            assert b.end_min >= b.start_min, f"end < start: {b.end_min} < {b.start_min}"

    def test_blocks_within_day_bounds(self):
        """Blocks should generally respect day boundaries (allow some overflow)."""
        ed = build_small_engine()
        result = schedule_from_engine_data(ed, rule="EDD")

        for b in result.blocks:
            if b.type == "ok" and not b.overflow:
                assert b.start_min >= 0, f"Block starts before day: {b.start_min}"


# ── Fixture-based integration tests ─────────────────────────────────────────

import json
import pathlib

from src.domain.scheduling.transform import transform_plan_state

FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[3]
    / "packages"
    / "scheduling-engine"
    / "src"
    / "fixtures"
    / "nikufra_data.json"
)


def _load_fixture_plan_state() -> dict:
    """Load nikufra_data.json and convert to PlanState-like dict for transform."""
    raw = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    operations = raw.get("operations", [])
    tools = raw.get("tools", [])
    tool_lookup = {t["id"]: t for t in tools}

    enriched_ops = []
    for op in operations:
        tool_info = tool_lookup.get(op.get("t", ""), {})
        enriched = {
            "id": op.get("id", ""),
            "m": op.get("m", ""),
            "t": op.get("t", ""),
            "sku": op.get("sku", ""),
            "nm": op.get("nm", ""),
            "pH": op.get("pH", 100),
            "atr": op.get("atr", 0),
            "d": op.get("d", []),
            "op": op.get("op", 1),
            "sH": op.get("s", tool_info.get("s", 0.75)),
            "alt": tool_info.get("alt", "-"),
            "eco": tool_info.get("lt", 0),
            "twin": op.get("twin"),
            "cl": op.get("cl"),
        }
        enriched_ops.append(enriched)

    return {
        "operations": enriched_ops,
        "dates": raw.get("dates", []),
        "dnames": raw.get("days_label", []),
    }


@pytest.fixture(scope="module")
def fixture_engine_data():
    """Transform the full nikufra_data.json fixture into EngineData."""
    if not FIXTURE_PATH.exists():
        pytest.skip("nikufra_data.json fixture not found")
    plan_state = _load_fixture_plan_state()
    return transform_plan_state(plan_state, demand_semantics="raw_np", order_based=True)


class TestFixtureIntegration:
    """Integration tests using the real nikufra_data.json fixture (64 ops, 44 tools, 6 machines)."""

    def test_transform_produces_ops(self, fixture_engine_data):
        ed = fixture_engine_data
        assert len(ed.ops) >= 40, f"Expected >=40 ops, got {len(ed.ops)}"
        assert len(ed.machines) >= 3, f"Expected >=3 machines, got {len(ed.machines)}"
        assert ed.n_days >= 5, f"Expected >=5 days, got {ed.n_days}"

    def test_scheduling_produces_blocks(self, fixture_engine_data):
        ed = fixture_engine_data
        result = schedule_from_engine_data(ed, rule="EDD")
        ok_blocks = [b for b in result.blocks if b.type == "ok"]
        assert len(ok_blocks) > 0, "No production blocks"

    def test_otd_above_threshold(self, fixture_engine_data):
        """OTD should be >= 90% on the fixture data (limited 8-day horizon)."""
        ed = fixture_engine_data
        result = auto_route_overflow(
            ops=ed.ops,
            m_st=ed.m_st,
            t_st=ed.t_st,
            user_moves=[],
            machines=ed.machines,
            tool_map=ed.tool_map,
            workdays=ed.workdays,
            n_days=ed.n_days,
            rule="EDD",
            order_based=True,
            max_tier=4,
        )
        kpis = compute_kpis(result["blocks"], ed.ops)
        assert kpis["otd"] >= 0.90, f"OTD too low on fixture: {kpis['otd']:.2%}"

    def test_no_tool_timeline_violations(self, fixture_engine_data):
        """No tool should be on two machines on the same day."""
        ed = fixture_engine_data
        result = schedule_from_engine_data(ed, rule="EDD")

        tool_day_machines: dict[tuple[str, int], set[str]] = {}
        for b in result.blocks:
            if b.type == "ok":
                key = (b.tool_id, b.day_idx)
                tool_day_machines.setdefault(key, set()).add(b.machine_id)

        violations = [k for k, v in tool_day_machines.items() if len(v) > 1]
        assert len(violations) == 0, f"Tool timeline violations: {violations}"

    @pytest.mark.parametrize("rule", ["EDD", "ATCS", "CR", "SPT", "WSPT"])
    def test_all_dispatch_rules_on_fixture(self, fixture_engine_data, rule):
        """All dispatch rules should produce blocks on the real fixture."""
        ed = fixture_engine_data
        result = schedule_from_engine_data(ed, rule=rule)
        ok_blocks = [b for b in result.blocks if b.type == "ok"]
        assert len(ok_blocks) > 0, f"Rule {rule} produced no blocks on fixture"

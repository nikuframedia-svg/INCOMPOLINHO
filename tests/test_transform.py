"""Tests for transform pipeline — Spec 01 §3-§6, §7."""

from __future__ import annotations

from backend.types import EOp, RawRow
from backend.transform.client_demands import extract_client_demands
from backend.transform.merge import merge_multi_client
from backend.transform.twins import (
    identify_twins_from_master,
    identify_twins_from_column_with_refs,
    identify_twins_from_tool_machine,
)
from backend.transform.transform import transform, _raw_to_eop, _resolve_holidays


# --- Fixtures ---


def _make_raw(
    client_name: str = "FAURECIA",
    sku: str = "1064169X100",
    machine: str = "PRM031",
    tool: str = "BFP079",
    eco_lot: int = 36400,
    pH: float = 1681.0,
    np: list[int] | None = None,
    twin_ref: str = "",
    operators: int = 1,
    backlog: int = 0,
    wip: int = 0,
) -> RawRow:
    return RawRow(
        client_id="210020",
        client_name=client_name,
        sku=sku,
        designation="Peça Test",
        eco_lot=eco_lot,
        machine_id=machine,
        tool_id=tool,
        pieces_per_hour=pH,
        operators=operators,
        wip=wip,
        backlog=backlog,
        twin_ref=twin_ref,
        np_values=np or [2751, 0, 0, -15600, 0, -10400],
    )


def _make_eop(
    sku: str = "SKU_A",
    machine: str = "PRM031",
    tool: str = "T1",
    client: str = "CLIENT_A",
    d: list[int] | None = None,
    eco_lot: int = 0,
) -> EOp:
    return EOp(
        id=f"{tool}_{machine}_{sku}",
        sku=sku,
        client=client,
        designation="Test",
        m=machine,
        t=tool,
        pH=100.0,
        sH=0.5,
        operators=1,
        eco_lot=eco_lot,
        alt=None,
        stk=0,
        backlog=0,
        d=d or [0, 500, 0, 300],
        oee=0.66,
        wip=0,
    )


WORKDAYS = ["2026-03-05", "2026-03-06", "2026-03-07", "2026-03-10", "2026-03-11", "2026-03-12"]


# --- Test: merge_multi_client ---


class TestMerge:
    def test_no_merge_single(self):
        ops = [_make_eop(sku="A"), _make_eop(sku="B", tool="T2")]
        merged = merge_multi_client(ops)
        assert len(merged) == 2

    def test_merge_same_sku_machine_tool(self):
        """Same (sku, machine, tool) from different clients → merge."""
        op1 = _make_eop(sku="A", client="FAURECIA", d=[0, 500, 0])
        op2 = _make_eop(sku="A", client="FAUR-SIEGE", d=[0, 300, 200])
        merged = merge_multi_client([op1, op2])
        assert len(merged) == 1
        assert merged[0].d == [0, 800, 200]
        assert "FAUR-SIEGE" in merged[0].client
        assert "FAURECIA" in merged[0].client

    def test_merge_demand_sum(self):
        """Demand is summed across clients."""
        op1 = _make_eop(d=[100, 200, 300])
        op2 = _make_eop(d=[50, 50, 50])
        merged = merge_multi_client([op1, op2])
        assert merged[0].d == [150, 250, 350]

    def test_merge_eco_lot_max(self):
        op1 = _make_eop(eco_lot=1000)
        op2 = _make_eop(eco_lot=2000)
        merged = merge_multi_client([op1, op2])
        assert merged[0].eco_lot == 2000

    def test_merge_ph_min(self):
        """pH = min (conservative)."""
        op1 = _make_eop()
        op1 = EOp(**{**{f.name: getattr(op1, f.name) for f in op1.__dataclass_fields__.values()}, "pH": 1000})
        op2 = _make_eop()
        op2 = EOp(**{**{f.name: getattr(op2, f.name) for f in op2.__dataclass_fields__.values()}, "pH": 500})
        merged = merge_multi_client([op1, op2])
        assert merged[0].pH == 500


# --- Test: twins ---


class TestTwinsFromMaster:
    def test_basic_pair(self):
        ops = [
            _make_eop(sku="SKU_A", tool="BFP079"),
            _make_eop(sku="SKU_B", tool="BFP079"),
        ]
        config = {"BFP079": ["SKU_A", "SKU_B"]}
        groups = identify_twins_from_master(ops, config)
        assert len(groups) == 1
        assert groups[0].sku_1 == "SKU_A"
        assert groups[0].sku_2 == "SKU_B"

    def test_missing_one_sku(self):
        ops = [_make_eop(sku="SKU_A", tool="BFP079")]
        config = {"BFP079": ["SKU_A", "SKU_MISSING"]}
        groups = identify_twins_from_master(ops, config)
        assert len(groups) == 0


class TestTwinsFromToolMachine:
    def test_two_skus_twin(self):
        ops = [
            _make_eop(sku="A", tool="T1", machine="M1"),
            _make_eop(sku="B", tool="T1", machine="M1"),
        ]
        groups, warnings = identify_twins_from_tool_machine(ops)
        assert len(groups) == 1
        assert len(warnings) == 0

    def test_three_skus_ambiguous(self):
        ops = [
            _make_eop(sku="A", tool="T1", machine="M1"),
            _make_eop(sku="B", tool="T1", machine="M1"),
            _make_eop(sku="C", tool="T1", machine="M1"),
        ]
        groups, warnings = identify_twins_from_tool_machine(ops)
        assert len(groups) == 0
        assert len(warnings) == 1
        assert "AMBIGUOUS" in warnings[0]

    def test_single_sku_no_twin(self):
        ops = [_make_eop(sku="A", tool="T1", machine="M1")]
        groups, warnings = identify_twins_from_tool_machine(ops)
        assert len(groups) == 0
        assert len(warnings) == 0


class TestTwinsFromColumn:
    def test_basic_pair(self):
        ops = [
            _make_eop(sku="SKU_A", tool="T1", machine="M1"),
            _make_eop(sku="SKU_B", tool="T1", machine="M1"),
        ]
        twin_refs = {
            "T1_M1_SKU_A": "SKU_B",
            "T1_M1_SKU_B": "SKU_A",
        }
        groups = identify_twins_from_column_with_refs(ops, twin_refs)
        assert len(groups) == 1


# --- Test: client_demands ---


class TestClientDemands:
    def test_basic_extraction(self):
        rows = [_make_raw(np=[2751, 0, 0, -15600, 0, -10400])]
        demands = extract_client_demands(rows, WORKDAYS)
        assert "1064169X100" in demands
        entries = demands["1064169X100"]
        assert len(entries) == 2
        assert entries[0].day_idx == 3
        assert entries[0].np_value == -15600
        # order_qty = abs(NP) — stock already deducted in NP
        assert entries[0].order_qty == 15600
        assert entries[1].order_qty == 10400

    def test_no_demand(self):
        rows = [_make_raw(np=[100, 200, 300])]
        demands = extract_client_demands(rows, WORKDAYS)
        assert len(demands) == 0

    def test_immediate_demand_no_stock(self):
        rows = [_make_raw(np=[-5000, 0, -3000, 0, 0, 0])]
        demands = extract_client_demands(rows, WORKDAYS)
        entries = demands["1064169X100"]
        assert entries[0].order_qty == 5000  # no prior stock
        assert entries[1].order_qty == 3000


# --- Test: _raw_to_eop ---


class TestRawToEop:
    def test_basic_conversion(self):
        raw = _make_raw()
        eop = _raw_to_eop(raw, None)
        assert eop.id == "BFP079_PRM031_1064169X100"
        assert eop.sku == "1064169X100"
        assert eop.m == "PRM031"
        assert eop.t == "BFP079"
        assert eop.pH == 1681.0
        assert eop.sH == 0.5  # default
        assert eop.stk == 2751
        assert eop.d == [0, 0, 0, 15600, 0, 10400]

    def test_ph_zero_defaults_to_one(self):
        raw = _make_raw(pH=0)
        eop = _raw_to_eop(raw, None)
        assert eop.pH == 1.0

    def test_master_data_setup_hours(self):
        raw = _make_raw()
        master = {"setup_hours": {"BFP079": 1.2, "_default": 0.5}}
        eop = _raw_to_eop(raw, master)
        assert eop.sH == 1.2

    def test_master_data_alt_machine(self):
        raw = _make_raw()
        master = {"alt_machines": {"BFP079": {"alt": "PRM039"}}}
        eop = _raw_to_eop(raw, master)
        assert eop.alt == "PRM039"


# --- Test: full transform pipeline ---


class TestHolidays:
    def test_resolve_holidays_matching(self):
        workdays = ["2026-04-01", "2026-04-02", "2026-04-03", "2026-04-04"]
        master = {"holidays": ["2026-04-03", "2026-04-05"]}
        indices = _resolve_holidays(workdays, master)
        assert indices == [2, 3]  # 04-03 is holiday, 04-04 (Saturday) auto-detected

    def test_resolve_holidays_none(self):
        assert _resolve_holidays(["2026-04-01"], None) == []

    def test_resolve_holidays_empty(self):
        assert _resolve_holidays(["2026-04-01"], {"holidays": []}) == []

    def test_resolve_holidays_no_overlap(self):
        workdays = ["2026-03-05", "2026-03-06"]
        master = {"holidays": ["2026-12-25"]}
        assert _resolve_holidays(workdays, master) == []


class TestTransformPipeline:
    def test_basic_transform(self):
        rows = [
            _make_raw(client_name="FAURECIA", np=[2751, -15600, 0, 0, 0, 0]),
            _make_raw(client_name="FAUR-SIEGE", np=[0, -5000, 0, -3000, 0, 0]),
        ]
        result = transform(rows, WORKDAYS, has_twin_col=False, master_data=None)
        # 2 rows with same sku+machine+tool → merged to 1
        assert len(result.ops) == 1
        assert result.ops[0].d[1] == 20600  # 15600 + 5000
        assert result.n_days == 6
        assert len(result.workdays) == 6
        assert len(result.machines) == 1
        assert result.machines[0].id == "PRM031"

    def test_transform_with_master_data(self):
        rows = [_make_raw(np=[0, -5000, 0, 0, 0, 0])]
        master = {
            "machines": {
                "PRM031": {"group": "Grandes", "day_capacity_min": 1020},
            },
            "setup_hours": {"BFP079": 1.0, "_default": 0.5},
            "alt_machines": {"BFP079": {"primary": "PRM031", "alt": "PRM039"}},
            "twins": {},
            "holidays": ["2026-03-06"],
            "factory": {"oee_default": 0.66},
        }
        result = transform(rows, WORKDAYS, has_twin_col=False, master_data=master)
        assert result.ops[0].sH == 1.0
        assert result.ops[0].alt == "PRM039"
        assert result.machines[0].group == "Grandes"
        assert result.machines[0].day_capacity == 1020
        assert result.holidays == [1, 2]  # "2026-03-06" is holiday (index 1), "2026-03-07" is Saturday (index 2)

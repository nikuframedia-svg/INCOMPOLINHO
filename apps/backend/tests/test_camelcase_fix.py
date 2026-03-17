"""Tests for camelCase → snake_case alias support (FINAL-01).

Ensures both camelCase (from TS frontend) and snake_case (Python internal)
are accepted by all Pydantic models.
"""

from __future__ import annotations

from src.domain.scheduling.types import Block, EngineData, EOp, TwinGroup


class TestEngineDataCamelCase:
    """EngineData accepts camelCase aliases from frontend."""

    def test_accepts_camelcase(self):
        ed = EngineData(
            ops=[],
            machines=[{"id": "PRM019", "area": "PG1"}],
            toolMap={
                "BFP001": {"id": "BFP001", "m": "PRM019", "alt": "-", "sH": 1.0, "pH": 100, "op": 1}
            },
            nDays=14,
            mSt={"PRM019": "60", "PRM031": "60"},
            tSt={"BFP001": "45", "BFP002": "45"},
            thirdShift=True,
            orderBased=True,
            focusIds=["PRM019"],
            preStartDays=2,
        )
        assert ed.n_days == 14
        assert ed.third_shift is True
        assert ed.order_based is True
        assert ed.focus_ids == ["PRM019"]
        assert ed.pre_start_days == 2
        assert len(ed.m_st) == 2
        assert len(ed.t_st) == 2
        assert "BFP001" in ed.tool_map

    def test_accepts_snake_case(self):
        ed = EngineData(
            ops=[],
            machines=[{"id": "PRM019", "area": "PG1"}],
            tool_map={"BFP001": {"id": "BFP001", "m": "PRM019", "alt": "-"}},
            n_days=10,
            m_st={"PRM019": "60"},
            t_st={"BFP001": "45"},
            third_shift=False,
            order_based=False,
        )
        assert ed.n_days == 10
        assert ed.third_shift is False
        assert ed.order_based is False


class TestEOpCamelCase:
    """EOp accepts camelCase aliases."""

    def test_accepts_camelcase(self):
        op = EOp(
            id="OP01",
            t="BFP001",
            m="PRM019",
            sku="SKU001",
            ltDays=5,
            clNm="Cliente A",
            shippingDayIdx=3,
        )
        assert op.lt_days == 5
        assert op.cl_nm == "Cliente A"
        assert op.shipping_day_idx == 3

    def test_accepts_snake_case(self):
        op = EOp(
            id="OP01",
            t="BFP001",
            m="PRM019",
            sku="SKU001",
            lt_days=7,
            cl_nm="Cliente B",
            shipping_day_idx=5,
        )
        assert op.lt_days == 7
        assert op.cl_nm == "Cliente B"


class TestBlockCamelCase:
    """Block accepts camelCase aliases."""

    def test_accepts_camelcase(self):
        b = Block(
            opId="OP01",
            toolId="BFP001",
            machineId="PRM019",
            dayIdx=2,
            startMin=420,
            endMin=930,
            prodMin=480,
            setupMin=30,
            qty=500,
        )
        assert b.op_id == "OP01"
        assert b.tool_id == "BFP001"
        assert b.machine_id == "PRM019"
        assert b.day_idx == 2
        assert b.start_min == 420
        assert b.end_min == 930
        assert b.prod_min == 480
        assert b.setup_min == 30
        assert b.qty == 500

    def test_accepts_snake_case(self):
        b = Block(
            op_id="OP02",
            tool_id="BFP002",
            machine_id="PRM031",
            day_idx=3,
            start_min=0,
            end_min=420,
        )
        assert b.op_id == "OP02"
        assert b.machine_id == "PRM031"


class TestTwinGroupCamelCase:
    """TwinGroup accepts camelCase aliases."""

    def test_accepts_camelcase(self):
        tg = TwinGroup(
            opId1="OP01",
            opId2="OP02",
            sku1="SKU-A",
            sku2="SKU-B",
            tool="BFP001",
            machine="PRM019",
            pH=100,
            operators=1,
        )
        assert tg.op_id1 == "OP01"
        assert tg.op_id2 == "OP02"

    def test_accepts_snake_case(self):
        tg = TwinGroup(
            op_id1="OP01",
            op_id2="OP02",
            sku1="SKU-A",
            sku2="SKU-B",
            tool="BFP001",
            machine="PRM019",
            pH=100,
            operators=1,
        )
        assert tg.op_id1 == "OP01"

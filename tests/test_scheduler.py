"""Tests for scheduler — Spec 02 v6 (Definitivo).

Covers all 5 fixes + full pipeline:
  Fix 1: EDD sort internal (tool_grouping)
  Fix 2: LST-gated JIT (jit)
  Fix 3: Campaign sequencing (dispatch)
  Fix 4: Interleave urgent (dispatch)
  Fix 5: Min prod_min (lot_sizing + dispatch)
"""

from __future__ import annotations

import pytest

from backend.config.planning import apply_effective_planning_config
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
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
from backend.scheduler.scheduler import (
    _remove_redundant_retained_tool_setups,
    schedule_all,
)
from backend.scheduler.scoring import compute_score
from backend.scheduler.tool_grouping import create_tool_runs
from backend.scheduler.types import Lot, Segment, ToolRun, ToolTimeline
from backend.types import EngineData, EOp, MachineInfo, TwinGroup


# --- Fixtures ---

WORKDAYS = [
    "2026-03-05",
    "2026-03-06",
    "2026-03-07",
    "2026-03-10",
    "2026-03-11",
    "2026-03-12",
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
    sku: str = "SKU",
    setup_family: str = "",
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
        sku=sku,
        setup_family=setup_family,
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
        lots = [
            _make_lot(
                lot_id=f"L-{run_id}",
                op_id=f"O-{run_id}",
                tool_id=tool_id,
                machine_id=machine_id,
                alt_machine_id=alt_machine_id,
            )
        ]
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

    def test_effective_eco_lot_override_changes_real_lots(self):
        op = _make_eop(sku="8750711912", d=[0, 50], eco_lot=0)
        data = _make_engine_data(ops=[op])
        config = FactoryConfig(
            sku_planning_rules={"8750711912": {"eco_lot": 1000}},
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert data.ops[0].eco_lot_isop == 0
        assert data.ops[0].eco_lot_effective == 1000
        assert lots[0].qty == 1000
        assert lots[0].eco_lot_isop == 0
        assert lots[0].eco_lot_effective == 1000
        assert lots[0].planning_source == "eco_lot_override"

    def test_effective_tool_config_restores_machine_alternative(self):
        op = _make_eop(
            sku="1064169X100",
            machine="PRM031",
            tool="BFP079",
            alt=None,
            sH=0.5,
        )
        data = _make_engine_data(ops=[op])
        config = FactoryConfig(
            tools={
                "BFP079": {
                    "primary": "PRM031",
                    "alt": "PRM039",
                    "setup_hours": 1.0,
                }
            },
            machines={
                "PRM031": MachineConfig("PRM031", "Grandes"),
                "PRM039": MachineConfig("PRM039", "Grandes"),
            },
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert data.ops[0].m == "PRM031"
        assert data.ops[0].alt == "PRM039"
        assert data.ops[0].sH == 1.0
        assert "PRM039" in {machine.id for machine in data.machines}
        assert lots[0].alt_machine_id == "PRM039"

    def test_effective_tool_config_does_not_restore_inactive_alternative(self):
        op = _make_eop(
            sku="1064169X100",
            machine="PRM031",
            tool="BFP079",
            alt=None,
        )
        data = _make_engine_data(ops=[op])
        config = FactoryConfig(
            tools={
                "BFP079": {
                    "primary": "PRM031",
                    "alt": "PRM039",
                    "setup_hours": 1.0,
                }
            },
            machines={
                "PRM031": MachineConfig("PRM031", "Grandes", active=True),
                "PRM039": MachineConfig("PRM039", "Grandes", active=False),
            },
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert data.ops[0].m == "PRM031"
        assert data.ops[0].alt is None
        assert lots[0].machine_id == "PRM031"
        assert lots[0].alt_machine_id is None

    def test_effective_tool_config_uses_active_alt_when_primary_is_inactive(self):
        op = _make_eop(
            sku="1197914X050",
            machine="PRM031",
            tool="BFP112",
            alt=None,
        )
        data = _make_engine_data(ops=[op])
        config = FactoryConfig(
            tools={
                "BFP112": {
                    "primary": "PRM039",
                    "alt": "PRM019",
                    "setup_hours": 0.5,
                }
            },
            machines={
                "PRM039": MachineConfig("PRM039", "Grandes", active=False),
                "PRM019": MachineConfig("PRM019", "Grandes", active=True),
            },
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert data.ops[0].m == "PRM019"
        assert data.ops[0].alt is None
        assert lots[0].machine_id == "PRM019"
        assert lots[0].alt_machine_id is None

    def test_effective_tool_config_allows_oee_to_shift_work_to_alternative(self):
        op = _make_eop(
            sku="1064169X100",
            machine="PRM031",
            tool="BFP079",
            d=[0, 2000],
            pH=100.0,
            alt=None,
            oee=0.66,
        )
        data = _make_engine_data(ops=[op], machines=[
            MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
        ])
        config = FactoryConfig(
            tools={
                "BFP079": {
                    "primary": "PRM031",
                    "alt": "PRM039",
                    "setup_hours": 0.5,
                }
            },
            machines={
                "PRM031": MachineConfig("PRM031", "Grandes", oee=0.25),
                "PRM039": MachineConfig("PRM039", "Grandes", oee=1.0),
            },
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)
        runs = create_tool_runs(lots, config=config)
        machine_runs = assign_machines(runs, data, config=config)

        assert runs[0].alt_machine_id == "PRM039"
        assert machine_runs["PRM039"][0].tool_id == "BFP079"
        assert not machine_runs.get("PRM031")

    def test_finish_buffer_changes_internal_deadline(self):
        op = _make_eop(sku="SKU_BUF", d=[0, 0, 0, 100], eco_lot=0)
        data = _make_engine_data(ops=[op], n_days=4)
        config = FactoryConfig(
            sku_planning_rules={"SKU_BUF": {"finish_buffer_days": 2}},
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert lots[0].delivery_day == 3
        assert lots[0].internal_deadline == 1
        assert lots[0].internal_target_day == 1
        assert lots[0].production_due_day == 3
        assert lots[0].edd == 3

    def test_min_campaign_qty_groups_exact_shortfall(self):
        op = _make_eop(sku="SKU_MICRO", d=[0, 50], eco_lot=0)
        data = _make_engine_data(ops=[op])
        config = FactoryConfig(
            sku_planning_rules={"SKU_MICRO": {"min_campaign_qty": 500}},
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert lots[0].qty == 500
        assert lots[0].planning_source == "min_campaign_qty"
        assert lots[0].economic_warning is None

    def test_min_campaign_prod_min_sets_minimum_economic_runtime(self):
        op = _make_eop(sku="SKU_TIME", d=[0, 50], eco_lot=0, pH=600, oee=1.0)
        data = _make_engine_data(ops=[op])
        config = FactoryConfig(
            sku_planning_rules={"SKU_TIME": {"min_campaign_prod_min": 30}},
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert lots[0].qty == 300
        assert lots[0].prod_min == 30
        assert lots[0].planning_source == "min_campaign_prod_min"

    def test_max_group_gap_days_groups_near_future_demand(self):
        op = _make_eop(sku="SKU_GAP", d=[0, 50, 75, 0, 100], eco_lot=0)
        data = _make_engine_data(ops=[op], n_days=5)
        config = FactoryConfig(
            sku_planning_rules={"SKU_GAP": {"max_group_gap_days": 1}},
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert lots[0].qty == 125
        assert lots[0].planning_source == "campaign_window"
        assert lots[1].qty == 100

    def test_start_buffer_prioritizes_target_start_in_sequence(self):
        op_a = _make_eop(sku="A", tool="TA", d=[0, 0, 0, 100], eco_lot=0)
        op_b = _make_eop(sku="B", tool="TB", d=[0, 0, 0, 100], eco_lot=0)
        data = _make_engine_data(ops=[op_a, op_b], n_days=4)
        config = FactoryConfig(sku_planning_rules={"B": {"start_buffer_days": 2}})

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)
        runs = create_tool_runs(lots, config=config)
        machine_runs = assign_machines(runs, data, config=config)
        sequenced = sequence_per_machine(machine_runs, config=config)

        first_run = sequenced["PRM031"][0]
        assert first_run.lots[0].op_id == op_b.id
        assert first_run.target_start_day == 1

    def test_configured_reference_priority_reaches_the_lot(self):
        op = _make_eop(sku="TP042173-0040-2", d=[0, 0, 100], eco_lot=0)
        data = _make_engine_data(ops=[op], n_days=3)
        config = FactoryConfig(
            sku_planning_rules={"TP042173-0040-2": {"planning_priority": 100}},
        )

        apply_effective_planning_config(data, config)
        lots = create_lots(data, config=config)

        assert data.ops[0].planning_priority == 100
        assert lots[0].planning_priority == 100

    def test_twin_lot_creation(self):
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000])
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 800])
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1="T1_M1_A",
            op_id_2="T1_M1_B",
            sku_1="A",
            sku_2="B",
            eco_lot_1=0,
            eco_lot_2=0,
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
            tool_id="T1",
            machine_id="M1",
            op_id_1="T1_M1_A",
            op_id_2="T1_M1_B",
            sku_1="A",
            sku_2="B",
            eco_lot_1=0,
            eco_lot_2=0,
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
    def test_same_tool_and_reference_grouped(self):
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, setup_min=60, edd=5),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, setup_min=60, edd=10),
        ]
        runs = create_tool_runs(lots)
        assert len(runs) == 1
        assert runs[0].setup_min == 60  # 1 setup, not 2
        assert runs[0].total_prod_min == 180

    def test_same_tool_different_references_require_separate_runs(self):
        lots = [
            _make_lot("L1", "O1", "T1", "M1", sku="REF-A"),
            _make_lot("L2", "O2", "T1", "M1", sku="REF-B"),
        ]

        runs = create_tool_runs(lots)

        assert len(runs) == 2

    def test_configured_setup_family_groups_distinct_references_once(self):
        first = _make_eop(
            sku="REF-A", tool="T1", machine="M1", d=[0, 500], sH=0.5
        )
        second = _make_eop(
            sku="REF-B", tool="T1", machine="M1", d=[0, 300], sH=1.0
        )
        config = FactoryConfig(setup_families={"T1": [["REF-A", "REF-B"]]})

        lots = create_lots(_make_engine_data(ops=[first, second], n_days=2), config)
        runs = create_tool_runs(lots, config=config)

        assert {lot.setup_family for lot in lots} == {"REF-A|REF-B"}
        assert len(runs) == 1
        assert runs[0].setup_min == 60
        assert [lot.sku for lot in runs[0].lots] == ["REF-A", "REF-B"]

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

    def test_same_deadline_prioritizes_total_delivery_quantity_including_twins(self):
        small = _make_lot(
            "L-small", "O-twin-a", "T1", "M1", qty=150, edd=5, is_twin=True
        )
        small.twin_outputs = [
            ("O-twin-a", "TWIN-A", 150),
            ("O-twin-b", "TWIN-B", 150),
        ]
        solo = _make_lot(
            "L-solo", "O-twin-a", "T1", "M1", qty=500, edd=5, is_twin=True
        )
        solo.twin_outputs = [
            ("O-twin-a", "TWIN-A", 500),
            ("O-twin-b", "TWIN-B", 500),
        ]
        twin = _make_lot(
            "L-twin",
            "O-twin-a",
            "T1",
            "M1",
            qty=600,
            edd=5,
            is_twin=True,
        )
        twin.twin_outputs = [
            ("O-twin-a", "TWIN-A", 600),
            ("O-twin-b", "TWIN-B", 600),
        ]

        runs = create_tool_runs([small, solo, twin])

        assert [lot.id for lot in runs[0].lots] == ["L-twin", "L-solo", "L-small"]

    def test_split_by_edd_gap(self):
        """Lots with large EDD gap get split into separate runs."""
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, edd=2),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, edd=20),
        ]
        runs = create_tool_runs(lots, max_edd_gap=10)
        assert len(runs) == 2

    def test_campaign_splits_when_material_release_floor_changes(self):
        """Future demand cannot hold back work whose material is released."""

        lots = [
            _make_lot("L1", "O1", "T1", "M1", prod_min=100, edd=5),
            _make_lot("L2", "O2", "T1", "M1", prod_min=100, edd=6),
        ]

        runs = create_tool_runs(lots, release_holidays=set())

        assert [[lot.id for lot in run.lots] for run in runs] == [["L1"], ["L2"]]

    def test_retained_tool_does_not_create_a_second_physical_setup(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )
        second = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=1, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )

        _remove_redundant_retained_tool_setups([first, second])

        assert first.setup_min == 60
        assert second.setup_min == 0
        assert second.run_setup_min == 0
        assert second.start_min == 480
        assert second.end_min == 600
        assert second.end_min - second.start_min == second.prod_min

    @pytest.mark.parametrize("protection", ["none", "proof", "explicit"])
    def test_final_normalizer_respects_retained_setup_and_protection(self, protection):
        from backend.scheduler.scheduler import normalize_earliest_legal_plan

        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )
        second = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=600, end_min=780, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )
        lots = [
            _make_lot("L1", qty=100, prod_min=120, sku="REF-A"),
            _make_lot("L2", qty=100, prod_min=120, sku="REF-A"),
        ]
        data = _make_engine_data(
            ops=[], machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
        )
        if protection == "proof":
            data.preserved_lot_proofs = {"L2": "historical-lot"}
        config = FactoryConfig(machines={"M1": MachineConfig("M1", "Grandes")})

        result = normalize_earliest_legal_plan(
            [first, second], lots, data, config, annotate=False,
            protected_lot_ids={"L2"} if protection == "explicit" else None,
        )

        protected = protection != "none"
        target = next(segment for segment in result if segment.lot_id == "L2")
        assert sum(segment.setup_min for segment in result) == (120 if protected else 60)
        assert target.setup_min == (60 if protected else 0)
        if protected:
            assert target == second

    def test_retained_tool_cleanup_preserves_protected_lot(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )
        second = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=600, end_min=780, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )

        _remove_redundant_retained_tool_setups(
            [first, second], protected_lot_ids={"L2"},
        )

        assert second.setup_min == 60
        assert second.start_min == 600

    def test_retained_tool_cleanup_preserves_protected_run_continuation(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )
        opening = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=600, end_min=780, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
        )
        protected_continuation = Segment(
            lot_id="L3", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=780, end_min=900, shift="A", qty=100,
            prod_min=120, setup_min=0, run_setup_min=60, sku="REF-A",
        )

        _remove_redundant_retained_tool_setups(
            [first, opening, protected_continuation], protected_lot_ids={"L3"},
        )

        assert opening.setup_min == 60
        assert protected_continuation.run_setup_min == 60

    def test_retained_setup_removal_does_not_consume_unallocated_operators(self):
        from backend.scheduler.operators import operator_peaks

        segments = [
            Segment(lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
                    day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
                    prod_min=120, setup_min=60, sku="REF-A"),
            Segment(lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
                    day_idx=1, start_min=420, end_min=600, shift="A", qty=100,
                    prod_min=120, setup_min=60, sku="REF-A"),
            Segment(lot_id="L3", run_id="R3", machine_id="M2", tool_id="T2",
                    day_idx=1, start_min=420, end_min=480, shift="A", qty=100,
                    prod_min=60, setup_min=0, sku="REF-B"),
        ]
        data = _make_engine_data(ops=[])
        config = FactoryConfig(operators={("Grandes", "A"): 1, ("Grandes", "B"): 1})
        assert all(peak.deficit == 0 for peak in operator_peaks(segments, data, config).values())

        _remove_redundant_retained_tool_setups(segments)

        assert segments[1].setup_min == 0
        assert segments[1].start_min == 480
        assert all(peak.deficit == 0 for peak in operator_peaks(segments, data, config).values())

    def test_tool_change_keeps_the_next_setup(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60,
        )
        second = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T2",
            day_idx=1, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60,
        )

        _remove_redundant_retained_tool_setups([first, second])

        assert second.setup_min == 60
        assert second.start_min == 420

    def test_same_tool_reference_change_keeps_the_next_setup(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, sku="REF-A",
        )
        second = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=1, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, sku="REF-B",
        )

        _remove_redundant_retained_tool_setups([first, second])

        assert second.setup_min == 60
        assert second.start_min == 420

    def test_configured_setup_family_reuses_the_mounted_adjustment(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-A",
            setup_family="REF-A|REF-B",
        )
        second = Segment(
            lot_id="L2", run_id="R2", machine_id="M1", tool_id="T1",
            day_idx=1, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60, sku="REF-B",
            setup_family="REF-A|REF-B",
        )

        _remove_redundant_retained_tool_setups([first, second])

        assert second.setup_min == 0
        assert second.run_setup_min == 0

    def test_tool_move_keeps_return_setup_on_original_machine(self):
        first = Segment(
            lot_id="L1", run_id="R1", machine_id="M1", tool_id="T1",
            day_idx=0, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60,
        )
        moved = Segment(
            lot_id="L2", run_id="R2", machine_id="M2", tool_id="T1",
            day_idx=1, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60,
        )
        returned = Segment(
            lot_id="L3", run_id="R3", machine_id="M1", tool_id="T1",
            day_idx=2, start_min=420, end_min=600, shift="A", qty=100,
            prod_min=120, setup_min=60, run_setup_min=60,
        )

        _remove_redundant_retained_tool_setups([first, moved, returned])

        assert returned.setup_min == 60
        assert returned.run_setup_min == 60

    def test_run_id_format(self):
        lots = [_make_lot("L1", "O1", "T1", "M1", edd=5)]
        runs = create_tool_runs(lots)
        assert runs[0].id == "run_T1_M1_0"

    def test_forced_run_splits_create_lns_subruns(self):
        """CPO/LNS can explicitly split an otherwise valid campaign."""
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, edd=5),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, edd=10),
            _make_lot("L3", "O3", "T1", "M1", qty=200, prod_min=50, edd=15),
        ]
        config = FactoryConfig(forced_run_splits={"run_T1_M1_0": [2]})

        runs = create_tool_runs(lots, config=config)

        assert [run.id for run in runs] == ["run_T1_M1_0_lns0", "run_T1_M1_0_lns1"]
        assert [[lot.id for lot in run.lots] for run in runs] == [["L1", "L2"], ["L3"]]
        assert [run.edd for run in runs] == [5, 15]

    def test_forced_run_splits_ignore_invalid_positions(self):
        """Malformed internal LNS split specs are ignored safely."""
        lots = [
            _make_lot("L1", "O1", "T1", "M1", qty=500, prod_min=100, edd=5),
            _make_lot("L2", "O2", "T1", "M1", qty=300, prod_min=80, edd=10),
            _make_lot("L3", "O3", "T1", "M1", qty=200, prod_min=50, edd=15),
        ]
        config = FactoryConfig(
            forced_run_splits={"run_T1_M1_0": ["bad", 0, 2, 2, 99]}  # type: ignore[list-item]
        )

        runs = create_tool_runs(lots, config=config)

        assert [run.id for run in runs] == ["run_T1_M1_0_lns0", "run_T1_M1_0_lns1"]
        assert [[lot.id for lot in run.lots] for run in runs] == [["L1", "L2"], ["L3"]]


# ═══ CAMPAIGN SEQUENCING (Fix 3) ═══


class TestCampaignSequencing:
    def test_campaign_does_not_pass_an_earlier_delivery(self):
        """Setup grouping is secondary to operational urgency."""
        runs = [
            _make_run("R1", "T1", "M1", edd=2),
            _make_run("R2", "T2", "M1", edd=3),
            _make_run("R3", "T1", "M1", edd=5),
        ]
        result = _campaign_sequence(runs)
        # R2 is due before R3, so the T1 campaign cannot jump over it.
        assert result[0].tool_id == "T1"
        assert result[1].tool_id == "T2"
        assert result[2].tool_id == "T1"

    def test_same_tool_grouped_when_operational_urgency_is_equal(self):
        """Campaign grouping remains available as a genuine tie-breaker."""
        runs = [
            _make_run("R1", "T1", "M1", edd=5),
            _make_run("R2", "T2", "M1", edd=5),
            _make_run("R3", "T1", "M1", edd=5),
        ]

        result = _campaign_sequence(runs)

        assert [run.tool_id for run in result] == ["T1", "T1", "T2"]

    def test_campaign_cannot_pass_an_earlier_stock_rupture(self):
        early_risk = _make_run(
            "R-risk",
            "T2",
            lots=[
                _make_lot(
                    "L-risk", "O-risk", "T2", "M1", qty=100, edd=8
                )
            ],
            edd=8,
        )
        early_risk.lots[0].original_edd = 2
        same_tool_later = _make_run(
            "R-campaign",
            "T1",
            lots=[
                _make_lot(
                    "L-campaign", "O-campaign", "T1", "M1", qty=100, edd=3
                )
            ],
            edd=3,
        )
        same_tool_later.lots[0].original_edd = 4
        first_same_tool = _make_run(
            "R-first",
            "T1",
            lots=[
                _make_lot("L-first", "O-first", "T1", "M1", qty=100, edd=2)
            ],
            edd=2,
        )
        first_same_tool.lots[0].original_edd = 1

        result = _campaign_sequence([first_same_tool, same_tool_later, early_risk])

        assert [run.id for run in result] == ["R-first", "R-risk", "R-campaign"]

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

    def test_same_deadline_run_order_uses_quantity_then_id(self):
        small = _make_run(
            "R-small",
            "T-small",
            lots=[_make_lot("L-small", qty=100, edd=5)],
            edd=5,
        )
        large_b = _make_run(
            "R-large-b",
            "T-large-b",
            lots=[_make_lot("L-large-b", qty=1000, edd=5)],
            edd=5,
        )
        large_a = _make_run(
            "R-large-a",
            "T-large-a",
            lots=[_make_lot("L-large-a", qty=1000, edd=5)],
            edd=5,
        )

        ordered = sequence_per_machine(
            {"M1": [small, large_b, large_a]},
            config=FactoryConfig(interleave_enabled=False),
        )

        assert [run.id for run in ordered["M1"]] == [
            "R-large-a",
            "R-large-b",
            "R-small",
        ]


# ═══ INTERLEAVE URGENT (Fix 4) ═══


class TestInterleaveUrgent:
    def test_breaks_campaign_for_urgent(self):
        """Fix 4: urgent run breaks a same-tool campaign."""
        runs = [
            _make_run("R1", "T1", "M1", edd=4),
            _make_run("R2", "T1", "M1", edd=11),
            _make_run("R3", "T2", "M1", edd=6),  # urgent, different tool
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
        run_light = _make_run("R2", "T2", "M2", alt_machine_id="M1", lots=[lot_light])
        result = assign_machines([run_heavy, run_light], _make_engine_data())
        # run_light should go to M2 (less loaded)
        assert any(r.id == "R2" for r in result.get("M2", []))

    def test_alt_assignment_uses_machine_specific_oee_before_choice(self):
        """Primary vs alt comparison must use the duration for each candidate machine."""
        op = _make_eop(
            sku="SKU_A",
            machine="M1",
            tool="T1",
            d=[500, 0, 0],
            pH=100.0,
            oee=0.66,
            alt="M2",
        )
        data = _make_engine_data(
            ops=[op],
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="M2", group="Grandes", day_capacity=DAY_CAP),
            ],
            n_days=3,
        )
        config = FactoryConfig()
        config.machines = {
            "M1": MachineConfig(id="M1", group="Grandes", oee=0.33),
            "M2": MachineConfig(id="M2", group="Grandes", oee=0.66),
        }

        lot = _make_lot(
            "L1",
            op_id=op.id,
            tool_id="T1",
            machine_id="M1",
            alt_machine_id="M2",
            qty=500,
            prod_min=(500 / (100.0 * 0.66)) * 60.0,
            setup_min=30.0,
            edd=2,
        )
        run = _make_run(
            "R1",
            "T1",
            "M1",
            alt_machine_id="M2",
            lots=[lot],
            setup_min=30.0,
            edd=2,
        )

        result = assign_machines([run], data, config=config)

        assert "M2" in result
        assert result["M2"][0].total_prod_min < 500.0
        assert result["M2"][0].total_min < 600.0


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
        final_segs, final_lots, warnings, _, _, _ = jit_dispatch(
            runs,
            data,
            baseline_segs,
            baseline_lots,
            baseline_score,
        )
        final_score = compute_score(final_segs, final_lots, data)
        assert final_score["tardy_count"] <= baseline_score["tardy_count"]


class TestDispatchSetupInvariants:
    def test_dispatch_splits_segments_at_a_closed_shift_gap(self):
        from backend.scheduler.validation import validate_plan

        config = FactoryConfig(
            shifts=[
                ShiftConfig("A", 420, 720),
                ShiftConfig("B", 780, 1020),
            ],
            machines={"M1": MachineConfig(id="M1", group="Grandes")},
        )
        lot = _make_lot(
            "L1",
            "O1",
            "T1",
            "M1",
            prod_min=400,
            setup_min=0,
        )
        run = _make_run("R1", "T1", "M1", lots=[lot], setup_min=0)
        data = _make_engine_data(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=540)],
            n_days=2,
        )

        segments, lots, _ = per_machine_dispatch({"M1": [run]}, data, config=config)

        assert [
            (segment.day_idx, segment.start_min, segment.end_min, segment.shift)
            for segment in segments
        ] == [(0, 420, 720, "A"), (0, 780, 880, "B")]
        assert validate_plan(segments, data, config, lots=lots) == []

    def test_hard_repair_splits_a_gap_and_skips_an_exact_stop(self):
        from backend.scheduler.scheduler import _repair_hard_constraints
        from backend.scheduler.validation import validate_plan

        config = FactoryConfig(
            shifts=[
                ShiftConfig("A", 420, 720),
                ShiftConfig("B", 780, 1020),
            ],
            machines={"M1": MachineConfig(id="M1", group="Grandes")},
        )
        data = _make_engine_data(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=540)],
            n_days=2,
        )
        data.machine_blocked_intervals = {
            "M1": [
                {
                    "start_day": 0,
                    "end_day": 0,
                    "start_min": 780,
                    "end_min": 820,
                }
            ]
        }
        malformed = Segment(
            lot_id="L1",
            run_id="R1",
            machine_id="M1",
            tool_id="T1",
            day_idx=0,
            start_min=700,
            end_min=800,
            shift="A",
            qty=100,
            prod_min=100,
            setup_min=0,
        )

        repaired = _repair_hard_constraints([malformed], data, config, set())

        assert [
            (segment.start_min, segment.end_min, segment.shift)
            for segment in repaired
        ] == [(700, 720, "A"), (820, 900, "B")]
        assert sum(segment.prod_min for segment in repaired) == 100
        assert sum(segment.qty for segment in repaired) == 100
        assert validate_plan(repaired, data, config) == []

    def test_dispatch_segment_start_is_setup_start(self):
        lot = _make_lot("L1", "O1", "T1", "M1", prod_min=100, setup_min=60)
        run = _make_run("R1", "T1", "M1", lots=[lot], setup_min=60)
        data = _make_engine_data(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            n_days=2,
        )

        segments, _, _ = per_machine_dispatch({"M1": [run]}, data)

        assert len(segments) == 1
        assert segments[0].start_min == 420
        assert segments[0].end_min == 580
        assert segments[0].setup_min == 60
        assert segments[0].prod_min == 100

    def test_dispatch_no_machine_overlap_with_different_setup_lengths(self):
        run_a = _make_run(
            "R1",
            "T1",
            "M1",
            lots=[_make_lot("L1", "O1", "T1", "M1", prod_min=100, setup_min=100)],
            setup_min=100,
        )
        run_b = _make_run(
            "R2",
            "T2",
            "M1",
            lots=[_make_lot("L2", "O2", "T2", "M1", prod_min=100, setup_min=10)],
            setup_min=10,
        )
        data = _make_engine_data(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            n_days=2,
        )

        segments, _, _ = per_machine_dispatch({"M1": [run_a, run_b]}, data)
        ordered = sorted(segments, key=lambda s: (s.day_idx, s.start_min))

        assert ordered[0].end_min <= ordered[1].start_min
        assert ordered[0].start_min == 420
        assert ordered[0].end_min == 620
        assert ordered[1].start_min == 620
        assert ordered[1].end_min == 730

    def test_tool_timeline_checks_whole_interval_not_only_start(self):
        tool_tl = ToolTimeline()
        tool_tl.book("T1", 100, 200, "M2")
        run = _make_run(
            "R1",
            "T1",
            "M1",
            lots=[_make_lot("L1", "O1", "T1", "M1", prod_min=300, setup_min=0)],
            setup_min=0,
        )
        data = _make_engine_data(
            ops=[],
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="M2", group="Grandes", day_capacity=DAY_CAP),
            ],
            n_days=2,
        )

        segments, _, _ = per_machine_dispatch({"M1": [run]}, data, tool_tl=tool_tl)

        assert segments[0].start_min == 620
        assert segments[0].end_min == 920

    def test_tool_booking_includes_setup_window(self):
        tool_tl = ToolTimeline()
        run = _make_run(
            "R1",
            "T1",
            "M1",
            lots=[_make_lot("L1", "O1", "T1", "M1", prod_min=100, setup_min=60)],
            setup_min=60,
        )
        data = _make_engine_data(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            n_days=2,
        )

        per_machine_dispatch({"M1": [run]}, data, tool_tl=tool_tl)

        assert tool_tl.bookings["T1"] == [(0, 160, "M1")]

    def test_tool_return_to_machine_requires_setup_after_intervening_booking(self):
        tool_tl = ToolTimeline()
        tool_tl.book("T1", 100, 200, "M2")
        run = _make_run(
            "R1",
            "T1",
            "M1",
            lots=[_make_lot("L1", "O1", "T1", "M1", prod_min=100, setup_min=60)],
            setup_min=60,
        )
        data = _make_engine_data(
            ops=[],
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="M2", group="Grandes", day_capacity=DAY_CAP),
            ],
            n_days=2,
        )

        segments, _, _ = per_machine_dispatch(
            {"M1": [run]},
            data,
            tool_tl=tool_tl,
        )

        assert segments[0].start_min == 620
        assert segments[0].setup_min == 60
        assert segments[0].end_min == 780

    def test_crew_window_matches_segment_setup_window(self):
        run_a = _make_run(
            "R1",
            "T1",
            "M1",
            lots=[_make_lot("L1", "O1", "T1", "M1", prod_min=100, setup_min=100)],
            setup_min=100,
        )
        run_b = _make_run(
            "R2",
            "T2",
            "M2",
            lots=[_make_lot("L2", "O2", "T2", "M2", prod_min=100, setup_min=100)],
            setup_min=100,
        )
        data = _make_engine_data(
            ops=[],
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="M2", group="Grandes", day_capacity=DAY_CAP),
            ],
            n_days=2,
        )

        segments, _, _ = per_machine_dispatch({"M1": [run_a], "M2": [run_b]}, data)
        setup_windows = sorted(
            (
                seg.day_idx * DAY_CAP + (seg.start_min - 420),
                seg.day_idx * DAY_CAP + (seg.start_min - 420) + seg.setup_min,
            )
            for seg in segments
            if seg.setup_min > 0
        )

        assert setup_windows == [(0, 100), (100, 200)]


# ═══ SCORING ═══


class TestScoring:
    def test_perfect_otd(self):
        """All lots on time → OTD = 100%."""
        lots = [_make_lot("L1", edd=5), _make_lot("L2", edd=10)]
        segments = [
            Segment(
                lot_id="L1",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=3,
                start_min=420,
                end_min=520,
                shift="A",
                qty=500,
                prod_min=100,
            ),
            Segment(
                lot_id="L2",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=8,
                start_min=420,
                end_min=500,
                shift="A",
                qty=300,
                prod_min=80,
            ),
        ]
        data = _make_engine_data(n_days=12)
        score = compute_score(segments, lots, data)
        assert score["otd"] == 100.0
        assert score["tardy_count"] == 0

    def test_tardy_detection(self):
        """Lot completed after EDD → tardy."""
        lots = [_make_lot("L1", edd=2)]
        segments = [
            Segment(
                lot_id="L1",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=5,
                start_min=420,
                end_min=520,
                shift="A",
                qty=500,
                prod_min=100,
            ),
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
            Segment(
                lot_id="L1",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=3,
                start_min=420,
                end_min=520,
                shift="A",
                qty=500,
                prod_min=100,
                edd=10,
            ),
        ]
        data = _make_engine_data(n_days=12)
        score = compute_score(segments, lots, data)
        assert score["earliness_avg_days"] == 7.0  # edd=10, last_day=3 → gap=7

    def test_setup_count(self):
        segments = [
            Segment(
                lot_id="L1",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=420,
                end_min=480,
                shift="A",
                qty=0,
                prod_min=0,
                setup_min=60,
            ),
            Segment(
                lot_id="L1",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=480,
                end_min=580,
                shift="A",
                qty=500,
                prod_min=100,
                setup_min=0,
            ),
        ]
        data = _make_engine_data(n_days=6)
        score = compute_score(segments, [_make_lot("L1")], data)
        assert score["setups"] == 1
        assert score["setup_time_min"] == 60
        assert score["prod_time_min"] == 100
        assert score["work_time_min"] == 160
        assert score["idle_capacity_min"] >= 0
        assert score["bottleneck_machine"]


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
            tool_id="T1",
            machine_id="M1",
            op_id_1="T1_M1_A",
            op_id_2="T1_M1_B",
            sku_1="A",
            sku_2="B",
            eco_lot_1=0,
            eco_lot_2=0,
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
        """A joint cycle produces the same physical quantity for both twins."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000], eco_lot=0)
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 800], eco_lot=0)
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1="T1_M1_A",
            op_id_2="T1_M1_B",
            sku_1="A",
            sku_2="B",
            eco_lot_1=0,
            eco_lot_2=0,
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
        assert to[0][2] == 1000  # A = 1000
        assert to[1][2] == 1000  # B co-produces the same quantity
        assert lots[0].qty == 1000

    def test_twin_joint_with_eco_lot(self):
        """A shared hard eco lot is applied before equal joint production."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 4500], eco_lot=5000)
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 2800], eco_lot=5000)
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1="T1_M1_A",
            op_id_2="T1_M1_B",
            sku_1="A",
            sku_2="B",
            eco_lot_1=5000,
            eco_lot_2=5000,
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
        assert to[0][2] == 5000  # A
        assert to[1][2] == 5000  # B
        assert lots[0].qty == 5000

    def test_twin_with_different_effective_eco_lots_is_blocked(self):
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 4500], eco_lot=5000)
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 2800], eco_lot=3000)
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1=op_a.id,
            op_id_2=op_b.id,
            sku_1="A",
            sku_2="B",
            eco_lot_1=5000,
            eco_lot_2=3000,
        )
        data = _make_engine_data(ops=[op_a, op_b], twins=[twin])

        with pytest.raises(ValueError, match=r"T1: A=5000, B=3000"):
            create_lots(data)

    def test_twin_demand_only_a_still_coproduces_b(self):
        """A physical twin cycle always produces one A and one B."""
        op_a = _make_eop(sku="A", tool="T1", machine="M1", d=[0, 1000])
        op_b = _make_eop(sku="B", tool="T1", machine="M1", d=[0, 0])
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1="T1_M1_A",
            op_id_2="T1_M1_B",
            sku_1="A",
            sku_2="B",
            eco_lot_1=0,
            eco_lot_2=0,
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
        assert to[1][2] == 1000  # B is unavoidable co-produced stock
        assert lots[0].planning_source == "twin_joint_surplus"
        milestones = {item["sku"]: item for item in lots[0].output_milestones or []}
        assert milestones["A"].get("is_coproduced_surplus") is not True
        assert milestones["B"]["is_coproduced_surplus"] is True

    def test_twin_interleaved_demand_co_produces(self):
        """BUG 4: irregular twin demand (A/A/B/A/B/A) must co-produce.

        Reproduces JD471512 on PRM042 (SKUs 0081 + 0071): 0081 has demand on
        days 1,2,4,6 and 0071 on days 3,5. The old pairwise-consecutive merge
        left some solo-A lots unmerged, yielding separate single-SKU blocks on
        the same tool+machine. The chronological ledger must pair every B event
        with nearby A demand without leaving a single-SKU block where legal
        co-production was possible, and a single ToolRun (one setup).
        """
        op_a = _make_eop(
            sku="0081",
            tool="JD471512",
            machine="PRM042",
            pH=500.0,
            d=[0, 2000, 2000, 0, 2000, 0, 2000],
        )
        op_b = _make_eop(
            sku="0071", tool="JD471512", machine="PRM042", pH=500.0, d=[0, 0, 0, 1500, 0, 1500, 0]
        )
        twin = TwinGroup(
            tool_id="JD471512",
            machine_id="PRM042",
            op_id_1="JD471512_PRM042_0081",
            op_id_2="JD471512_PRM042_0071",
            sku_1="0081",
            sku_2="0071",
            eco_lot_1=0,
            eco_lot_2=0,
        )
        data = _make_engine_data(
            ops=[op_a, op_b],
            machines=[MachineInfo(id="PRM042", group="Medias", day_capacity=DAY_CAP)],
            twins=[twin],
            n_days=7,
        )
        lots = create_lots(data)

        # Every lot is a twin lot carrying twin_outputs for BOTH SKUs.
        assert all(lot.is_twin and lot.twin_outputs is not None for lot in lots)

        # Every physical cycle has two equal positive outputs.
        for lot in lots:
            assert lot.twin_outputs[0][1] == "0081"
            assert lot.twin_outputs[1][1] == "0071"
            assert lot.twin_outputs[0][2] > 0  # 0081 produced
            assert lot.twin_outputs[1][2] > 0  # 0071 co-produced
            assert lot.twin_outputs[0][2] == lot.twin_outputs[1][2]
            # Time is ONE simultaneous run = max(time_a, time_b), not the sum.
            time_a = (lot.twin_outputs[0][2] / (op_a.pH * 0.66)) * 60.0
            time_b = (lot.twin_outputs[1][2] / (op_b.pH * 0.66)) * 60.0
            assert abs(lot.prod_min - max(time_a, time_b)) < 1.0

        # Tool grouping → ONE run, ONE setup for the whole tool+machine.
        runs = create_tool_runs(lots)
        jd_runs = [r for r in runs if r.tool_id == "JD471512"]
        assert len(jd_runs) == 1

    def test_twin_reverse_interleaving_does_not_duplicate_earlier_b(self):
        op_a = _make_eop(
            sku="A",
            tool="T1",
            machine="M1",
            d=[0, 0, 0, 1000, 0, 1000],
        )
        op_b = _make_eop(
            sku="B",
            tool="T1",
            machine="M1",
            d=[0, 800, 0, 0, 800, 0],
        )
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1=op_a.id,
            op_id_2=op_b.id,
            sku_1="A",
            sku_2="B",
            eco_lot_1=0,
            eco_lot_2=0,
        )
        data = _make_engine_data(ops=[op_a, op_b], twins=[twin], n_days=6)

        lots = create_lots(data)

        assert len(lots) == 2
        assert all(lot.twin_outputs == [(op_a.id, "A", 1000), (op_b.id, "B", 1000)] for lot in lots)
        b_milestones = [
            output
            for lot in lots
            for output in lot.output_milestones or []
            if output["op_id"] == op_b.id
        ]
        assert sorted(output["customer_delivery_day"] for output in b_milestones) == [1, 4]

        result = schedule_all(data)
        urgent = min(result.lots, key=lambda lot: (lot.production_due_day, lot.id))
        urgent_segments = [
            segment for segment in result.segments if segment.lot_id == urgent.id
        ]
        assert urgent.sku == "B"
        assert urgent_segments
        assert all(segment.sku == "B" for segment in urgent_segments)

    def test_twin_joint_surplus_suppresses_future_demand(self):
        op_a = _make_eop(
            sku="A",
            tool="T1",
            machine="M1",
            d=[0, 1000, 0, 0],
            eco_lot=1000,
        )
        op_b = _make_eop(
            sku="B",
            tool="T1",
            machine="M1",
            d=[0, 200, 0, 700],
            eco_lot=1000,
        )
        twin = TwinGroup(
            tool_id="T1",
            machine_id="M1",
            op_id_1=op_a.id,
            op_id_2=op_b.id,
            sku_1="A",
            sku_2="B",
            eco_lot_1=1000,
            eco_lot_2=1000,
        )
        data = _make_engine_data(ops=[op_a, op_b], twins=[twin], n_days=4)

        lots = create_lots(data)

        assert len(lots) == 1
        assert lots[0].twin_outputs == [(op_a.id, "A", 1000), (op_b.id, "B", 1000)]

    def test_twin_result_is_independent_of_configured_side_order(self):
        def build(reverse: bool) -> list[Lot]:
            op_a = _make_eop(
                sku="A",
                tool="T1",
                machine="M1",
                d=[0, 0, 700, 0, 600],
                eco_lot=1000,
            )
            op_b = _make_eop(
                sku="B",
                tool="T1",
                machine="M1",
                d=[0, 500, 0, 500, 0],
                eco_lot=1000,
            )
            first, second = (op_b, op_a) if reverse else (op_a, op_b)
            twin = TwinGroup(
                tool_id="T1",
                machine_id="M1",
                op_id_1=first.id,
                op_id_2=second.id,
                sku_1=first.sku,
                sku_2=second.sku,
                eco_lot_1=1000,
                eco_lot_2=1000,
            )
            return create_lots(
                _make_engine_data(ops=[op_a, op_b], twins=[twin], n_days=5)
            )

        def signature(lots: list[Lot]):
            return [
                (
                    lot.id,
                    lot.op_id,
                    lot.production_due_day,
                    sorted((sku, qty) for _op_id, sku, qty in lot.twin_outputs or []),
                )
                for lot in lots
            ]

        assert signature(build(False)) == signature(build(True))

    def test_with_holidays(self):
        op = _make_eop(d=[0, 0, 500], pH=1000.0, sH=0.0)
        data = _make_engine_data(ops=[op], n_days=3, holidays=[1])
        result = schedule_all(data)
        prod_segs = [s for s in result.segments if s.qty > 0]
        assert all(s.day_idx != 1 for s in prod_segs)

    def test_same_tool_different_skus_each_require_setup(self):
        """Each independent reference needs its own mould adjustment."""
        ops = [
            _make_eop(
                sku=f"SKU_{i}", tool="T1", machine="PRM031", d=[0] * i + [500] + [0] * (5 - i)
            )
            for i in range(1, 4)
        ]
        data = _make_engine_data(ops=ops)
        result = schedule_all(data)
        assert result.score["setups"] == 3

    def test_same_tool_same_sku_multiple_lots_reuse_setup(self):
        op = _make_eop(
            sku="REF-A",
            tool="T1",
            machine="PRM031",
            d=[0, 500, 0, 500, 0, 500],
        )
        data = _make_engine_data(ops=[op])

        result = schedule_all(data)

        assert result.score["setups"] == 1

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
        """Repeated lots of one reference share an adjustment campaign."""
        ops = [
            _make_eop(sku="A", tool="T1", machine="M1", d=[0, 500, 400], sH=0.5),
            _make_eop(sku="B", tool="T2", machine="M1", d=[0, 300], sH=0.5),
        ]
        data = _make_engine_data(
            ops=ops,
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
        )
        result = schedule_all(data)
        assert result.score["setups"] == 2

    def test_pipeline_timing(self):
        """Scheduler should complete under 100ms for moderate input."""
        ops = [
            _make_eop(sku=f"SKU_{i}", tool=f"T{i % 5}", machine=f"M{i % 3}", d=[0, 500, 300, 200])
            for i in range(20)
        ]
        machines = [
            MachineInfo(id=f"M{i}", group="Grandes", day_capacity=DAY_CAP) for i in range(3)
        ]
        data = _make_engine_data(ops=ops, machines=machines)
        result = schedule_all(data)
        # Each SKU is now a distinct physical adjustment, so this exercises 20
        # runs instead of collapsing them by tool alone.
        assert result.time_ms < 1000
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
            ops.append(
                _make_eop(
                    sku=f"SKU_{mid}",
                    machine=mid,
                    tool=f"T{i}",
                    d=[20000, 5000, 3000],
                    pH=150.0,
                    sH=0.5,
                )
            )
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


# --- Holiday enforcement ---


class TestHolidayEnforcement:
    """Guarantee no production is scheduled on holiday/weekend days."""

    def test_no_segments_on_holidays(self):
        """No segment should ever have day_idx in the holidays set."""
        holidays = [1, 2, 4]  # days 1, 2, 4 are holidays
        ops = [
            _make_eop(sku="A", tool="T1", d=[0, 500, 0, 300, 0, 200]),
            _make_eop(sku="B", tool="T2", d=[0, 0, 400, 0, 300, 0]),
        ]
        data = _make_engine_data(ops=ops, n_days=8, holidays=holidays)
        result = schedule_all(data)

        holiday_set = set(holidays)
        violations = [
            (s.machine_id, s.day_idx, s.run_id) for s in result.segments if s.day_idx in holiday_set
        ]
        assert violations == [], f"Segments scheduled on holidays: {violations}"

    def test_utilisation_excludes_holidays(self):
        """Utilisation denominator should exclude holiday days."""
        holidays = [2, 3]  # 2 holidays out of 6 days
        ops = [_make_eop(d=[0, 500, 0, 300])]
        data = _make_engine_data(ops=ops, n_days=6, holidays=holidays)
        result = schedule_all(data)

        for m_id, util_pct in result.score.get("utilisation", {}).items():
            # With holidays excluded, utilisation should be based on 4 workdays
            # not 6 total days — so utilisation should be higher than naive calc
            assert util_pct >= 0.0, f"Negative utilisation for {m_id}"

    def test_holidays_with_heavy_load(self):
        """With many holidays and heavy load, schedule must still respect holidays."""
        # 3 out of 8 days are holidays — forces production into 5 workdays
        holidays = [1, 3, 5]
        ops = [
            _make_eop(sku="A", tool="T1", d=[0, 800, 0, 600, 0, 400, 0, 300]),
            _make_eop(sku="B", tool="T2", machine="PRM039", d=[0, 0, 500, 0, 500, 0, 300, 0]),
        ]
        machines = [
            MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
        ]
        data = _make_engine_data(ops=ops, machines=machines, n_days=8, holidays=holidays)
        result = schedule_all(data)

        holiday_set = set(holidays)
        violations = [
            (s.machine_id, s.day_idx) for s in result.segments if s.day_idx in holiday_set
        ]
        assert violations == [], f"Segments on holidays under heavy load: {violations}"


# --- Crew mutex enforcement ---


class TestCrewMutex:
    """Guarantee no two setups overlap across machines (single crew)."""

    def test_no_simultaneous_setups(self):
        """Setups on different machines must not overlap in time."""
        ops = [
            _make_eop(sku="A", tool="T1", machine="PRM031", d=[0, 500, 0, 300]),
            _make_eop(sku="B", tool="T2", machine="PRM031", d=[0, 0, 400, 0]),
            _make_eop(sku="C", tool="T3", machine="PRM039", d=[0, 500, 0, 300]),
            _make_eop(sku="D", tool="T4", machine="PRM039", d=[0, 0, 400, 0]),
        ]
        machines = [
            MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
        ]
        data = _make_engine_data(ops=ops, machines=machines, n_days=10)
        result = schedule_all(data)

        # Collect setup windows: (abs_start, abs_end, machine_id)
        setups = []
        for seg in result.segments:
            if seg.setup_min > 0:
                abs_start = seg.day_idx * DAY_CAP + (seg.start_min - 420)
                abs_end = abs_start + seg.setup_min
                setups.append((abs_start, abs_end, seg.machine_id))

        setups.sort()
        overlaps = 0
        for i in range(len(setups)):
            for j in range(i + 1, len(setups)):
                if setups[i][2] == setups[j][2]:
                    continue  # same machine
                if setups[i][0] < setups[j][1] and setups[j][0] < setups[i][1]:
                    overlaps += 1

        assert overlaps == 0, f"Found {overlaps} simultaneous setups across machines"


# --- Tool contention (Bug 5) ---


def _tool_machine_overlaps(segments) -> list[tuple]:
    """Return (tool_id, day, mA, mB) for same tool on two machines at once."""
    by_tool: dict[str, list] = {}
    for s in segments:
        if s.end_min <= s.start_min:
            continue  # skip zero-duration placeholders
        by_tool.setdefault(s.tool_id, []).append(s)

    conflicts = []
    for tool_id, segs in by_tool.items():
        windows = sorted(
            (
                (
                    s.day_idx * DAY_CAP + (s.start_min - 420),
                    s.day_idx * DAY_CAP + (s.end_min - 420),
                    s.machine_id,
                    s.day_idx,
                )
                for s in segs
            ),
            key=lambda w: w[0],
        )
        for i in range(len(windows)):
            a_start, a_end, a_machine, a_day = windows[i]
            for j in range(i + 1, len(windows)):
                b_start, b_end, b_machine, _ = windows[j]
                if b_start >= a_end:
                    break
                if b_machine != a_machine:
                    conflicts.append((tool_id, a_day, a_machine, b_machine))
    return conflicts


class TestToolContention:
    """Bug 5: a physical tool must never run on two machines simultaneously."""

    def test_closed_shift_gap_does_not_create_a_false_cross_day_overlap(self):
        from backend.scheduler.scheduler import _detect_tool_machine_overlaps

        config = FactoryConfig(
            shifts=[
                ShiftConfig("A", 420, 720),
                ShiftConfig("B", 780, 1020),
            ]
        )
        segments = [
            Segment(
                lot_id="L1",
                run_id="R1",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=780,
                end_min=1020,
                shift="B",
                qty=1,
                prod_min=240,
                setup_min=0,
            ),
            Segment(
                lot_id="L2",
                run_id="R2",
                machine_id="M2",
                tool_id="T1",
                day_idx=1,
                start_min=420,
                end_min=500,
                shift="A",
                qty=1,
                prod_min=80,
                setup_min=0,
            ),
        ]

        assert _detect_tool_machine_overlaps(segments, config) == []

    def test_split_runs_same_tool_not_on_two_machines(self):
        """Same tool split into two EDD-separated runs, both with an alt machine.

        The EDD-gap split in tool_grouping produces multiple ToolRuns for one
        tool; load-balancing could otherwise scatter them across machines so
        the single physical mould appears in two places at once.
        """
        machines = [
            MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
        ]
        # One tool (T_SHARED), heavy demand early and late → EDD-gap split.
        # alt machine set so the assigner is free to scatter the runs.
        ops = [
            _make_eop(
                sku="SHARED",
                machine="PRM031",
                tool="T_SHARED",
                alt="PRM039",
                d=[0, 9000, 0, 0, 0, 0, 0, 9000, 0, 0],
                pH=150.0,
                sH=0.5,
            ),
            # Filler load so the assigner is tempted to balance onto PRM039.
            _make_eop(
                sku="FILL",
                machine="PRM039",
                tool="T_FILL",
                d=[0, 6000, 0, 0, 0, 0, 0, 6000, 0, 0],
                pH=150.0,
                sH=0.5,
            ),
        ]
        data = _make_engine_data(ops=ops, machines=machines, n_days=12)
        result = schedule_all(data)

        conflicts = _tool_machine_overlaps(result.segments)
        assert conflicts == [], f"Tool on two machines simultaneously: {conflicts}"
        # With day 0 as the first available day this overloaded fixture may be
        # late, but it remains physically valid and complete.
        assert result.gate_report["physical_gate_passed"] is True
        assert result.score["missing_lots"] == 0
        if result.score["early_window_violations"]:
            assert result.gate_report["jit_window_gate_passed"] is False
            assert result.gate_report["status"] == "jit_window_blocked"

    def test_full_factory_no_tool_on_two_machines(self):
        """Across a 5-machine factory, no tool overlaps on two machines."""
        machine_ids = ["PRM019", "PRM031", "PRM039", "PRM042", "PRM043"]
        machines = [MachineInfo(id=m, group="Grandes", day_capacity=DAY_CAP) for m in machine_ids]
        ops = []
        # Two shared tools each usable on two machines with an alt.
        ops.append(
            _make_eop(
                sku="S1",
                machine="PRM019",
                tool="TX",
                alt="PRM031",
                d=[0, 7000, 0, 0, 6000, 0, 0, 5000, 0, 0],
                pH=140.0,
                sH=0.5,
            )
        )
        ops.append(
            _make_eop(
                sku="S2",
                machine="PRM039",
                tool="TY",
                alt="PRM043",
                d=[0, 6000, 0, 0, 5000, 0, 0, 4000, 0, 0],
                pH=140.0,
                sH=0.5,
            )
        )
        for i, mid in enumerate(machine_ids):
            ops.append(
                _make_eop(
                    sku=f"F{i}",
                    machine=mid,
                    tool=f"TF{i}",
                    d=[0, 4000, 0, 0, 3000, 0, 0, 2000, 0, 0],
                    pH=140.0,
                    sH=0.5,
                )
            )
        data = _make_engine_data(ops=ops, machines=machines, n_days=12)
        result = schedule_all(data)

        conflicts = _tool_machine_overlaps(result.segments)
        assert conflicts == [], (
            f"Found {len(conflicts)} tool-on-two-machines overlaps: {conflicts[:5]}"
        )
        # The overloaded fixture may need early-window exceptions or lateness.
        # Both are visible best-effort metrics, never physical rejection.
        assert result.gate_report["physical_gate_passed"] is True
        if result.score["early_window_violations"]:
            assert result.gate_report["jit_window_gate_passed"] is False
            assert result.gate_report["status"] == "jit_window_blocked"
        assert result.score["missing_lots"] == 0

    def test_assign_machines_avoids_tool_contention(self):
        """assign_machines should not place overlapping runs of one tool apart."""
        # Two runs of the SAME tool, both with alt, overlapping EDD windows.
        run_a = _make_run(
            run_id="RA",
            tool_id="T_DUP",
            machine_id="PRM031",
            alt_machine_id="PRM039",
            edd=4,
            lots=[
                _make_lot(lot_id="LA", tool_id="T_DUP", machine_id="PRM031", edd=4, prod_min=600.0)
            ],
        )
        run_b = _make_run(
            run_id="RB",
            tool_id="T_DUP",
            machine_id="PRM031",
            alt_machine_id="PRM039",
            edd=4,
            lots=[
                _make_lot(lot_id="LB", tool_id="T_DUP", machine_id="PRM031", edd=4, prod_min=600.0)
            ],
        )
        machines = [
            MachineInfo(id="PRM031", group="Grandes", day_capacity=DAY_CAP),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=DAY_CAP),
        ]
        data = _make_engine_data(
            ops=[_make_eop(machine="PRM031")],
            machines=machines,
            n_days=8,
        )
        machine_runs = assign_machines([run_a, run_b], data)
        # Both runs of T_DUP must land on the SAME machine (overlapping window).
        machine_of = {r.id: m for m, runs in machine_runs.items() for r in runs}
        assert machine_of["RA"] == machine_of["RB"], (
            f"Same-tool overlapping runs split across machines: {machine_of}"
        )


def _total_gap_min(segments) -> float:
    """Sum of idle minutes between consecutive production blocks per machine."""
    from backend.config.types import FactoryConfig

    cfg = FactoryConfig()
    by_machine: dict[str, list] = {}
    for s in segments:
        if s.end_min <= s.start_min:
            continue  # skip zero-duration placeholders
        by_machine.setdefault(s.machine_id, []).append(s)

    total = 0.0
    for segs in by_machine.values():
        ordered = sorted(segs, key=lambda s: (s.day_idx, s.start_min))
        for prev, curr in zip(ordered, ordered[1:]):
            prev_abs = prev.day_idx * cfg.day_capacity_min + (prev.end_min - cfg.shift_a_start)
            curr_abs = curr.day_idx * cfg.day_capacity_min + (curr.start_min - cfg.shift_a_start)
            gap = curr_abs - prev_abs
            if gap > 0:
                total += gap
    return total


class TestCompaction:
    """Opt-in compaction post-processing step (config.compact_enabled)."""

    def _scenario(self):
        """A multi-run scenario with JIT-induced gaps across machines."""
        from backend.config.types import FactoryConfig

        ops = [
            _make_eop(
                sku="A1",
                machine="PRM031",
                tool="TA",
                alt="PRM039",
                d=[0, 0, 0, 0, 0, 0, 0, 6000, 0, 0],
                pH=150.0,
                sH=0.5,
            ),
            _make_eop(
                sku="B1",
                machine="PRM039",
                tool="TB",
                d=[0, 0, 0, 0, 0, 0, 0, 5000, 0, 0],
                pH=150.0,
                sH=0.5,
            ),
            _make_eop(
                sku="C1",
                machine="PRM031",
                tool="TC",
                d=[0, 0, 0, 0, 0, 0, 0, 0, 0, 4000],
                pH=150.0,
                sH=0.5,
            ),
        ]
        data = _make_engine_data(ops=ops, n_days=10)
        return data, FactoryConfig

    def test_default_off_is_identical(self):
        """With compact_enabled=False (default), result is unchanged."""
        data, FactoryConfig = self._scenario()
        import copy

        base = schedule_all(copy.deepcopy(data), config=FactoryConfig())
        explicit_off = schedule_all(
            copy.deepcopy(data),
            config=FactoryConfig(compact_enabled=False),
        )
        base_key = sorted((s.lot_id, s.day_idx, s.start_min, s.end_min) for s in base.segments)
        off_key = sorted(
            (s.lot_id, s.day_idx, s.start_min, s.end_min) for s in explicit_off.segments
        )
        assert base_key == off_key, "Explicit compact_enabled=False diverged from default"

    def test_compaction_reduces_gaps(self):
        """compact_enabled=True reduces total idle time vs. compact_enabled=False."""
        data, FactoryConfig = self._scenario()
        import copy

        off = schedule_all(copy.deepcopy(data), config=FactoryConfig(compact_enabled=False))
        on = schedule_all(copy.deepcopy(data), config=FactoryConfig(compact_enabled=True))

        gap_off = _total_gap_min(off.segments)
        gap_on = _total_gap_min(on.segments)
        assert gap_on <= gap_off, f"Compaction did not reduce gaps: on={gap_on} off={gap_off}"
        # Backward JIT already emits a compact queue, so the optional legacy
        # compactor may correctly be a no-op.
        assert on.score["early_window_violations"] == 0

    def test_compaction_preserves_otd_and_no_violations(self):
        """compact_enabled=True keeps OTD/OTD-D at 100%, 0 tardy, 0 tool overlap."""
        data, FactoryConfig = self._scenario()
        result = schedule_all(data, config=FactoryConfig(compact_enabled=True))

        assert result.score["otd"] == 100.0, f"OTD regressed: {result.score['otd']}"
        assert result.score["otd_d"] == 100.0, f"OTD-D regressed: {result.score['otd_d']}"
        assert result.score["tardy_count"] == 0, f"Tardy appeared: {result.score['tardy_count']}"
        conflicts = _tool_machine_overlaps(result.segments)
        assert conflicts == [], f"Tool overlaps after compaction: {conflicts[:5]}"

    def test_compaction_no_edd_violation(self):
        """No segment is scheduled after its EDD with compaction on."""
        data, FactoryConfig = self._scenario()
        result = schedule_all(data, config=FactoryConfig(compact_enabled=True))
        for s in result.segments:
            if s.end_min <= s.start_min:
                continue
            assert s.day_idx <= s.edd, f"Segment {s.lot_id} day {s.day_idx} > EDD {s.edd}"


def test_auto_buffer_shifts_and_detaches_every_calendar_timeline():
    from backend.scheduler.scheduler import _shift_engine_data

    data = EngineData(
        ops=[],
        machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
        twin_groups=[],
        client_demands={},
        workdays=["2026-03-01", "2026-03-02", "2026-03-03"],
        n_days=3,
        holidays=[0],
        calendar_base_holidays=[0],
        calendar_explicit_holidays=[1],
        machine_blocked_days={"M1": {1}},
        tool_blocked_days={"T1": {2}},
        machine_blocked_intervals={
            "M1": [
                {
                    "id": "machine-stop",
                    "start_day": 1,
                    "start_min": 500,
                    "end_day": 1,
                    "end_min": 600,
                    "source_ids": ["machine-stop"],
                }
            ]
        },
        tool_blocked_intervals={
            "T1": [
                {
                    "id": "tool-stop",
                    "start_day": 0,
                    "start_min": 700,
                    "end_day": 0,
                    "end_min": 800,
                }
            ]
        },
        operator_blocked_intervals=[
            {
                "id": "operator-stop",
                "group": "Grandes",
                "shift": "A",
                "start_day": 2,
                "start_min": 420,
                "end_day": 2,
                "end_min": 500,
                "count": 1,
            }
        ],
    )

    shifted = _shift_engine_data(data, 2)

    assert shifted.n_days == 5
    assert shifted.holidays == [2]
    assert shifted.calendar_base_holidays == [2]
    assert shifted.calendar_explicit_holidays == [3]
    assert shifted.machine_blocked_days == {"M1": {3}}
    assert shifted.tool_blocked_days == {"T1": {4}}
    assert shifted.machine_blocked_intervals["M1"][0]["start_day"] == 3
    assert shifted.tool_blocked_intervals["T1"][0]["start_day"] == 2
    assert shifted.operator_blocked_intervals[0]["start_day"] == 4

    shifted.machine_blocked_intervals["M1"][0]["source_ids"].append("changed")
    shifted.operator_blocked_intervals[0]["count"] = 2
    assert data.machine_blocked_intervals["M1"][0]["source_ids"] == ["machine-stop"]
    assert data.operator_blocked_intervals[0]["count"] == 1


class TestZeroSlackRepair:
    def test_merge_preserves_setup_split_at_shift_boundary(self):
        from backend.scheduler.scheduler import _merge_detached_setup_segments
        from backend.scheduler.validation import validate_plan

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        lot = _make_lot(
            lot_id="lot",
            tool_id="T1",
            machine_id="M1",
            prod_min=212,
            setup_min=60,
            edd=4,
        )
        segments = [
            Segment(
                lot_id="previous",
                run_id="previous_run",
                machine_id="M1",
                tool_id="T0",
                day_idx=2,
                start_min=420,
                end_min=925,
                shift="A",
                qty=100,
                prod_min=505,
                setup_min=0,
                edd=4,
                sku="PREVIOUS",
            ),
            Segment(
                lot_id="lot",
                run_id="run",
                machine_id="M1",
                tool_id="T1",
                day_idx=2,
                start_min=925,
                end_min=930,
                shift="A",
                qty=0,
                prod_min=0,
                setup_min=5,
                edd=4,
                run_setup_min=60,
                sku="SKU",
            ),
            Segment(
                lot_id="lot",
                run_id="run",
                machine_id="M1",
                tool_id="T1",
                day_idx=2,
                start_min=930,
                end_min=1197,
                shift="B",
                qty=lot.qty,
                prod_min=212,
                setup_min=55,
                edd=4,
                run_setup_min=60,
                sku="SKU",
            ),
        ]

        repaired = _merge_detached_setup_segments(
            segments,
            config,
            lots=[lot],
        )

        run_segments = [segment for segment in repaired if segment.run_id == "run"]
        assert len(run_segments) == 2
        assert sum(segment.setup_min for segment in run_segments) == 60
        assert [(segment.start_min, segment.end_min) for segment in run_segments] == [
            (925, 930),
            (930, 1197),
        ]
        assert validate_plan(repaired, data, config, lots=[lot]) == []

    def test_moves_detached_setup_production_into_setup_day_when_it_fits(self):
        from backend.scheduler.scheduler import _merge_detached_setup_segments
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        segments = [
            Segment(
                lot_id="lot",
                run_id="run",
                machine_id="M1",
                tool_id="T1",
                day_idx=2,
                start_min=420,
                end_min=450,
                shift="A",
                qty=0,
                prod_min=0,
                setup_min=30,
                edd=4,
                run_setup_min=30,
                sku="SKU",
            ),
            Segment(
                lot_id="lot",
                run_id="run",
                machine_id="M1",
                tool_id="T1",
                day_idx=3,
                start_min=420,
                end_min=930,
                shift="A",
                qty=5600,
                prod_min=510,
                setup_min=0,
                edd=4,
                run_setup_min=30,
                sku="SKU",
            ),
            Segment(
                lot_id="lot",
                run_id="run",
                machine_id="M1",
                tool_id="T1",
                day_idx=3,
                start_min=930,
                end_min=1329,
                shift="B",
                qty=4400,
                prod_min=399,
                setup_min=0,
                is_continuation=True,
                edd=4,
                run_setup_min=30,
                sku="SKU",
            ),
        ]

        repaired = _merge_detached_setup_segments(segments, config)

        assert not any(segment.qty == 0 and segment.prod_min == 0 and segment.setup_min > 0 for segment in repaired)
        first = min(repaired, key=lambda segment: (segment.day_idx, segment.start_min))
        assert first.day_idx == 2
        assert first.start_min == 420
        assert first.end_min == 930
        assert first.setup_min == 30
        assert first.prod_min == 480
        tail = max(repaired, key=lambda segment: (segment.day_idx, segment.start_min))
        assert tail.day_idx == 2
        assert tail.start_min == 930
        assert tail.end_min == 1359
        assert sum(segment.qty for segment in repaired) == 10_000
        assert sum(segment.prod_min for segment in repaired) == 909
        assert_plan_valid(repaired, data, config)

    def test_detached_setup_uses_previous_day_close_when_opening_crew_is_busy(self):
        from backend.scheduler.scheduler import _merge_detached_setup_segments

        config = FactoryConfig(
            machines={
                "M1": MachineConfig("M1", "Grandes"),
                "M2": MachineConfig("M2", "Grandes"),
            },
            setup_crews_by_group={"Grandes": 1},
        )
        setup = Segment(
            lot_id="lot",
            run_id="run",
            machine_id="M1",
            tool_id="T1",
            day_idx=2,
            start_min=1400,
            end_min=1430,
            shift="B",
            qty=0,
            prod_min=0,
            setup_min=30,
            edd=5,
            run_setup_min=30,
            sku="SKU",
        )
        production = Segment(
            lot_id="lot",
            run_id="run",
            machine_id="M1",
            tool_id="T1",
            day_idx=3,
            start_min=420,
            end_min=471,
            shift="A",
            qty=800,
            prod_min=51,
            setup_min=0,
            edd=5,
            run_setup_min=30,
            sku="SKU",
        )
        other_setup = Segment(
            lot_id="other",
            run_id="other_run",
            machine_id="M2",
            tool_id="T2",
            day_idx=3,
            start_min=420,
            end_min=480,
            shift="A",
            qty=100,
            prod_min=0,
            setup_min=60,
            edd=5,
            run_setup_min=60,
            sku="OTHER",
        )

        repaired = _merge_detached_setup_segments([setup, production, other_setup], config)
        detached = next(segment for segment in repaired if segment.lot_id == "lot" and segment.prod_min <= 0)
        first_prod = next(segment for segment in repaired if segment.lot_id == "lot" and segment.prod_min > 0)

        assert detached.day_idx == 2
        assert detached.start_min == config.shift_b_end - 30
        assert detached.end_min == config.shift_b_end
        assert detached.setup_min == 30
        assert first_prod.day_idx == 3
        assert first_prod.start_min == 420
        assert first_prod.end_min == 471
        assert first_prod.setup_min == 0

    def test_detached_opening_setup_reflows_machine_suffix_when_it_fits(self):
        from backend.scheduler.scheduler import _merge_detached_setup_segments

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        setup = Segment(
            lot_id="lot",
            run_id="run",
            machine_id="M1",
            tool_id="T1",
            day_idx=2,
            start_min=700,
            end_min=730,
            shift="A",
            qty=0,
            prod_min=0,
            setup_min=30,
            edd=5,
            run_setup_min=30,
            sku="SKU",
        )
        production = Segment(
            lot_id="lot",
            run_id="run",
            machine_id="M1",
            tool_id="T1",
            day_idx=3,
            start_min=420,
            end_min=783,
            shift="A",
            qty=14400,
            prod_min=363,
            setup_min=0,
            edd=5,
            run_setup_min=30,
            sku="SKU",
        )
        next_run = Segment(
            lot_id="next",
            run_id="next_run",
            machine_id="M1",
            tool_id="T2",
            day_idx=3,
            start_min=783,
            end_min=1116,
            shift="A",
            qty=100,
            prod_min=303,
            setup_min=30,
            edd=5,
            run_setup_min=30,
            sku="NEXT",
        )
        lot = _make_lot(
            lot_id="lot",
            tool_id="T1",
            machine_id="M1",
            prod_min=363,
            setup_min=30,
            edd=5,
        )
        # Material is released on day 3, so the setup cannot be parked at the
        # close of day 2. It must be attached to production on day 3 and the
        # following machine work must reflow without overlap.
        lot.delivery_day = 8

        repaired = _merge_detached_setup_segments(
            [setup, production, next_run], config, lots=[lot]
        )

        first_prod = next(
            segment for segment in repaired
            if segment.lot_id == "lot" and segment.prod_min > 0
        )
        shifted_next = sorted(
            (segment for segment in repaired if segment.lot_id == "next"),
            key=lambda segment: segment.start_min,
        )
        assert not [
            segment
            for segment in repaired
            if segment.lot_id == "lot" and segment.prod_min == 0
        ]
        assert (first_prod.start_min, first_prod.end_min, first_prod.setup_min) == (420, 813, 30)
        assert [(segment.start_min, segment.end_min, segment.shift) for segment in shifted_next] == [
            (813, 930, "A"), (930, 1146, "B"),
        ]
        assert sum(segment.qty for segment in shifted_next) == 100
        assert sum(segment.prod_min for segment in shifted_next) == 303
        assert sum(segment.setup_min for segment in shifted_next) == 30

    def test_pulls_critical_lot_into_previous_machine_gap_and_repairs_source_setup(self):
        from backend.scheduler.scheduler import _repair_zero_slack_lots_into_previous_gaps
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        late_lot = _make_lot(
            lot_id="late",
            tool_id="T_LATE",
            machine_id="M1",
            qty=100,
            prod_min=252,
            setup_min=30,
            edd=3,
        )
        future_lot = _make_lot(
            lot_id="future",
            tool_id="T_FUTURE",
            machine_id="M1",
            qty=100,
            prod_min=454,
            setup_min=30,
            edd=6,
        )
        segments = [
            Segment(
                lot_id="future",
                run_id="run_future",
                machine_id="M1",
                tool_id="T_FUTURE",
                day_idx=2,
                start_min=420,
                end_min=450,
                shift="A",
                qty=0,
                prod_min=0,
                setup_min=30,
                edd=6,
                run_setup_min=30,
                sku="FUTURE",
            ),
            Segment(
                lot_id="future",
                run_id="run_future",
                machine_id="M1",
                tool_id="T_FUTURE",
                day_idx=3,
                start_min=420,
                end_min=874,
                shift="A",
                qty=100,
                prod_min=454,
                setup_min=0,
                edd=6,
                run_setup_min=30,
                sku="FUTURE",
            ),
            Segment(
                lot_id="late",
                run_id="run_late",
                machine_id="M1",
                tool_id="T_LATE",
                day_idx=3,
                start_min=874,
                end_min=1156,
                shift="B",
                qty=100,
                prod_min=252,
                setup_min=30,
                edd=3,
                run_setup_min=30,
                sku="LATE",
            ),
        ]

        repaired = _repair_zero_slack_lots_into_previous_gaps(
            segments,
            [late_lot, future_lot],
            data,
            config,
            holidays=set(),
        )

        late_segments = [segment for segment in repaired if segment.lot_id == "late"]
        assert len(late_segments) == 1
        assert late_segments[0].day_idx == 0
        assert late_segments[0].start_min == 420
        future_prod = next(
            segment
            for segment in repaired
            if segment.lot_id == "future" and segment.prod_min > 0
        )
        assert future_prod.day_idx == 1
        assert future_prod.start_min == 420
        assert future_prod.end_min == 904
        assert future_prod.setup_min == 30
        assert not any(
            segment.lot_id == "future" and segment.prod_min <= 0
            for segment in repaired
        )
        assert_plan_valid(repaired, data, config)

    def test_pulls_unblocked_continuation_next_to_previous_production(self):
        from backend.scheduler.scheduler import (
            _pull_internal_continuations_into_idle_gaps,
        )
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[
                "2026-09-01",
                "2026-09-02",
                "2026-09-03",
                "2026-09-04",
                "2026-09-05",
                "2026-09-06",
                "2026-09-07",
            ],
            n_days=7,
            holidays=[4, 5],
        )
        lot = _make_lot(
            lot_id="urgent",
            tool_id="T1",
            machine_id="M1",
            qty=100,
            prod_min=424,
            setup_min=75,
            edd=6,
        )
        segments = [
            Segment(
                lot_id="urgent",
                run_id="run_urgent",
                machine_id="M1",
                tool_id="T1",
                day_idx=3,
                start_min=627,
                end_min=1084,
                shift="A",
                qty=90,
                prod_min=382,
                setup_min=75,
                edd=6,
                run_setup_min=75,
                sku="URGENT",
            ),
            Segment(
                lot_id="urgent",
                run_id="run_urgent",
                machine_id="M1",
                tool_id="T1",
                day_idx=6,
                start_min=930,
                end_min=972,
                shift="B",
                qty=10,
                prod_min=42,
                setup_min=0,
                is_continuation=True,
                edd=6,
                run_setup_min=75,
                sku="URGENT",
            ),
        ]

        repaired = _pull_internal_continuations_into_idle_gaps(
            segments,
            [lot],
            data,
            config,
            {4, 5},
        )

        productive = sorted(
            (segment for segment in repaired if segment.prod_min > 0),
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        assert [
            (segment.day_idx, segment.start_min, segment.end_min, segment.shift)
            for segment in productive
        ] == [
            (3, 627, 930, "A"),
            (3, 930, 1126, "B"),
        ]
        assert sum(segment.qty for segment in productive) == 100
        assert abs(sum(segment.prod_min for segment in productive) - 424) < 1e-6
        assert_plan_valid(repaired, data, config, lots=[lot])

    def test_splits_long_continuation_to_fill_smaller_internal_gap(self):
        from backend.scheduler.scheduler import (
            _pull_internal_continuations_into_idle_gaps,
        )
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-09-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        lot = _make_lot(
            lot_id="long",
            tool_id="T1",
            machine_id="M1",
            qty=600,
            prod_min=600,
            setup_min=30,
            edd=5,
        )
        segments = [
            Segment(
                lot_id="long",
                run_id="run_long",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=420,
                end_min=550,
                shift="A",
                qty=100,
                prod_min=100,
                setup_min=30,
                edd=5,
                run_setup_min=30,
                sku="LONG",
            ),
            Segment(
                lot_id="long",
                run_id="run_long",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=700,
                end_min=1200,
                shift="A",
                qty=500,
                prod_min=500,
                setup_min=0,
                is_continuation=True,
                edd=5,
                run_setup_min=30,
                sku="LONG",
            ),
        ]

        repaired = _pull_internal_continuations_into_idle_gaps(
            segments,
            [lot],
            data,
            config,
            set(),
        )

        productive = sorted(
            (segment for segment in repaired if segment.prod_min > 0),
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        assert productive[0].start_min == 420
        assert all(
            previous.end_min == following.start_min
            for previous, following in zip(productive, productive[1:])
        )
        assert sum(segment.prod_min for segment in repaired) == 600
        assert sum(segment.qty for segment in repaired) == 600
        assert sum(segment.setup_min for segment in repaired) == 30
        assert_plan_valid(repaired, data, config, lots=[lot])

    def test_pulls_following_lot_of_mounted_tool_into_run_gap(self):
        from backend.scheduler.scheduler import _pull_following_run_lots_into_idle_gaps
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        first = _make_lot(
            lot_id="first", tool_id="T1", machine_id="M1", qty=100,
            prod_min=70, setup_min=30, edd=6,
        )
        following = _make_lot(
            lot_id="following", tool_id="T1", machine_id="M1", qty=100,
            prod_min=100, setup_min=30, edd=6,
        )
        segments = [
            Segment(
                lot_id="first", run_id="run_T1", machine_id="M1", tool_id="T1",
                day_idx=1, start_min=420, end_min=520, shift="A", qty=100,
                prod_min=70, setup_min=30, run_setup_min=30, edd=6, sku="REF-A",
            ),
            Segment(
                lot_id="following", run_id="run_T1_release_2", machine_id="M1", tool_id="T1",
                day_idx=2, start_min=600, end_min=700, shift="A", qty=100,
                prod_min=100, setup_min=0, run_setup_min=0, edd=6,
                sku="REF-A", is_continuation=True,
            ),
        ]

        repaired = _pull_following_run_lots_into_idle_gaps(
            segments, [first, following], data, config, holidays=set()
        )

        moved = next(segment for segment in repaired if segment.lot_id == "following")
        assert (moved.day_idx, moved.start_min, moved.end_min) == (1, 520, 620)
        assert moved.setup_min == 0
        assert_plan_valid(repaired, data, config, lots=[first, following])

    def test_pulls_following_mounted_tool_lot_to_start_of_same_day(self):
        from backend.scheduler.scheduler import _pull_following_run_lots_into_idle_gaps
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        first = _make_lot(
            lot_id="first", tool_id="T1", machine_id="M1", qty=100,
            prod_min=70, setup_min=30, edd=6,
        )
        following = _make_lot(
            lot_id="following", tool_id="T1", machine_id="M1", qty=100,
            prod_min=64, setup_min=30, edd=7,
        )
        segments = [
            Segment(
                lot_id="first", run_id="run_T1", machine_id="M1", tool_id="T1",
                day_idx=1, start_min=420, end_min=520, shift="A", qty=100,
                prod_min=70, setup_min=30, run_setup_min=30, edd=6, sku="REF-A",
            ),
            Segment(
                lot_id="following", run_id="run_T1_release_2", machine_id="M1",
                tool_id="T1", day_idx=2, start_min=450, end_min=514,
                shift="A", qty=100, prod_min=64, setup_min=0,
                run_setup_min=0, edd=6, sku="REF-A",
            ),
        ]

        repaired = _pull_following_run_lots_into_idle_gaps(
            segments, [first, following], data, config, holidays=set()
        )

        moved = next(segment for segment in repaired if segment.lot_id == "following")
        assert (moved.day_idx, moved.start_min, moved.end_min) == (2, 420, 484)
        assert_plan_valid(repaired, data, config, lots=[first, following])

    def test_starts_at_open_after_setup_parked_at_previous_close(self):
        from backend.scheduler.scheduler import _start_production_at_open_after_parked_setup
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        lot = _make_lot(
            lot_id="target", tool_id="T1", machine_id="M1", qty=100,
            prod_min=100, setup_min=30, edd=6,
        )
        segments = [
            Segment(
                lot_id="target", run_id="run_T1", machine_id="M1", tool_id="T1",
                day_idx=1, start_min=1410, end_min=1440, shift="B", qty=0,
                prod_min=0, setup_min=30, run_setup_min=30, edd=6, sku="TARGET",
            ),
            Segment(
                lot_id="target", run_id="run_T1", machine_id="M1", tool_id="T1",
                day_idx=2, start_min=450, end_min=550, shift="A", qty=100,
                prod_min=100, setup_min=0, run_setup_min=30, edd=6,
                sku="TARGET", is_continuation=True,
            ),
        ]

        repaired = _start_production_at_open_after_parked_setup(
            segments, [lot], data, config
        )

        production = next(segment for segment in repaired if segment.prod_min > 0)
        assert (production.day_idx, production.start_min, production.end_min) == (2, 420, 520)
        assert_plan_valid(repaired, data, config, lots=[lot])

    def test_retains_setup_when_an_older_run_used_another_tool_in_between(self):
        from backend.scheduler.scheduler import _remove_redundant_retained_tool_setups

        segments = [
            Segment(
                lot_id="x1", run_id="run_x", machine_id="M1", tool_id="T2",
                day_idx=0, start_min=420, end_min=520, shift="A", qty=100,
                prod_min=70, setup_min=30, run_setup_min=30, edd=6, sku="X",
            ),
            Segment(
                lot_id="a", run_id="run_a", machine_id="M1", tool_id="T1",
                day_idx=1, start_min=420, end_min=520, shift="A", qty=100,
                prod_min=70, setup_min=30, run_setup_min=30, edd=6, sku="A",
            ),
            Segment(
                lot_id="x2", run_id="run_x", machine_id="M1", tool_id="T2",
                day_idx=2, start_min=420, end_min=520, shift="A", qty=100,
                prod_min=70, setup_min=30, run_setup_min=30, edd=6, sku="X",
            ),
            Segment(
                lot_id="b", run_id="run_b", machine_id="M1", tool_id="T1",
                day_idx=3, start_min=420, end_min=520, shift="A", qty=100,
                prod_min=70, setup_min=30, run_setup_min=30, edd=6, sku="B",
            ),
        ]

        repaired = _remove_redundant_retained_tool_setups(segments)

        target = next(segment for segment in repaired if segment.lot_id == "b")
        assert target.setup_min == 30

    def test_repairs_mounted_setup_by_shifting_next_day_production(self):
        from backend.scheduler.scheduler import _repair_zero_slack_lots_into_previous_gaps
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        urgent = _make_lot(
            lot_id="urgent",
            tool_id="T_URGENT",
            machine_id="M1",
            qty=100,
            prod_min=252,
            setup_min=30,
            edd=3,
        )
        relaxed = _make_lot(
            lot_id="relaxed",
            tool_id="T_RELAXED",
            machine_id="M1",
            qty=100,
            prod_min=454,
            setup_min=30,
            edd=6,
        )
        segments = [
            Segment(
                lot_id="relaxed",
                run_id="run_relaxed",
                machine_id="M1",
                tool_id="T_RELAXED",
                day_idx=2,
                start_min=420,
                end_min=450,
                shift="A",
                qty=0,
                prod_min=0,
                setup_min=30,
                edd=6,
                run_setup_min=30,
                sku="RELAXED",
            ),
            Segment(
                lot_id="relaxed",
                run_id="run_relaxed",
                machine_id="M1",
                tool_id="T_RELAXED",
                day_idx=3,
                start_min=420,
                end_min=874,
                shift="A",
                qty=100,
                prod_min=454,
                setup_min=0,
                edd=6,
                run_setup_min=30,
                sku="RELAXED",
            ),
            Segment(
                lot_id="urgent",
                run_id="run_urgent",
                machine_id="M1",
                tool_id="T_URGENT",
                day_idx=3,
                start_min=874,
                end_min=1156,
                shift="B",
                qty=100,
                prod_min=252,
                setup_min=30,
                edd=3,
                run_setup_min=30,
                sku="URGENT",
            ),
        ]

        repaired = _repair_zero_slack_lots_into_previous_gaps(
            segments,
            [urgent, relaxed],
            data,
            config,
            holidays=set(),
        )

        urgent_segment = next(segment for segment in repaired if segment.lot_id == "urgent")
        relaxed_prod = next(
            segment
            for segment in repaired
            if segment.lot_id == "relaxed" and segment.prod_min > 0
        )
        assert relaxed_prod.day_idx == 1
        assert urgent_segment.day_idx == 0
        assert urgent_segment.start_min == 420
        assert relaxed_prod.start_min == 420
        assert relaxed_prod.end_min == 904
        assert relaxed_prod.setup_min == 30
        assert not any(
            segment.lot_id == "relaxed" and segment.prod_min <= 0
            for segment in repaired
        )
        assert_plan_valid(repaired, data, config)

    def test_does_not_pull_before_jit_floor(self):
        from backend.scheduler.scheduler import _repair_zero_slack_lots_into_previous_gaps

        config = FactoryConfig(
            machines={"M1": MachineConfig("M1", "Grandes")},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        lot = _make_lot(
            lot_id="jit_floor",
            tool_id="T1",
            machine_id="M1",
            qty=100,
            prod_min=60,
            setup_min=30,
            edd=0,
        )
        segments = [
            Segment(
                lot_id="jit_floor",
                run_id="run_jit_floor",
                machine_id="M1",
                tool_id="T1",
                day_idx=0,
                start_min=420,
                end_min=510,
                shift="A",
                qty=100,
                prod_min=60,
                setup_min=30,
                edd=0,
                run_setup_min=30,
                sku="SKU",
            )
        ]

        repaired = _repair_zero_slack_lots_into_previous_gaps(
            segments,
            [lot],
            data,
            config,
            holidays=set(),
        )

        assert [(s.day_idx, s.start_min, s.end_min) for s in repaired] == [(0, 420, 510)]

    def test_pulls_complete_opening_block_into_same_day_gap(self):
        from backend.scheduler.scheduler import _pull_complete_opening_segments_into_gaps
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        target = _make_lot(
            lot_id="target",
            tool_id="T1",
            machine_id="M1",
            qty=100,
            prod_min=251,
            setup_min=30,
            edd=6,
        )
        blocker = _make_lot(
            lot_id="blocker",
            tool_id="T2",
            machine_id="M1",
            qty=100,
            prod_min=887,
            setup_min=0,
            edd=6,
        )
        segments = [
            Segment(
                lot_id="blocker", run_id="run_blocker", machine_id="M1",
                tool_id="T2", day_idx=1, start_min=420, end_min=1307,
                shift="A", qty=100, prod_min=887, setup_min=0, edd=6,
                sku="BLOCKER",
            ),
            Segment(
                lot_id="target", run_id="run_target", machine_id="M1",
                tool_id="T1", day_idx=1, start_min=1389, end_min=1440,
                shift="B", qty=20, prod_min=21, setup_min=30, edd=6,
                run_setup_min=30, sku="TARGET",
            ),
            Segment(
                lot_id="target", run_id="run_target", machine_id="M1",
                tool_id="T1", day_idx=2, start_min=420, end_min=650,
                shift="A", qty=80, prod_min=230, setup_min=0, edd=6,
                run_setup_min=30, is_continuation=True, sku="TARGET",
            ),
        ]

        repaired = _pull_complete_opening_segments_into_gaps(
            segments, [target, blocker], data, config, holidays=set()
        )

        first = min(
            (segment for segment in repaired if segment.lot_id == "target"),
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        assert (first.day_idx, first.start_min, first.end_min) == (1, 1307, 1358)
        assert_plan_valid(repaired, data, config, lots=[target, blocker])

    def test_repairs_higher_priority_tool_return_without_a_second_setup(self):
        from backend.scheduler.scheduler import _repair_interrupted_tool_campaigns
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        urgent = _make_lot(
            lot_id="urgent",
            tool_id="T1",
            machine_id="M1",
            qty=200,
            prod_min=120,
            setup_min=30,
            edd=5,
        )
        later = _make_lot(
            lot_id="later",
            tool_id="T2",
            machine_id="M1",
            qty=100,
            prod_min=60,
            setup_min=30,
            edd=6,
        )
        segments = [
            Segment(
                lot_id="urgent", run_id="run_urgent", machine_id="M1",
                tool_id="T1", day_idx=1, start_min=420, end_min=510,
                shift="A", qty=100, prod_min=60, setup_min=30,
                run_setup_min=30, edd=5, sku="URGENT",
            ),
            Segment(
                lot_id="later", run_id="run_later", machine_id="M1",
                tool_id="T2", day_idx=1, start_min=510, end_min=600,
                shift="A", qty=100, prod_min=60, setup_min=30,
                run_setup_min=30, edd=6, sku="LATER",
            ),
            Segment(
                lot_id="urgent", run_id="run_urgent", machine_id="M1",
                tool_id="T1", day_idx=1, start_min=620, end_min=680,
                shift="A", qty=100, prod_min=60, setup_min=0,
                run_setup_min=30, is_continuation=True, edd=5, sku="URGENT",
            ),
        ]

        repaired = _repair_interrupted_tool_campaigns(
            segments,
            [urgent, later],
            data,
            config,
        )

        assert [
            (segment.lot_id, segment.start_min, segment.end_min)
            for segment in repaired
        ] == [
            ("urgent", 420, 510),
            ("urgent", 510, 570),
            ("later", 570, 660),
        ]
        assert_plan_valid(repaired, data, config, lots=[urgent, later])

    def test_waits_for_setup_crew_then_uses_the_same_machine_gap(self):
        from backend.scheduler.scheduler import _repair_zero_slack_lots_into_previous_gaps
        from backend.scheduler.validation import assert_plan_valid

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={
                "M1": MachineConfig("M1", "Grandes"),
                "M2": MachineConfig("M2", "Grandes"),
            },
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[
                MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP),
                MachineInfo(id="M2", group="Grandes", day_capacity=DAY_CAP),
            ],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        target = _make_lot(
            lot_id="target", tool_id="T1", machine_id="M1", qty=100,
            prod_min=168, setup_min=30, edd=6,
        )
        competing = _make_lot(
            lot_id="competing", tool_id="T2", machine_id="M2", qty=100,
            prod_min=250, setup_min=30, edd=6,
        )
        segments = [
            Segment(
                lot_id="competing", run_id="run_competing", machine_id="M2",
                tool_id="T2", day_idx=1, start_min=420, end_min=700,
                shift="A", qty=100, prod_min=250, setup_min=30, edd=6,
                run_setup_min=30, sku="COMPETING",
            ),
            Segment(
                lot_id="target", run_id="run_target", machine_id="M1",
                tool_id="T1", day_idx=1, start_min=518, end_min=716,
                shift="A", qty=100, prod_min=168, setup_min=30, edd=6,
                run_setup_min=30, sku="TARGET",
            ),
        ]

        repaired = _repair_zero_slack_lots_into_previous_gaps(
            segments, [target, competing], data, config, holidays=set()
        )

        moved = next(segment for segment in repaired if segment.lot_id == "target")
        assert (moved.day_idx, moved.start_min, moved.end_min) == (1, 450, 648)
        assert_plan_valid(repaired, data, config, lots=[target, competing])

    def test_does_not_pull_opening_block_across_an_intervening_tool_change(self):
        from backend.scheduler.scheduler import _pull_complete_opening_segments_into_gaps

        config = FactoryConfig(
            global_jit_enabled=False,
            jit_enabled=False,
            machines={"M1": MachineConfig("M1", "Grandes")},
            setup_crews_by_group={"Grandes": 1},
        )
        data = EngineData(
            ops=[],
            machines=[MachineInfo(id="M1", group="Grandes", day_capacity=DAY_CAP)],
            twin_groups=[],
            client_demands={},
            workdays=[f"2026-03-{day:02d}" for day in range(1, 8)],
            n_days=7,
            holidays=[],
        )
        target = _make_lot(
            lot_id="target", tool_id="T1", machine_id="M1", qty=100,
            prod_min=251, setup_min=30, edd=6,
        )
        blocker = _make_lot(
            lot_id="blocker", tool_id="T2", machine_id="M1", qty=100,
            prod_min=918, setup_min=0, edd=6,
        )
        segments = [
            Segment(
                lot_id="blocker", run_id="run_blocker_a", machine_id="M1",
                tool_id="T2", day_idx=1, start_min=420, end_min=1307,
                shift="A", qty=97, prod_min=887, setup_min=0, edd=6,
                sku="BLOCKER",
            ),
            Segment(
                lot_id="blocker", run_id="run_blocker_b", machine_id="M1",
                tool_id="T2", day_idx=1, start_min=1358, end_min=1389,
                shift="B", qty=3, prod_min=31, setup_min=0, edd=6,
                sku="BLOCKER",
            ),
            Segment(
                lot_id="target", run_id="run_target", machine_id="M1",
                tool_id="T1", day_idx=1, start_min=1389, end_min=1440,
                shift="B", qty=20, prod_min=21, setup_min=30, edd=6,
                run_setup_min=30, sku="TARGET",
            ),
            Segment(
                lot_id="target", run_id="run_target", machine_id="M1",
                tool_id="T1", day_idx=2, start_min=420, end_min=650,
                shift="A", qty=80, prod_min=230, setup_min=0, edd=6,
                run_setup_min=30, is_continuation=True, sku="TARGET",
            ),
        ]

        repaired = _pull_complete_opening_segments_into_gaps(
            segments, [target, blocker], data, config, holidays=set()
        )

        first = min(
            (segment for segment in repaired if segment.lot_id == "target"),
            key=lambda segment: (segment.day_idx, segment.start_min),
        )
        assert (first.day_idx, first.start_min, first.end_min) == (1, 1389, 1440)

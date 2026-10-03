"""A shift exchange must be physically proved before it can replace a plan."""

from dataclasses import replace
from datetime import date, timedelta

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.global_jit import materialise_fixed_run
from backend.scheduler.shift_exchange import repair_shift_capacity_exchange
from backend.scheduler.types import Lot, ToolRun
from backend.scheduler.validation import assert_plan_valid, validate_plan
from backend.types import EOp, EngineData, MachineInfo, TwinGroup


def _fixture(*, busy_second_shift=False, twin_tail=False):
    config = FactoryConfig(
        machines={key: MachineConfig(key, "Grandes") for key in ("M1", "M2")},
        operators={("Grandes", "A"): 3, ("Grandes", "B"): 2},
    )
    specs = (
        ("TAIL", "M1", "T1", 28300, 1),
        ("NEXT", "M1", "T2", 477, 2),
        ("OTHER", "M2", "T3", 1349, 1),
    )
    data = EngineData(
        ops=[
            EOp(
                id=key, sku=key, client="C", designation=key, m=machine,
                t=tool, pH=1200 if key == "TAIL" else 60, sH=.5,
                operators=operators, eco_lot=0,
                alt=None, stk=0, backlog=0, d=[0, 0, 0, 0, qty, 0],
                oee=1, wip=0,
            )
            for key, machine, tool, qty, operators in specs
        ],
        machines=[MachineInfo(key, "Grandes", 1020) for key in ("M1", "M2")],
        twin_groups=[], client_demands={}, n_days=6,
        workdays=[(date(2026, 10, 5) + timedelta(days=day)).isoformat()
                  for day in range(6)],
    )
    lots = [
        Lot(
            id=key, op_id=key, sku=key, tool_id=tool, machine_id=machine,
            alt_machine_id=None, qty=qty, prod_min=prod_min, setup_min=30,
            edd=4, is_twin=False, material_release_day=0,
            production_due_day=4, delivery_day=4, customer_delivery_day=4,
        )
        for (key, machine, tool, qty, _), prod_min in zip(specs, (1415, 477, 1349))
    ]
    if twin_tail:
        data.ops.append(EOp(
            id="TAIL2", sku="TAIL2", client="C", designation="TAIL2",
            m="M1", t="T1", pH=1200, sH=.5, operators=1,
            eco_lot=0, alt=None, stk=0, backlog=0,
            d=[0, 0, 0, 0, 28300, 0], oee=1, wip=0,
        ))
        data.twin_groups.append(TwinGroup(
            "T1", "M1", "TAIL", "TAIL2", "TAIL", "TAIL2", 0, 0,
        ))
        lots[0].is_twin = True
        lots[0].twin_outputs = [
            ("TAIL", "TAIL", 28300), ("TAIL2", "TAIL2", 28300),
        ]
    def run(lot):
        return ToolRun(
            id=f"run-{lot.id}", tool_id=lot.tool_id,
            machine_id=lot.machine_id, alt_machine_id=None, lots=[lot],
            setup_min=30, total_prod_min=lot.prod_min,
            total_min=lot.prod_min + 30, edd=lot.edd,
        )

    tail = materialise_fixed_run(run(lots[0]), "M1", 0, list(range(6)), config)
    next_parts = materialise_fixed_run(
        run(lots[1]), "M1", 1020 + 425, list(range(6)), config,
    )
    assert len(next_parts) == 2
    # The two-operator run can resume only after the one-operator M2 run ends.
    next_parts[1] = replace(
        next_parts[1], start_min=1289, end_min=1430,
        prod_min=141, qty=141,
    )
    next_parts.append(replace(
        next_parts[1], day_idx=2, start_min=420, end_min=701,
        shift="A", prod_min=281, qty=281,
    ))
    other = materialise_fixed_run(
        run(lots[2]), "M2", 510, list(range(6)), config,
    )
    busy = []
    if busy_second_shift:
        config.machines["M3"] = MachineConfig("M3", "Grandes")
        data.machines.append(MachineInfo("M3", "Grandes", 1020))
        data.ops.append(EOp(
            id="BUSY", sku="BUSY", client="C", designation="BUSY",
            m="M3", t="T4", pH=60, sH=.5, operators=1,
            eco_lot=0, alt=None, stk=0, backlog=0,
            d=[0, 0, 0, 0, 330, 0], oee=1, wip=0,
        ))
        busy_lot = Lot(
            id="BUSY", op_id="BUSY", sku="BUSY", tool_id="T4",
            machine_id="M3", alt_machine_id=None, qty=330, prod_min=330,
            setup_min=30, edd=4, is_twin=False, material_release_day=0,
            production_due_day=4, delivery_day=4, customer_delivery_day=4,
        )
        lots.append(busy_lot)
        busy = materialise_fixed_run(
            run(busy_lot), "M3", 1020 + 480, list(range(6)), config,
        )
    segments = sorted(tail + next_parts + other + busy,
                      key=lambda seg: (seg.day_idx, seg.start_min, seg.machine_id))
    assert not validate_plan(segments, data, config, lots=lots), validate_plan(
        segments, data, config, lots=lots,
    )
    assert_plan_valid(segments, data, config, lots=lots)
    return segments, lots, data, config


def test_exchange_with_reinstall_setup_is_proposed_not_applied():
    """The exchange completes NEXT a day earlier but reinstalls TAIL's tool.

    The extra setup is no longer a veto (AGENTS.md §1.5), but TAIL ranks
    first in the canonical commercial order and finishes later: the move is
    described, never applied automatically.
    """
    segments, lots, data, config = _fixture()
    tradeoffs: list[dict] = []

    repaired = repair_shift_capacity_exchange(
        segments, lots, data, config, tradeoffs=tradeoffs,
    )

    assert repaired == segments
    assert [item["advanced_lot_id"] for item in tradeoffs] == ["NEXT"]
    assert tradeoffs[0]["applied"] is False
    assert tradeoffs[0]["reasons"] == ["antecipacao atrasa um lote de maior prioridade comercial"]


def test_exchange_rejected_when_second_shift_has_no_headcount():
    segments, lots, data, config = _fixture(busy_second_shift=True)
    assert repair_shift_capacity_exchange(segments, lots, data, config) == segments


def test_exchange_rejected_when_tail_tool_blocked():
    segments, lots, data, config = _fixture()
    data.tool_blocked_intervals.setdefault("T1", []).append({
        "start_day": 1, "end_day": 1,
        "start_min": 930, "end_min": 1440,
    })
    assert repair_shift_capacity_exchange(segments, lots, data, config) == segments


def test_twin_tail_exchange_is_also_only_proposed():
    segments, lots, data, config = _fixture(twin_tail=True)
    tradeoffs: list[dict] = []

    repaired = repair_shift_capacity_exchange(
        segments, lots, data, config, tradeoffs=tradeoffs,
    )

    assert repaired == segments
    assert [item["resumed_lot_id"] for item in tradeoffs] == ["TAIL"]


def test_exchange_with_extra_setup_is_applied_when_the_advanced_lot_ranks_first():
    """Decision of 02/10/2026: the reinstall setup does not veto the exchange
    once the earlier lot is the commercially more urgent one."""
    from backend.scheduler.improvement import physical_setups, production_windows

    segments, lots, data, config = _fixture()
    for lot in lots:
        if lot.id == "NEXT":
            lot.planning_priority = 1

    repaired = repair_shift_capacity_exchange(segments, lots, data, config)

    assert repaired != segments
    assert not validate_plan(repaired, data, config, lots=lots)
    assert physical_setups(repaired).count == physical_setups(segments).count + 1
    assert production_windows(repaired)["NEXT"] < production_windows(segments)["NEXT"]

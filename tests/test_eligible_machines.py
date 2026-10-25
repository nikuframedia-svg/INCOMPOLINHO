"""A lot on its alternative keeps its primary (E13, 23/10/2026).

Before: when the builder chose the alternative it wrote it as the lot's
machine without touching the lot's alternative, so the lot carried
alternative/alternative and the primary was lost. Every later calculation
(a move, a breakdown) and the screen then read only that pair, and the lot
could never go back to its primary. The machines of a lot now always come
from its operations (``config.planning.lot_tool_machines``).
"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import asdict
from datetime import date, timedelta

import pytest

from backend.api import data as data_api
from backend.config.planning import lot_alternative_on, lot_eligible_machines, lot_tool_machines
from backend.config.types import FactoryConfig, MachineConfig
from backend.copilot.state import state
from backend.scheduler.alternative_repair import _rebound_lot
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.quantity_dispatch import _CampaignBuilder, schedule_quantity_releases
from backend.scheduler.types import Lot
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, EOp, MachineInfo

N_DAYS = 20


def _op(op_id, *, machine="M1", alt="M2", demand_day=12, qty=100):
    demand = [0] * N_DAYS
    demand[demand_day] = qty
    return EOp(
        id=op_id, sku=op_id, client="CLIENT", designation=op_id, m=machine, t="TA",
        pH=60, sH=1.0, operators=1, eco_lot=0, alt=alt, stk=0, backlog=0,
        d=demand, oee=1.0, wip=0,
    )


def _data(ops, machines=("M1", "M2")):
    days = [(date(2026, 10, 7) + timedelta(days=i)).isoformat() for i in range(N_DAYS)]
    return EngineData(
        ops=list(ops),
        machines=[MachineInfo(id=m, group="Grandes", day_capacity=1020) for m in machines],
        twin_groups=[],
        client_demands={},
        workdays=days,
        n_days=N_DAYS,
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _config(machines=("M1", "M2")):
    return FactoryConfig(machines={m: MachineConfig(id=m, group="Grandes") for m in machines})


def _lot(lot_id="L1", *, op_id="A", machine="M1", alt="M2", twin_outputs=None) -> Lot:
    return Lot(
        id=lot_id, op_id=op_id, tool_id="TA", machine_id=machine, alt_machine_id=alt,
        qty=100, prod_min=100, setup_min=60, edd=12, is_twin=twin_outputs is not None,
        twin_outputs=twin_outputs,
    )


def _machines_of(result_segments, lot_id):
    return {segment.machine_id for segment in result_segments if segment.lot_id == lot_id}


# ── builder ──────────────────────────────────────────────────────────────


def test_builder_keeps_both_machines_after_choosing_the_alternative():
    data = _data([_op("A")])
    config = _config()
    data.machine_blocked_days = {"M1": set(range(N_DAYS))}
    (lot,) = create_lots(data)
    assert (lot.machine_id, lot.alt_machine_id) == ("M1", "M2")

    segments, lots = schedule_quantity_releases([lot], data, config)

    assert _machines_of(segments, lot.id) == {"M2"}
    assert [(item.machine_id, item.alt_machine_id) for item in lots] == [("M2", "M1")]
    assert not validate_plan(segments, data, config, lots=lots)


def test_a_later_rebuild_brings_the_lot_back_to_its_primary():
    data = _data([_op("A")])
    config = _config()
    blocked = copy.deepcopy(data)
    blocked.machine_blocked_days = {"M1": set(range(N_DAYS))}
    (lot,) = create_lots(data)
    _, on_alternative = schedule_quantity_releases([lot], blocked, config)

    segments, lots = schedule_quantity_releases(on_alternative, data, config)

    assert _machines_of(segments, lot.id) == {"M1"}
    assert [(item.machine_id, item.alt_machine_id) for item in lots] == [("M1", "M2")]


def test_a_saved_lot_that_lost_its_primary_is_rebuilt_on_the_primary():
    """Plans saved before E13 carry alternative/alternative (26 lots of the
    live revision 188): the builder reads the operations, not that pair."""
    data = _data([_op("A")])
    config = _config()
    (lot,) = create_lots(data)
    lot.machine_id = lot.alt_machine_id = "M2"

    segments, lots = schedule_quantity_releases([lot], data, config)

    assert _machines_of(segments, lot.id) == {"M1"}
    assert [(item.machine_id, item.alt_machine_id) for item in lots] == [("M1", "M2")]


def test_the_rest_of_a_started_lot_stays_on_its_machine():
    """Rule 4: the protection gives the rest of a started lot only its own
    machine (no alternative); the operations do not widen it."""
    data = _data([_op("A")])
    config = _config()
    (lot,) = create_lots(data)
    lot.machine_id, lot.alt_machine_id = "M2", None
    data.residual_lot_remainders = [asdict(lot)]

    builder = _CampaignBuilder([lot], data, config)

    assert builder.machines(lot.id) == ["M2"]
    parent = builder.parent(lot.id, "M2")
    assert (parent.machine_id, parent.alt_machine_id) == ("M2", None)


def test_alternative_repair_rebound_keeps_the_primary():
    data = _data([_op("A")])
    config = _config()

    rebound = _rebound_lot(_lot(), "M2", data, config)

    assert (rebound.machine_id, rebound.alt_machine_id) == ("M2", "M1")


# ── helpers ──────────────────────────────────────────────────────────────


def test_tool_machines_come_from_the_operations_with_the_lot_pair_as_fallback():
    data = _data([_op("A")])
    broken = _lot(machine="M2", alt="M2")

    assert lot_tool_machines(broken, data) == ["M1", "M2"]
    assert lot_alternative_on(broken, "M2", data) == "M1"
    unknown = _lot(op_id="UNKNOWN", machine="M2", alt="M1")
    assert lot_tool_machines(unknown, data) == ["M2", "M1"]


def test_eligible_machines_leave_out_an_inactive_machine():
    data = _data([_op("A")])
    config = _config()
    config.machines["M2"].active = False

    assert lot_eligible_machines(_lot(), data, config) == ["M1"]
    assert lot_tool_machines(_lot(), data) == ["M1", "M2"]


# ── API ──────────────────────────────────────────────────────────────────


@pytest.fixture
def api_state():
    previous = {key: getattr(state, key) for key in state.__dataclass_fields__}
    yield state
    for key, value in previous.items():
        setattr(state, key, value)


def _api_lots(api_state, ops, lots, config=None):
    api_state.engine_data = _data(ops)
    api_state.config = config or _config()
    api_state.lots = lots
    api_state.segments = []
    return {item["id"]: item for item in asyncio.run(data_api.get_lots())}


def test_api_lots_carry_the_machines_of_their_tool(api_state):
    lots = _api_lots(api_state, [_op("A")], [
        _lot("ON_ALT", machine="M2", alt="M2"),
        _lot("UNKNOWN", op_id="GONE", machine="M2", alt="M1"),
    ])

    assert lots["ON_ALT"]["eligible_machines"] == ["M1", "M2"]
    assert (lots["ON_ALT"]["machine_id"], lots["ON_ALT"]["alt_machine_id"]) == ("M2", "M2")
    assert lots["UNKNOWN"]["eligible_machines"] == ["M2", "M1"]


def test_api_twin_lot_offers_only_machines_both_sides_allow(api_state):
    twins = [("A", "A", 100), ("B", "B", 100)]
    lots = _api_lots(
        api_state,
        [_op("A"), _op("B"), _op("C"), _op("D", alt="M3")],
        [
            _lot("TWIN", twin_outputs=twins, machine="M2", alt="M2"),
            _lot("ODD", op_id="C", twin_outputs=[("C", "C", 100), ("D", "D", 100)]),
        ],
    )

    assert lots["TWIN"]["eligible_machines"] == ["M1", "M2"]
    assert lots["ODD"]["eligible_machines"] == ["M1"]


def test_api_lists_an_inactive_alternative_as_the_configuration_has_it(api_state):
    """The «Mover lote» shows the two machines of the tool; a move to the
    inactive one is refused with «não está ativa»."""
    config = _config()
    config.machines["M2"].active = False

    lots = _api_lots(api_state, [_op("A")], [_lot()], config)

    assert lots["L1"]["eligible_machines"] == ["M1", "M2"]

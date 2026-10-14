"""A scenario or a CTP promise is saved with the boundary of its own calculation.

The plan's history boundary (AGENTS §2 rule 4, ``scheduler.history``) goes
with every calculated plan. Applying a scenario («aplicar cenário») or a
promise («aplicar CTP») saves the simulated plan; its validations at apply
and at commit must read the boundary of the simulation (the factory minute it
was calculated at), never the one of the plan it started from — none after a
«Recalcular plano», or an earlier minute. Judged with no boundary, history is
taken for new work: the started part of a lot cut by rule 4, or the old
productions of a lot carried over from material versions 1-2, look like a
lot «partido» and the apply is refused (live revision 128, 13/10/2026).
"""

from __future__ import annotations

import copy

import pytest

from backend.api.data import _schedule_result_from_simulation
from backend.calendar import fixed_factory_clock
from backend.copilot.state import CopilotState
from backend.plans import frozen
from backend.plans.serialize import serialize_result_snapshot
from backend.plans.store import PlansStore, _assert_activatable_payload
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.types import ScheduleResult
from backend.scheduler.validation import validate_plan
from backend.simulator.simulator import Mutation, simulate
from tests.test_now_boundary import _at, _config, _data, _plan, _segment

RUSH = Mutation(type="rush_order", params={"sku": "SKU_OP2", "qty": "10", "deadline_day": "8"})


def _rule_4_plan():
    """At 10:00 of day 1 OP1 runs since 07:00 and OP2 (due today) must go
    first: OP1 is cut at 10:00 and its rest follows OP2 (rule 4)."""
    config = _config()
    data = _data(second_due=1)
    baseline, _lots = _plan(data, config, {
        "OP1": [(1, 420, 100, 30), (3, 420, 100, 0)], "OP2": [(3, 480, 200, 30)],
    })
    result = frozen.optimize_preserving_started_lots(
        copy.deepcopy(data), config, baseline, mode="quick", now=_at(1, 600),
    )
    assert result.history_boundary == [1, 600]
    return config, data, result


def _carried_over_plan():
    """A lot of material version 2 made on day 0 and again on day 2, with
    another lot in between, as the old per-delivery contract allowed. It is
    taken over as one economic lot that keeps its two productions."""
    config = _config()
    data = _data(second_due=1)
    lots = {lot.op_id: lot for lot in create_lots(data, config, quantity_material=2)}
    later = _segment(lots["OP1"], 2, 420, 100, 30)
    later.run_id = f"quantity:{later.lot_id}:1"
    segments = [
        _segment(lots["OP1"], 0, 420, 100, 30),
        _segment(lots["OP2"], 1, 420, 200, 30),
        later,
    ]
    result = ScheduleResult(
        segments=segments, lots=list(lots.values()), score={}, time_ms=0, warnings=[],
        operator_alerts=[],
    )
    assert not validate_plan(segments, data, config, lots=result.lots)
    return config, data, result


def _apply(sim, config, tmp_path, monkeypatch, *, boundary_before):
    """What «aplicar cenário» and «aplicar CTP» do with the simulated plan."""
    monkeypatch.setattr(CopilotState, "_refresh_analytics", lambda _self: None)
    store = PlansStore(tmp_path / "plans.db")
    before = copy.deepcopy(sim.mutated_data)
    before.history_boundary = boundary_before
    live = CopilotState(
        engine_data=before, config=config, default_config=config, segments=[], lots=[],
        score={}, plan_revision=7, dataset_info={"id": "ds", "filename": "isop.xlsx"},
        plans_store=store,
    )
    try:
        live.engine_data = sim.mutated_data
        live.update_schedule(
            _schedule_result_from_simulation(sim), plan_source="simulation_apply",
        )
        return live.engine_data.history_boundary, store.active()
    finally:
        store.close()


@pytest.mark.parametrize("plan", [_rule_4_plan, _carried_over_plan])
@pytest.mark.parametrize("stored_boundary", [None, [1, 600]])
def test_applied_scenario_is_saved_with_the_simulation_boundary(
    plan, stored_boundary, tmp_path, monkeypatch,
):
    """The state holds no boundary (after «Recalcular plano») or an earlier
    one (10:00); the scenario is calculated at 11:00 and applied."""
    config, data, baseline = plan()
    data.history_boundary = stored_boundary
    with fixed_factory_clock(_at(1, 660)):
        sim = simulate(
            data, baseline.score or {}, [RUSH], config,
            baseline_result=baseline, active_mutations=[],
        )
    assert sim.history_boundary == [1, 660]
    assert sim.mutated_data.history_boundary == [1, 660]
    assert data.history_boundary == stored_boundary  # the input is not changed
    assert _schedule_result_from_simulation(sim).history_boundary == [1, 660]
    # The saved scenario and the plan saved at apply are both valid.
    _assert_activatable_payload(serialize_result_snapshot(
        sim.mutated_data, config, _schedule_result_from_simulation(sim), plan_revision=8,
        dataset_info={"id": "ds"},
    ))
    boundary, active = _apply(sim, config, tmp_path, monkeypatch, boundary_before=stored_boundary)
    assert boundary == [1, 660]
    assert active is not None and active["source"] == "simulation_apply"


def test_the_carried_over_lot_would_be_split_without_the_boundary():
    """Why the boundary matters: judged from D0, the history break of the
    carried-over lot counts as a new production."""
    config, data, baseline = _carried_over_plan()
    with fixed_factory_clock(_at(1, 660)):
        sim = simulate(
            data, baseline.score or {}, [RUSH], config,
            baseline_result=baseline, active_mutations=[],
        )
    assert not validate_plan(sim.segments, sim.mutated_data, config, lots=sim.lots)
    judged_from_start = copy.deepcopy(sim.mutated_data)
    judged_from_start.history_boundary = None
    kinds = {v["kind"] for v in validate_plan(
        sim.segments, judged_from_start, config, lots=sim.lots,
    )}
    assert "lot_split" in kinds


def test_recalculate_rebuilds_a_plan_with_a_rule_4_cut():
    """The rest of OP1 follows the urgent OP2: valid at the replan's boundary,
    two productions from D0, so «Recalcular plano» rebuilds instead of
    compacting (review of 13/10/2026)."""
    from backend.api.data import stored_plan_needs_rebuild

    config, data, result = _rule_4_plan()
    stored = copy.deepcopy(data)
    stored.history_boundary = result.history_boundary
    assert not validate_plan(result.segments, stored, config, lots=result.lots)
    assert stored_plan_needs_rebuild(stored, result.segments, result.lots, config)


@pytest.mark.needs_private
def test_rev128_ctp_promise_applies_on_the_live_plan_of_13_10():
    """Live revision 128 (13/10 16:00, no stored boundary after the ISOP
    load): a promise for the HAN002 reference used to be refused at apply,
    its carried-over lot «passa de 1 para 2 produções» with the part of D0
    judged as new. With the simulation's boundary the saved plan is valid."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from backend.plans.serialize import deserialize_snapshot
    from tests.snapshot_fixture import load_payload

    _manifest, payload = load_payload("rev128")
    restored = deserialize_snapshot(copy.deepcopy(payload))
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    assert data.history_boundary is None
    today = data.workdays.index("2026-10-13")
    sku = next(op.sku for op in data.ops if op.id.startswith("HAN002"))
    rush = Mutation("rush_order", {"sku": sku, "qty": "100", "deadline_day": str(today + 20)})
    with fixed_factory_clock(datetime(2026, 10, 13, 16, 0, tzinfo=ZoneInfo("Europe/Lisbon"))):
        sim = simulate(
            data, result.score, [rush], config, baseline_result=result, active_mutations=[],
        )
    assert sim.history_boundary == [today, 960]
    _assert_activatable_payload(serialize_result_snapshot(
        sim.mutated_data, sim.mutated_config or config, _schedule_result_from_simulation(sim),
        plan_revision=129, dataset_info=payload.get("dataset_info"),
    ))

"""C01/C12: timing out cannot relabel an old plan as a new scenario."""

import copy
from unittest.mock import patch

import pytest

from backend.config.types import FactoryConfig
from backend.planning_control import PlanningTimeout
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.validation import validate_plan
from backend.simulator import Mutation, simulate
from backend.simulator.mutations import apply_mutation
from tests.test_simulator import _engine, _eop


@pytest.mark.parametrize("mutation", [
    Mutation("oee_change", {"tool_id": "T1", "new_oee": 0.33}),
    Mutation("advance_edd", {"sku": "SKU1", "days": 3}),
])
def test_timeout_without_scenario_candidate_cannot_reuse_old_lots(mutation):
    data, config = _engine(ops=[_eop(d=[0, 0, 0, 300, 0, 0])]), FactoryConfig()
    baseline = schedule_all(copy.deepcopy(data), config)
    before = copy.deepcopy((data, config, baseline))
    with patch("backend.plans.frozen.optimize_preserving_started_lots", side_effect=PlanningTimeout()):
        with pytest.raises(PlanningTimeout):
            simulate(data, baseline.score, [mutation], config, baseline_result=baseline)
    assert (data, config, baseline) == before


@pytest.mark.parametrize("mutation", [
    Mutation("oee_change", {"tool_id": "T1", "new_oee": 0.33}),
    Mutation("advance_edd", {"sku": "SKU1", "days": 3}),
])
def test_source_contract_rejects_stale_lot_duration_and_deadline(mutation):
    data, config = _engine(ops=[_eop(d=[0, 0, 0, 300, 0, 0])]), FactoryConfig()
    baseline = schedule_all(copy.deepcopy(data), config)
    apply_mutation(data, mutation.type, mutation.params, config)
    violations = validate_plan(baseline.segments, data, config, lots=baseline.lots)
    assert any(v["kind"] == "source_contract" for v in violations)


def test_source_contract_names_the_lot_with_inconsistent_milestones():
    from backend.scheduler.canonical import source_contract_violations
    from backend.scheduler.lot_sizing import create_lots

    data = _engine(ops=[
        _eop(op_id="OP1", sku="SKU1", d=[0, 0, 0, 300, 0, 0]),
        _eop(op_id="OP2", sku="SKU2", d=[0, 0, 0, 100, 0, 0]),
    ])
    config = FactoryConfig()
    lots = create_lots(data, config)
    assert len(lots) == 2
    lots[1].output_milestones[0]["material_release_day"] -= 1
    violations = source_contract_violations([], lots, data, config)
    assert [violation["lot_id"] for violation in violations] == [lots[1].id]
    assert violations[0]["actual"][0]["material_release_day"] == lots[1].output_milestones[0]["material_release_day"]


@pytest.mark.parametrize("cancel", [False, True])
def test_closeout_retains_only_a_complete_current_scenario_candidate(cancel):
    from backend.planning_control import PlanningCancelled, candidate_completed
    from backend.plans.frozen import optimize_preserving_started_lots

    data = _engine(ops=[_eop(d=[0, 0, 0, 300, 0, 0])])
    config = FactoryConfig()
    baseline = schedule_all(copy.deepcopy(data), config=config)
    apply_mutation(data, "oee_change", {"tool_id": "T1", "new_oee": 0.33}, config)
    fresh = schedule_all(copy.deepcopy(data), config=config)

    def interrupted(*args, **kwargs):
        candidate_completed(fresh)
        fresh.segments.clear()  # The coordinator owns a detached complete copy.
        raise PlanningCancelled() if cancel else PlanningTimeout()

    with patch("backend.plans.frozen._current_planning_day", return_value=0):
        if cancel:
            with pytest.raises(PlanningCancelled):
                optimize_preserving_started_lots(data, config, baseline, optimizer=interrupted)
        else:
            result = optimize_preserving_started_lots(data, config, baseline, optimizer=interrupted)
            assert result.segments
            assert result.lots[0].prod_min == pytest.approx(baseline.lots[0].prod_min * 2)
            assert result.gate_report["physical_gate_passed"] is True

"""CTP promises require a complete executable candidate, including reinstalls."""

import copy
from types import SimpleNamespace
from unittest.mock import patch

from backend.analytics.ctp import verify_ctp
from backend.config.types import FactoryConfig, MachineConfig, ShiftConfig
from backend.scheduler.types import Lot, ScheduleResult, Segment
from backend.scheduler.validation import assert_plan_valid
from tests.test_simulator import _engine, _eop


def test_disjoint_free_windows_do_not_prove_a_ctp_promise():
    busy = _eop(sku="BUSY", machine="M1", tool="BUSY", d=[0, 170, 0], pH=60)
    new = _eop(sku="NEW", machine="M1", tool="NEW", d=[0, 0, 0], pH=60)
    busy.id, new.id = "busy", "new"
    busy.oee = new.oee = 1
    busy.sH = new.sH = 1
    data = _engine(ops=[busy, new])
    data.workdays = ["2026-09-21", "2026-09-22", "2026-09-23"]
    data.n_days = 3
    config = FactoryConfig(
        machines={"M1": MachineConfig("M1", "Grandes", oee=1)},
        shifts=[ShiftConfig("A", 420, 900, "A")],
    )
    lot = Lot("started", busy.id, "BUSY", "M1", None, 170, 170, 60, 1, False, sku="BUSY")
    segments = [
        Segment("started", "busy", "M1", "BUSY", 0, 420, 490, "A", 10, 10, setup_min=60, sku="BUSY"),
        Segment("started", "busy", "M1", "BUSY", 1, 600, 760, "A", 160, 160, sku="BUSY", is_continuation=True),
    ]
    baseline = ScheduleResult(segments, [lot], {"otd": 100}, 0, [], [])
    original = copy.deepcopy((data, config, baseline))
    with patch("backend.plans.frozen._current_planning_day", return_value=1):
        promise, candidate = verify_ctp("NEW", 240, 1, baseline, data, config)
    assert promise.feasible is False
    assert candidate is not None
    assert_plan_valid(candidate.segments, candidate.mutated_data, candidate.mutated_config,
                      lots=candidate.lots)
    assert (data, config, baseline) == original


def test_promise_eta_does_not_include_unused_tail_of_same_lot(monkeypatch):
    from backend.scheduler.lot_sizing import create_lots
    from backend.simulator.mutations import apply_mutation

    data = _engine(ops=[_eop(d=[0] * 9 + [200], pH=60, oee=1, eco_lot=300)], n_days=10)
    data.workdays = [f"2026-09-{day:02d}" for day in range(21, 31)]
    config = FactoryConfig()
    changed = copy.deepcopy(data)
    apply_mutation(changed, "rush_order", {"sku": "SKU1", "qty": 100, "deadline_day": 2})
    lot = create_lots(changed, config)[0]
    segments = [
        Segment(lot.id, "run", "M1", "T1", 1, 420, 550, "A", 100, 100, setup_min=30, sku="SKU1"),
        Segment(lot.id, "run", "M1", "T1", 9, 420, 620, "A", 200, 200, sku="SKU1"),
    ]
    scenario = SimpleNamespace(segments=segments, lots=[lot], mutated_data=changed,
                               gate_report={"physical_gate_passed": True, "apply_decision": "allow"})
    monkeypatch.setattr("backend.simulator.simulator.simulate", lambda *a, **kw: scenario)
    baseline = ScheduleResult([], [], {}, 0, [], [])
    promise, candidate = verify_ctp("SKU1", 100, 2, baseline, data, config)
    assert candidate is scenario and promise.feasible
    assert promise.earliest_end_day == 1
    assert promise.prod_days == 1 and promise.required_min == 130

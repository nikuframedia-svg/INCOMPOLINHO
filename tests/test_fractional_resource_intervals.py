"""Physical resource occupancy must not depend on minute rounding policy."""

import copy
import math
from dataclasses import replace

import pytest

from backend.plans.frozen import _install_frozen_reservations, _restore_frozen_reservations
from backend.plans.manual_move import _operator_free_gaps
from backend.scheduler.gap_filling import evaluate_legal_interval, find_opening_gap_opportunities
from backend.scheduler.global_jit import _fixed_block_interval, _preemptive_operator_windows, cp_model
from backend.scheduler.operators import operator_peaks
from backend.scheduler.scheduler import _setup_aware_candidate_starts
from tests.test_setup_boundary_search import operator_boundary_case


@pytest.mark.parametrize("setup", [42.25, 42.5, 42.75])
@pytest.mark.parametrize("path", ["interval", "peak"])
def test_fractional_setup_cannot_hide_productive_overlap(setup, path):
    data, config, segments, lots = operator_boundary_case(release=552, setup=setup)
    start = 552 - math.ceil(setup)
    moved = replace(segments[0], day_idx=0, start_min=start, end_min=613)
    assert moved.start_min + moved.setup_min < segments[1].end_min
    if path == "interval":
        result = evaluate_legal_interval(
            segments, segments[0], data, config, 0, start, 613,
            setup_min=setup, ignored_lot_ids={lots[0].id},
        )
        assert not result.allowed
        assert any("blocked_by_operator_capacity" in reason for reason in result.blocking_reasons)
    else:
        assert operator_peaks([moved, segments[1]], data, config)[(0, "Grandes", "A")].deficit == 1


@pytest.mark.parametrize("setup", [42.25, 42.5, 42.75])
def test_other_setup_does_not_reserve_operators_before_it_finishes(setup):
    data, config, segments, lots = operator_boundary_case(release=552, setup=0)
    other = replace(segments[1], start_min=509, setup_min=setup, end_min=613, prod_min=60)
    result = evaluate_legal_interval(
        [segments[0], other], segments[0], data, config, 0, 490, 551.2,
        ignored_lot_ids={lots[0].id},
    )
    assert result.allowed, result.blocking_reasons


@pytest.mark.parametrize("path", ["manual", "global"])
@pytest.mark.parametrize("blocker", ["production", "absence"])
def test_integer_operator_windows_are_inside_exact_free_time(path, blocker):
    data, config, segments, _lots = operator_boundary_case(release=552, setup=0)
    other = replace(segments[1], start_min=509, setup_min=42.5, end_min=613, prod_min=60)
    occupied = [other] if blocker == "production" else []
    if blocker == "absence":
        data.operator_blocked_intervals = [{
            "start_day": 0, "end_day": 0, "start_min": 420, "end_min": 510.5,
            "group": "Grandes", "shift": "A", "count": 1,
        }]
    if path == "manual":
        windows = _operator_free_gaps(
            occupied, data, config, day=0, shift="A", shift_start=420, shift_end=930,
            machine_id="M1", required=1,
        )
    else:
        windows = _preemptive_operator_windows(
            occupied, data, config, 0, "A", "Grandes", 1, 420, 930,
        )
    assert windows == ([(420, 551), (613, 930)] if blocker == "production" else [(511, 930)])


@pytest.mark.parametrize("setup", [42.25, 42.5, 42.75])
def test_frozen_operator_reservation_keeps_exact_production_start(setup):
    data, config, segments, lots = operator_boundary_case(setup=setup)
    before = copy.deepcopy(data)
    snapshot = _install_frozen_reservations(data, segments[:1], lots[:1], 1, config)
    try:
        reservation = data.operator_blocked_intervals[0]
        assert reservation["start_min"] == segments[0].start_min + setup
        assert reservation["end_min"] == segments[0].end_min
    finally:
        _restore_frozen_reservations(data, snapshot)
    assert data == before


@pytest.mark.parametrize("blocker", ["production", "absence"])
def test_fractional_boundary_search_matches_independent_minute_oracle(blocker):
    setup = 42.5
    data, config, segments, lots = operator_boundary_case(release=552, setup=setup)
    release = 552
    if blocker == "absence":
        release = 552.5
        segments, lots, data.ops = segments[:1], lots[:1], data.ops[:1]
        data.operator_blocked_intervals = [{
            "start_day": 0, "end_day": 0, "start_min": 420, "end_min": release,
            "group": "Grandes", "shift": "A", "count": 1,
        }]
    expected = min(start for start in range(420, 930) if start + setup >= release)
    before = copy.deepcopy((data, config, segments, lots))
    opportunity = next(
        item for item in find_opening_gap_opportunities(segments, lots, data, config)
        if item.lot_id == lots[0].id
    )
    assert (opportunity.gap_day, opportunity.gap_start_min) == (0, expected)
    assert (data, config, segments, lots) == before


@pytest.mark.parametrize("setup", [42.25, 42.5, 42.75])
def test_setup_search_includes_first_integer_minute_after_crew_release(setup):
    data, config, segments, _lots = operator_boundary_case(setup=setup)
    busy = replace(segments[1], start_min=420, setup_min=setup, end_min=523)
    candidates = _setup_aware_candidate_starts(
        [busy], config, machine_id="M1", day_idx=0, earliest=420, latest=930,
        setup_min=30, data=data,
    )
    assert candidates[0] == math.ceil(420 + setup)


def test_irrelevant_fractional_events_do_not_break_a_free_clock_window():
    data, config, segments, _lots = operator_boundary_case(setup=0)
    config.operators[("Grandes", "A")] = 2
    other = replace(segments[1], start_min=509, setup_min=42.5, end_min=613)
    assert _operator_free_gaps(
        [other], data, config, day=0, shift="A", machine_id="M1", required=1,
        shift_start=420, shift_end=930,
    ) == [(420, 930)]


@pytest.mark.parametrize("setup", [0, 42.25, 42.5, 42.75])
@pytest.mark.parametrize("absence", [False, True])
def test_interval_evaluator_agrees_with_exact_independent_occupancy_oracle(setup, absence):
    data, config, segments, _lots = operator_boundary_case(setup=setup)
    config.setup_crews_by_group["Grandes"] = 2
    other = replace(segments[1], start_min=509, setup_min=42.5, end_min=613)
    if absence:
        data.operator_blocked_intervals = [{
            "start_day": 0, "end_day": 0, "start_min": 420, "end_min": 490.5,
            "group": "Grandes", "shift": "A", "count": 1,
        }]
    for start in range(420, 650):
        end = start + math.ceil(setup + 60)
        exact_production_start = start + setup
        overlapping_production = exact_production_start < 613 and 551.5 < end
        overlapping_absence = absence and exact_production_start < 490.5
        expected = not overlapping_production and not overlapping_absence
        result = evaluate_legal_interval(
            [segments[0], other], segments[0], data, config, 0, start, end,
            setup_min=setup, ignored_lot_ids={segments[0].lot_id},
        )
        assert result.allowed == expected, (setup, absence, start, result.blocking_reasons)


@pytest.mark.parametrize("setup", [42.25, 42.5, 42.75])
def test_integer_solver_does_not_release_fractional_crew_reservation_early(setup):
    _data, config, _segments, _lots = operator_boundary_case(setup=setup)
    model = cp_model.CpModel()
    fixed = _fixed_block_interval(
        model, {"start_day": 0, "start_min": 420, "end_min": 420 + setup},
        [0], config.day_capacity_min, config, config.day_capacity_min, "history-setup",
    )
    start = model.new_int_var(0, 300, "next-setup-start")
    end = model.new_int_var(30, 330, "next-setup-end")
    following = model.new_interval_var(start, 30, end, "next-setup")
    model.add_no_overlap([fixed, following])
    model.minimize(start)
    solver = cp_model.CpSolver()
    assert solver.solve(model) == cp_model.OPTIMAL
    assert solver.value(start) == math.ceil(setup)

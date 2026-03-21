"""Tests for PORT-05 (Overflow + Auto-Routing)."""

from __future__ import annotations

from src.domain.scheduling.overflow.overflow_helpers import (
    cap_analysis,
    compute_advanced_edd,
    compute_tardiness,
    sum_overflow,
)
from src.domain.scheduling.types import (
    Block,
    EMachine,
    EOp,
)

# ── Overflow helpers tests ──


def test_sum_overflow_empty():
    assert sum_overflow([]) == 0


def test_sum_overflow_with_overflow_blocks():
    blocks = [
        Block(
            op_id="op1",
            tool_id="T1",
            machine_id="M1",
            overflow=True,
            overflow_min=60,
            type="overflow",
        ),
        Block(
            op_id="op2",
            tool_id="T2",
            machine_id="M1",
            overflow=True,
            overflow_min=30,
            type="overflow",
        ),
        Block(op_id="op3", tool_id="T3", machine_id="M1", type="ok", prod_min=100),
    ]
    assert sum_overflow(blocks) == 90


def test_sum_overflow_infeasible():
    blocks = [
        Block(op_id="op1", tool_id="T1", machine_id="M1", type="infeasible", prod_min=120),
    ]
    assert sum_overflow(blocks) == 120


def test_compute_tardiness_none():
    blocks = [
        Block(
            op_id="op1", tool_id="T1", machine_id="M1", type="ok", day_idx=3, edd_day=5, prod_min=60
        ),
    ]
    assert compute_tardiness(blocks) == 0


def test_compute_tardiness_late():
    blocks = [
        Block(
            op_id="op1", tool_id="T1", machine_id="M1", type="ok", day_idx=7, edd_day=5, prod_min=60
        ),
        Block(
            op_id="op2",
            tool_id="T2",
            machine_id="M1",
            type="ok",
            day_idx=3,
            edd_day=5,
            prod_min=100,
        ),
    ]
    assert compute_tardiness(blocks) == 60  # only op1 is late


def test_cap_analysis_basic():
    blocks = [
        Block(
            op_id="op1",
            tool_id="T1",
            machine_id="M1",
            day_idx=0,
            prod_min=100,
            setup_min=30,
            type="ok",
        ),
        Block(
            op_id="op2",
            tool_id="T2",
            machine_id="M1",
            day_idx=1,
            prod_min=200,
            setup_min=0,
            type="ok",
        ),
    ]
    machines = [EMachine(id="M1", area="A")]
    result = cap_analysis(blocks, machines)
    assert result["M1"][0]["prod"] == 100
    assert result["M1"][0]["setup"] == 30
    assert result["M1"][1]["prod"] == 200


def test_compute_advanced_edd_basic():
    workdays = [True, True, True, True, True, False, False, True, True, True]
    # from day 9, go back 3 working days
    result = compute_advanced_edd(9, 3, workdays)
    assert result == 4  # day 8(T,1), 7(T,2), 6(F), 5(F), 4(T,3)


def test_compute_advanced_edd_all_workdays():
    workdays = [True] * 10
    result = compute_advanced_edd(5, 3, workdays)
    assert result == 2


def test_compute_advanced_edd_not_enough():
    workdays = [True, True]
    result = compute_advanced_edd(1, 5, workdays)
    assert result == -1  # not enough working days


def test_overflow_helpers_combined():
    """Test all helper functions work together."""
    workdays = [True, True, True, True, True]
    blocks = [
        Block(
            op_id="op1",
            tool_id="T1",
            machine_id="M1",
            day_idx=0,
            type="ok",
            prod_min=100,
            setup_min=30,
            qty=50,
            edd_day=2,
        ),
        Block(
            op_id="op2",
            tool_id="T2",
            machine_id="M1",
            day_idx=4,
            type="ok",
            prod_min=60,
            setup_min=15,
            qty=30,
            edd_day=1,
        ),
        Block(
            op_id="op3",
            tool_id="T3",
            machine_id="M2",
            day_idx=2,
            type="overflow",
            overflow=True,
            overflow_min=45,
            prod_min=45,
        ),
    ]
    machines = [EMachine(id="M1", area="A"), EMachine(id="M2", area="B")]

    assert sum_overflow(blocks) == 45
    assert compute_tardiness(blocks) == 60  # op2 late: day_idx=4 > edd_day=1

    cap = cap_analysis(blocks, machines)
    assert cap["M1"][0]["prod"] == 100
    assert cap["M1"][4]["prod"] == 60
    assert cap["M2"][2]["prod"] == 45

    assert compute_advanced_edd(4, 2, workdays) == 2

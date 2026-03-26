"""Tests for backend/cpo/cpsat_polish.py — CP-SAT surgical polisher."""

import copy
from collections import defaultdict
from unittest.mock import patch

from backend.cpo.cpsat_polish import (
    _HAS_ORTOOLS,
    cpsat_polish,
    identify_bottleneck_machines,
)
from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.types import EngineData, EOp, MachineInfo


def _make_data(n_days=30, n_ops=3) -> EngineData:
    """Minimal EngineData for testing."""
    ops = []
    for i in range(n_ops):
        d = [0] * n_days
        d[10 + i] = 100  # demand on day 10+i
        ops.append(EOp(
            id=f"OP_{i}", sku=f"SKU_{i}", client="TEST", designation="Test",
            m="PRM019", t=f"T00{i}", pH=100.0, sH=0.5, operators=1,
            eco_lot=0, alt=None, stk=0, backlog=0, d=d, oee=0.66, wip=0,
        ))
    return EngineData(
        ops=ops,
        machines=[MachineInfo(id="PRM019", group="Grandes", day_capacity=1020)],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{i+1:02d}" for i in range(n_days)],
        n_days=n_days,
        holidays=[],
    )


def _make_segments_and_lots(data: EngineData) -> tuple[list[Segment], list[Lot], dict]:
    """Create minimal segments/lots/machine_runs for testing."""
    segments = []
    lots = []
    machine_runs: dict[str, list[ToolRun]] = defaultdict(list)

    for i, op in enumerate(data.ops):
        lot = Lot(
            id=f"LOT_{i}", op_id=op.id, tool_id=op.t, machine_id="PRM019",
            alt_machine_id=None, qty=100, prod_min=90.0, setup_min=30.0,
            edd=10 + i, is_twin=False,
        )
        lots.append(lot)

        seg = Segment(
            lot_id=lot.id, run_id=f"RUN_{i}", machine_id="PRM019",
            tool_id=op.t, day_idx=5 + i, start_min=420, end_min=540,
            shift="A", qty=100, prod_min=90.0, setup_min=30.0, edd=lot.edd,
        )
        segments.append(seg)

        run = ToolRun(
            id=f"RUN_{i}", tool_id=op.t, machine_id="PRM019",
            alt_machine_id=None, lots=[lot], setup_min=30.0,
            total_prod_min=90.0, total_min=120.0, edd=lot.edd,
        )
        machine_runs["PRM019"].append(run)

    return segments, lots, dict(machine_runs)


def test_identify_bottleneck_redundant_setup():
    """Machine with redundant setups (same tool interrupted) is flagged."""
    data = _make_data(n_days=30, n_ops=3)
    segments = [
        Segment(lot_id="L1", run_id="R1", machine_id="PRM019", tool_id="T001",
                day_idx=5, start_min=420, end_min=600, shift="A", qty=100,
                prod_min=150.0, setup_min=30.0, edd=10),
        # Different tool in between
        Segment(lot_id="L2", run_id="R2", machine_id="PRM019", tool_id="T002",
                day_idx=5, start_min=600, end_min=700, shift="A", qty=50,
                prod_min=70.0, setup_min=30.0, edd=12),
        # Same tool as first → redundant setup
        Segment(lot_id="L3", run_id="R3", machine_id="PRM019", tool_id="T002",
                day_idx=5, start_min=700, end_min=800, shift="A", qty=50,
                prod_min=70.0, setup_min=30.0, edd=14),
    ]
    lots = [
        Lot(id="L1", op_id="OP_0", tool_id="T001", machine_id="PRM019",
            alt_machine_id=None, qty=100, prod_min=150.0, setup_min=30.0,
            edd=10, is_twin=False),
        Lot(id="L2", op_id="OP_1", tool_id="T002", machine_id="PRM019",
            alt_machine_id=None, qty=50, prod_min=70.0, setup_min=30.0,
            edd=12, is_twin=False),
        Lot(id="L3", op_id="OP_2", tool_id="T002", machine_id="PRM019",
            alt_machine_id=None, qty=50, prod_min=70.0, setup_min=30.0,
            edd=14, is_twin=False),
    ]
    config = FactoryConfig()
    bottlenecks = identify_bottleneck_machines(segments, lots, data, config)
    assert "PRM019" in bottlenecks


def test_identify_bottleneck_tardy():
    """Machine with tardy lots is flagged."""
    data = _make_data(n_days=30, n_ops=1)
    # Lot completes on day 15, EDD is 5 → tardy
    segments = [
        Segment(lot_id="L1", run_id="R1", machine_id="PRM019", tool_id="T001",
                day_idx=15, start_min=420, end_min=600, shift="A", qty=100,
                prod_min=150.0, setup_min=30.0, edd=5),
    ]
    lots = [
        Lot(id="L1", op_id="OP_0", tool_id="T001", machine_id="PRM019",
            alt_machine_id=None, qty=100, prod_min=150.0, setup_min=30.0,
            edd=5, is_twin=False),
    ]
    config = FactoryConfig()
    bottlenecks = identify_bottleneck_machines(segments, lots, data, config)
    assert "PRM019" in bottlenecks


def test_no_bottleneck_light_machine():
    """Lightly loaded machine with no tardies → not a bottleneck."""
    data = _make_data(n_days=60, n_ops=1)
    segments = [
        Segment(lot_id="L1", run_id="R1", machine_id="PRM019", tool_id="T001",
                day_idx=5, start_min=420, end_min=500, shift="A", qty=50,
                prod_min=60.0, setup_min=20.0, edd=30),
    ]
    lots = [
        Lot(id="L1", op_id="OP_0", tool_id="T001", machine_id="PRM019",
            alt_machine_id=None, qty=50, prod_min=60.0, setup_min=20.0,
            edd=30, is_twin=False),
    ]
    config = FactoryConfig()
    bottlenecks = identify_bottleneck_machines(segments, lots, data, config)
    assert "PRM019" not in bottlenecks


def test_cpsat_polish_no_ortools():
    """When ortools unavailable, returns original schedule unchanged."""
    data = _make_data()
    segments, lots, machine_runs = _make_segments_and_lots(data)
    config = FactoryConfig()

    with patch("backend.cpo.cpsat_polish._HAS_ORTOOLS", False):
        result_segs, result_lots, score = cpsat_polish(
            segments, lots, machine_runs, data, config,
        )
    # Should return originals
    assert result_segs is segments
    assert result_lots is lots
    assert "otd" in score


def test_cpsat_polish_safety_net():
    """CP-SAT polish never worsens tardy count."""
    data = _make_data()
    segments, lots, machine_runs = _make_segments_and_lots(data)
    config = FactoryConfig()

    if not _HAS_ORTOOLS:
        return  # skip if ortools not installed

    result_segs, result_lots, score = cpsat_polish(
        segments, lots, machine_runs, data, config,
    )
    # Original has 0 tardies, result should also have 0
    assert score["tardy_count"] == 0

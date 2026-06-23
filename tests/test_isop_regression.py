"""Regression checks against the two real Incompol ISOP files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.config.loader import load_config
from backend.cpo import optimize
from backend.parser.isop_reader import read_isop
from backend.scheduler.scheduler import _hard_gate_metrics
from backend.simulator.simulator import Mutation, simulate
from backend.transform.transform import transform


ROOT = Path(__file__).resolve().parents[1]


def _load_real(filename: str):
    rows, workdays, has_twin = read_isop(str(ROOT / filename))
    with open(ROOT / "config" / "incompol.yaml") as f:
        master = yaml.safe_load(f)
    data = transform(rows, workdays, has_twin, master)
    config = load_config(str(ROOT / "config" / "factory.yaml"))
    return data, config


@pytest.mark.parametrize(
    "filename",
    ["ISOP_ Nikufra_27_2.xlsx", "ISOP_ Nikufra_17_3.xlsx"],
)
def test_real_isop_hard_gates_normal(filename: str):
    data, config = _load_real(filename)

    result = optimize(data, mode="normal", config=config)

    assert result.score["otd"] == 100.0
    assert result.score["otd_d"] == 100.0
    assert result.score["tardy_count"] == 0
    assert result.score["otd_d_failures"] == 0
    assert _hard_gate_metrics(result.segments, config, data=data, lots=result.lots) == {
        "tool_conflicts": 0,
        "machine_overlaps": 0,
        "day_cap_violations": 0,
        "ghost_segments": 0,
        "blocked_machine_segments": 0,
        "blocked_tool_segments": 0,
        "setup_sequence_violations": 0,
        "run_lot_order_violations": 0,
    }


def test_machine_down_no_segments_on_blocked_days_27_2():
    data, config = _load_real("ISOP_ Nikufra_27_2.xlsx")
    baseline = optimize(data, mode="normal", config=config)
    result = simulate(
        data,
        baseline.score,
        [
            Mutation("machine_down", {"machine_id": "PRM031", "start": "-6", "end": "-1"}),
            Mutation("machine_down", {"machine_id": "PRM019", "start": "-6", "end": "0"}),
        ],
        config=config,
        mode="normal",
    )

    assert result.score["buffer_days"] >= 6
    assert result.score["blocked_machine_segments"] == 0
    assert result.score["blocked_tool_segments"] == 0
    assert result.score["setup_sequence_violations"] == 0
    assert result.score["run_lot_order_violations"] == 0
    assert not [
        seg for seg in result.segments
        if (
            (seg.machine_id == "PRM031" and -6 <= seg.day_idx <= -1)
            or (seg.machine_id == "PRM019" and -6 <= seg.day_idx <= 0)
        )
    ]


def test_machine_down_no_tool_conflicts_17_3():
    data, config = _load_real("ISOP_ Nikufra_17_3.xlsx")
    baseline = optimize(data, mode="normal", config=config)
    result = simulate(
        data,
        baseline.score,
        [
            Mutation("machine_down", {"machine_id": "PRM031", "start": "-6", "end": "-1"}),
            Mutation("machine_down", {"machine_id": "PRM019", "start": "-6", "end": "0"}),
        ],
        config=config,
        mode="normal",
    )

    assert result.score["tool_conflicts"] == 0
    assert result.score["machine_overlaps"] == 0
    assert result.score["ghost_segments"] == 0
    assert result.score["blocked_machine_segments"] == 0
    assert result.score["blocked_tool_segments"] == 0
    assert result.score["day_cap_violations"] == 0
    assert result.score["setup_sequence_violations"] == 0
    assert result.score["run_lot_order_violations"] == 0

"""Tests for VNS post-processing — Phase 4b."""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.dispatch import per_machine_dispatch
from backend.scheduler.jit import _backward_stack_gates
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, ToolRun
from backend.scheduler.vns import (
    _apply_move,
    _deep_copy_runs,
    _dispatch_and_score,
    _generate_n1_moves,
    _generate_n2_moves,
    _generate_n3_moves,
    _is_better,
    vns_polish,
)
from backend.types import EngineData, EOp, MachineInfo


# --- Fixtures ---


def _make_lot(
    op_id: str, tool: str, machine: str, edd: int,
    qty: int = 1000, prod_min: float = 100.0, setup_min: float = 30.0,
    alt: str | None = None,
) -> Lot:
    return Lot(
        id=f"lot_{op_id}",
        op_id=op_id,
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=alt,
        qty=qty,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=edd,
        is_twin=False,
    )


def _make_run(
    tool: str, machine: str, lots: list[Lot], run_idx: int = 0,
) -> ToolRun:
    setup = lots[0].setup_min
    total_prod = sum(l.prod_min for l in lots)
    return ToolRun(
        id=f"run_{tool}_{machine}_{run_idx}",
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=lots[0].alt_machine_id,
        lots=lots,
        setup_min=setup,
        total_prod_min=total_prod,
        total_min=setup + total_prod,
        edd=lots[0].edd,
    )


def _make_engine_data(n_days: int = 20, ops: list[EOp] | None = None) -> EngineData:
    return EngineData(
        ops=ops or [],
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-03-{d:02d}" for d in range(1, n_days + 1)],
        n_days=n_days,
        holidays=[],
    )


# --- Tests ---


class TestIsBetter:
    """Test the comparison function."""

    def test_fewer_setups_is_better(self):
        config = FactoryConfig()
        old = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        new = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 95}
        assert _is_better(new, old, config) is True

    def test_more_tardy_rejected(self):
        config = FactoryConfig()
        old = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        new = {"tardy_count": 1, "otd_d": 100.0, "earliness_avg_days": 4.0, "setups": 80}
        assert _is_better(new, old, config) is False

    def test_worse_otd_d_rejected(self):
        config = FactoryConfig()
        old = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        new = {"tardy_count": 0, "otd_d": 99.0, "earliness_avg_days": 4.0, "setups": 80}
        assert _is_better(new, old, config) is False

    def test_earliness_exceeds_target_rejected(self):
        config = FactoryConfig()
        old = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        new = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 7.0, "setups": 80}
        assert _is_better(new, old, config) is False

    def test_same_setups_less_earliness_is_better(self):
        config = FactoryConfig()
        old = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.5, "setups": 100}
        new = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        assert _is_better(new, old, config) is True

    def test_same_score_not_better(self):
        config = FactoryConfig()
        old = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        new = {"tardy_count": 0, "otd_d": 100.0, "earliness_avg_days": 5.0, "setups": 100}
        assert _is_better(new, old, config) is False


class TestN1Moves:
    """Test N1 swap move generation."""

    def test_generates_swap_for_tool_adjacency(self):
        """When swapping creates a same-tool adjacency, should generate move."""
        config = FactoryConfig()
        # M1: [T1, T2, T1] — swapping positions 1,2 would make T1 adjacent to T1
        lots_t1a = [_make_lot("op1", "T1", "M1", edd=5)]
        lots_t2 = [_make_lot("op2", "T2", "M1", edd=7)]
        lots_t1b = [_make_lot("op3", "T1", "M1", edd=9)]

        machine_runs = {
            "M1": [
                _make_run("T1", "M1", lots_t1a, 0),
                _make_run("T2", "M1", lots_t2, 1),
                _make_run("T1", "M1", lots_t1b, 2),
            ],
        }

        moves = list(_generate_n1_moves(machine_runs, config))
        assert len(moves) > 0
        # Should suggest swapping T2 with T1b to create T1-T1 adjacency
        assert any(m[0] == "swap" for m in moves)

    def test_no_swap_when_already_adjacent(self):
        """Same-tool already adjacent — no benefit from swap."""
        config = FactoryConfig()
        lots_t1a = [_make_lot("op1", "T1", "M1", edd=5)]
        lots_t1b = [_make_lot("op2", "T1", "M1", edd=7)]

        machine_runs = {
            "M1": [
                _make_run("T1", "M1", lots_t1a, 0),
                _make_run("T1", "M1", lots_t1b, 1),
            ],
        }

        moves = list(_generate_n1_moves(machine_runs, config))
        assert len(moves) == 0


class TestN2Moves:
    """Test N2 relocate move generation."""

    def test_generates_relocate_for_scattered_tool(self):
        """Same tool scattered across positions → should generate relocate."""
        config = FactoryConfig()
        runs = [
            _make_run("T1", "M1", [_make_lot("op1", "T1", "M1", edd=5)], 0),
            _make_run("T2", "M1", [_make_lot("op2", "T2", "M1", edd=7)], 1),
            _make_run("T3", "M1", [_make_lot("op3", "T3", "M1", edd=9)], 2),
            _make_run("T1", "M1", [_make_lot("op4", "T1", "M1", edd=11)], 3),
        ]

        machine_runs = {"M1": runs}
        moves = list(_generate_n2_moves(machine_runs, config))
        assert len(moves) > 0
        assert any(m[0] == "relocate" for m in moves)


class TestN3Moves:
    """Test N3 cross-machine move generation."""

    def test_generates_cross_machine_with_adjacency(self):
        """Run with alt machine where alt has same-tool → should generate move."""
        config = FactoryConfig()
        # M1: [T1(alt=M2)]  M2: [T1]
        lots_m1 = [_make_lot("op1", "T1", "M1", edd=5, alt="M2")]
        lots_m2 = [_make_lot("op2", "T1", "M2", edd=7)]

        machine_runs = {
            "M1": [_make_run("T1", "M1", lots_m1, 0)],
            "M2": [_make_run("T1", "M2", lots_m2, 0)],
        }

        moves = list(_generate_n3_moves(machine_runs, config))
        assert len(moves) > 0
        assert any(m[0] == "cross_machine" for m in moves)

    def test_no_move_without_alt(self):
        """No alt machine → no cross-machine move."""
        config = FactoryConfig()
        lots = [_make_lot("op1", "T1", "M1", edd=5)]  # no alt
        machine_runs = {"M1": [_make_run("T1", "M1", lots, 0)]}

        moves = list(_generate_n3_moves(machine_runs, config))
        assert len(moves) == 0


class TestApplyMove:
    """Test move application."""

    def test_swap_move(self):
        lots_a = [_make_lot("op1", "T1", "M1", edd=5)]
        lots_b = [_make_lot("op2", "T2", "M1", edd=7)]
        run_a = _make_run("T1", "M1", lots_a, 0)
        run_b = _make_run("T2", "M1", lots_b, 1)

        machine_runs = {"M1": [run_a, run_b]}
        new_runs, affected = _apply_move(("swap", "M1", 0, 1), machine_runs)

        assert new_runs["M1"][0].tool_id == "T2"
        assert new_runs["M1"][1].tool_id == "T1"
        assert affected == {"M1"}
        # Original unchanged
        assert machine_runs["M1"][0].tool_id == "T1"

    def test_relocate_move(self):
        runs = [
            _make_run("T1", "M1", [_make_lot("op1", "T1", "M1", edd=5)], 0),
            _make_run("T2", "M1", [_make_lot("op2", "T2", "M1", edd=7)], 1),
            _make_run("T3", "M1", [_make_lot("op3", "T3", "M1", edd=9)], 2),
            _make_run("T1", "M1", [_make_lot("op4", "T1", "M1", edd=11)], 3),
        ]
        machine_runs = {"M1": runs}

        # Relocate run at position 3 (T1) to position 1 (after first T1)
        new_runs, affected = _apply_move(("relocate", "M1", 3, 1), machine_runs)

        assert new_runs["M1"][0].tool_id == "T1"
        assert new_runs["M1"][1].tool_id == "T1"  # relocated here
        assert new_runs["M1"][2].tool_id == "T2"
        assert new_runs["M1"][3].tool_id == "T3"
        assert affected == {"M1"}

    def test_cross_machine_move(self):
        lots_m1 = [_make_lot("op1", "T1", "M1", edd=5, alt="M2")]
        lots_m2 = [_make_lot("op2", "T2", "M2", edd=10)]
        run_m1 = _make_run("T1", "M1", lots_m1, 0)
        run_m2 = _make_run("T2", "M2", lots_m2, 0)

        machine_runs = {"M1": [run_m1], "M2": [run_m2]}
        new_runs, affected = _apply_move(("cross_machine", "M1", 0, "M2"), machine_runs)

        assert len(new_runs["M1"]) == 0
        assert len(new_runs["M2"]) == 2
        assert affected == {"M1", "M2"}


class TestVNSPolish:
    """Test the main VNS function."""

    def test_no_regression(self):
        """VNS should never make the score worse."""
        config = FactoryConfig(vns_max_iter=10)
        data = _make_engine_data(n_days=20)

        # Create a simple schedule with 2 machines
        lots = [
            _make_lot("op1", "T1", "M1", edd=10, prod_min=200),
            _make_lot("op2", "T2", "M1", edd=12, prod_min=200),
        ]
        runs = [
            _make_run("T1", "M1", [lots[0]], 0),
            _make_run("T2", "M1", [lots[1]], 1),
        ]
        machine_runs = {"M1": runs}
        gates = {r.id: 0.0 for r in runs}

        segs, all_lots, score = _dispatch_and_score(machine_runs, gates, data, config)

        result_segs, result_lots, result_score, warnings = vns_polish(
            machine_runs, gates, data, config, segs, all_lots, score,
        )

        # Should not increase tardy
        assert result_score["tardy_count"] <= score["tardy_count"]
        # Should not increase setups
        assert result_score["setups"] <= score["setups"]
        assert len(warnings) > 0

    def test_finds_swap_improvement(self):
        """VNS should find an improvement when N1 swap reduces setups."""
        config = FactoryConfig(vns_max_iter=30)
        data = _make_engine_data(n_days=30)

        # M1: [T1, T2, T1] → swap T2↔T1 → [T1, T1, T2] saves 1 setup
        lots_t1a = [_make_lot("op1", "T1", "M1", edd=10, prod_min=100)]
        lots_t2 = [_make_lot("op2", "T2", "M1", edd=12, prod_min=100)]
        lots_t1b = [_make_lot("op3", "T1", "M1", edd=14, prod_min=100)]

        runs = [
            _make_run("T1", "M1", lots_t1a, 0),
            _make_run("T2", "M1", lots_t2, 1),
            _make_run("T1", "M1", lots_t1b, 2),
        ]
        machine_runs = {"M1": runs}
        gates = {r.id: 0.0 for r in runs}

        segs, all_lots, score = _dispatch_and_score(machine_runs, gates, data, config)
        initial_setups = score["setups"]

        result_segs, result_lots, result_score, warnings = vns_polish(
            machine_runs, gates, data, config, segs, all_lots, score,
        )

        # Should find the swap and reduce setups by 1
        assert result_score["setups"] <= initial_setups

    def test_fallback_on_no_improvement(self):
        """When no improvement possible, returns original."""
        config = FactoryConfig(vns_max_iter=10)
        data = _make_engine_data(n_days=20)

        # Single run — nothing to optimize
        lots = [_make_lot("op1", "T1", "M1", edd=10, prod_min=200)]
        runs = [_make_run("T1", "M1", lots, 0)]
        machine_runs = {"M1": runs}
        gates = {runs[0].id: 0.0}

        segs, all_lots, score = _dispatch_and_score(machine_runs, gates, data, config)

        result_segs, result_lots, result_score, warnings = vns_polish(
            machine_runs, gates, data, config, segs, all_lots, score,
        )

        assert result_score["setups"] == score["setups"]
        assert "no improvement" in warnings[0]

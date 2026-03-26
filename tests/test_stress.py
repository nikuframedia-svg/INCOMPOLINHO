"""Tests for backend/scheduler/stress.py — stress map + summary."""

from backend.scheduler.stress import compute_stress_map, stress_summary, SegmentStress
from backend.scheduler.types import Lot, Segment


def _seg(lot_id="LOT_1", machine_id="PRM019", day_idx=5, start_min=420, end_min=600,
         prod_min=150.0, setup_min=30.0, tool_id="T001", qty=100):
    return Segment(
        lot_id=lot_id, run_id="RUN_1", machine_id=machine_id, tool_id=tool_id,
        day_idx=day_idx, start_min=start_min, end_min=end_min, shift="A",
        qty=qty, prod_min=prod_min, setup_min=setup_min, edd=10,
    )


def _lot(id="LOT_1", edd=10):
    return Lot(
        id=id, op_id="OP_1", tool_id="T001", machine_id="PRM019",
        alt_machine_id=None, qty=100, prod_min=150.0, setup_min=30.0,
        edd=edd, is_twin=False,
    )


def test_basic_stress_values():
    """Stress values are non-negative floats."""
    segs = [_seg(day_idx=5), _seg(lot_id="LOT_2", day_idx=8)]
    lots = [_lot(), _lot(id="LOT_2", edd=12)]
    result = compute_stress_map(segs, lots, n_days=20)
    assert len(result) == 2
    for s in result:
        assert s.stress >= 0.0
        assert s.level in ("critical", "warning", "ok")


def test_high_utilisation_high_stress():
    """Machine at ~100% utilisation with tight EDD → high stress."""
    # Fill machine near capacity: 20 days × 1020 min ≈ 20400 min
    segs = [_seg(lot_id=f"LOT_{i}", day_idx=i, prod_min=900.0, setup_min=100.0)
            for i in range(20)]
    lots = [_lot(id=f"LOT_{i}", edd=i) for i in range(20)]  # EDD = completion day → 0 slack
    result = compute_stress_map(segs, lots, n_days=20)
    # At least some segments should be critical or warning
    levels = [s.level for s in result]
    assert "critical" in levels or "warning" in levels


def test_idle_machine_low_stress():
    """Single segment on a machine with lots of capacity → low stress."""
    segs = [_seg(day_idx=2, prod_min=30.0, setup_min=0.0)]
    lots = [_lot(edd=30)]  # EDD far in the future → lots of slack
    result = compute_stress_map(segs, lots, n_days=40)
    assert len(result) == 1
    assert result[0].level == "ok"
    assert result[0].stress < 1.0


def test_empty_inputs():
    """Empty segments → empty stress map."""
    result = compute_stress_map([], [], n_days=20)
    assert result == []


def test_summary_fields():
    """stress_summary returns all expected fields."""
    segs = [
        _seg(lot_id="LOT_1", day_idx=5, prod_min=100.0),
        _seg(lot_id="LOT_2", machine_id="PRM031", day_idx=5, prod_min=100.0),
    ]
    lots = [_lot(id="LOT_1", edd=6), _lot(id="LOT_2", edd=20)]
    stress_map = compute_stress_map(segs, lots, n_days=30)
    summary = stress_summary(stress_map)

    assert "total_segments" in summary
    assert "critical" in summary
    assert "warning" in summary
    assert "ok" in summary
    assert "fragility_pct" in summary
    assert "worst_machine" in summary
    assert "top_fragile" in summary
    assert summary["total_segments"] == 2
    assert summary["critical"] + summary["warning"] + summary["ok"] == 2


def test_summary_empty():
    """stress_summary with empty list returns zeros."""
    summary = stress_summary([])
    assert summary["total_segments"] == 0
    assert summary["fragility_pct"] == 0.0
    assert summary["worst_machine"] is None


def test_skips_buffer_and_setup_only():
    """Segments with day_idx < 0 or prod_min <= 0 are skipped."""
    segs = [
        _seg(day_idx=-1, prod_min=100.0),   # buffer day
        _seg(lot_id="LOT_S", day_idx=5, prod_min=0.0, setup_min=30.0),  # setup-only
        _seg(lot_id="LOT_OK", day_idx=5, prod_min=100.0),  # valid
    ]
    lots = [_lot(), _lot(id="LOT_S", edd=10), _lot(id="LOT_OK", edd=10)]
    result = compute_stress_map(segs, lots, n_days=20)
    assert len(result) == 1
    assert result[0].lot_id == "LOT_OK"

"""Repair targets late deliveries per portion, not lots that end after their first date.

``alternative_repair._delivery_risk_run_ids`` reads the shared
``delivery_readiness`` evaluator: an economic lot whose first delivery is
ready on time is not a repair target just because its last portion (for a
later delivery) is produced after the first delivery date.
"""

from __future__ import annotations

from backend.scheduler.alternative_repair import _delivery_risk_run_ids
from backend.scheduler.types import ToolRun
from tests.oracle_delivery import oracle_orders
from tests.test_delivery_views_agree import FIXTURES


def _run_map(lots):
    return {
        f"RUN-{lot.id}": ToolRun(
            id=f"RUN-{lot.id}", tool_id=lot.tool_id, machine_id=lot.machine_id,
            alt_machine_id=None, lots=[lot], setup_min=0.0, total_prod_min=lot.prod_min,
            total_min=lot.prod_min, edd=lot.edd,
        )
        for lot in lots
    }


def test_on_time_portions_are_not_repair_targets():
    for name in ("F1", "F2", "F3", "F5"):
        segments, lots, data = FIXTURES[name]()
        if name != "F5":  # F5's first delivery is served by stock and supply.
            # The lot ends (day 13) after its first delivery (day 12): the old
            # lot-end rule made this a repair target.
            assert max(segment.day_idx for segment in segments) > min(
                int(output["customer_delivery_day"]) for output in lots[0].output_milestones
            )
        assert not any(order.late for order in oracle_orders(segments, lots, data)), name
        assert _delivery_risk_run_ids(segments, _run_map(lots), data) == set(), name


def test_a_late_portion_still_marks_its_run():
    for name in ("F1-late", "F2-late"):
        segments, lots, data = FIXTURES[name]()
        assert any(order.late for order in oracle_orders(segments, lots, data)), name
        assert _delivery_risk_run_ids(segments, _run_map(lots), data) == {
            f"RUN-{lots[0].id}"
        }, name


def test_lot_without_segments_is_a_repair_target():
    segments, lots, data = FIXTURES["F1"]()
    assert _delivery_risk_run_ids([], _run_map(lots), data) == {f"RUN-{lots[0].id}"}

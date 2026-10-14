"""Stock screen (Entregas), 14/10/2026: a subcontracted reference behaves like
any other one. Its pieces count on the day they are produced in the factory;
no trips to or from the subcontractor are shown. The rupture follows that
stock (Incompol, 14/10/2026): a production that misses the subcontract
deadline (five working days before the delivery) is a late order, reported by
the plan, not a rupture while the stock shown covers the delivery."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from backend.analytics.stock_projection import compute_stock_projections
from backend.config.planning import apply_effective_planning_config
from backend.scheduler.lot_sizing import create_lots
from tests.test_subcontract_release import _config, _engine, _op, _segment


def _subcontracted_plan(stamping_days: list[int]):
    op = _op(delivery_day=14)
    data = _engine(op)
    apply_effective_planning_config(data, _config())
    lot = create_lots(data, _config())[0]
    share = lot.qty // len(stamping_days)
    segments = [
        replace(_segment(lot, day), qty=share if index else lot.qty - share * (len(stamping_days) - 1))
        for index, day in enumerate(stamping_days)
    ]
    return op, data, lot, segments


def test_production_deadline_is_five_working_days_before_the_delivery():
    from backend.config.planning import planning_milestones_for_op
    from backend.scheduler.jit_policy import calendar_holidays

    op, data, _lot, _segments = _subcontracted_plan([7])
    holidays = calendar_holidays(data, -90, data.n_days + 14)
    # Delivery Mon 21/09 (day 14): production finished by Mon 14/09 (day 7),
    # five working days before (the weekend does not count).
    milestones = planning_milestones_for_op(op, 14, holidays)
    assert milestones.production_due_day == 7


def test_subcontracted_pieces_count_on_the_day_they_are_produced():
    _op_, data, lot, segments = _subcontracted_plan([7])

    projection = compute_stock_projections(segments, [lot], data)[0]
    days = {day.day_idx: day for day in projection.days}

    assert days[7].produced == 100 and days[7].stock == 100
    assert sum(day.produced for day in projection.days) == 100
    assert days[14].demand == 100 and days[14].stock == 0
    # Made on its deadline: on time.
    assert projection.stockout_day is None


def test_lot_made_over_several_days_shows_each_days_pieces():
    _op_, data, lot, segments = _subcontracted_plan([6, 7])

    projection = compute_stock_projections(segments, [lot], data)[0]
    days = {day.day_idx: day for day in projection.days}

    assert (days[6].produced, days[7].produced) == (50, 50)
    assert (days[6].stock, days[7].stock) == (50, 100)
    assert projection.stockout_day is None


def test_production_after_its_deadline_is_not_a_rupture_while_stock_covers():
    _op_, data, lot, segments = _subcontracted_plan([8])

    projection = compute_stock_projections(segments, [lot], data)[0]
    days = {day.day_idx: day for day in projection.days}

    # Finished one working day after its deadline (day 7): a late order for
    # the plan, but the stock shown never goes negative, so no rupture.
    assert days[8].produced == 100 and days[14].stock == 0
    assert all(day.stock >= 0 for day in projection.days)
    assert projection.stockout_day is None
    assert projection.coverage_days == float(data.n_days)


def test_subcontracted_rupture_is_the_first_negative_day_shown():
    _op_, data, lot, segments = _subcontracted_plan([15])

    projection = compute_stock_projections(segments, [lot], data)[0]
    days = {day.day_idx: day for day in projection.days}

    assert days[14].stock == -100 and days[15].stock == 0
    assert projection.stockout_day == 14
    assert projection.coverage_days == 14.0


def test_late_subcontracted_production_is_still_a_late_order():
    from backend.analytics.late_delivery import analyze_late_deliveries

    _op_, data, lot, segments = _subcontracted_plan([8])
    report = analyze_late_deliveries(segments, [lot], data, _config())
    assert report.tardy_count == 1


def test_in_house_reference_is_unchanged():
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config(subcontracted=False)
    apply_effective_planning_config(data, config)
    lot = create_lots(data, config)[0]

    projection = compute_stock_projections([_segment(lot, 8)], [lot], data)[0]

    assert projection.days[8].produced == 100
    assert projection.stockout_day is None
    assert projection.subcontract_due_workdays is None
    late = compute_stock_projections([_segment(lot, 15)], [lot], data)[0]
    assert late.stockout_day == 14 and late.days[14].stock == -100


def test_stock_endpoints_send_no_subcontract_movements(monkeypatch):
    from backend.api.data import get_stock_detail, get_stock_summary
    from backend.copilot.state import state

    _op_, data, lot, segments = _subcontracted_plan([7])
    monkeypatch.setattr(state, "engine_data", data)
    monkeypatch.setattr(state, "stock_projections",
                        compute_stock_projections(segments, [lot], data))

    (row,) = asyncio.run(get_stock_summary())
    days = {day["day"]: day for day in row["days"]}
    assert days[7]["produced"] == 100
    assert row["subcontract_company_id"] == "SUPPLIER"
    # The «S» badge says how many working days before the delivery.
    assert row["subcontract_due_workdays"] == 5
    assert set(days[7]) == {"day", "date", "stock", "demand", "produced", "workday", "is_buffer"}

    detail = asyncio.run(get_stock_detail("SUB"))
    detail_days = {day["day_idx"]: day for day in detail["days"]}
    assert detail_days[7]["produced"] == 100
    assert all("subcontract_sent" not in day and "subcontract_returns" not in day
               for day in detail["days"])

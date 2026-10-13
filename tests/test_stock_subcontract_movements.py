"""Stock screen: subcontracted pieces leave on their stamping days and count on return."""

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


def test_subcontracted_pieces_are_sent_on_stamping_day_and_return_with_origin():
    _op_, data, lot, segments = _subcontracted_plan([8])

    projection = compute_stock_projections(segments, [lot], data)[0]
    days = {day.day_idx: day for day in projection.days}

    # Stamped on day 8 (Tue 15/09): leaves that day, back five working days later.
    assert days[8].subcontract_sent == 100
    assert days[8].produced == 0
    assert days[15].produced == 100
    assert days[15].subcontract_returns == [{
        "qty": 100,
        "stamped_from_day": 8,
        "stamped_to_day": 8,
        "machines": ["M1"],
        "stamped_from_date": "2026-09-15",
        "stamped_to_date": "2026-09-15",
    }]
    assert sum(day.subcontract_sent for day in projection.days) == 100
    assert [day.day_idx for day in projection.days if day.subcontract_returns] == [15]
    # Back on day 15 for a day-14 delivery: the screen shows it late.
    assert projection.stockout_day == 14


def test_subcontracted_delivery_stamped_over_several_days_is_sent_on_each_stamping_day():
    _op_, data, lot, segments = _subcontracted_plan([7, 8])

    projection = compute_stock_projections(segments, [lot], data)[0]
    days = {day.day_idx: day for day in projection.days}

    # Each stamping day shows its own pieces; they all come back together.
    assert (days[7].subcontract_sent, days[8].subcontract_sent) == (50, 50)
    assert days[7].produced == days[8].produced == 0
    (back,) = days[15].subcontract_returns
    assert (back["qty"], back["stamped_from_day"], back["stamped_to_day"]) == (100, 7, 8)
    assert back["stamped_from_date"] == "2026-09-14"


def test_in_house_reference_has_no_subcontract_movements():
    op = _op(delivery_day=14)
    data = _engine(op)
    config = _config(subcontracted=False)
    apply_effective_planning_config(data, config)
    lot = create_lots(data, config)[0]

    projection = compute_stock_projections([_segment(lot, 8)], [lot], data)[0]

    assert projection.days[8].produced == 100
    assert all(day.subcontract_sent == 0 and day.subcontract_returns == []
               for day in projection.days)


def test_stock_endpoint_sends_movements_only_on_days_that_have_them(monkeypatch):
    from backend.api.data import get_stock_summary
    from backend.copilot.state import state

    _op_, data, lot, segments = _subcontracted_plan([8])
    monkeypatch.setattr(state, "engine_data", data)
    monkeypatch.setattr(state, "stock_projections",
                        compute_stock_projections(segments, [lot], data))

    (row,) = asyncio.run(get_stock_summary())
    days = {day["day"]: day for day in row["days"]}

    assert days[8]["subcontract_sent"] == 100
    assert days[15]["produced"] == 100
    assert days[15]["subcontract_returns"][0]["stamped_from_date"] == "2026-09-15"
    assert days[15]["subcontract_returns"][0]["machines"] == ["M1"]
    untouched = [day for index, day in days.items() if index not in (8, 15)]
    assert all("subcontract_sent" not in day and "subcontract_returns" not in day
               for day in untouched)


def test_deliveries_stamped_together_come_back_as_one_return():
    op = _op(delivery_day=14)
    op.d[14] = 60
    op.d[12] = 40
    data = _engine(op)
    apply_effective_planning_config(data, _config())
    lots = create_lots(data, _config())
    segments = [_segment(lot, 8) for lot in lots]

    projection = compute_stock_projections(segments, lots, data)[0]
    days = {day.day_idx: day for day in projection.days}

    assert days[8].subcontract_sent == 100
    assert [(item["qty"], item["stamped_from_day"]) for item in days[15].subcontract_returns] == [
        (100, 8),
    ]


def test_stock_detail_endpoint_keeps_old_shape_on_days_without_movements(monkeypatch):
    from backend.api.data import get_stock_detail
    from backend.copilot.state import state

    _op_, data, lot, segments = _subcontracted_plan([8])
    monkeypatch.setattr(state, "engine_data", data)
    monkeypatch.setattr(state, "stock_projections",
                        compute_stock_projections(segments, [lot], data))

    detail = asyncio.run(get_stock_detail("SUB"))
    days = {day["day_idx"]: day for day in detail["days"]}

    assert days[8]["subcontract_sent"] == 100
    assert days[15]["subcontract_returns"][0]["qty"] == 100
    assert "subcontract_sent" not in days[0] and "subcontract_returns" not in days[0]

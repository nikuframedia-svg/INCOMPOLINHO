"""Tests for coverage-based alerts engine."""

from __future__ import annotations

from datetime import date, timedelta

from src.domain.stock_alerts.coverage_engine import compute_coverage_alerts

TODAY = date(2026, 3, 15)


def _make_order(sku="REF001", qty=1000, deadline=None, client_code="CLI01"):
    return {
        "sku": sku,
        "client_code": client_code,
        "qty": qty,
        "deadline": deadline or TODAY + timedelta(days=1),
    }


def _make_sku(sku="REF001", designation="Peça Teste", stock=0, atraso=0, orders=None):
    ords = orders or []
    return {
        "sku": sku,
        "designation": designation,
        "machine": "PRM019",
        "tool": "T001",
        "pieces_per_hour": 500,
        "stock": stock,
        "atraso": atraso,
        "orders": ords,
        "clients": list({o.get("client_code", "CLI01") for o in ords}) or ["CLI01"],
    }


def test_no_alert_when_covered():
    orders = [_make_order(qty=500, deadline=TODAY + timedelta(days=i)) for i in range(5, 20)]
    skus = {"REF001": _make_sku(stock=50000, orders=orders)}
    assert len(compute_coverage_alerts(skus, TODAY)) == 0


def test_red_alert_tomorrow():
    order = _make_order(qty=5000, deadline=TODAY + timedelta(days=1))
    skus = {"REF001": _make_sku(stock=0, orders=[order])}
    alerts = compute_coverage_alerts(skus, TODAY)
    assert len(alerts) == 1
    assert alerts[0].severity == "red"


def test_yellow_alert_2days():
    order = _make_order(qty=5000, deadline=TODAY + timedelta(days=2))
    skus = {"REF001": _make_sku(stock=0, orders=[order])}
    alerts = compute_coverage_alerts(skus, TODAY)
    assert len(alerts) == 1
    assert alerts[0].severity == "yellow"


def test_atraso_priority():
    atraso_sku = _make_sku(
        sku="LATE",
        designation="Atrasada",
        stock=0,
        atraso=-500,
        orders=[_make_order(sku="LATE", qty=3000, deadline=TODAY + timedelta(days=5))],
    )
    red_sku = _make_sku(
        sku="URGENT",
        designation="Urgente",
        stock=0,
        orders=[_make_order(sku="URGENT", qty=2000, deadline=TODAY + timedelta(days=1))],
    )
    skus = {"LATE": atraso_sku, "URGENT": red_sku}
    alerts = compute_coverage_alerts(skus, TODAY)
    assert len(alerts) == 2
    assert alerts[0].severity == "atraso"
    assert alerts[0].sku == "LATE"
    assert alerts[1].severity == "red"


def test_stock_covers_orders():
    order = _make_order(qty=3000, deadline=TODAY + timedelta(days=1))
    skus = {"REF001": _make_sku(stock=5000, orders=[order])}
    assert len(compute_coverage_alerts(skus, TODAY)) == 0


def test_multi_order_drain():
    orders = [
        _make_order(qty=2000, deadline=TODAY + timedelta(days=1)),
        _make_order(qty=2000, deadline=TODAY + timedelta(days=2)),
        _make_order(qty=2000, deadline=TODAY + timedelta(days=3)),
    ]
    skus = {"REF001": _make_sku(stock=5000, orders=orders)}
    alerts = compute_coverage_alerts(skus, TODAY)
    assert len(alerts) == 1
    assert alerts[0].shortage_qty == 1000
    assert alerts[0].severity == "yellow"


def test_sorted_by_severity_and_shortage():
    skus = {
        "Y1": _make_sku(
            sku="Y1",
            stock=0,
            orders=[_make_order(sku="Y1", qty=100, deadline=TODAY + timedelta(days=2))],
        ),
        "R1": _make_sku(
            sku="R1",
            stock=0,
            orders=[_make_order(sku="R1", qty=9000, deadline=TODAY + timedelta(days=1))],
        ),
        "A1": _make_sku(
            sku="A1",
            stock=0,
            atraso=-200,
            orders=[_make_order(sku="A1", qty=500, deadline=TODAY + timedelta(days=5))],
        ),
        "R2": _make_sku(
            sku="R2",
            stock=0,
            orders=[_make_order(sku="R2", qty=300, deadline=TODAY + timedelta(days=1))],
        ),
    }
    alerts = compute_coverage_alerts(skus, TODAY)
    assert len(alerts) == 4
    assert alerts[0].severity == "atraso"
    assert alerts[1].severity == "red"
    assert alerts[1].shortage_qty == 9000
    assert alerts[2].severity == "red"
    assert alerts[3].severity == "yellow"

"""Scenario demand and customer-order diagnostics must describe the same inputs."""

import copy

import pytest

from backend.simulator.mutations import apply_mutation
from backend.types import ClientDemandEntry
from tests.test_simulator import _engine, _eop


@pytest.fixture
def demand_trace():
    data = _engine(ops=[_eop(d=[0, 5, 0, 0, 0, 0])])
    data.client_demands["SKU1"] = [
        ClientDemandEntry("A", "SKU1", 1, data.workdays[1], 2, -2),
        ClientDemandEntry("B", "SKU1", 1, data.workdays[1], 3, -3),
    ]
    return data


@pytest.mark.parametrize("factor", [.01, .5, 1.5, 2])
def test_scaled_orders_conserve_rounded_daily_demand(demand_trace, factor):
    data = demand_trace
    apply_mutation(data, "demand_change", {"sku": "SKU1", "factor": factor})
    entries = data.client_demands.get("SKU1", [])
    assert sum(abs(entry.np_value) for entry in entries) == sum(data.ops[0].d)
    assert sum(entry.order_qty for entry in entries) == round(5 * factor)


def test_order_scaling_preserves_existing_stock_credit(demand_trace):
    data = demand_trace
    data.client_demands["SKU1"][0].order_qty += 7
    apply_mutation(data, "demand_change", {"sku": "SKU1", "factor": 2})
    entries = data.client_demands["SKU1"]
    assert sum(entry.order_qty for entry in entries) == 17
    assert sum(abs(entry.np_value) for entry in entries) == 10


@pytest.mark.parametrize("mutation, days, expected", [("advance_edd", 3, 0), ("delay_edd", 8, 9)])
def test_changed_due_date_moves_all_clients_and_extends_dates(demand_trace, mutation, days, expected):
    data = demand_trace
    apply_mutation(data, mutation, {"sku": "SKU1", "days": days})
    assert data.ops[0].d[expected] == 5
    assert {(entry.day_idx, entry.date) for entry in data.client_demands["SKU1"]} == {
        (expected, data.workdays[expected]),
    }


def test_cancel_then_add_demand_preserves_other_client_trace_and_source(demand_trace):
    original = copy.deepcopy(demand_trace)
    data = copy.deepcopy(demand_trace)
    apply_mutation(data, "cancel_order", {"sku": "SKU1", "from_day": 0, "to_day": 5})
    assert data.client_demands == {} and sum(data.ops[0].d) == 0
    apply_mutation(data, "rush_order", {"sku": "SKU1", "qty": 7, "deadline_day": 4})
    assert sum(data.ops[0].d) == 7
    assert [(entry.day_idx, entry.order_qty, entry.np_value) for entry in data.client_demands["SKU1"]] == [(4, 7, -7)]
    assert demand_trace == original

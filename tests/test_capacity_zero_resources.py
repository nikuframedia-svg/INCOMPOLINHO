"""Capacity diagnostics must not hide load without a physical resource."""

from dataclasses import replace

import pytest

from backend.analytics.capacity import compute_capacity
from tests.test_capacity import _fixture


@pytest.mark.parametrize("granularity", ["day", "week"])
@pytest.mark.parametrize("blocked", ["holiday", "machine", "inactive"])
def test_positive_load_without_machine_capacity_is_undefined(granularity, blocked):
    segments, data, config = _fixture()
    segment = replace(segments[0], day_idx=0)
    data.n_days = 1
    data.workdays = data.workdays[:1]
    data.holidays = [0] if blocked == "holiday" else []
    data.machine_blocked_days = {"M1": {0}} if blocked == "machine" else {}
    if blocked == "inactive":
        config.machines["M1"].active = False
    rows = compute_capacity([segment], data, config, granularity)["items"]
    row = next(item for item in rows if item["machine_id"] == "M1")
    assert row["load_min"] == 330
    assert row["cap_min"] == 0
    assert row["util_pct"] is None
    assert row["overload"] is True


@pytest.mark.parametrize("granularity", ["day", "week"])
def test_positive_load_without_operators_is_undefined(granularity):
    segments, data, config = _fixture()
    data.n_days = 1
    data.workdays = data.workdays[:1]
    config.operators[("Grandes", "A")] = 0
    row = next(item for item in compute_capacity(segments[:1], data, config, granularity)["operators"]
               if item["group"] == "Grandes" and item["shift"] == "A")
    assert row["load_operator_min"] > 0
    assert row["capacity_operator_min"] == 0
    assert row["util_pct"] is None
    assert row["overload"] is True


@pytest.mark.parametrize("granularity", ["day", "week"])
def test_closed_resources_without_load_remain_zero(granularity):
    _, data, config = _fixture()
    data.n_days = 1
    data.workdays = data.workdays[:1]
    data.holidays = [0]
    result = compute_capacity([], data, config, granularity)
    assert all(row["util_pct"] == 0 and not row["overload"] for row in result["items"])
    assert all(row["util_pct"] == 0 and not row["overload"] for row in result["operators"])

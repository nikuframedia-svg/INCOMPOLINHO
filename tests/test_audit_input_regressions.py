"""C03/C15: invalid inputs must never silently remove demand or grant approval."""

import pytest

from backend.api.manual_plan import _request_values
from backend.config.loader import _normalize_unavailability
from backend.parser.isop_reader import read_isop
from tests.test_parser import _make_isop_wb


@pytest.mark.parametrize("value", ["-15600x", "#VALUE!", "=-(10000+5600)", -1.5, True])
def test_import_rejects_indeterminate_demand_with_cell_origin(tmp_path, value):
    wb = _make_isop_wb()
    wb.active["O6"] = value
    path = tmp_path / "invalid.xlsx"
    wb.save(path)
    wb.close()
    with pytest.raises(ValueError, match="O6"):
        read_isop(path)


@pytest.mark.parametrize("value", [True, 3.9, "3.0", float("nan"), float("inf")])
def test_loaded_absence_rejects_non_integer_count(value):
    with pytest.raises(ValueError):
        _normalize_unavailability([{"count": value}], operators=True)


@pytest.mark.parametrize("field,value", [
    ("target_day", True), ("target_day", 1.9), ("target_start_min", 2.5),
    ("approve_exceptions", "false"), ("confirm_delivery_risk", 1),
])
def test_manual_request_rejects_lossy_numbers_and_approval(field, value):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        _request_values({"lot_id": "L1", "target_day": 1, field: value})
    assert error.value.status_code == 400


def test_blank_cadence_warning_keeps_cell_origin_through_dqa_and_snapshot(tmp_path):
    from dataclasses import asdict
    from backend.transform.transform import transform
    from backend.dqa.trust_index import compute_trust_index
    from backend.plans.serialize import deserialize_engine_data

    wb = _make_isop_wb()
    wb.active["I6"] = None
    path = tmp_path / "default-cadence.xlsx"
    wb.save(path)
    wb.close()
    rows, days, twins = read_isop(path)
    data = transform(rows, days, twins, None)
    assert any("I6" in warning for warning in data.input_warnings)
    restored = deserialize_engine_data(asdict(data))
    assert restored.input_warnings == data.input_warnings
    assert "I6" in str(asdict(compute_trust_index(restored)))


@pytest.mark.parametrize("value", [0, -1, "NaN", "inf"])
def test_explicit_invalid_cadence_is_not_replaced_by_default(tmp_path, value):
    wb = _make_isop_wb()
    wb.active["I6"] = value
    path = tmp_path / "bad-cadence.xlsx"
    wb.save(path)
    wb.close()
    with pytest.raises(ValueError, match="I6"):
        read_isop(path)

# Testes para ingest
# Conforme SP-BE-03

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.domain.ingest.isop_parser import generate_import_report, sha256_file
from src.domain.snapshot.hash import calculate_snapshot_hash, canonical_json
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_sha256_file():
    """Testa cálculo de SHA-256 de ficheiro"""
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("test content")
        tmp_path = Path(f.name)

    try:
        hash1 = sha256_file(tmp_path)
        hash2 = sha256_file(tmp_path)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex
    finally:
        tmp_path.unlink()


def test_canonical_json():
    """Testa geração de JSON canónico"""
    data1 = {"b": 2, "a": 1, "c": 3}
    data2 = {"c": 3, "a": 1, "b": 2}

    json1 = canonical_json(data1)
    json2 = canonical_json(data2)

    assert json1 == json2  # Deve ser igual independente da ordem


def test_calculate_snapshot_hash():
    """Testa cálculo de snapshot_hash (determinístico)"""
    snapshot1 = {
        "snapshot_id": "id1",
        "created_at": "2026-01-01T00:00:00Z",
        "master_data": {"items": [{"item_sku": "SKU1"}]},
        "semantics": {"series_semantics": "DEMAND_QTY_BY_DATE"},
    }

    snapshot2 = {
        "snapshot_id": "id2",  # ID diferente
        "created_at": "2026-01-02T00:00:00Z",  # Data diferente
        "master_data": {"items": [{"item_sku": "SKU1"}]},
        "semantics": {"series_semantics": "DEMAND_QTY_BY_DATE"},
    }

    hash1 = calculate_snapshot_hash(snapshot1)
    hash2 = calculate_snapshot_hash(snapshot2)

    assert hash1 == hash2  # Deve ser igual (ignorando ID e created_at)


def test_generate_import_report():
    """Testa geração de import report"""
    snapshot = {
        "master_data": {
            "items": [{"item_sku": "SKU1"}],
            "resources": [{"resource_code": "RES1"}],
            "tools": [{"tool_code": "TOOL1"}],
            "customers": [{"customer_code": "CUST1"}],
        },
        "routing": [{"item_sku": "SKU1"}],
        "series": [{"item_sku": "SKU1", "date": "2026-01-01", "quantity": 100}],
        "trust_index": {"overall": 0.9},
    }

    report = generate_import_report(snapshot)

    assert report["items_count"] == 1
    assert report["resources_count"] == 1
    assert report["tools_count"] == 1
    assert report["customers_count"] == 1
    assert report["routings_count"] == 1
    assert report["series_entries_count"] == 1
    assert report["trust_index"] == 0.9

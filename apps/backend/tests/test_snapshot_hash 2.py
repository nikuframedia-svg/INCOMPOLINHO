# Testes para hash canónico
# Conforme SP-BE-04

from src.domain.snapshot.hash import calculate_snapshot_hash, canonical_json


def test_canonical_json_stable_ordering():
    """Testa que canonical_json produz sempre o mesmo resultado para o mesmo input"""
    data1 = {"b": 2, "a": 1, "c": 3}
    data2 = {"c": 3, "a": 1, "b": 2}

    json1 = canonical_json(data1)
    json2 = canonical_json(data2)

    assert json1 == json2  # Deve ser igual independente da ordem


def test_canonical_json_excludes_non_deterministic():
    """Testa que campos não determinísticos são excluídos"""
    snapshot1 = {
        "snapshot_id": "id1",
        "created_at": "2026-01-01T00:00:00Z",
        "sources": [{"file_hash_sha256": "hash1"}],
        "master_data": {"items": [{"item_sku": "SKU1"}]},
        "semantics": {"series_semantics": "DEMAND_QTY_BY_DATE"},
    }

    snapshot2 = {
        "snapshot_id": "id2",  # ID diferente
        "created_at": "2026-01-02T00:00:00Z",  # Data diferente
        "sources": [{"file_hash_sha256": "hash2"}],  # Hash diferente
        "master_data": {"items": [{"item_sku": "SKU1"}]},
        "semantics": {"series_semantics": "DEMAND_QTY_BY_DATE"},
    }

    json1 = canonical_json(snapshot1)
    json2 = canonical_json(snapshot2)

    assert json1 == json2  # Deve ser igual (campos não determinísticos excluídos)


def test_calculate_snapshot_hash_deterministic():
    """Testa que snapshot_hash é determinístico"""
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

    assert hash1 == hash2  # Deve ser igual
    assert len(hash1) == 64  # SHA-256 hex


def test_canonical_json_sorts_lists():
    """Testa que listas são ordenadas por key estável"""
    snapshot1 = {
        "master_data": {
            "items": [
                {"item_sku": "SKU2"},
                {"item_sku": "SKU1"},
            ],
        },
    }

    snapshot2 = {
        "master_data": {
            "items": [
                {"item_sku": "SKU1"},
                {"item_sku": "SKU2"},
            ],
        },
    }

    json1 = canonical_json(snapshot1)
    json2 = canonical_json(snapshot2)

    assert json1 == json2  # Deve ser igual (listas ordenadas)

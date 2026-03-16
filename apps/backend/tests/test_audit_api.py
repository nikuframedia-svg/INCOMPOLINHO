# Tests for Audit API endpoints
# Conforme C-15: Observability and Audit Trail

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db.base import get_db
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_db():
    session = MagicMock(spec=Session)
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()


def _make_audit_entry(**overrides):
    """Create a mock AuditLog ORM object."""
    entry = MagicMock()
    entry.audit_id = overrides.get("audit_id", uuid4())
    entry.timestamp = overrides.get("timestamp", datetime.utcnow())
    entry.actor = overrides.get("actor", "test-user")
    entry.action = overrides.get("action", "PLAN_COMMITTED")
    entry.correlation_id = overrides.get("correlation_id", uuid4())
    entry.entity_type = overrides.get("entity_type", "PLAN")
    entry.entity_id = overrides.get("entity_id", "plan-001")
    entry.before = overrides.get("before", None)
    entry.after = overrides.get("after", None)
    entry.audit_metadata = overrides.get("audit_metadata", {})
    return entry


class TestListAuditEntries:
    @patch("src.api.v1.audit.AuditService")
    def test_list_entries_empty(self, mock_svc, client, mock_db):
        mock_svc.list_entries.return_value = []
        response = client.get("/v1/audit/entries")
        assert response.status_code == 200
        assert response.json() == []

    @patch("src.api.v1.audit.AuditService")
    def test_list_entries_returns_data(self, mock_svc, client, mock_db):
        entry = _make_audit_entry()
        mock_svc.list_entries.return_value = [entry]
        response = client.get("/v1/audit/entries")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["action"] == "PLAN_COMMITTED"
        assert data[0]["entity_type"] == "PLAN"

    @patch("src.api.v1.audit.AuditService")
    def test_list_entries_with_filters(self, mock_svc, client, mock_db):
        mock_svc.list_entries.return_value = []
        response = client.get(
            "/v1/audit/entries",
            params={
                "entity_type": "SNAPSHOT",
                "actor": "admin",
                "limit": 50,
                "offset": 10,
                "sort_order": "asc",
            },
        )
        assert response.status_code == 200
        mock_svc.list_entries.assert_called_once()
        call_kwargs = mock_svc.list_entries.call_args
        assert call_kwargs[1]["entity_type"] == "SNAPSHOT"
        assert call_kwargs[1]["actor"] == "admin"
        assert call_kwargs[1]["limit"] == 50
        assert call_kwargs[1]["offset"] == 10

    def test_list_entries_invalid_sort_order(self, client, mock_db):
        response = client.get("/v1/audit/entries", params={"sort_order": "invalid"})
        assert response.status_code == 422


class TestGetAuditEntry:
    @patch("src.api.v1.audit.AuditService")
    def test_get_entry_found(self, mock_svc, client, mock_db):
        aid = str(uuid4())
        entry = _make_audit_entry(audit_id=aid)
        mock_svc.get_entry.return_value = entry
        response = client.get(f"/v1/audit/entries/{aid}")
        assert response.status_code == 200
        assert response.json()["audit_id"] == str(aid)

    @patch("src.api.v1.audit.AuditService")
    def test_get_entry_not_found(self, mock_svc, client, mock_db):
        mock_svc.get_entry.return_value = None
        response = client.get(f"/v1/audit/entries/{uuid4()}")
        assert response.status_code == 404


class TestGetByCorrelation:
    @patch("src.api.v1.audit.AuditService")
    def test_correlation_found(self, mock_svc, client, mock_db):
        cid = uuid4()
        entries = [_make_audit_entry(correlation_id=cid) for _ in range(3)]
        mock_svc.get_by_correlation.return_value = entries
        response = client.get(f"/v1/audit/correlation/{cid}")
        assert response.status_code == 200
        assert len(response.json()) == 3

    @patch("src.api.v1.audit.AuditService")
    def test_correlation_not_found(self, mock_svc, client, mock_db):
        mock_svc.get_by_correlation.return_value = []
        response = client.get(f"/v1/audit/correlation/{uuid4()}")
        assert response.status_code == 404


class TestGetForEntity:
    @patch("src.api.v1.audit.AuditService")
    def test_entity_history(self, mock_svc, client, mock_db):
        entries = [_make_audit_entry(entity_type="PLAN", entity_id="p1")]
        mock_svc.get_for_entity.return_value = entries
        response = client.get("/v1/audit/entity/PLAN/p1")
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestGetByActor:
    @patch("src.api.v1.audit.AuditService")
    def test_actor_entries(self, mock_svc, client, mock_db):
        entries = [_make_audit_entry(actor="admin")]
        mock_svc.get_by_actor.return_value = entries
        response = client.get("/v1/audit/actor/admin")
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestAuditStats:
    @patch("src.api.v1.audit.AuditService")
    def test_stats(self, mock_svc, client, mock_db):
        mock_svc.get_stats.return_value = {
            "total": 100,
            "entries_24h": 10,
            "entries_7d": 50,
            "top_actions": [{"action": "PLAN_COMMITTED", "count": 20}],
            "top_actors": [{"actor": "admin", "count": 30}],
            "top_entity_types": [{"entity_type": "PLAN", "count": 40}],
        }
        response = client.get("/v1/audit/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 100
        assert data["entries_last_24h"] == 10
        assert data["entries_last_7d"] == 50


class TestActionAndEntityTypes:
    @patch("src.api.v1.audit.AuditService")
    def test_list_action_types(self, mock_svc, client, mock_db):
        mock_svc.get_action_types.return_value = ["PLAN_COMMITTED", "SNAPSHOT_CREATED"]
        response = client.get("/v1/audit/actions")
        assert response.status_code == 200
        assert "PLAN_COMMITTED" in response.json()

    @patch("src.api.v1.audit.AuditService")
    def test_list_entity_types(self, mock_svc, client, mock_db):
        mock_svc.get_entity_types.return_value = ["PLAN", "SNAPSHOT"]
        response = client.get("/v1/audit/entity-types")
        assert response.status_code == 200
        assert "PLAN" in response.json()


class TestAuditExport:
    @patch("src.api.v1.audit.AuditService")
    def test_export_basic(self, mock_svc, client, mock_db):
        mock_svc.count_for_export.return_value = 42
        now = datetime.utcnow()
        response = client.post(
            "/v1/audit/export",
            json={
                "start_date": (now - timedelta(days=7)).isoformat(),
                "end_date": now.isoformat(),
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "COMPLETED"
        assert data["entries_count"] == 42
        assert "download_url" in data


class TestAuditSearch:
    @patch("src.api.v1.audit.AuditService")
    def test_search_entries(self, mock_svc, client, mock_db):
        entries = [_make_audit_entry(action="PLAN_COMMITTED")]
        mock_svc.search.return_value = entries
        response = client.get("/v1/audit/search", params={"q": "PLAN"})
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_search_too_short_query(self, client, mock_db):
        response = client.get("/v1/audit/search", params={"q": "P"})
        assert response.status_code == 422

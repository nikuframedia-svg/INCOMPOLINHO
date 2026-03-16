# Tests for Decision Ledger API endpoints
# Conforme Contrato C3: Decision Ledger

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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


def _make_entry_response(**overrides):
    """Create a mock DecisionEntry ORM object."""
    entry = MagicMock()
    entry.id = overrides.get("id", uuid4())
    entry.tenant_id = overrides.get("tenant_id", uuid4())
    entry.user_id = overrides.get("user_id", uuid4())
    entry.decision_type = overrides.get("decision_type", "schedule_override")
    entry.optimal_state = overrides.get("optimal_state", {"tardiness": 0})
    entry.proposed_state = overrides.get("proposed_state", {"tardiness": 60})
    entry.deviation_cost = overrides.get("deviation_cost", Decimal("50.00"))
    entry.incentive_category = overrides.get("incentive_category", "technical")
    entry.declared_reason = overrides.get("declared_reason", "Machine maintenance")
    entry.governance_level = overrides.get("governance_level", "L1")
    entry.contrafactual = overrides.get("contrafactual", None)
    entry.approved_by = overrides.get("approved_by", None)
    entry.approved_at = overrides.get("approved_at", None)
    entry.outcome = overrides.get("outcome", None)
    entry.outcome_variance = overrides.get("outcome_variance", None)
    entry.created_at = overrides.get("created_at", datetime.utcnow())
    return entry


def _make_create_payload(**overrides):
    base = {
        "tenant_id": str(uuid4()),
        "user_id": str(uuid4()),
        "decision_type": "schedule_override",
        "optimal_state": {"tardiness": 0},
        "proposed_state": {"tardiness": 60},
        "deviation_cost": 50.0,
        "incentive_category": "technical",
        "declared_reason": "Machine maintenance",
        "governance_level": "L1",
    }
    base.update(overrides)
    return base


class TestCreateDecisionEntry:
    @patch("src.api.v1.ledger.LedgerService")
    def test_create_entry_success(self, mock_svc, client, mock_db):
        entry = _make_entry_response()
        mock_svc.create_entry.return_value = entry
        response = client.post(
            "/v1/ledger/entries",
            json=_make_create_payload(),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 201

    def test_create_entry_invalid_category(self, client, mock_db):
        response = client.post(
            "/v1/ledger/entries",
            json=_make_create_payload(incentive_category="invalid"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422

    def test_create_entry_invalid_governance_level(self, client, mock_db):
        response = client.post(
            "/v1/ledger/entries",
            json=_make_create_payload(governance_level="X9"),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422


class TestListDecisionEntries:
    @patch("src.api.v1.ledger.LedgerRepository")
    def test_list_empty(self, mock_repo, client, mock_db):
        mock_repo.list_entries.return_value = []
        response = client.get("/v1/ledger/entries")
        assert response.status_code == 200
        assert response.json() == []

    @patch("src.api.v1.ledger.LedgerRepository")
    def test_list_with_filters(self, mock_repo, client, mock_db):
        mock_repo.list_entries.return_value = []
        tid = str(uuid4())
        response = client.get(
            "/v1/ledger/entries",
            params={"tenant_id": tid, "decision_type": "schedule_override", "limit": 50},
        )
        assert response.status_code == 200


class TestGetDecisionEntry:
    @patch("src.api.v1.ledger.LedgerRepository")
    def test_get_entry_not_found(self, mock_repo, client, mock_db):
        mock_repo.get_by_id.return_value = None
        response = client.get(f"/v1/ledger/entries/{uuid4()}")
        assert response.status_code == 404

    @patch("src.api.v1.ledger.LedgerRepository")
    def test_get_entry_found(self, mock_repo, client, mock_db):
        entry = _make_entry_response()
        mock_repo.get_by_id.return_value = entry
        response = client.get(f"/v1/ledger/entries/{entry.id}")
        assert response.status_code == 200


class TestApproveDecisionEntry:
    @patch("src.api.v1.ledger.LedgerService")
    def test_approve_success(self, mock_svc, client, mock_db):
        entry = _make_entry_response(governance_level="L4")
        mock_svc.approve_entry.return_value = entry
        response = client.patch(
            f"/v1/ledger/entries/{entry.id}/approve",
            json={"approved_by": str(uuid4())},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 200


class TestLedgerStats:
    @patch("src.api.v1.ledger.LedgerRepository")
    def test_stats(self, mock_repo, client, mock_db):
        mock_repo.get_stats.return_value = {
            "total_entries": 10,
            "total_deviation_cost": Decimal("500.00"),
            "entries_by_category": {"technical": 5, "commercial_pressure": 5},
            "entries_by_type": {"schedule_override": 10},
            "pending_approvals": 2,
        }
        response = client.get("/v1/ledger/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_entries"] == 10
        assert data["pending_approvals"] == 2

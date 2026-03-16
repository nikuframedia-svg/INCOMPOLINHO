# Testes unitários para middleware
# Conforme SP-BE-01

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_correlation_id_generated(client):
    """Testa que correlation_id é gerado se não fornecido"""
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert "X-Correlation-ID" in response.headers
    correlation_id = response.headers["X-Correlation-ID"]
    assert len(correlation_id) == 36  # UUID format


def test_correlation_id_preserved(client):
    """Testa que correlation_id fornecido é preservado"""
    correlation_id = "123e4567-e89b-12d3-a456-426614174000"
    response = client.get("/v1/health", headers={"X-Correlation-ID": correlation_id})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == correlation_id


def test_idempotency_key_required_for_post(client):
    """Testa que Idempotency-Key é obrigatório para POST"""
    # Nota: Não temos endpoints POST ainda, mas o middleware deve validar
    # Este teste será expandido quando houver endpoints mutáveis
    pass


def test_health_endpoint(client):
    """Testa endpoint /v1/health"""
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_version_endpoint(client):
    """Testa endpoint /v1/version"""
    response = client.get("/v1/version")
    assert response.status_code == 200
    data = response.json()
    assert "service_version" in data
    assert "contracts_version" in data

"""``max_run_days`` (limite de dias seguidos) saiu do contrato a 09/10/2026.

O GET deixa de o expor e o PUT ignora-o quando um cliente antigo o envia:
a gravação não pode falhar por causa de uma chave retirada.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api import data as data_api
from backend.api.copilot import app
from backend.copilot.state import state
from tests.test_api_validation import _mutation, loaded_state  # noqa: F401


def test_get_config_no_longer_exposes_max_run_days():
    response = TestClient(app).get("/api/data/config")

    assert response.status_code == 200
    assert "max_run_days" not in response.json()


def test_put_config_with_only_retired_key_is_a_no_op():
    assert state.config.max_run_days is None

    response = TestClient(app).put(
        "/api/data/config",
        json=_mutation({"max_run_days": 5}),
    )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == []
    assert state.config.max_run_days is None


def test_put_config_ignores_retired_key_and_saves_the_rest(monkeypatch):
    monkeypatch.setattr(
        data_api,
        "_recompute",
        lambda _config: SimpleNamespace(time_ms=1.0),
    )

    response = TestClient(app).put(
        "/api/data/config",
        json=_mutation({"max_run_days": None, "compact_enabled": "true"}),
    )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == ["compact_enabled"]
    assert state.config.compact_enabled is True
    assert state.config.max_run_days is None

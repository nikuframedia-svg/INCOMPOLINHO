"""A failed move check stores a stable code and Portuguese text, never str(exc)."""

from __future__ import annotations

import threading

import pytest

from backend.planning_control import PlanningTimeout
from backend.plans import manual_move_jobs
from backend.plans.manual_move_jobs import INTERNAL_ERROR_TEXT, ManualMoveJobManager


@pytest.fixture
def manager():
    created = ManualMoveJobManager()
    yield created
    created.executor.shutdown(wait=True)


def _run(manager, monkeypatch, failure):
    def move_lot(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(manual_move_jobs, "move_lot", move_lot)
    manager.jobs["J"] = {"id": "J", "status": "queued", "created_at": "2026-10-10T00:00:00+00:00"}
    manager._run(
        "J", threading.Event(), [], [], {}, None, None,
        "LOT", 3, None, None, "teste", "planeador",
    )
    return manager.get("J")


def test_unexpected_error_is_coded_and_portuguese(manager, monkeypatch):
    job = _run(manager, monkeypatch, KeyError("unexpected english failure"))
    assert job["status"] == "failed"
    assert job["code"] == "internal_error"
    assert job["error"] == INTERNAL_ERROR_TEXT
    assert "english" not in job["error"] and "KeyError" not in job["error"]
    assert "não foi alterado" in job["error"]


def test_timeout_is_coded(manager, monkeypatch):
    job = _run(manager, monkeypatch, PlanningTimeout("Planning deadline expired"))
    assert job["code"] == "planning_timeout"
    assert "Planning deadline" not in job["error"]

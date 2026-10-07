"""Tests can never write the running factory's configuration or data (07/10/2026)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import textwrap

import pytest

from backend.config.loader import load_config, save_config
from backend.runtime_guard import (
    LIVE_DIRS,
    REPO_ROOT,
    LiveDataWriteError,
    assert_isolated_environment,
    assert_writable,
)

LIVE_CONFIG = REPO_ROOT / "config" / "factory.yaml"


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def test_suite_runs_isolated_from_live_files():
    for name in ("PP1_CONFIG_PATH", "PP1_DATA_DIR"):
        value = os.path.realpath(os.environ[name])
        assert not any(value.startswith(str(live)) for live in LIVE_DIRS), name


@pytest.mark.parametrize("relative", ["config/factory.yaml", "data/plans.db", "data/new.json"])
def test_writes_into_live_directories_are_refused(relative):
    with pytest.raises(LiveDataWriteError):
        assert_writable(REPO_ROOT / relative)


def test_writes_elsewhere_are_allowed(tmp_path):
    assert_writable(tmp_path / "factory.yaml")


def test_save_config_refuses_the_live_file_before_touching_it():
    before = _digest(LIVE_CONFIG)
    with pytest.raises(LiveDataWriteError):
        save_config(load_config(os.environ["PP1_CONFIG_PATH"]), str(LIVE_CONFIG))
    assert _digest(LIVE_CONFIG) == before


@pytest.mark.parametrize("missing", ["PP1_CONFIG_PATH", "PP1_DATA_DIR"])
def test_environment_without_isolation_is_refused(monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(LiveDataWriteError):
        assert_isolated_environment()


def test_environment_pointing_at_live_files_is_refused(monkeypatch):
    monkeypatch.setenv("PP1_CONFIG_PATH", str(LIVE_CONFIG))
    with pytest.raises(LiveDataWriteError):
        assert_isolated_environment()


def test_a_test_run_outside_tests_dir_fails_without_touching_live_config(tmp_path):
    """The exact incident: pytest on a file outside tests/, so no conftest."""
    probe = tmp_path / "test_probe.py"
    probe.write_text(textwrap.dedent("""
        from backend.config.loader import DEFAULT_CONFIG_PATH, load_config, save_config

        def test_probe():
            save_config(load_config(DEFAULT_CONFIG_PATH), DEFAULT_CONFIG_PATH)
    """))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PP1_")}
    env["PYTHONPATH"] = str(REPO_ROOT)
    before = _digest(LIVE_CONFIG)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(probe)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode != 0
    assert "Testes sem isolamento" in completed.stdout + completed.stderr
    assert _digest(LIVE_CONFIG) == before

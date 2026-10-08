"""Keep automated tests away from the running factory's durable files.

On 07/10/2026 a test run outside ``tests/`` (so without ``tests/conftest.py``)
fell back to the default paths and overwrote ``config/factory.yaml``. Two
guards prevent a repeat whenever the code runs inside pytest:

* ``assert_isolated_environment`` (called when ``backend`` is imported):
  ``PP1_CONFIG_PATH`` and ``PP1_DATA_DIR`` must be set and point outside the
  repository's live ``config/`` and ``data/`` directories;
* ``assert_writable`` (called by the durable writers): refuses any write
  into those directories, whatever the environment says.

Outside pytest nothing changes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_DIRS = (REPO_ROOT / "config", REPO_ROOT / "data")


class LiveDataWriteError(RuntimeError):
    """A test tried to read or write the running application's files."""


def under_pytest() -> bool:
    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


def _is_live(path: str | os.PathLike) -> bool:
    resolved = Path(path).resolve()
    return any(resolved == live or live in resolved.parents for live in LIVE_DIRS)


def assert_isolated_environment() -> None:
    if not under_pytest():
        return
    problems = []
    for name in ("PP1_CONFIG_PATH", "PP1_DATA_DIR"):
        value = os.environ.get(name)
        if not value:
            problems.append(f"{name} não definido")
        elif _is_live(value):
            problems.append(f"{name}={value} aponta para os ficheiros reais")
    if problems:
        raise LiveDataWriteError(
            "Testes sem isolamento: " + "; ".join(problems)
            + ". Corra o pytest a partir de tests/ (o conftest cria uma pasta temporária)."
        )


def assert_writable(path: str | os.PathLike) -> None:
    if under_pytest() and _is_live(path):
        raise LiveDataWriteError(f"Escrita recusada durante testes: {Path(path).resolve()}")

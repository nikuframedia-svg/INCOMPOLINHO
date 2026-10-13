"""Keep the test suite away from the running application's durable files."""

import os
import shutil
import tempfile
from pathlib import Path


_storage = tempfile.TemporaryDirectory(prefix="pp1-tests-")
_root = Path(__file__).resolve().parents[1]
_config = Path(_storage.name) / "factory.yaml"
shutil.copy2(_root / "config" / "factory.yaml", _config)
os.environ["PP1_DATA_DIR"] = _storage.name
os.environ["PP1_CONFIG_PATH"] = str(_config)
# Commits start no background robustness battery unless a test opts in.
os.environ["PP1_AUTO_ROBUSTNESS"] = "0"


import pytest  # noqa: E402


@pytest.fixture
def legacy_engine(monkeypatch):
    """Lots sized without a material version (version 0, before 08/10/2026).

    Since material version 3 (13/10/2026) every current lot is planned by the
    quantity builder; the legacy engine (global constructor, dispatch audit
    trail, final scheduler passes) only plans lots of such older plans. Tests
    of that engine pin this version, in every module that holds it (some
    import the constant by value, e.g. ``canonical``).
    """
    import sys

    import backend.scheduler.canonical  # noqa: F401  (holds the constant by value)

    for name, module in list(sys.modules.items()):
        if name.startswith("backend.") and hasattr(module, "QUANTITY_MATERIAL_VERSION"):
            monkeypatch.setattr(module, "QUANTITY_MATERIAL_VERSION", 0)

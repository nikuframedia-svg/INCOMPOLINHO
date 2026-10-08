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

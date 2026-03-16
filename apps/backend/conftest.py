"""Root conftest — exclude macOS duplicate files from collection."""

from __future__ import annotations

import pathlib

collect_ignore_glob = [str(p) for p in pathlib.Path(".").rglob("* [0-9]*")]

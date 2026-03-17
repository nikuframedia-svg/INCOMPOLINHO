"""Settings store — in-memory singleton with JSON file persistence.

Phase 1: JSON file on disk (data/settings.json).
Phase 2 (F3-01): PostgreSQL via SQLAlchemy.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .schema import SettingsModel, SettingsUpdate

# Default path for settings file
_DEFAULT_PATH = Path(__file__).parent.parent.parent.parent / "data" / "settings.json"


class SettingsStore:
    """Thread-safe settings singleton with JSON persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._lock = threading.Lock()
        self._settings = SettingsModel()
        self._load()

    def _load(self) -> None:
        """Load settings from disk if file exists."""
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._settings = SettingsModel(**raw)
            except Exception:
                # Corrupted file — use defaults
                self._settings = SettingsModel()

    def _save(self) -> None:
        """Persist settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = self._settings.model_dump(mode="json")
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get(self) -> SettingsModel:
        """Return current settings (immutable copy)."""
        with self._lock:
            return self._settings.model_copy()

    def get_dict(self) -> dict[str, Any]:
        """Return settings as JSON-serializable dict."""
        with self._lock:
            return self._settings.model_dump(mode="json")

    def update(self, patch: SettingsUpdate) -> SettingsModel:
        """Apply partial update and persist."""
        with self._lock:
            current = self._settings.model_dump()
            updates = patch.model_dump(exclude_none=True)
            current.update(updates)
            self._settings = SettingsModel(**current)
            self._save()
            return self._settings.model_copy()

    def replace(self, full: SettingsModel) -> SettingsModel:
        """Full replacement of all settings."""
        with self._lock:
            self._settings = full.model_copy()
            self._save()
            return self._settings.model_copy()

    def reset(self) -> SettingsModel:
        """Reset to defaults."""
        with self._lock:
            self._settings = SettingsModel()
            self._save()
            return self._settings.model_copy()


# ── Module-level singleton ──
settings_store = SettingsStore()

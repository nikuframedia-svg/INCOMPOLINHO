"""Settings API — GET/PUT /v1/settings + schema endpoint.

Exposes the 41 scheduling settings via REST API.
Frontend can sync its localStorage settings with the backend.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...core.logging import get_logger
from ...domain.settings.schema import SettingsModel, SettingsUpdate
from ...domain.settings.store import settings_store

logger = get_logger(__name__)

settings_router = APIRouter(prefix="/settings", tags=["settings"])


@settings_router.get("", response_model=SettingsModel)
async def get_settings() -> SettingsModel:
    """Return current settings."""
    return settings_store.get()


@settings_router.put("", response_model=SettingsModel)
async def update_settings(patch: SettingsUpdate) -> SettingsModel:
    """Partial update — only send fields to change."""
    updated = settings_store.update(patch)
    logger.info(
        "settings.updated",
        fields=list(patch.model_dump(exclude_none=True).keys()),
    )
    return updated


@settings_router.post("/reset", response_model=SettingsModel)
async def reset_settings() -> SettingsModel:
    """Reset all settings to defaults."""
    result = settings_store.reset()
    logger.info("settings.reset")
    return result


@settings_router.get("/schema")
async def get_settings_schema() -> dict:
    """Return JSON Schema for settings model (for dynamic UI generation)."""
    return SettingsModel.model_json_schema()

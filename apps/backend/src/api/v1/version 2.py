# Version endpoint
# Conforme SP-BE-01

from fastapi import APIRouter
from pydantic import BaseModel

from ...core.config import settings
from ...core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/version", tags=["version"])


class VersionResponse(BaseModel):
    service_version: str
    contracts_version: str


@router.get("", response_model=VersionResponse)
async def version():
    """Version endpoint"""
    logger.info("Version check requested")
    return VersionResponse(
        service_version=settings.app_version,
        contracts_version="20260204.1",  # Versão atual dos contratos
    )

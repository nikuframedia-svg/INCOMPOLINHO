# Health endpoint
# Conforme SP-BE-01

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ...core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    logger.info("Health check requested")
    return HealthResponse(status="ok")

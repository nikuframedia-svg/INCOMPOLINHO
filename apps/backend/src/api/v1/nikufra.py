# Nikufra Data API
# Serves combined ISOP + PP data for the NikufraPlan frontend component

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ...core.config import settings
from ...core.errors import APIException, ErrorCodes
from ...core.logging import get_logger
from ...domain.copilot.state import copilot_state

logger = get_logger(__name__)

nikufra_router = APIRouter(prefix="/nikufra", tags=["nikufra"])

# Lazy-init service singleton
_service = None


def _get_service():
    global _service
    if _service is None:
        from ...domain.nikufra.service import NikufraService

        data_dir = Path(getattr(settings, "nikufra_data_dir", "data/nikufra"))
        if not data_dir.is_absolute():
            # Resolve relative to backend root
            data_dir = Path(__file__).resolve().parents[3] / data_dir
        if not data_dir.exists():
            raise APIException(
                status_code=500,
                code=ErrorCodes.ERR_SERVER_ERROR,
                message=f"Nikufra data directory not found: {data_dir}",
            )
        _service = NikufraService(data_dir)
    return _service


@nikufra_router.get("/data")
async def get_nikufra_data() -> dict[str, Any]:
    """Return combined ISOP + PP data for the NikufraPlan component (V1 format).

    Response contains:
    - dates: 8-day horizon labels
    - days_label: day-of-week labels
    - mo: MO load per area per day
    - machines: machine blocks with MAN minutes
    - tools: tool master data with rates and stock
    - operations: production operations with daily quantities
    - history: recent event history
    """
    try:
        service = _get_service()
        data = service.get_data()
        # Include ISOP reference date (first date from ISOP, not system date)
        if service.isop_date:
            data["isop_date"] = service.isop_date.isoformat()

        # ── Populate copilot state ──
        copilot_state.isop_data = data
        copilot_state.isop_date = data.get("isop_date")

        # Compute coverage alerts if SKU data available
        skus = data.get("skus")
        if skus and isinstance(skus, dict):
            try:
                from ...domain.stock_alerts.coverage_engine import compute_coverage_alerts

                alerts = compute_coverage_alerts(skus)
                copilot_state.alerts = [
                    a.model_dump() if hasattr(a, "model_dump") else a.dict() for a in alerts
                ]
            except Exception as alert_err:
                logger.warning(f"Could not compute coverage alerts: {alert_err}")

        return data
    except FileNotFoundError as e:
        raise APIException(status_code=404, code=ErrorCodes.ERR_NOT_FOUND, message=str(e))
    except Exception as e:
        logger.error(f"Error loading Nikufra data: {e}")
        raise APIException(
            status_code=500,
            code=ErrorCodes.ERR_SERVER_ERROR,
            message=f"Failed to load data: {str(e)}",
        )


@nikufra_router.post("/upload")
async def upload_isop_data(data: dict) -> dict:
    """Receive ISOP data from frontend for copilot context."""
    copilot_state.isop_data = data
    copilot_state.isop_date = data.get("isop_date")

    # Compute basic alerts from SKU data
    skus = data.get("skus")
    if skus and isinstance(skus, dict):
        alerts = []
        for sku_code, s in skus.items():
            atr = s.get("atraso", 0)
            if isinstance(atr, (int, float)) and atr < 0:
                alerts.append(
                    {"severity": "atraso", "message": f"Ref {sku_code} em atraso ({atr})"}
                )
        copilot_state.alerts = alerts

    n = len(skus) if skus else 0
    logger.info("nikufra.upload", skus_loaded=n)
    return {"status": "ok", "skus_loaded": n}


@nikufra_router.post("/reload")
async def reload_nikufra_data() -> dict[str, Any]:
    """Force re-parse of all source files and return fresh data."""
    try:
        service = _get_service()
        data = service.reload()

        # ── Populate copilot state on reload ──
        copilot_state.isop_data = data
        if service.isop_date:
            copilot_state.isop_date = service.isop_date.isoformat()

        return data
    except FileNotFoundError as e:
        raise APIException(status_code=404, code=ErrorCodes.ERR_NOT_FOUND, message=str(e))
    except Exception as e:
        logger.error(f"Error reloading Nikufra data: {e}")
        raise APIException(
            status_code=500, code=ErrorCodes.ERR_SERVER_ERROR, message=f"Failed to reload: {str(e)}"
        )

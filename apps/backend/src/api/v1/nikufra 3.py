# Nikufra Data API
# Serves combined ISOP + PP data for the NikufraPlan frontend component

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from ...core.config import settings
from ...core.errors import APIException, ErrorCodes
from ...core.logging import get_logger

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
        return service.get_data()
    except FileNotFoundError as e:
        raise APIException(status_code=404, code=ErrorCodes.ERR_NOT_FOUND, message=str(e))
    except Exception as e:
        logger.error(f"Error loading Nikufra data: {e}")
        raise APIException(
            status_code=500,
            code=ErrorCodes.ERR_SERVER_ERROR,
            message=f"Failed to load data: {str(e)}",
        )


@nikufra_router.post("/reload")
async def reload_nikufra_data() -> dict[str, Any]:
    """Force re-parse of all source files and return fresh data."""
    try:
        service = _get_service()
        return service.reload()
    except FileNotFoundError as e:
        raise APIException(status_code=404, code=ErrorCodes.ERR_NOT_FOUND, message=str(e))
    except Exception as e:
        logger.error(f"Error reloading Nikufra data: {e}")
        raise APIException(
            status_code=500, code=ErrorCodes.ERR_SERVER_ERROR, message=f"Failed to reload: {str(e)}"
        )

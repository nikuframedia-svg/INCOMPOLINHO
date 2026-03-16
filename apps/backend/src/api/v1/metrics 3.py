# Metrics API endpoint
# Conforme SP-OBS-01

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.logging import get_logger
from ...core.metrics import get_metrics_collector
from ...db.base import get_db

logger = get_logger(__name__)

metrics_router = APIRouter(prefix="/metrics", tags=["observability"])


@metrics_router.get("")
def get_metrics(db: Session = Depends(get_db)):
    """
    Obtém métricas do sistema.

    Conforme SP-OBS-01:
    - Retorna contadores, timers (stats), e gauges
    - Útil para monitorização e SLOs

    Returns:
        Dict com métricas
    """
    collector = get_metrics_collector()
    metrics = collector.get_metrics()

    logger.debug("Metrics requested", extra={"metrics_count": len(metrics.get("counters", {}))})

    return metrics

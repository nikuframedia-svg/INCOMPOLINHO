# Logging estruturado
# Conforme SP-BE-01 e C-15

import logging
import sys

from pythonjsonlogger import jsonlogger

from .config import settings


class CorrelationFilter(logging.Filter):
    """Filter para adicionar correlation_id aos logs"""

    def __init__(self):
        super().__init__()
        self.correlation_id: str | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        if self.correlation_id:
            record.correlation_id = self.correlation_id
        return True


correlation_filter = CorrelationFilter()


def setup_logging():
    """Configurar logging estruturado conforme C-15"""

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Remover handlers existentes
    root_logger.handlers.clear()

    # Handler para stdout
    handler = logging.StreamHandler(sys.stdout)

    if settings.log_format == "json":
        # Logging estruturado (JSON)
        formatter = jsonlogger.JsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s %(correlation_id)s",
            timestamp=True,
        )
    else:
        # Logging texto (desenvolvimento)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s [correlation_id=%(correlation_id)s]"
        )

    handler.setFormatter(formatter)
    handler.addFilter(correlation_filter)
    root_logger.addHandler(handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Obter logger com nome"""
    logger = logging.getLogger(name)
    return logger

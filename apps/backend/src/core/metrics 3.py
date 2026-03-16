# Metrics collection
# Conforme SP-OBS-01

import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from .logging import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """
    Coletor de métricas simples (v0).

    Conforme SP-OBS-01:
    - Métricas para SLOs
    - Timers para performance
    - Contadores para eventos

    Nota: Implementação v0 em memória. Em produção, integrar com Prometheus/StatsD.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timers: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}
        self._start_times: dict[str, float] = {}

    def increment(self, metric_name: str, value: int = 1, tags: dict[str, str] | None = None):
        """
        Incrementa contador.

        Args:
            metric_name: Nome da métrica
            value: Valor a incrementar (default: 1)
            tags: Tags opcionais (não usados em v0)
        """
        with self._lock:
            self._counters[metric_name] += value
            logger.debug(
                f"Metric incremented: {metric_name}",
                extra={
                    "metric_name": metric_name,
                    "value": value,
                    "total": self._counters[metric_name],
                },
            )

    def timer_start(self, metric_name: str) -> str:
        """
        Inicia timer.

        Args:
            metric_name: Nome da métrica

        Returns:
            Timer ID (para usar em timer_stop)
        """
        timer_id = f"{metric_name}_{time.time()}_{id(self)}"
        with self._lock:
            self._start_times[timer_id] = time.time()
        return timer_id

    def timer_stop(self, timer_id: str, metric_name: str | None = None):
        """
        Para timer e registra duração.

        Args:
            timer_id: ID do timer (retornado por timer_start)
            metric_name: Nome da métrica (opcional, extraído do timer_id se não fornecido)
        """
        with self._lock:
            if timer_id not in self._start_times:
                logger.warning(f"Timer not found: {timer_id}")
                return

            start_time = self._start_times.pop(timer_id)
            duration_ms = (time.time() - start_time) * 1000

            if metric_name is None:
                # Extrair metric_name do timer_id
                metric_name = timer_id.split("_")[0]

            self._timers[metric_name].append(duration_ms)

            # Manter apenas últimas 1000 medições
            if len(self._timers[metric_name]) > 1000:
                self._timers[metric_name] = self._timers[metric_name][-1000:]

            logger.debug(
                f"Timer stopped: {metric_name}",
                extra={"metric_name": metric_name, "duration_ms": duration_ms},
            )

    def gauge_set(self, metric_name: str, value: float, tags: dict[str, str] | None = None):
        """
        Define valor de gauge.

        Args:
            metric_name: Nome da métrica
            value: Valor do gauge
            tags: Tags opcionais (não usados em v0)
        """
        with self._lock:
            self._gauges[metric_name] = value
            logger.debug(
                f"Gauge set: {metric_name}",
                extra={"metric_name": metric_name, "value": value},
            )

    def get_metrics(self) -> dict[str, Any]:
        """
        Obtém todas as métricas.

        Returns:
            Dict com contadores, timers (stats), e gauges
        """
        with self._lock:
            timer_stats = {}
            for metric_name, durations in self._timers.items():
                if durations:
                    timer_stats[metric_name] = {
                        "count": len(durations),
                        "min_ms": min(durations),
                        "max_ms": max(durations),
                        "mean_ms": sum(durations) / len(durations),
                        "p50_ms": sorted(durations)[len(durations) // 2] if durations else 0,
                        "p95_ms": sorted(durations)[int(len(durations) * 0.95)] if durations else 0,
                        "p99_ms": sorted(durations)[int(len(durations) * 0.99)] if durations else 0,
                    }

            return {
                "counters": dict(self._counters),
                "timers": timer_stats,
                "gauges": dict(self._gauges),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

    def reset(self):
        """Reseta todas as métricas (útil para testes)"""
        with self._lock:
            self._counters.clear()
            self._timers.clear()
            self._gauges.clear()
            self._start_times.clear()


# Instância global
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Obtém instância global do coletor de métricas"""
    return _metrics_collector


def increment(metric_name: str, value: int = 1, tags: dict[str, str] | None = None):
    """Helper para incrementar contador"""
    _metrics_collector.increment(metric_name, value, tags)


def timer_start(metric_name: str) -> str:
    """Helper para iniciar timer"""
    return _metrics_collector.timer_start(metric_name)


def timer_stop(timer_id: str, metric_name: str | None = None):
    """Helper para parar timer"""
    _metrics_collector.timer_stop(timer_id, metric_name)


def gauge_set(metric_name: str, value: float, tags: dict[str, str] | None = None):
    """Helper para definir gauge"""
    _metrics_collector.gauge_set(metric_name, value, tags)

# Middleware para correlation_id e Idempotency-Key
# Conforme SP-BE-01, C-00, C-15

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .errors import ErrorCodes, ErrorModel
from .logging import correlation_filter, get_logger
from .metrics import increment, timer_start, timer_stop

logger = get_logger(__name__)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware para correlation_id (obrigatório conforme C-15)"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extrair ou gerar correlation_id
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            # Gerar UUID se não fornecido
            correlation_id = str(uuid.uuid4())
            logger.info(f"Generated correlation_id: {correlation_id}")

        # Validar formato UUID
        try:
            uuid.UUID(correlation_id)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=ErrorModel(
                    code=ErrorCodes.ERR_INVALID_UUID,
                    message=f"Invalid correlation_id format: {correlation_id}",
                ).model_dump(),
            )

        # Definir correlation_id no filter para logs
        correlation_filter.correlation_id = correlation_id

        # Adicionar correlation_id à resposta
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id

        return response


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware para Idempotency-Key (obrigatório em requests mutáveis conforme C-00)"""

    # Store simples em memória (em produção, usar Redis ou DB)
    _idempotency_store: dict[str, tuple[Response, float]] = {}
    _TTL_SECONDS = 3600  # 1 hour TTL for cached responses
    _MAX_ENTRIES = 10000  # Hard limit to prevent unbounded growth

    def _cleanup_expired(self) -> None:
        """Remove entries older than TTL to prevent memory leak."""
        now = time.time()
        expired = [
            k for k, (_, ts) in self._idempotency_store.items() if now - ts > self._TTL_SECONDS
        ]
        for k in expired:
            del self._idempotency_store[k]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Verificar se é request mutável
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            idempotency_key = request.headers.get("Idempotency-Key")

            if not idempotency_key:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=ErrorModel(
                        code=ErrorCodes.ERR_IDEMPOTENCY_KEY_CONFLICT,
                        message="Idempotency-Key header is required for mutating requests",
                        correlation_id=correlation_filter.correlation_id,
                    ).model_dump(),
                )

            # Validar formato UUID
            try:
                uuid.UUID(idempotency_key)
            except ValueError:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=ErrorModel(
                        code=ErrorCodes.ERR_INVALID_UUID,
                        message=f"Invalid Idempotency-Key format: {idempotency_key}",
                        correlation_id=correlation_filter.correlation_id,
                    ).model_dump(),
                )

            # Periodic cleanup of expired entries
            if len(self._idempotency_store) > self._MAX_ENTRIES // 2:
                self._cleanup_expired()

            # Verificar se já existe resposta para esta key
            if idempotency_key in self._idempotency_store:
                stored_response, _ = self._idempotency_store[idempotency_key]
                logger.info(f"Returning cached response for Idempotency-Key: {idempotency_key}")
                # Criar nova resposta a partir da armazenada
                return Response(
                    content=stored_response.body,
                    status_code=stored_response.status_code,
                    headers=dict(stored_response.headers),
                    media_type=stored_response.media_type,
                )

            # Processar request
            response = await call_next(request)

            # Armazenar resposta se sucesso (2xx)
            if 200 <= response.status_code < 300:
                # Ler corpo da resposta uma vez
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk

                # Criar resposta armazenável
                stored_response = Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

                # Armazenar (com timestamp para limpeza futura)
                self._idempotency_store[idempotency_key] = (stored_response, time.time())

                # Retornar resposta original
                return Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

            # Non-2xx: return the error response as-is
            return response

        # Request não mutável ou não precisa de idempotency
        return await call_next(request)


class AuditMiddleware(BaseHTTPMiddleware):
    """Middleware para auto-captura de ações mutáveis no audit_log (C-15).

    Logs successful POST/PUT/PATCH/DELETE requests to the audit_log table
    using the correlation_id from CorrelationMiddleware.
    """

    # Map path patterns → (action, entity_type)
    _ROUTE_MAP = {
        "POST:/v1/snapshots/import": ("SNAPSHOT_IMPORTED", "SNAPSHOT"),
        "POST:/v1/events": ("EVENT_RECEIVED", "EVENT"),
        "POST:/v1/audit/export": ("AUDIT_EXPORTED", "AUDIT"),
    }

    # Dynamic patterns: POST /v1/{prefix}/{id}/{action_suffix}
    _DYNAMIC_PATTERNS = {
        ("POST", "snapshots", "seal"): ("SNAPSHOT_SEALED", "SNAPSHOT"),
        ("POST", "plans", "commit"): ("PLAN_COMMITTED", "PLAN"),
    }

    # Paths to skip (read-only or internal)
    _SKIP_PREFIXES = (
        "/v1/health",
        "/v1/version",
        "/v1/metrics",
        "/v1/audit/entries",
        "/v1/audit/search",
        "/v1/audit/stats",
        "/v1/audit/actions",
        "/v1/audit/entity-types",
        "/v1/audit/correlation",
        "/v1/audit/actor",
        "/v1/audit/entity",
    )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Only intercept mutating methods
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return await call_next(request)

        path = request.url.path
        method = request.method

        # Skip paths that shouldn't be audited
        if any(path.startswith(p) for p in self._SKIP_PREFIXES):
            return await call_next(request)

        # Process the request
        response = await call_next(request)

        # Only audit successful mutations
        if not (200 <= response.status_code < 300):
            return response

        # Resolve action + entity from path
        action, entity_type, entity_id = self._resolve_action(method, path)
        if not action:
            return response

        # Write audit entry asynchronously (fire-and-forget, non-blocking)
        try:
            self._write_audit(
                actor=request.headers.get("X-Actor", "system-api"),
                action=action,
                correlation_id=correlation_filter.correlation_id or str(uuid.uuid4()),
                entity_type=entity_type,
                entity_id=entity_id or "unknown",
                metadata={
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                },
            )
        except Exception as exc:
            # Never fail the request due to audit write failure
            logger.warning(f"Audit middleware write failed: {exc}")

        return response

    def _resolve_action(self, method: str, path: str):
        """Resolve action name, entity_type, entity_id from HTTP method + path."""
        key = f"{method}:{path}"

        # Exact match
        if key in self._ROUTE_MAP:
            action, entity_type = self._ROUTE_MAP[key]
            return action, entity_type, None

        # Dynamic match: /v1/{prefix}/{id}/{suffix}
        parts = path.strip("/").split("/")
        # parts: ["v1", "prs", "pr-001", "approve"]
        if len(parts) >= 4:
            prefix = parts[1]  # e.g. "prs"
            eid = parts[2]  # e.g. "pr-001"
            suffix = parts[3]  # e.g. "approve"
            dkey = (method, prefix, suffix)
            if dkey in self._DYNAMIC_PATTERNS:
                action, entity_type = self._DYNAMIC_PATTERNS[dkey]
                return action, entity_type, eid

        return None, None, None

    def _write_audit(self, *, actor, action, correlation_id, entity_type, entity_id, metadata):
        """Write audit entry using a fresh DB session (independent of request session)."""
        from ..db.base import SessionLocal
        from ..domain.models.audit import AuditLog

        db = SessionLocal()
        try:
            entry = AuditLog(
                audit_id=uuid.uuid4(),
                actor=actor,
                action=action,
                correlation_id=uuid.UUID(correlation_id)
                if isinstance(correlation_id, str)
                else correlation_id,
                entity_type=entity_type,
                entity_id=entity_id,
                audit_metadata=metadata,
            )
            db.add(entry)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware para logging de requests (duration_ms conforme SP-BE-01)"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Iniciar timer para métricas
        timer_id = timer_start(f"http_request.{request.method.lower()}.{request.url.path}")

        # Incrementar contador de requests
        increment("http_requests_total", tags={"method": request.method, "path": request.url.path})

        # Log request start
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "correlation_id": correlation_filter.correlation_id,
            },
        )

        try:
            # Processar request
            response = await call_next(request)

            # Calcular duration
            duration_ms = int((time.time() - start_time) * 1000)

            # Parar timer
            timer_stop(timer_id, f"http_request.{request.method.lower()}.{request.url.path}")

            # Incrementar contador de sucesso/erro
            if 200 <= response.status_code < 300:
                increment(
                    "http_requests_success",
                    tags={
                        "method": request.method,
                        "path": request.url.path,
                        "status": str(response.status_code),
                    },
                )
            else:
                increment(
                    "http_requests_error",
                    tags={
                        "method": request.method,
                        "path": request.url.path,
                        "status": str(response.status_code),
                    },
                )

            # Log request end
            logger.info(
                f"Request completed: {request.method} {request.url.path} - {response.status_code}",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "correlation_id": correlation_filter.correlation_id,
                },
            )

            # Adicionar duration_ms ao header (opcional, para debugging)
            response.headers["X-Request-Duration-Ms"] = str(duration_ms)

            return response
        except Exception:
            # Parar timer em caso de erro
            timer_stop(timer_id, f"http_request.{request.method.lower()}.{request.url.path}")
            increment(
                "http_requests_error",
                tags={"method": request.method, "path": request.url.path, "status": "500"},
            )
            raise

# API key authentication stub
# When api_keys is empty (dev mode), auth is skipped entirely.

from __future__ import annotations

from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

# Paths that skip auth regardless
_PUBLIC_PATHS = ("/health", "/version", "/docs", "/redoc", "/openapi.json")


class AuthMiddleware(BaseHTTPMiddleware):
    """Validate X-API-Key header against configured api_keys."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Dev mode: no keys configured → skip auth
        if not settings.api_keys:
            return await call_next(request)

        # Public endpoints skip auth
        path = request.url.path
        if any(path.endswith(p) or f"{p}/" in path for p in _PUBLIC_PATHS):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key not in settings.api_keys:
            return JSONResponse(
                status_code=401,
                content={
                    "code": "ERR_UNAUTHORIZED",
                    "message": "Invalid or missing API key",
                },
            )

        return await call_next(request)

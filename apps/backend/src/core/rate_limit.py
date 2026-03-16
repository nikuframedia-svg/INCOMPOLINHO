# Simple in-memory rate limiter middleware
# Default: 100 req/min per IP, 10 req/min for /solver/ endpoints

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiter with stricter limits for solver endpoints."""

    def __init__(self, app, default_rpm: int = 100, solver_rpm: int = 10):
        super().__init__(app)
        self.default_rpm = default_rpm
        self.solver_rpm = solver_rpm
        # {ip: [(timestamp, ...)]]}
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._window = 60.0  # 1 minute window

    def _cleanup(self, key: str, now: float) -> None:
        """Remove entries older than the window."""
        cutoff = now - self._window
        self._hits[key] = [t for t in self._hits[key] if t > cutoff]

    def _is_rate_limited(self, key: str, limit: int) -> bool:
        now = time.monotonic()
        self._cleanup(key, now)
        if len(self._hits[key]) >= limit:
            return True
        self._hits[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Determine rate limit based on path
        is_solver = "/solver/" in path or path.endswith("/solver")
        limit = self.solver_rpm if is_solver else self.default_rpm
        key = f"{client_ip}:solver" if is_solver else client_ip

        if self._is_rate_limited(key, limit):
            return JSONResponse(
                status_code=429,
                content={
                    "code": "ERR_RATE_LIMITED",
                    "message": f"Rate limit exceeded: {limit} requests/min",
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)

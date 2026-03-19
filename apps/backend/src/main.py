# Main application
# Conforme SP-BE-01

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend root (works regardless of cwd)
_backend_root = Path(__file__).resolve().parent.parent
load_dotenv(_backend_root / ".env")

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import router as v1_router
from .core.auth import AuthMiddleware
from .core.config import settings
from .core.errors import APIException
from .core.exception_handler import (
    api_exception_handler,
    general_exception_handler,
    validation_exception_handler,
)
from .core.logging import setup_logging
from .core.middleware import (
    AuditMiddleware,
    CorrelationMiddleware,
    IdempotencyMiddleware,
    RequestLoggingMiddleware,
)
from .core.rate_limit import RateLimitMiddleware

# Setup logging
setup_logging()

# Criar app FastAPI
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Adicionar middleware (ordem importa!)
# Starlette processes middleware in reverse order of add_middleware calls.
# So the first added is the outermost (runs last on request, first on response).
app.add_middleware(CorrelationMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(IdempotencyMiddleware)
app.add_middleware(AuditMiddleware)
app.add_middleware(RequestLoggingMiddleware)

# Exception handlers
app.add_exception_handler(APIException, api_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

# Incluir routers
app.include_router(v1_router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "api_version": settings.api_version,
    }

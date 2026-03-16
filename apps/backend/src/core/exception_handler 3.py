# Exception handler global
# Conforme SP-BE-01

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import settings
from .errors import APIException, ErrorCodes, ErrorModel
from .logging import correlation_filter, get_logger

logger = get_logger(__name__)


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    """Handler para APIException (com ErrorModel)"""
    error_model = exc.to_error_model()
    logger.error(
        f"API Exception: {exc.code} - {exc.detail}",
        extra={
            "code": exc.code,
            "correlation_id": exc.correlation_id,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_model.model_dump(),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handler para erros de validação do Pydantic"""
    error_model = ErrorModel(
        code=ErrorCodes.ERR_INVALID_UUID,  # Usar código genérico de validação
        message="Validation error",
        correlation_id=correlation_filter.correlation_id,
        details={"errors": exc.errors()},
    )
    logger.warning(
        f"Validation error: {exc.errors()}",
        extra={"correlation_id": correlation_filter.correlation_id},
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_model.model_dump(),
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler para exceções genéricas"""
    correlation_id = correlation_filter.correlation_id

    # Log erro completo
    logger.exception(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)}",
        extra={"correlation_id": correlation_id},
    )

    # Criar ErrorModel
    error_model = ErrorModel(
        code=ErrorCodes.ERR_NETWORK_ERROR,
        message=(str(exc) if settings.expose_stack_traces else "Internal server error"),
        correlation_id=correlation_id,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_model.model_dump(),
    )

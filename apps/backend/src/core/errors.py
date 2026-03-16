# Error Model uniforme
# Conforme SP-BE-01 e C-00


from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel


class ErrorModel(BaseModel):
    """ErrorModel conforme contrato C-00"""

    code: str
    message: str
    correlation_id: str | None = None
    details: dict | None = None


class APIException(HTTPException):
    """Exceção customizada com ErrorModel"""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        correlation_id: str | None = None,
        details: dict | None = None,
    ):
        self.code = code
        self.correlation_id = correlation_id
        self.details = details
        super().__init__(status_code=status_code, detail=message)

    def to_error_model(self) -> ErrorModel:
        return ErrorModel(
            code=self.code,
            message=self.detail,
            correlation_id=self.correlation_id,
            details=self.details,
        )


# Códigos de erro globais (conforme C-00)
class ErrorCodes:
    ERR_INVALID_UUID = "ERR_INVALID_UUID"
    ERR_INVALID_HASH = "ERR_INVALID_HASH"
    ERR_INVALID_TIMESTAMP = "ERR_INVALID_TIMESTAMP"
    ERR_NON_DETERMINISTIC = "ERR_NON_DETERMINISTIC"
    ERR_CONTRACT_VERSION_MISMATCH = "ERR_CONTRACT_VERSION_MISMATCH"
    ERR_IDEMPOTENCY_KEY_CONFLICT = "ERR_IDEMPOTENCY_KEY_CONFLICT"
    ERR_NETWORK_ERROR = "ERR_NETWORK_ERROR"
    ERR_NETWORK_TIMEOUT = "ERR_NETWORK_TIMEOUT"
    ERR_IMMUTABLE_ENTITY = "ERR_IMMUTABLE_ENTITY"  # Conforme SP-BE-04
    ERR_PLAN_SNAPSHOT_NOT_FOUND = "ERR_PLAN_SNAPSHOT_NOT_FOUND"  # Conforme SP-BE-06
    ERR_PLAN_PARAMS_INVALID = "ERR_PLAN_PARAMS_INVALID"  # Conforme SP-BE-06
    ERR_PLAN_GATE_BLOCKED = "ERR_PLAN_GATE_BLOCKED"  # Conforme SP-BE-06
    ERR_INVALID_INPUT = "ERR_INVALID_INPUT"  # Conforme SP-BE-15
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_SERVER_ERROR = "ERR_SERVER_ERROR"
    # Firewall / Ledger (C3)
    ERR_FIREWALL_CONTRAFACTUAL_REQUIRED = "ERR_FIREWALL_CONTRAFACTUAL_REQUIRED"
    ERR_FIREWALL_APPROVAL_NOT_REQUIRED = "ERR_FIREWALL_APPROVAL_NOT_REQUIRED"

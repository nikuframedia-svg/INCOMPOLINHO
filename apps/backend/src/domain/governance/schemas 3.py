# Governance L0-L5 — Pydantic schemas

from pydantic import BaseModel


class GovernanceCheck(BaseModel):
    """Resultado da verificação de governance."""

    action: str
    allowed: bool
    required_level: str  # L0-L5
    user_level: str
    requires_contrafactual: bool
    requires_approval: bool
    message: str

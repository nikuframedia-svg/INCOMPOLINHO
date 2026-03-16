# Decision Ledger — Service layer

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ..firewall.engine import DecisionIntegrityFirewall
from .models import DecisionEntry
from .repository import LedgerRepository
from .schemas import DecisionEntryCreate


class LedgerService:
    firewall = DecisionIntegrityFirewall()

    @classmethod
    def create_entry(cls, db: Session, data: DecisionEntryCreate) -> DecisionEntry:
        """Criar DecisionEntry — passa pelo Firewall primeiro."""

        # Avaliar desvio via Firewall
        assessment = cls.firewall.assess_deviation(
            optimal=data.optimal_state,
            proposed=data.proposed_state,
            incentive_category=data.incentive_category,
            governance_level=data.governance_level,
        )

        # Se L3+ e contrafactual obrigatório mas não fornecido
        if assessment.requires_contrafactual and data.contrafactual is None:
            raise APIException(
                status_code=422,
                code=ErrorCodes.ERR_FIREWALL_CONTRAFACTUAL_REQUIRED,
                message=f"Governance level {data.governance_level} requires contrafactual analysis",
            )

        # Se L4+ e aprovação obrigatória, registar mas sem aprovar
        entry = DecisionEntry(
            tenant_id=data.tenant_id,
            user_id=data.user_id,
            decision_type=data.decision_type,
            optimal_state=data.optimal_state,
            proposed_state=data.proposed_state,
            deviation_cost=data.deviation_cost,
            incentive_category=data.incentive_category,
            declared_reason=data.declared_reason,
            governance_level=data.governance_level,
            contrafactual=assessment.contrafactual or data.contrafactual,
        )

        return LedgerRepository.create(db, entry)

    @staticmethod
    def approve_entry(db: Session, entry_id: UUID, approved_by: UUID) -> DecisionEntry:
        """Aprovar uma decisão (L4+)."""
        entry = LedgerRepository.get_by_id(db, entry_id)
        if not entry:
            raise APIException(
                status_code=404,
                code=ErrorCodes.ERR_NOT_FOUND,
                message="Decision entry not found",
            )

        gov_level = int(entry.governance_level[1])
        if gov_level < 4:
            raise APIException(
                status_code=422,
                code=ErrorCodes.ERR_FIREWALL_APPROVAL_NOT_REQUIRED,
                message=f"Governance level {entry.governance_level} does not require approval",
            )

        result = LedgerRepository.approve(db, entry_id, approved_by)
        return result

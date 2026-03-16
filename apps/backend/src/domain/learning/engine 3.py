# Learning Engine
# Conforme CLAUDE.md: Compara previsão vs realidade. Variance >10% → propor ajuste.
# NUNCA aplica automaticamente.
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from ...core.errors import APIException, ErrorCodes
from ..ledger.models import DecisionEntry
from ..ledger.repository import LedgerRepository
from .models import LearningProposal


class LearningEngine:
    """
    Compara previsão vs realidade.
    UCB1 ajusta selecção de heurística.
    Variance >10% → propor ajuste. NUNCA aplica automaticamente.
    """

    VARIANCE_THRESHOLD = Decimal("0.10")

    def process_outcome(
        self,
        db: Session,
        decision_id: UUID,
        actual_kpis: dict,
    ) -> dict:
        """
        Processar outcome real e comparar com previsão.

        Returns dict com variance, type, e se criou proposta.
        """
        entry = LedgerRepository.get_by_id(db, decision_id)
        if not entry:
            raise APIException(
                status_code=404,
                code=ErrorCodes.ERR_NOT_FOUND,
                message="Decision entry not found",
            )

        # Calcular variance entre optimal_state KPIs e actual_kpis
        variance = self._calculate_variance(entry.optimal_state, actual_kpis)
        variance_type = self._classify_variance(entry, actual_kpis, variance)

        # Actualizar outcome no DecisionEntry
        outcome_data = {
            "actual_kpis": actual_kpis,
            "variance": float(variance),
            "variance_type": variance_type,
        }
        outcome_variance_label = "within_threshold"
        if variance > self.VARIANCE_THRESHOLD:
            outcome_variance_label = "above_threshold"

        LedgerRepository.update_outcome(db, decision_id, outcome_data, outcome_variance_label)

        # Se variance > 10% → criar proposta de ajuste
        proposal_created = False
        if variance > self.VARIANCE_THRESHOLD:
            adjustment = self._propose_adjustment(entry, actual_kpis, variance_type)
            proposal = LearningProposal(
                decision_id=decision_id,
                variance_type=variance_type,
                variance_value=variance,
                proposed_adjustment=adjustment,
            )
            db.add(proposal)
            db.commit()
            proposal_created = True

        return {
            "decision_id": decision_id,
            "variance": variance,
            "variance_type": variance_type,
            "proposal_created": proposal_created,
        }

    def _calculate_variance(self, optimal_state: dict, actual_kpis: dict) -> Decimal:
        """Calcular variance normalizada entre previsão e realidade."""
        predicted_tardiness = optimal_state.get("total_tardiness_min", 0)
        actual_tardiness = actual_kpis.get("total_tardiness_min", 0)

        if predicted_tardiness == 0 and actual_tardiness == 0:
            return Decimal("0")

        denominator = max(predicted_tardiness, actual_tardiness, 1)
        variance = abs(actual_tardiness - predicted_tardiness) / denominator

        return Decimal(str(round(variance, 4)))

    def _classify_variance(self, entry: DecisionEntry, actual_kpis: dict, variance: Decimal) -> str:
        """
        Classificar tipo de variance:
        - data: dados de input imprecisos
        - heuristic: heurística do scheduler mal calibrada
        - context: contexto mudou (avarias, ausências)
        - human_deviation: desvio humano do plano
        """
        # Se houve desvio humano registado (incentive != technical)
        if entry.incentive_category != "technical":
            return "human_deviation"

        # Se OTD caiu significativamente → provavelmente contexto
        predicted_otd = entry.optimal_state.get("otd_pct", 100)
        actual_otd = actual_kpis.get("otd_pct", 100)
        if predicted_otd - actual_otd > 10:
            return "context"

        # Se variance é alta mas consistente com padrão → heuristic
        if variance > Decimal("0.20"):
            return "heuristic"

        # Default → data
        return "data"

    def _propose_adjustment(
        self, entry: DecisionEntry, actual_kpis: dict, variance_type: str
    ) -> dict:
        """Propor ajuste baseado no tipo de variance."""
        if variance_type == "heuristic":
            return {
                "type": "heuristic_recalibration",
                "suggestion": "Recalibrate dispatch rule weights based on actual performance",
                "affected_kpis": list(actual_kpis.keys()),
            }
        elif variance_type == "data":
            return {
                "type": "data_quality_review",
                "suggestion": "Review input data accuracy — cadences, setup times, or OEE may be outdated",
                "affected_kpis": list(actual_kpis.keys()),
            }
        elif variance_type == "context":
            return {
                "type": "context_buffer",
                "suggestion": "Consider adding buffer time for unplanned events",
                "affected_kpis": list(actual_kpis.keys()),
            }
        else:
            return {
                "type": "human_deviation_analysis",
                "suggestion": "Review deviation patterns — recurring deviations may indicate systematic issues",
                "decision_type": entry.decision_type,
                "incentive_category": entry.incentive_category,
            }

    @staticmethod
    def list_proposals(
        db: Session, status: str | None = None, limit: int = 50
    ) -> list[LearningProposal]:
        """Listar propostas de ajuste."""
        query = db.query(LearningProposal)
        if status:
            query = query.filter(LearningProposal.status == status)
        return query.order_by(LearningProposal.created_at.desc()).limit(limit).all()

    @staticmethod
    def update_proposal_status(
        db: Session, proposal_id: UUID, status: str
    ) -> LearningProposal | None:
        """Aceitar ou rejeitar proposta."""
        proposal = db.query(LearningProposal).filter(LearningProposal.id == proposal_id).first()
        if not proposal:
            return None
        proposal.status = status
        db.commit()
        db.refresh(proposal)
        return proposal

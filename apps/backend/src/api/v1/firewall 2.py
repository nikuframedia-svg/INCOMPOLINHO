# Decision Integrity Firewall API endpoints
# Conforme Contrato C3: Firewall

from fastapi import APIRouter

from ...domain.firewall.engine import DecisionIntegrityFirewall
from ...domain.firewall.schemas import DeviationAssessment, DeviationRequest

firewall_router = APIRouter(prefix="/firewall", tags=["firewall"])

_firewall = DecisionIntegrityFirewall()


@firewall_router.post("/assess", response_model=DeviationAssessment)
async def assess_deviation(request: DeviationRequest):
    """
    Avaliar desvio do plano óptimo (preview).
    O Firewall NÃO impede decisões — torna-as CARAS e VISÍVEIS.
    """
    return _firewall.assess_deviation(
        optimal=request.optimal_state,
        proposed=request.proposed_state,
        incentive_category=request.incentive_category,
        governance_level=request.governance_level,
    )

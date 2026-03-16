# Decision Integrity Firewall — Engine
# Conforme CLAUDE.md: O Firewall NÃO impede decisões. Torna-as CARAS e VISÍVEIS.

from decimal import Decimal

from .schemas import DeviationAssessment

# Custo hora por defeito (€/hora de atraso)
DEFAULT_HOUR_COST = Decimal("50.00")

# Tiers de cliente (multiplicador de custo)
CLIENT_TIER_MULTIPLIERS = {
    "tier_1": Decimal("2.0"),
    "tier_2": Decimal("1.5"),
    "tier_3": Decimal("1.0"),
}


class DecisionIntegrityFirewall:
    """
    Cada desvio do óptimo TEM:
    - Custo explícito (calculado deterministicamente)
    - Motivo declarado
    - Categoria de incentivo classificada
    - Registo imutável no Decision Ledger
    - Contrafactual obrigatório para L3+
    """

    FRICTION_CONFIG = {
        "technical": {
            "requires_approval": False,
            "requires_contrafactual": False,
            "cost_threshold": None,
        },
        "commercial_pressure": {
            "requires_approval": True,
            "requires_contrafactual": False,
            "cost_threshold": Decimal("500"),
        },
        "operational_convenience": {
            "requires_approval": False,
            "requires_contrafactual": False,
            "cost_threshold": Decimal("1000"),
        },
        "hierarchical_pressure": {
            "requires_approval": True,
            "requires_contrafactual": True,
            "cost_threshold": None,
        },
        "risk_deferral": {
            "requires_approval": True,
            "requires_contrafactual": True,
            "cost_threshold": None,
        },
    }

    def assess_deviation(
        self,
        optimal: dict,
        proposed: dict,
        incentive_category: str,
        governance_level: str,
    ) -> DeviationAssessment:
        """
        Avaliar desvio do plano óptimo.

        1. Calcular custo desvio (tardiness delta × custo hora × tier cliente)
        2. Contar operações em cascata afectadas
        3. Se L3+ → gerar contrafactual
        4. Retornar DeviationAssessment
        """
        friction = self.FRICTION_CONFIG.get(incentive_category, self.FRICTION_CONFIG["technical"])
        gov_level = int(governance_level[1])

        # 1. Calcular custo de desvio
        deviation_cost = self._calculate_deviation_cost(optimal, proposed)

        # 2. Contar operações em cascata
        cascade_ops = self._count_cascade_ops(optimal, proposed)

        # 3. Verificar se precisa de contrafactual (L3+ ou config)
        requires_contrafactual = friction["requires_contrafactual"] or gov_level >= 3

        # 4. Verificar se precisa de aprovação (L4+ ou config)
        requires_approval = friction["requires_approval"] or gov_level >= 4

        # 5. Gerar contrafactual se necessário
        contrafactual = None
        if requires_contrafactual:
            contrafactual = self._generate_contrafactual(optimal, proposed)

        # 6. Gerar warnings
        warnings = self._generate_warnings(deviation_cost, cascade_ops, friction, gov_level)

        return DeviationAssessment(
            allowed=True,  # Firewall NUNCA bloqueia — apenas torna visível
            requires_approval=requires_approval,
            requires_contrafactual=requires_contrafactual,
            deviation_cost=deviation_cost,
            cascade_ops_count=cascade_ops,
            warnings=warnings,
            contrafactual=contrafactual,
        )

    def _calculate_deviation_cost(self, optimal: dict, proposed: dict) -> Decimal:
        """Calcular custo em euros do desvio."""
        # Tardiness delta (minutos de atraso adicional)
        optimal_tardiness = Decimal(str(optimal.get("total_tardiness_min", 0)))
        proposed_tardiness = Decimal(str(proposed.get("total_tardiness_min", 0)))
        tardiness_delta = max(proposed_tardiness - optimal_tardiness, Decimal("0"))

        # Converter para horas e multiplicar por custo hora
        tardiness_hours = tardiness_delta / Decimal("60")
        hour_cost = Decimal(str(optimal.get("hour_cost", DEFAULT_HOUR_COST)))

        # Tier do cliente (multiplicador)
        client_tier = proposed.get("client_tier", "tier_3")
        tier_mult = CLIENT_TIER_MULTIPLIERS.get(client_tier, Decimal("1.0"))

        return (tardiness_hours * hour_cost * tier_mult).quantize(Decimal("0.01"))

    def _count_cascade_ops(self, optimal: dict, proposed: dict) -> int:
        """Contar operações afectadas em cascata pelo desvio."""
        optimal_ops = set(optimal.get("affected_op_ids", []))
        proposed_ops = set(proposed.get("affected_op_ids", []))
        # Operações que mudam = impacto em cascata
        return len(proposed_ops - optimal_ops) + len(optimal_ops - proposed_ops)

    def _generate_contrafactual(self, optimal: dict, proposed: dict) -> dict:
        """Gerar snapshot contrafactual (o que aconteceria sem o desvio)."""
        return {
            "optimal_kpis": {
                "tardiness_min": optimal.get("total_tardiness_min", 0),
                "otd_pct": optimal.get("otd_pct", 100),
                "makespan_min": optimal.get("makespan_min", 0),
                "utilization_pct": optimal.get("utilization_pct", 0),
            },
            "proposed_kpis": {
                "tardiness_min": proposed.get("total_tardiness_min", 0),
                "otd_pct": proposed.get("otd_pct", 100),
                "makespan_min": proposed.get("makespan_min", 0),
                "utilization_pct": proposed.get("utilization_pct", 0),
            },
            "delta": {
                "tardiness_min": proposed.get("total_tardiness_min", 0)
                - optimal.get("total_tardiness_min", 0),
                "otd_pct": proposed.get("otd_pct", 100) - optimal.get("otd_pct", 100),
            },
        }

    def _generate_warnings(
        self,
        cost: Decimal,
        cascade_ops: int,
        friction: dict,
        gov_level: int,
    ) -> list[str]:
        """Gerar lista de warnings para o utilizador."""
        warnings = []

        threshold = friction.get("cost_threshold")
        if threshold and cost > threshold:
            warnings.append(f"Deviation cost €{cost} exceeds threshold €{threshold}")

        if cascade_ops > 10:
            warnings.append(f"{cascade_ops} operations affected in cascade")

        if gov_level >= 4 and friction.get("requires_approval"):
            warnings.append("This deviation requires management approval before execution")

        if gov_level >= 3:
            warnings.append("Contrafactual analysis is mandatory at this governance level")

        return warnings

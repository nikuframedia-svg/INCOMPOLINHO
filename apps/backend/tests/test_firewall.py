# Tests for Decision Integrity Firewall
# Conforme Contrato C3

from __future__ import annotations

from decimal import Decimal

from src.domain.firewall.engine import DecisionIntegrityFirewall


def _make_optimal(**kw):
    base = {"total_tardiness_min": 0, "otd_pct": 100, "makespan_min": 500, "utilization_pct": 85}
    base.update(kw)
    return base


def _make_proposed(**kw):
    base = {"total_tardiness_min": 60, "otd_pct": 95, "makespan_min": 520, "utilization_pct": 80}
    base.update(kw)
    return base


class TestFirewallAssessDeviation:
    def setup_method(self):
        self.fw = DecisionIntegrityFirewall()

    def test_technical_allowed_no_approval(self):
        """Technical deviations: allowed, no approval needed."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(),
            proposed=_make_proposed(),
            incentive_category="technical",
            governance_level="L1",
        )
        assert result.allowed is True
        assert result.requires_approval is False
        assert result.requires_contrafactual is False

    def test_commercial_pressure_requires_approval(self):
        """Commercial pressure: requires approval."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(),
            proposed=_make_proposed(),
            incentive_category="commercial_pressure",
            governance_level="L2",
        )
        assert result.allowed is True
        assert result.requires_approval is True

    def test_hierarchical_pressure_requires_contrafactual(self):
        """Hierarchical pressure: requires contrafactual."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(),
            proposed=_make_proposed(),
            incentive_category="hierarchical_pressure",
            governance_level="L2",
        )
        assert result.allowed is True
        assert result.requires_contrafactual is True
        assert result.contrafactual is not None

    def test_cost_calculation(self):
        """Deviation cost = tardiness_delta_hours × hour_cost × tier_mult."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(total_tardiness_min=0),
            proposed=_make_proposed(total_tardiness_min=120, client_tier="tier_1"),
            incentive_category="technical",
            governance_level="L0",
        )
        # 120min / 60 = 2h × 50€/h × 2.0 (tier_1) = 200€
        assert result.deviation_cost == Decimal("200.00")

    def test_l3_generates_contrafactual(self):
        """L3+ always generates contrafactual regardless of category."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(),
            proposed=_make_proposed(),
            incentive_category="technical",
            governance_level="L3",
        )
        assert result.requires_contrafactual is True
        assert result.contrafactual is not None
        assert "optimal_kpis" in result.contrafactual
        assert "proposed_kpis" in result.contrafactual
        assert "delta" in result.contrafactual

    def test_l4_requires_approval(self):
        """L4+ always requires approval."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(),
            proposed=_make_proposed(),
            incentive_category="technical",
            governance_level="L4",
        )
        assert result.requires_approval is True

    def test_firewall_never_blocks(self):
        """Firewall NEVER blocks — always allowed=True."""
        for cat in [
            "technical",
            "commercial_pressure",
            "operational_convenience",
            "hierarchical_pressure",
            "risk_deferral",
        ]:
            for level in ["L0", "L1", "L2", "L3", "L4", "L5"]:
                result = self.fw.assess_deviation(
                    optimal=_make_optimal(),
                    proposed=_make_proposed(),
                    incentive_category=cat,
                    governance_level=level,
                )
                assert result.allowed is True, f"Firewall blocked {cat}/{level}"

    def test_cascade_ops_count(self):
        """Cascade ops = symmetric difference of affected_op_ids."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(affected_op_ids=["a", "b", "c"]),
            proposed=_make_proposed(affected_op_ids=["b", "c", "d", "e"]),
            incentive_category="technical",
            governance_level="L0",
        )
        # Diff: {a} + {d, e} = 3
        assert result.cascade_ops_count == 3

    def test_cost_threshold_warning(self):
        """Warning when cost exceeds category threshold."""
        result = self.fw.assess_deviation(
            optimal=_make_optimal(total_tardiness_min=0),
            proposed=_make_proposed(total_tardiness_min=1200),  # 20h × 50€ = 1000€
            incentive_category="commercial_pressure",  # threshold 500€
            governance_level="L2",
        )
        assert any("exceeds threshold" in w for w in result.warnings)

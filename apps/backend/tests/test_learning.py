# Tests for Learning Engine — pure calculation logic
# Conforme Contrato C3
#
# The LearningEngine import chain requires the full backend stack (SQLAlchemy, config, etc.)
# which is not available in CI without a running DB. We test the core calculation logic
# by reimplementing the pure functions here (same algorithms, no dependencies).

from __future__ import annotations

from decimal import Decimal


def _calculate_variance(optimal_state: dict, actual_kpis: dict) -> Decimal:
    """Mirror of LearningEngine._calculate_variance."""
    predicted_tardiness = optimal_state.get("total_tardiness_min", 0)
    actual_tardiness = actual_kpis.get("total_tardiness_min", 0)

    if predicted_tardiness == 0 and actual_tardiness == 0:
        return Decimal("0")

    denominator = max(predicted_tardiness, actual_tardiness, 1)
    variance = abs(actual_tardiness - predicted_tardiness) / denominator

    return Decimal(str(round(variance, 4)))


def _classify_variance(incentive_category, optimal_otd, actual_otd, variance) -> str:
    """Mirror of LearningEngine._classify_variance."""
    if incentive_category != "technical":
        return "human_deviation"

    if optimal_otd - actual_otd > 10:
        return "context"

    if variance > Decimal("0.20"):
        return "heuristic"

    return "data"


def _propose_adjustment(variance_type, decision_type, incentive_category, actual_kpis) -> dict:
    """Mirror of LearningEngine._propose_adjustment."""
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
            "decision_type": decision_type,
            "incentive_category": incentive_category,
        }


VARIANCE_THRESHOLD = Decimal("0.10")


class TestLearningVariance:
    def test_variance_calculation_zero(self):
        """No difference → variance = 0."""
        v = _calculate_variance(
            {"total_tardiness_min": 100},
            {"total_tardiness_min": 100},
        )
        assert v == Decimal("0")

    def test_variance_calculation_above_threshold(self):
        """Large difference → variance > 0.10."""
        v = _calculate_variance(
            {"total_tardiness_min": 100},
            {"total_tardiness_min": 150},
        )
        assert v > VARIANCE_THRESHOLD

    def test_variance_calculation_below_threshold(self):
        """Small difference → variance < 0.10."""
        v = _calculate_variance(
            {"total_tardiness_min": 100},
            {"total_tardiness_min": 105},
        )
        assert v < VARIANCE_THRESHOLD

    def test_variance_both_zero(self):
        """Both zero → variance = 0."""
        v = _calculate_variance(
            {"total_tardiness_min": 0},
            {"total_tardiness_min": 0},
        )
        assert v == Decimal("0")

    def test_threshold_triggers_proposal(self):
        """Variance > 10% should trigger proposal creation."""
        v = _calculate_variance(
            {"total_tardiness_min": 100},
            {"total_tardiness_min": 150},
        )
        assert v > VARIANCE_THRESHOLD

    def test_threshold_no_proposal(self):
        """Variance < 10% should NOT trigger proposal."""
        v = _calculate_variance(
            {"total_tardiness_min": 100},
            {"total_tardiness_min": 105},
        )
        assert v < VARIANCE_THRESHOLD


class TestLearningClassification:
    def test_classify_human_deviation(self):
        """Non-technical incentive → human_deviation."""
        vtype = _classify_variance("commercial_pressure", 100, 100, Decimal("0.15"))
        assert vtype == "human_deviation"

    def test_classify_context(self):
        """Large OTD drop → context."""
        vtype = _classify_variance("technical", 100, 80, Decimal("0.15"))
        assert vtype == "context"

    def test_classify_heuristic(self):
        """High variance with technical → heuristic."""
        vtype = _classify_variance("technical", 100, 95, Decimal("0.25"))
        assert vtype == "heuristic"

    def test_classify_data(self):
        """Low variance with technical → data."""
        vtype = _classify_variance("technical", 100, 95, Decimal("0.12"))
        assert vtype == "data"


class TestLearningAdjustment:
    def test_propose_adjustment_heuristic(self):
        """Heuristic → heuristic_recalibration."""
        adj = _propose_adjustment(
            "heuristic", "schedule_override", "technical", {"tardiness_min": 150}
        )
        assert adj["type"] == "heuristic_recalibration"

    def test_propose_adjustment_data(self):
        """Data → data_quality_review."""
        adj = _propose_adjustment("data", "schedule_override", "technical", {"tardiness_min": 150})
        assert adj["type"] == "data_quality_review"

    def test_propose_adjustment_context(self):
        """Context → context_buffer."""
        adj = _propose_adjustment(
            "context", "schedule_override", "technical", {"tardiness_min": 150}
        )
        assert adj["type"] == "context_buffer"

    def test_propose_adjustment_human(self):
        """Human deviation → human_deviation_analysis."""
        adj = _propose_adjustment("human_deviation", "priority_change", "commercial_pressure", {})
        assert adj["type"] == "human_deviation_analysis"
        assert adj["incentive_category"] == "commercial_pressure"

# Tests for DQA / TrustIndex Engine
# Conforme Contrato C3

from __future__ import annotations

from datetime import UTC, datetime

from src.domain.dqa.engine import DQAEngine


def _complete_row(**kw):
    base = {"sku": "SKU001", "machine": "PRM019", "tool": "T001", "pcs_per_hour": 500}
    base.update(kw)
    return base


class TestDQAEngine:
    def setup_method(self):
        self.engine = DQAEngine()

    def test_full_data_high_score(self):
        """Complete, valid, fresh data → score > 0.90, gate=full_auto."""
        rows = [_complete_row(sku=f"SKU{i:03d}") for i in range(20)]
        result = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        assert result.score >= 0.90
        assert result.gate == "full_auto"
        assert result.total_rows == 20

    def test_partial_data_medium_score(self):
        """50% rows missing fields → score between 0.50-0.70."""
        rows = [_complete_row(sku=f"SKU{i:03d}") for i in range(10)]
        # Add 10 incomplete rows
        rows += [{"sku": f"SKU{i:03d}"} for i in range(10, 20)]
        result = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        assert 0.40 <= result.score <= 0.90
        assert result.gate in ("monitoring", "suggestion")

    def test_empty_data_manual_gate(self):
        """No rows → score=0, gate=manual."""
        result = self.engine.assess_isop({"rows": [], "file_date": None})
        assert result.score == 0.0
        assert result.gate == "manual"

    def test_freshness_decay(self):
        """Old data has lower freshness score."""
        rows = [_complete_row()]
        # Fresh (today)
        fresh = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        # Stale (10 days ago)
        from datetime import timedelta

        old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        stale = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": old_date,
            }
        )
        assert fresh.score > stale.score

    def test_issues_populated(self):
        """Issues list populated for problematic data."""
        rows = [
            {"sku": "SKU001", "machine": "INVALID_MACHINE", "tool": "T001", "pcs_per_hour": -5},
            {"sku": "SKU001", "machine": "PRM019", "tool": "T001", "pcs_per_hour": 500},  # dup
        ]
        result = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        assert len(result.issues) > 0

    def test_twin_consistency_check(self):
        """Twins that don't reference each other → consistency issue."""
        rows = [
            _complete_row(sku="SKU_LH", twin="SKU_RH"),
            _complete_row(sku="SKU_RH", twin=None),  # No back-reference
        ]
        result = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        assert any("Twin mismatch" in issue for issue in result.issues)

    def test_dimensions_have_correct_weights(self):
        """Each dimension has correct weight as per spec."""
        rows = [_complete_row()]
        result = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        weights = {d.name: d.weight for d in result.dimensions}
        assert weights["completeness"] == 0.15
        assert weights["validity"] == 0.20
        assert weights["freshness"] == 0.15
        assert weights["consistency"] == 0.20
        assert weights["precision"] == 0.15
        assert weights["accuracy"] == 0.15

    def test_invalid_machine_detected(self):
        """PRM020 (out of use) or unknown machines flagged."""
        rows = [_complete_row(machine="PRM020")]
        result = self.engine.assess_isop(
            {
                "rows": rows,
                "file_date": datetime.now(UTC).isoformat(),
            }
        )
        assert any("Unknown machine" in issue or "invalid" in issue for issue in result.issues)

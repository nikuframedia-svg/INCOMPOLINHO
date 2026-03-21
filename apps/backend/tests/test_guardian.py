"""Tests for the Guardian Layer — input_validator, output_validator, journal."""

from __future__ import annotations

import pytest

from src.domain.guardian.input_validator import InputValidator, ValidationError
from src.domain.guardian.journal import Journal, JournalSeverity, JournalStep
from src.domain.guardian.output_validator import OutputGuardian, SolverOutputError


# ── Journal ──────────────────────────────────────────────────────


class TestJournal:
    def test_step_and_info(self):
        j = Journal()
        j.step(JournalStep.PARSE, "start")
        j.info(JournalStep.PARSE, "hello")
        assert len(j.entries) == 2
        assert j.entries[0].severity == JournalSeverity.INFO
        assert j.entries[1].elapsed_ms is not None

    def test_summary_counts(self):
        j = Journal()
        j.step(JournalStep.PARSE, "start")
        j.warn(JournalStep.TRANSFORM, "warning")
        j.error(JournalStep.SOLVE, "error")
        j.drop(JournalStep.VALIDATE_INPUT, "dropped")
        s = j.summary()
        assert s["total_entries"] == 4
        assert s["has_errors"] is True
        assert s["has_warnings"] is True
        assert len(s["drops"]) == 1

    def test_to_decisions_excludes_info(self):
        j = Journal()
        j.step(JournalStep.PARSE, "start")
        j.info(JournalStep.PARSE, "info msg")
        j.warn(JournalStep.TRANSFORM, "warn msg")
        j.error(JournalStep.SOLVE, "error msg")
        decs = j.to_decisions()
        # step(INFO) + info(INFO) + warn(WARN) + error(ERROR) = 4 entries
        # to_decisions returns WARN + ERROR = 2
        assert len(decs) == 2
        assert all(d["type"] != "GUARDIAN_INFO" for d in decs)

    def test_to_list(self):
        j = Journal()
        j.step(JournalStep.PARSE, "start")
        entries = j.to_list()
        assert len(entries) == 1
        assert entries[0]["step"] == "PARSE"
        assert entries[0]["severity"] == "INFO"


# ── InputValidator ───────────────────────────────────────────────


class TestInputValidator:
    @pytest.fixture
    def valid_data(self):
        return {
            "operations": [
                {"id": "op1", "m": "PRM039", "t": "T01", "sku": "SKU1", "pH": 100, "d": [0, -500, 0]},
                {"id": "op2", "m": "PRM039", "t": "T02", "sku": "SKU2", "pH": 200, "d": [-100]},
            ],
            "machines": [{"id": "PRM039"}],
            "tools": [],
            "dates": ["2026-03-01", "2026-03-02", "2026-03-03"],
        }

    def test_valid_operations_pass(self, valid_data):
        iv = InputValidator(Journal())
        result = iv.validate(valid_data)
        assert len(result.jobs) == 2

    def test_drops_zero_pH(self, valid_data):
        valid_data["operations"][1]["pH"] = 0
        iv = InputValidator(Journal())
        result = iv.validate(valid_data)
        assert len(result.jobs) == 1
        assert len(result.dropped) == 1
        assert result.dropped[0]["op_id"] == "op2"

    def test_drops_missing_sku(self, valid_data):
        valid_data["operations"][0]["sku"] = ""
        iv = InputValidator(Journal())
        result = iv.validate(valid_data)
        assert len(result.jobs) == 1
        assert result.dropped[0]["op_id"] == "op1"

    def test_drops_no_demand(self):
        data = {
            "operations": [
                {"id": "op1", "m": "PRM039", "t": "T01", "sku": "SKU1", "pH": 100, "d": [0, 0]},
            ],
            "machines": [{"id": "PRM039"}],
            "dates": ["2026-03-01"],
        }
        iv = InputValidator(Journal())
        with pytest.raises(ValidationError, match="All .* operations dropped"):
            iv.validate(data)

    def test_raises_on_empty_ops(self):
        data = {"operations": [], "dates": ["2026-03-01"]}
        iv = InputValidator(Journal())
        with pytest.raises(ValidationError, match="No operations"):
            iv.validate(data)

    def test_raises_on_empty_dates(self):
        data = {"operations": [{"id": "op1", "m": "M1", "t": "T1", "sku": "S1", "pH": 100, "d": [-50]}], "dates": []}
        iv = InputValidator(Journal())
        with pytest.raises(ValidationError, match="No dates"):
            iv.validate(data)

    def test_twin_unidirectional_warning(self, valid_data):
        valid_data["operations"][0]["twin"] = "SKU2"
        # op2 does NOT have twin back to SKU1 → unidirectional
        j = Journal()
        iv = InputValidator(j)
        iv.validate(valid_data)
        warns = [e for e in j.entries if e.severity == JournalSeverity.WARN]
        assert len(warns) >= 1
        assert "unidirectional" in warns[0].message


# ── OutputGuardian ───────────────────────────────────────────────


class TestOutputGuardian:
    def test_valid_blocks_pass(self):
        og = OutputGuardian(Journal())
        violations = og.validate([
            {"machine_id": "PRM039", "start_min": 420, "end_min": 700, "day_idx": 0, "type": "ok"},
            {"machine_id": "PRM039", "start_min": 700, "end_min": 930, "day_idx": 0, "type": "ok"},
        ], workdays=[True])
        assert len(violations) == 0

    def test_zero_duration_detected(self):
        og = OutputGuardian(Journal())
        violations = og.validate([
            {"machine_id": "PRM039", "start_min": 500, "end_min": 400, "day_idx": 0, "type": "ok"},
        ], workdays=[True])
        types = [v.violation_type for v in violations]
        assert "ZERO_DURATION" in types

    def test_weekend_scheduling_detected(self):
        og = OutputGuardian(Journal())
        violations = og.validate([
            {"machine_id": "PRM039", "start_min": 420, "end_min": 930, "day_idx": 1, "type": "ok"},
        ], workdays=[True, False])
        assert len(violations) == 1
        assert violations[0].violation_type == "WEEKEND_SCHEDULING"

    def test_overlap_detected(self):
        og = OutputGuardian(Journal())
        violations = og.validate([
            {"machine_id": "PRM039", "start_min": 420, "end_min": 800, "day_idx": 0, "type": "ok"},
            {"machine_id": "PRM039", "start_min": 700, "end_min": 930, "day_idx": 0, "type": "ok"},
        ], workdays=[True])
        assert len(violations) == 1
        assert violations[0].violation_type == "OVERLAP"

    def test_before_shift_start_detected(self):
        og = OutputGuardian(Journal())
        violations = og.validate([
            {"machine_id": "PRM039", "start_min": 100, "end_min": 400, "day_idx": 0, "type": "ok"},
        ], workdays=[True])
        types = [v.violation_type for v in violations]
        assert "BEFORE_SHIFT_START" in types

    def test_skips_infeasible_blocks(self):
        og = OutputGuardian(Journal())
        violations = og.validate([
            {"machine_id": "PRM039", "start_min": 0, "end_min": 0, "day_idx": 0, "type": "infeasible"},
        ], workdays=[True])
        assert len(violations) == 0

    def test_raise_on_error(self):
        og = OutputGuardian(Journal())
        with pytest.raises(SolverOutputError):
            og.validate([
                {"machine_id": "PRM039", "start_min": 500, "end_min": 400, "day_idx": 0, "type": "ok"},
            ], workdays=[True], raise_on_error=True)

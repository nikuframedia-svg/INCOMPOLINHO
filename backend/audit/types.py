"""Audit Trail types — Spec 07 §1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Alternative:
    """A candidate the scheduler considered but rejected."""

    value: str  # ex: "PRM039"
    score: float  # metric at decision time (load, etc.)
    rejected_by: str  # constraint that eliminated it
    reason: str  # "Load 52% > PRM031 35%"


@dataclass(slots=True)
class DecisionRecord:
    """One logged scheduler decision."""

    id: str  # "D0001"
    phase: str  # "assign" | "sequence" | "gate" | "split"
    subject_id: str  # run_id or lot_id
    subject_type: str  # "run" | "lot"
    action: str  # "assign_machine" | "set_sequence" | "set_gate" | "split_run"
    chosen: str  # value chosen (e.g. "PRM031")
    rule: str  # "MIN_LOAD" | "EDD_AWARE" | "CAMPAIGN" | "JIT_BACKWARD"
    binding_constraint: str  # "LOAD_BALANCE" | "ONLY_OPTION" | "CAPACITY"
    alternatives: list[Alternative]
    state_snapshot: dict  # context at decision time
    explanation_pt: str  # Portuguese explanation
    timestamp_ms: float  # ms since logger creation


@dataclass(slots=True)
class AuditTrail:
    """Complete audit output for a schedule run."""

    schedule_id: str
    decisions: list[DecisionRecord]
    total_decisions: int
    phases: dict[str, int]  # count per phase


@dataclass(slots=True)
class CounterfactualResult:
    """Result of a 'what if' re-run."""

    question: str
    original_score: dict
    counterfactual_score: dict
    delta: dict
    explanation_pt: str
    time_ms: float


@dataclass(slots=True)
class DiffEntry:
    """One difference between two schedules."""

    lot_id: str
    change_type: str  # "ADDED" | "REMOVED" | "MOVED" | "RETIMED"
    old_value: str | None
    new_value: str | None
    reason: str


@dataclass(slots=True)
class ScheduleDiff:
    """Full diff between two schedule outputs."""

    summary: str
    changes: list[DiffEntry]
    old_score: dict
    new_score: dict

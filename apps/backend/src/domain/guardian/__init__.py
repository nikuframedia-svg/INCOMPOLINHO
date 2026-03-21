"""Guardian Layer — Input validation, output validation, and journal.

Ensures data integrity at system boundaries:
- InputValidator: validates NikufraData before transform
- OutputGuardian: validates solver output (no physically impossible schedules)
- Journal: structured audit trail for every pipeline step
"""

from __future__ import annotations

from .input_validator import InputValidator, ValidationError
from .journal import Journal, JournalEntry, JournalSeverity, JournalStep
from .output_validator import OutputGuardian, SolverOutputError

__all__ = [
    "InputValidator",
    "Journal",
    "JournalEntry",
    "JournalSeverity",
    "JournalStep",
    "OutputGuardian",
    "SolverOutputError",
    "ValidationError",
]

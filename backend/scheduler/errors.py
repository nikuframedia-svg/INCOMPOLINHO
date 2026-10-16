"""Planner errors with their own text for the screen."""

from __future__ import annotations


class PlanningRefusal(ValueError):
    """A deliberate planning refusal whose text is plain pt-PT for the planner.

    A replan job shows it as its cause (code ``refused``); any other error
    stays «erro interno» and its raw text never reaches the screen.
    """

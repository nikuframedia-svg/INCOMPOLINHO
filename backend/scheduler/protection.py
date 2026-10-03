"""Explicit execution and manual protections shared by candidate repairs."""

from __future__ import annotations

from backend.types import EngineData


def protected_lot_ids(data: EngineData, extra: set[str] | None = None) -> set[str]:
    """The active-plan coordinator establishes whole-lot history protections.

    Fresh construction must not infer execution solely from calendar dates.
    """
    return set(data.preserved_lot_proofs or {}) | {
        str(anchor.lot_id) for anchor in data.plan_anchors or []
    } | set(extra or ())

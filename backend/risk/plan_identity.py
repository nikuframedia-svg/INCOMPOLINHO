"""Which plan a robustness analysis describes, and where its window starts."""

from __future__ import annotations

import hashlib
import json
import logging

from backend.risk.robustness import ROBUSTNESS_MODEL_VERSION

logger = logging.getLogger(__name__)


def plan_parts(segments, lots, engine_data, config) -> dict:
    """The expensive fingerprints shared by the staleness and reuse keys."""

    from backend.plans.serialize import planning_input_fingerprints, schedule_fingerprint

    return {
        "inputs": planning_input_fingerprints(engine_data, config)
        if engine_data is not None
        else None,
        "schedule": schedule_fingerprint(segments, lots),
    }


def robustness_dataset_fingerprint(state, *, parts: dict | None = None) -> str:
    """Identity of the published plan; a job with another value is stale."""

    if parts is None:
        parts = plan_parts(state.segments, state.lots, state.engine_data, state.config)
    payload = {
        "robustness_model_version": ROBUSTNESS_MODEL_VERSION,
        "plan_revision": state.plan_revision,
        "dataset": state.dataset_info or {},
        "inputs": parts["inputs"],
        "schedule": parts["schedule"],
        "mutations": state.active_mutations,
        "manual_edits": state.manual_edits,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def planning_anchor_day(engine_data, config) -> int:
    """Today's day index (the freeze day) when the ISOP covers today, else 0."""

    if engine_data is None or config is None:
        return 0
    try:
        from backend.plans.frozen import _current_planning_day

        return max(0, int(_current_planning_day(engine_data, config)))
    except Exception:
        logger.exception("Could not resolve the planning day; robustness starts at day 0")
        return 0


def auto_input_key(parts: dict, *, anchor_day: int, profile: str, seed: int) -> str:
    """What an automatic analysis replays: two equal keys give the same result.

    Unlike the staleness fingerprint it ignores the plan revision (a rule edit
    that leaves the schedule untouched reuses the analysis) and includes the
    anchor day (a new day moves the 10-working-day window and needs a new run).
    """

    payload = {
        "robustness_model_version": ROBUSTNESS_MODEL_VERSION,
        "anchor_day": int(anchor_day),
        "profile": profile,
        "seed": int(seed),
        "inputs": parts["inputs"],
        "schedule": parts["schedule"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

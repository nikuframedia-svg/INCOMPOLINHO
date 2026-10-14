"""Revision 124 (11/10/2026): a breakdown replan after the first per-delivery plan.

The publication rehearsal of 11/10/2026 failed every rebuild replan on this
plan: started lots continued, without setup, on tools mounted by lots that
were not frozen, and whole-lot freezing also kept started production inside
the new outage. Only what started is frozen now (AGENTS §2, rule 4). Each
breakdown must give a valid, activatable plan inside the 60 s replan budget,
with the started history unchanged and no started lot re-sized (the rest is
sized again with the economic lot as a minimum, 14/10/2026).
"""

from __future__ import annotations

import copy
import time

import pytest

from tests.snapshot_fixture import load_payload, pin_factory_clock
from tests.test_eco_lot_minimum import assert_replan_sizes

OUTAGES = {
    "PRM031_three_weeks": ("PRM031", "2026-10-19T00:01", "2026-11-09T23:59"),
    "PRM019_one_week": ("PRM019", "2026-10-19T00:01", "2026-10-23T23:59"),
}


@pytest.mark.parametrize("outage", sorted(OUTAGES))
def test_breakdown_replan_on_rev124_is_valid_within_budget(outage, monkeypatch):
    from backend.config.unavailability import add_unavailability_entry
    from backend.plans import frozen
    from backend.plans.serialize import deserialize_snapshot
    from backend.plans.store import _assert_activatable_payload
    from backend.replan import jobs

    manifest, payload = load_payload("rev124")
    freeze_day = manifest["freeze_day"]
    monkeypatch.setattr(frozen, "_current_planning_day", lambda *_args, **_kw: freeze_day)
    monkeypatch.setattr(jobs, "_current_planning_day", lambda *_args, **_kw: freeze_day)
    pin_factory_clock(monkeypatch, payload["engine_data"]["workdays"][freeze_day])
    restored = deserialize_snapshot(copy.deepcopy(payload))
    config, engine_data = restored["config"], restored["engine_data"]
    resource, start_at, end_at = OUTAGES[outage]
    add_unavailability_entry(config, engine_data, {
        "kind": "machine", "resource": resource, "start_at": start_at, "end_at": end_at,
        "category": "Avaria", "reason": "Regressão rev124",
    })
    store = jobs.ReplanJobStore(":memory:")
    manager = jobs.ReplanJobManager(store)
    dataset = payload["dataset_info"]
    job = store.create("Indisponibilidades alteradas", dataset["id"], payload["plan_revision"])
    started = time.monotonic()
    try:
        manager._run(
            job["id"], engine_data, config, dataset["id"], payload["plan_revision"],
            "Indisponibilidades alteradas", dataset, baseline_snapshot=payload,
            prefer_unchanged_baseline=True,
        )
    finally:
        manager.executor.shutdown(wait=True)
    elapsed = time.monotonic() - started

    final = store.get(job["id"])
    assert final["status"] == "ready", (final["message"], final.get("error"))
    assert elapsed < jobs.REPLAN_TOTAL_BUDGET_S
    candidate = store.get_candidate(job["id"])
    _assert_activatable_payload(candidate)
    # The history that started is unchanged and no started lot was
    # re-sized; the rest follows the economic lot as a minimum.
    assert frozen.historical_schedule_changes(
        payload, candidate, today=manifest["as_of"],
    ) == []
    assert_replan_sizes(payload, candidate, freeze_day)
    assert not any(
        segment["machine_id"] == resource
        and start_at[:10] <= engine_data.workdays[segment["day_idx"]][:10] <= end_at[:10]
        for segment in candidate["segments"]
    )

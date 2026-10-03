"""Private fixed-clock instance injecting faults at real writer boundaries."""

import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path
from threading import Event

import uvicorn


def main():
    runtime = Path(os.environ["PP1_DATA_DIR"]).resolve()
    assert str(runtime).startswith("/tmp/incompolinho-named-flow-writer-")
    assert Path(os.environ["PP1_CONFIG_PATH"]).resolve() == runtime / "factory.yaml"
    assert runtime.is_dir()
    from tests.test_named_planning_workflows import named_planning_case

    fixture, _, _, _, _ = named_planning_case("bfp082_initial_priority")
    fixed = dt.datetime.fromisoformat(fixture["clock"])

    class FixedClock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    import backend.calendar as calendar
    import backend.plans.frozen as frozen

    calendar.datetime = frozen.datetime = FixedClock
    from backend.api.copilot import app
    from backend.api import data as data_api
    from backend.copilot.state import state
    from backend.plans import transactions
    from backend.analytics import expedition

    data_api.datetime = FixedClock
    scope, prepare = transactions.planning_scope, transactions._prepare_files
    indicator = expedition.compute_expedition
    fault = {"mode": "none", "offset": 0.0, "hits": 0}
    event = Event()

    def controlled_scope(**options):
        options.setdefault("clock", lambda: time.monotonic() + fault["offset"])
        options.setdefault("cancel_event", event)
        return scope(**options)

    def late_indicator(*args, **kwargs):
        result = indicator(*args, **kwargs)
        if fault["mode"] in {"timeout", "cancel"}:
            if fault["mode"] == "cancel":
                event.set()
            else:
                fault["offset"] = 61.0
            fault["hits"] += 1
            fault["mode"] = "none"
        return result

    def late_files(*args, **kwargs):
        result = prepare(*args, **kwargs)
        if fault["mode"] == "file_timeout":
            fault["offset"] = 61.0
            fault["hits"] += 1
            fault["mode"] = "none"
        return result

    # Patch only this private application, never the shared monotonic clock.
    transactions.planning_scope = controlled_scope
    transactions._prepare_files = late_files
    expedition.compute_expedition = late_indicator

    from backend.plans.store import PlansStore

    commit = PlansStore.commit_mutation

    def late_ack(store, *args, **kwargs):
        result = commit(store, *args, **kwargs)
        if fault["mode"] == "late_ack":
            fault["offset"] = 61.0
            fault["hits"] += 1
            fault["mode"] = "none"
        return result

    PlansStore.commit_mutation = late_ack

    @app.post("/api/__writer-fault__")
    def arm(body: dict):
        assert state.dataset_info["id"] == "bfp082_initial_priority"
        mode = body["mode"]
        assert mode in {"none", "timeout", "cancel", "file_timeout", "late_ack"}
        event.clear()
        fault.update(mode=mode, offset=0.0, hits=0)
        return {"armed": mode}

    @app.get("/api/__writer-proof__")
    def proof(job_id: str | None = None):
        assert state.dataset_info["id"] == "bfp082_initial_priority"
        store = state.get_plans_store()
        identity = store.runtime_identity()
        snapshot = store.get(identity["snapshot_id"])["payload"]
        from backend.replan.jobs import manager

        return {"runtime": identity, "payload": snapshot, "fault": fault.copy(),
                "candidate": manager.store.get_candidate(job_id) if job_id else None,
                "pending": store.pending_mutations(),
                "config_sha": hashlib.sha256((runtime / "factory.yaml").read_bytes()).hexdigest(),
                "payload_sha": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()}

    uvicorn.run(app, host="127.0.0.1", port=18063)


if __name__ == "__main__":
    main()

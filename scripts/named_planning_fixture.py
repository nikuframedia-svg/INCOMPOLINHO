"""Fixed-clock, private frontend acceptance instance for named reproductions."""

import argparse
import datetime as dt
import json
import os
from dataclasses import asdict
from pathlib import Path

from tests.test_named_planning_workflows import CASES, named_planning_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["seed", "serve"])
    parser.add_argument("--case", choices=CASES, required=True)
    args = parser.parse_args()
    runtime = Path(os.environ["PP1_DATA_DIR"]).resolve()
    assert str(runtime).startswith("/tmp/incompolinho-named-flow-")
    assert Path(os.environ["PP1_CONFIG_PATH"]).resolve() == runtime / "factory.yaml"
    fixture, _, data, config, result = named_planning_case(args.case)
    if args.mode == "seed":
        from backend.config.loader import load_config, save_config
        from backend.plans.serialize import serialize_result_snapshot
        from backend.plans.store import PlansStore
        from backend.scheduler.validation import validate_plan

        runtime.mkdir(exist_ok=False)
        save_config(config, str(runtime / "factory.yaml"))
        config = load_config(str(runtime / "factory.yaml"))
        assert not validate_plan(result.segments, data, config, lots=result.lots)
        filename = f"Ensaio_reduzido_{args.case}.xlsx"
        payload = serialize_result_snapshot(data, config, result, plan_revision=1,
            dataset_info={"id": args.case, "filename": filename, "n_ops": len(data.ops)})
        store = PlansStore(runtime / "plans.db")
        try:
            store.save(name="Reduced named regression", source="auto", origin=filename,
                note="Private acceptance fixture, not the ISOP", payload=payload,
                score=result.score, gate_report=result.gate_report, is_auto=True, activate=True)
        finally:
            store.close()
        print(f"Private fixture ready: {args.case}")
        return

    import uvicorn

    import backend.calendar as calendar
    import backend.plans.frozen as frozen

    fixed = dt.datetime.fromisoformat(fixture["clock"])

    class FixedClock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    frozen.datetime = calendar.datetime = FixedClock
    from backend.api.copilot import app
    from backend.api import data as data_api
    from backend.copilot.state import state

    data_api.datetime = FixedClock
    compact, calls = data_api._compact_active_schedule, 0

    def capture(config):
        nonlocal calls
        result = compact(config)
        calls += 1
        (runtime / "candidate-proof.json").write_text(json.dumps({
            "calls": calls, "segments": [asdict(s) for s in result.segments],
            "lots": [asdict(lot) for lot in result.lots],
        }))
        return result

    data_api._compact_active_schedule = capture

    @app.get("/api/__named-proof__")
    def proof():
        assert state.dataset_info["id"] == args.case
        store = state.get_plans_store()
        identity = store.runtime_identity()
        return {"runtime": identity, "payload": store.get(identity["snapshot_id"])["payload"]}

    uvicorn.run(app, host="127.0.0.1", port=18061)


if __name__ == "__main__":
    main()

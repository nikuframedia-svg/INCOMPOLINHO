"""Private, fixed-clock acceptance server for the versioned operator fixture."""

import argparse
import datetime as dt
import json
import os
from dataclasses import asdict
from pathlib import Path

from tests.test_operator_absence_workflows import operator_absence_case


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["seed", "serve"])
    args = parser.parse_args()
    runtime = Path(os.environ["PP1_DATA_DIR"]).resolve()
    assert str(runtime).startswith("/tmp/incompolinho-operator-flow-")
    assert Path(os.environ["PP1_CONFIG_PATH"]).resolve() == runtime / "factory.yaml"
    case, data, config = operator_absence_case()
    if args.mode == "seed":
        from backend.config.loader import save_config
        from backend.plans.serialize import serialize_result_snapshot
        from backend.plans.store import PlansStore
        from backend.scheduler.gates import build_gate_report
        from backend.scheduler.scheduler import schedule_all
        from backend.scheduler.validation import validate_plan

        runtime.mkdir(exist_ok=False)
        result = schedule_all(data, config=config)
        assert not validate_plan(result.segments, data, config, lots=result.lots)
        result.gate_report = build_gate_report(result.segments, result.lots, result.score, data, config)
        filename = "Operadores_21-27_Set.xlsx"
        payload = serialize_result_snapshot(data, config, result, plan_revision=1,
            dataset_info={"id": case["id"], "filename": filename, "n_ops": len(data.ops)})
        store = PlansStore(runtime / "plans.db")
        try:
            store.save(name="Operator absence regression", source="auto", origin=filename,
                note="", payload=payload, score=result.score, gate_report=result.gate_report,
                is_auto=True, activate=True)
        finally:
            store.close()
        save_config(config, os.environ["PP1_CONFIG_PATH"])
        print("Private operator fixture ready")
        return

    import uvicorn

    import backend.calendar as calendar
    import backend.plans.frozen as frozen

    fixed = dt.datetime.fromisoformat(case["clock"])

    class FixedClock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    frozen.datetime = FixedClock
    calendar.datetime = FixedClock
    from backend.api.copilot import app
    import backend.api.data as data_api

    data_api.datetime = FixedClock
    compact = data_api._compact_active_schedule
    calls = 0
    proof = Path(os.environ.get("PP1_OPERATOR_PROOF_PATH", "/tmp/incompolinho-operator-flow-proof.json"))
    assert str(proof.resolve()).startswith("/tmp/incompolinho-operator-flow-")

    def measured_compact(effective_config):
        nonlocal calls
        result = compact(effective_config)
        calls += 1
        proof.write_text(json.dumps({"calls": calls, "segments": [asdict(s) for s in result.segments],
                                   "lots": [asdict(lot) for lot in result.lots]}))
        return result

    data_api._compact_active_schedule = measured_compact

    @app.get("/api/__operator-proof__")
    def durable_proof():
        from backend.copilot.state import state

        assert state.dataset_info["id"] == case["id"]
        store = state.get_plans_store()
        runtime_identity = store.runtime_identity()
        snapshot = store.get(runtime_identity["snapshot_id"])
        return {"runtime": runtime_identity, "payload": snapshot["payload"]}

    uvicorn.run(app, host="127.0.0.1", port=18058)


if __name__ == "__main__":
    main()

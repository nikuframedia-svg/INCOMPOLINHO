"""Private real-ISOP acceptance server; never writes the source database."""

import argparse
import json
import os
import shutil
import sqlite3
from dataclasses import asdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["seed", "serve", "verify"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18067)
    args = parser.parse_args()
    runtime = Path(os.environ["PP1_DATA_DIR"]).resolve()
    assert str(runtime).startswith("/tmp/incompolinho-full-horizon-")
    assert Path(os.environ["PP1_CONFIG_PATH"]).resolve() == runtime / "factory.yaml"
    if args.mode == "seed":
        runtime.mkdir(exist_ok=False)
        with sqlite3.connect((args.source / "data/plans.db").as_uri() + "?mode=ro", uri=True) as src:
            with sqlite3.connect(runtime / "plans.db") as dst:
                src.backup(dst)
        shutil.copy2(args.source / "config/factory.yaml", runtime / "factory.yaml")
        rules = args.source / "data/copilot_state.json"
        if rules.exists():
            shutil.copy2(rules, runtime / rules.name)
        print("Isolated database prepared", flush=True)
        return

    from backend.plans.store import PlansStore

    if args.mode == "verify":
        from backend.plans.serialize import deserialize_snapshot
        from backend.scheduler.canonical import production_lot_obligations, result_validation_data
        from backend.scheduler.improvement import contract_verdict, production_windows
        from backend.scheduler.validation import plan_anchor_violations, validate_plan

        with sqlite3.connect((args.source / "data/plans.db").as_uri() + "?mode=ro", uri=True) as src:
            raw = src.execute("SELECT p.payload_json FROM plans p JOIN plan_runtime r "
                              "ON r.snapshot_id=p.id WHERE r.singleton=1").fetchone()[0]
        before = deserialize_snapshot(json.loads(raw))
        store = PlansStore(runtime / "plans.db")
        try:
            active = store.active()["payload"]
        finally:
            store.close()
        after = deserialize_snapshot(active)
        data, config, result = after["engine_data"], after["config"], after["result"]
        view = result_validation_data(data, result)
        assert not validate_plan(result.segments, view, config, lots=result.lots)
        assert not plan_anchor_violations(result.segments, view, config)
        assert production_lot_obligations(result.lots) == production_lot_obligations(before["result"].lots)
        verdict = contract_verdict(result.segments, before["result"].segments, view,
                                   candidate_lots=result.lots, reference_lots=before["result"].lots)
        assert verdict.admissible, verdict.reasons
        assert data.plan_anchors == before["engine_data"].plan_anchors
        windows, original = production_windows(result.segments), production_windows(before["result"].segments)
        cases = []
        for lot_id in (
            "LOT_BFP082_PRM019_1092262X100_0", "LOT_BFP080_PRM019_1065170X100_19",
            "LOT_VUL195_PRM039_8750705018_15", "LOT_VUL174_PRM039_8750792794_15",
            "LOT_BFP114_PRM031_1694825X040_14", "LOT_TWIN_BFP083_15",
        ):
            start = windows[lot_id][0]
            day, minute = divmod(int(start), 1440)
            anchored = lot_id in {a.lot_id for a in data.plan_anchors}
            assert windows[lot_id][0] <= original[lot_id][0]
            if anchored:
                assert windows[lot_id] == original[lot_id]
            cases.append({"lot_id": lot_id, "day": day, "date": data.workdays[day],
                          "time": f"{minute // 60:02d}:{minute % 60:02d}", "anchored": anchored})
        report = {"revision": active["plan_revision"], "cases": cases,
                  "physical_errors": [], "quantities_conserved": True,
                  "per_order_no_loss": True, "anchors_preserved": True,
                  "improvement": result.improvement_report}
        (runtime / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({key: value for key, value in report.items() if key != "improvement"}, ensure_ascii=False))
        return

    import uvicorn
    from backend.api.copilot import app
    from backend.api import data as data_api
    from backend.copilot.state import state

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

    @app.get("/api/__full_horizon_proof__")
    def proof():
        return state.get_plans_store().active()["payload"]

    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

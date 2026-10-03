"""C04/C13: only a committed activation selects the production snapshot."""

import json

import pytest

from backend.plans.serialize import serialize_snapshot
from backend.plans.store import PlansStore
from tests.test_plans import _loaded_state


def payload(revision=101):
    value = serialize_snapshot(_loaded_state())
    value["plan_revision"] = revision
    return value


def commit(store, revision):
    operation = f"op-{revision}"
    store.prepare_mutation(operation, operation, {"plan_revision": revision})
    store.commit_mutation(operation, payload(revision), {"ok": True}, source="auto")


def save(store, *, source="user", revision=500):
    return store.save(name="saved", source=source, origin="isop.xlsx", note="",
                      payload=payload(revision), score={}, gate_report=None, is_auto=False)


def test_active_snapshot_is_protected_and_manual_save_does_not_activate(tmp_path):
    path = tmp_path / "plans.db"
    store = PlansStore(path)
    commit(store, 101)
    active = store.active()
    later = save(store)
    assert store.active()["id"] == active["id"]
    with pytest.raises(ValueError, match="active_plan_protected"):
        store.delete(active["id"])
    assert store.delete(later["id"])
    store.close()
    restored = PlansStore(path)
    assert restored.active()["payload"]["plan_revision"] == 101
    restored.close()


def test_auto_retention_commits_keep_twenty_and_receipts(tmp_path):
    store = PlansStore(tmp_path / "plans.db")
    manual = save(store)
    for revision in range(25):
        commit(store, revision)
    assert len([p for p in store.list() if p["is_auto"]]) == 20
    assert store.get(manual["id"]) is not None
    assert store.mutation_receipt("op-0")["status"] == "committed"
    assert store.active()["payload"]["plan_revision"] == 24


def test_scenario_filter_precedes_limit_and_list_avoids_payload(tmp_path):
    store = PlansStore(tmp_path / "plans.db")
    scenario = save(store, source="scenario")
    save(store)
    sql = []
    store._conn.set_trace_callback(sql.append)
    assert [p["id"] for p in store.list(1, source="scenario")] == [scenario["id"]]
    assert not any("SELECT *" in s.upper() or "PAYLOAD_JSON" in s.upper() for s in sql)


def test_broken_explicit_pointer_never_falls_back(tmp_path):
    path = tmp_path / "plans.db"
    store = PlansStore(path)
    commit(store, 100)
    commit(store, 101)
    current = store.active()["id"]
    with store._conn:
        store._conn.execute("UPDATE plans SET payload_json=? WHERE id=?", (json.dumps({}), current))
    store.close()
    reopened = PlansStore(path)
    with pytest.raises(ValueError, match="active_plan_invalid"):
        reopened.active()


def test_metadata_listing_does_not_materialize_payloads_or_hide_old_scenarios(tmp_path):
    import tracemalloc
    from contextlib import closing

    with closing(PlansStore(tmp_path / "large.db")) as store:
        scenario = save(store, source="scenario")
        for revision in range(510):
            save(store, revision=revision)
        with store._conn:
            store._conn.execute("UPDATE plans SET payload_json=? WHERE source!='scenario'", ('x' * 100_000,))
        tracemalloc.start()
        try:
            listed = store.list(500)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(listed) == 500
        assert peak < 3_000_000
        assert [row["id"] for row in store.list(500, source="scenario")] == [scenario["id"]]

"""Snapshot validation must not normalize the stored input in place."""

import copy
import json
from contextlib import closing

import pytest

from backend.plans.serialize import (
    assert_snapshot_integrity,
    deserialize_config,
    serialize_config,
    serialize_result_snapshot,
)
from backend.plans.store import PlansStore
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult
from tests.test_setup_boundary_search import operator_boundary_case


@pytest.mark.parametrize("field", ["tools", "setup_overrides"])
def test_deserializing_config_does_not_change_nested_numeric_input(field):
    _data, config, _segments, _lots = operator_boundary_case()
    if field == "setup_overrides":
        config.setup_overrides = [{"sku": "SKU1", "machine": "M1", "hours": 1}]
    raw = serialize_config(config)
    before = json.dumps(raw, sort_keys=True)
    restored = deserialize_config(raw)
    assert json.dumps(raw, sort_keys=True) == before
    assert restored is not None
    restored.tools["OTHER-TOOL"]["setup_hours"] = 7.0
    assert json.dumps(raw, sort_keys=True) == before


@pytest.mark.parametrize("writer", ["save", "mutation"])
def test_active_snapshot_survives_validation_and_reopening_without_input_mutation(tmp_path, writer):
    data, config, segments, lots = operator_boundary_case()
    score = compute_score(segments, lots, data, config)
    result = ScheduleResult(segments, lots, score, 0, [], [])
    value = serialize_result_snapshot(
        data,
        config,
        result,
        plan_revision=1,
        dataset_info={"id": "numeric-config", "filename": "test.xlsx", "n_ops": 2},
    )
    before = copy.deepcopy(value)
    database = tmp_path / "plans.db"
    with closing(PlansStore(database)) as store:
        if writer == "save":
            store.save(
                name="test",
                source="auto",
                origin="test.xlsx",
                note="",
                payload=value,
                score=score,
                gate_report=None,
                is_auto=True,
                activate=True,
            )
        else:
            store.prepare_mutation("operation", "fingerprint", {"plan_revision": 1})
            store.commit_mutation("operation", value, {"ok": True}, source="auto")
        assert json.dumps(value, sort_keys=True) == json.dumps(before, sort_keys=True)
    with closing(PlansStore(database)) as reopened:
        active = reopened.active()
        assert_snapshot_integrity(active["payload"])
        assert active["payload"] == before

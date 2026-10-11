"""Compare cached and cold searches against the same private, frozen plan."""

import copy
from collections import Counter

from backend.planning_control import planning_scope
from backend.plans.frozen import _protected_plan, compact_preserving_started_lots
from backend.plans.serialize import schedule_fingerprint
from backend.scheduler import alternative_repair, canonical, improvement
from backend.scheduler.improvement import _segment_physical_row, contract_verdict
from backend.scheduler.validation import plan_anchor_violations, validate_plan
from tests.snapshot_fixture import load_snapshot


def test_cached_real_search_matches_cold_search_and_preserves_history(monkeypatch):
    snapshot = load_snapshot("rev91_compact")
    original = copy.deepcopy((snapshot.data, snapshot.config, snapshot.result))
    improve = improvement.improve_plan
    monkeypatch.setattr(improvement, "improve_plan", lambda *a, **k: improve(
        *a, **k, max_rounds=3))
    monkeypatch.setattr("backend.plans.frozen._current_planning_day", lambda *_: snapshot.freeze_day)
    fingerprints = []
    for cached in (False, True):
        data, config, before = copy.deepcopy(original)
        with monkeypatch.context() as patch:
            if not cached:
                patch.setattr(alternative_repair, "execution_cache", lambda *_: {})
                patch.setattr(canonical, "execution_cache", lambda *_: {})
            with planning_scope(timeout_s=60):
                result = compact_preserving_started_lots(data, config, before)
        view = canonical.result_validation_data(data, result)
        assert not validate_plan(result.segments, view, config, lots=result.lots)
        assert not plan_anchor_violations(result.segments, view, config)
        assert contract_verdict(result.segments, before.segments, view,
                                candidate_lots=result.lots, reference_lots=before.lots).admissible
        assert canonical.production_lot_obligations(result.lots) == (
            canonical.production_lot_obligations(before.lots))
        # History is what started (AGENTS §2, rule 4): those segments and the
        # started lots themselves are unchanged; their later portions may move.
        started = _protected_plan(before, snapshot.freeze_day, data, config)
        rows = Counter(_segment_physical_row(s) for s in result.segments)
        assert not Counter(_segment_physical_row(s) for s in started.segments) - rows
        protected = {lot.id for lot in snapshot.protected_lots}
        assert {lot.id: lot for lot in result.lots if lot.id in protected} == {
            lot.id: lot for lot in before.lots if lot.id in protected
        }
        assert result.improvement_report["stop_reason"] == "search_limit"
        assert result.improvement_report["moves_accepted"] >= 3
        assert (snapshot.data, snapshot.config, snapshot.result) == original
        fingerprints.append(schedule_fingerprint(result.segments, result.lots))
    assert fingerprints[0] == fingerprints[1]

"""Built transfer alternatives must not disappear before common validation."""

from dataclasses import replace

import pytest

from backend.scheduler import transfer_consolidation as consolidation
from backend.scheduler.improvement import improve_plan
from backend.scheduler.validation import validate_plan
from tests.test_transfer_consolidation import _only_consolidation, _ping_pong


@pytest.mark.parametrize("renamed", [False, True])
def test_third_built_alternative_reaches_the_common_evaluator(monkeypatch, renamed):
    segments, lots, data, config = _ping_pong()
    if renamed:
        segments = [replace(s, run_id=f"alias-{s.run_id}") for s in reversed(segments)]
    good, good_lots, _ = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    assert not validate_plan(good, data, config, lots=good_lots)
    assert good != segments
    # Identical quantity and setup saving, but the first two alternatives are
    # physically invalid. The evaluator, not generator order, must decide.
    bad = [replace(s, shift="A", start_min=0, end_min=int(s.end_min-s.start_min))
           for s in good]
    hop = consolidation.enumerate_transfer_hops(segments, lots, data, config)[0]
    monkeypatch.setattr(consolidation, "enumerate_transfer_hops", lambda *_: [hop])
    monkeypatch.setattr(consolidation, "_first_run_stay_hop", lambda *_: None)
    monkeypatch.setattr(consolidation, "_rebuild", lambda *_a, **_k: [
        (bad, good_lots, ()), (bad, good_lots, ()), (good, good_lots, ()),
    ])
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    assert improved == good
    assert improved_lots == good_lots
    assert report["moves_accepted"] == 1
    assert report["rejections"][f"{consolidation.SCOPE}:physical"] == 1


def test_local_comparison_also_emits_every_built_alternative(monkeypatch):
    segments, lots, data, config = _ping_pong()
    good, good_lots, _ = improve_plan(
        segments, lots, data, config, generators=_only_consolidation(data, config),
    )
    hop = consolidation.enumerate_transfer_hops(segments, lots, data, config)[0]
    run_map = consolidation._resolve_runs(segments, lots, None)
    monkeypatch.setattr(consolidation, "_local_displaced_runs", lambda *_: ([], None))
    monkeypatch.setattr(consolidation, "_rebuild", lambda *_a, **_k: [
        (good, good_lots, (("choice", str(index)),)) for index in range(3)
    ])
    proposals = list(consolidation._local_stay_proposals(
        hop, segments, lots, run_map, set(), data, config,
        consolidation.physical_setups(segments),
    ))
    assert len(proposals) == 3
    assert {p.subject["assignments"]["choice"] for p in proposals} == {"0", "1", "2"}


def test_beam_pruning_is_reported_by_the_builder():
    segments, lots, data, config = _ping_pong()
    hop = next(h for h in consolidation.enumerate_transfer_hops(segments, lots, data, config)
               if h.from_machine == "M2")
    limits = set()
    states = consolidation._rebuild(
        hop, ["RU"], segments, lots,
        consolidation._resolve_runs(segments, lots, None), data, config,
        beam_width=1, search_limits=limits,
    )
    assert len(states) == 1
    assert limits == {"beam_width"}


@pytest.mark.parametrize("local", [False, True])
def test_truncated_beam_reaches_the_coordinator_and_cached_skips(monkeypatch, local):
    from backend.planning_control import planning_scope

    segments, lots, data, config = _ping_pong()
    hop = consolidation.enumerate_transfer_hops(segments, lots, data, config)[0]
    monkeypatch.setattr(consolidation, "enumerate_transfer_hops", lambda *_: [hop])
    monkeypatch.setattr(consolidation, "_first_run_stay_hop",
                        lambda *_: hop if local else None)
    monkeypatch.setattr(consolidation, "_local_displaced_runs", lambda *_: ([], None))
    calls = []

    def truncated(*_args, search_limits, **_kwargs):
        search_limits.add("beam_width")
        calls.append(1)
        return []

    monkeypatch.setattr(consolidation, "_rebuild", truncated)
    with planning_scope(timeout_s=60):
        for _ in range(2):
            improved, output_lots, report = improve_plan(
                segments, lots, data, config, generators=_only_consolidation(data, config),
            )
            assert improved == segments
            assert output_lots == lots
            assert report["status"] == "partial"
            assert report["stop_reason"] == "search_limit"
            assert report["limited_by_scope"][consolidation.SCOPE] == 1
    assert calls


def test_unpruned_small_search_does_not_invent_a_limit():
    segments, lots, data, config = _ping_pong()
    hop = next(h for h in consolidation.enumerate_transfer_hops(segments, lots, data, config)
               if h.from_machine == "M2")
    limits = set()
    states = consolidation._rebuild(
        hop, ["RU"], segments, lots,
        consolidation._resolve_runs(segments, lots, None), data, config,
        beam_width=4, search_limits=limits,
    )
    assert len(states) == 2
    assert limits == set()

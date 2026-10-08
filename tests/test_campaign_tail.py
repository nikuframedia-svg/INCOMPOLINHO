"""Tests for validation-gated short-run placement after setup campaigns."""

from __future__ import annotations

from datetime import date, timedelta

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.campaign_tail import (
    CampaignTailResult,
    campaign_tail_warnings,
    repair_short_runs_after_merged_campaigns,
)
from backend.scheduler.gap_filling import find_gap_opportunities
from backend.scheduler.global_jit import materialise_fixed_run
from backend.scheduler.operational_audit import (
    actionable_gap_opportunities,
    build_operational_audit,
)
from backend.scheduler.priority_normalization import _working_days
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import Lot, Segment, ToolRun
from backend.scheduler.validation import assert_plan_valid
from backend.types import EngineData, MachineInfo


def _data(*, second_machine: bool = False) -> EngineData:
    start = date(2026, 10, 5)
    machine_ids = ["M1", *( ["M2"] if second_machine else [])]
    return EngineData(
        ops=[],
        machines=[
            MachineInfo(id=machine_id, group="Grandes", day_capacity=1020)
            for machine_id in machine_ids
        ],
        twin_groups=[],
        client_demands={},
        workdays=[str(start + timedelta(days=offset)) for offset in range(9)],
        n_days=9,
    )


def _config(*, second_machine: bool = False) -> FactoryConfig:
    config = FactoryConfig(setup_families={"JDE": [["FAMILY-A", "FAMILY-B"]]})
    machine_ids = ["M1", *( ["M2"] if second_machine else [])]
    config.machines = {
        machine_id: MachineConfig(id=machine_id, group="Grandes")
        for machine_id in machine_ids
    }
    return config


def _lot(
    lot_id: str,
    *,
    tool: str,
    sku: str,
    prod_min: float,
    setup_min: float,
    due: int = 7,
    machine: str = "M1",
    setup_family: str = "",
) -> Lot:
    return Lot(
        id=lot_id,
        op_id=f"OP-{lot_id}",
        tool_id=tool,
        machine_id=machine,
        alt_machine_id=None,
        qty=100,
        prod_min=prod_min,
        setup_min=setup_min,
        edd=due,
        is_twin=False,
        sku=sku,
        setup_family=setup_family,
        original_edd=due,
        internal_deadline=due,
        delivery_day=due,
        customer_delivery_day=due,
        production_due_day=due,
        material_release_day=0,
    )


def _run(run_id: str, lots: list[Lot], *, setup_min: float) -> ToolRun:
    total_prod = sum(lot.prod_min for lot in lots)
    return ToolRun(
        id=run_id,
        tool_id=lots[0].tool_id,
        machine_id=lots[0].machine_id,
        alt_machine_id=None,
        lots=lots,
        setup_min=setup_min,
        total_prod_min=total_prod,
        total_min=setup_min + total_prod,
        edd=min(lot.edd for lot in lots),
        production_due_day=min(lot.production_due_day or lot.edd for lot in lots),
    )


def _segments(
    run: ToolRun,
    *,
    day: int,
    minute: int,
    data: EngineData,
    config: FactoryConfig,
) -> list[Segment]:
    working_days = _working_days(data, config)
    slot = working_days.index(day)
    start_coord = slot * config.day_capacity_min
    for shift in sorted(config.shifts, key=lambda item: item.start_min):
        if minute >= shift.end_min:
            start_coord += shift.duration_min
        elif minute > shift.start_min:
            start_coord += minute - shift.start_min
            break
        else:
            break
    return materialise_fixed_run(
        run,
        run.machine_id,
        start_coord,
        working_days,
        config,
    )


def _fixture(
    *,
    short_prod_min: float = 152,
    campaign_prod_min: float = 550,
    campaign_due: int = 7,
    short_due: int = 7,
    campaign_family: str = "FAMILY-A|FAMILY-B",
    distinct_campaign_refs: bool = True,
    short_after_campaign: bool = False,
    source_follower: bool = False,
    tool_conflict: bool = False,
) -> tuple[list[Segment], list[Lot], EngineData, FactoryConfig]:
    data = _data(second_machine=tool_conflict)
    config = _config(second_machine=tool_conflict)
    short = _lot(
        "SHORT",
        tool="SHORT-TOOL",
        sku="SHORT-SKU",
        prod_min=short_prod_min,
        setup_min=30,
        due=short_due,
    )
    family_a = _lot(
        "FAMILY-A",
        tool="JDE",
        sku="FAMILY-A",
        prod_min=campaign_prod_min,
        setup_min=60,
        due=campaign_due,
        setup_family=campaign_family,
    )
    family_b = _lot(
        "FAMILY-B",
        tool="JDE",
        sku="FAMILY-B" if distinct_campaign_refs else "FAMILY-A",
        prod_min=campaign_prod_min,
        setup_min=60,
        due=campaign_due,
        setup_family=campaign_family,
    )
    tail = _lot(
        "TAIL",
        tool="TAIL-TOOL",
        sku="TAIL-SKU",
        prod_min=180,
        setup_min=30,
    )
    short_run = _run("RUN-SHORT", [short], setup_min=30)
    campaign_run = _run("RUN-CAMPAIGN", [family_a, family_b], setup_min=60)
    tail_run = _run("RUN-TAIL", [tail], setup_min=30)
    campaign_segments = _segments(
        campaign_run,
        day=3,
        minute=420,
        data=data,
        config=config,
    )
    segments = [
        *campaign_segments,
        *_segments(tail_run, day=4, minute=930, data=data, config=config),
    ]
    campaign_end = max(
        campaign_segments,
        key=lambda segment: (segment.day_idx, segment.end_min),
    )
    segments.extend(
        _segments(
            short_run,
            day=campaign_end.day_idx if short_after_campaign else 1,
            minute=campaign_end.end_min if short_after_campaign else 420,
            data=data,
            config=config,
        )
    )
    lots = [short, family_a, family_b, tail]

    if source_follower:
        follower = _lot(
            "FOLLOWER",
            tool="FOLLOWER-TOOL",
            sku="FOLLOWER-SKU",
            prod_min=100,
            setup_min=30,
            due=6,
        )
        follower.material_release_day = 1
        follower_run = _run("RUN-FOLLOWER", [follower], setup_min=30)
        segments.extend(
            _segments(follower_run, day=1, minute=602, data=data, config=config)
        )
        lots.append(follower)

    if tool_conflict:
        occupied = _lot(
            "OCCUPIED",
            tool="SHORT-TOOL",
            sku="OTHER-SKU",
            prod_min=300,
            setup_min=0,
            machine="M2",
        )
        occupied_run = _run("RUN-OCCUPIED", [occupied], setup_min=0)
        segments.extend(
            _segments(occupied_run, day=4, minute=930, data=data, config=config)
        )
        lots.append(occupied)

    assert_plan_valid(segments, data, config, lots=lots)
    return segments, lots, data, config


def _placements(segments):
    return sorted(
        (segment.lot_id, segment.day_idx, segment.start_min, segment.end_min)
        for segment in segments
    )


def test_pure_deferral_to_final_shift_is_not_applied():
    """A setup family never reserves the final shift without a strict gain."""

    segments, lots, data, config = _fixture()

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []
    assert repaired.tradeoffs == []
    assert _placements(repaired.segments) == _placements(segments)
    assert campaign_tail_warnings(repaired) == []


def test_short_run_after_campaign_is_not_pushed_to_final_shift():
    segments, lots, data, config = _fixture(short_after_campaign=True)

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []
    assert _placements(repaired.segments) == _placements(segments)
    assert_plan_valid(repaired.segments, data, config, lots=lots)


def test_cpo_closeout_does_not_reserve_final_shift_for_campaign_tail(monkeypatch):
    from backend.cpo import optimizer as optimizer_module

    segments, lots, data, config = _fixture(
        short_after_campaign=True,
        campaign_prod_min=641,
    )
    for lot in lots:
        lot.material_release_day = 3 if lot.id.startswith("FAMILY-") else 4
    result = optimizer_module.ScheduleResult(
        segments=segments,
        lots=lots,
        score=compute_score(segments, lots, data, config=config),
        time_ms=0.0,
        warnings=[],
        operator_alerts=[],
    )
    normalized = optimizer_module._normalize_operational_result(
        result,
        data,
        config,
    )

    moved = [segment for segment in normalized.segments if segment.run_id == "RUN-SHORT"]
    # Material is released on day 4: the earliest legal start is shift A.
    assert {(segment.day_idx, segment.shift) for segment in moved} == {(4, "A")}
    assert not any(
        warning.startswith("Campanhas de setup:") for warning in normalized.warnings
    )
    assert normalized.score["left_shift_opportunities"] == 0


def test_cpo_closeout_normalizes_actionable_gap_created_by_tail_repair(monkeypatch):
    from backend.cpo import optimizer as optimizer_module
    from backend.scheduler import campaign_tail as campaign_tail_module
    from backend.scheduler.scheduler import normalize_earliest_legal_plan

    data = _data()
    config = _config()
    lot = _lot(
        "LATE-TAIL",
        tool="TAIL-TOOL",
        sku="TAIL-SKU",
        prod_min=120,
        setup_min=30,
        due=7,
    )
    run = _run("RUN-LATE-TAIL", [lot], setup_min=30)
    delayed = _segments(run, day=1, minute=480, data=data, config=config)
    settled = normalize_earliest_legal_plan(delayed, [lot], data, config)
    result = optimizer_module.ScheduleResult(
        segments=settled,
        lots=[lot],
        score=compute_score(settled, [lot], data, config=config),
        time_ms=0.0,
        warnings=[],
        operator_alerts=[],
    )
    monkeypatch.setattr(
        campaign_tail_module,
        "repair_short_runs_after_merged_campaigns",
        lambda *_args, **_kwargs: CampaignTailResult(
            segments=delayed,
            moves=[{"skus": [lot.sku]}],
        ),
    )
    closed = optimizer_module._normalize_operational_result(
        result,
        data,
        config,
    )

    assert min(segment.start_min for segment in closed.segments) == 420
    assert closed.score["left_shift_opportunities"] == 0


def test_final_shift_gap_is_actionable_whatever_the_setup_family():
    """No gap is hidden from the audit because of a campaign-tail policy."""

    segments, lots, data, config = _fixture(short_after_campaign=True)
    next(lot for lot in lots if lot.id == "SHORT").material_release_day = 4
    raw = find_gap_opportunities(segments, lots, data, config)
    assert raw

    actionable = actionable_gap_opportunities(
        segments, lots, data, config, gap_opportunities=raw
    )
    assert actionable == raw
    audit = build_operational_audit(
        segments, lots, data, config, gap_opportunities=raw
    )
    assert len(audit["left_shift_detail"]) == len(raw)


def test_campaign_without_two_distinct_family_references_does_not_trigger():
    segments, lots, data, config = _fixture(distinct_campaign_refs=False)

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []


def test_stale_segment_family_not_present_in_config_does_not_trigger():
    segments, lots, data, config = _fixture(campaign_family="STALE-A|STALE-B")

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []


def test_run_larger_than_campaign_tail_limit_does_not_move():
    segments, lots, data, config = _fixture(short_prod_min=220)

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []


def test_delivery_degradation_rejects_otherwise_feasible_move():
    segments, lots, data, config = _fixture(
        campaign_prod_min=700,
        campaign_due=3,
        short_due=3,
    )
    for lot in lots:
        if lot.id in {"FAMILY-A", "FAMILY-B"}:
            lot.material_release_day = 3

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []


def test_cross_machine_tool_conflict_rejects_move():
    segments, lots, data, config = _fixture(tool_conflict=True)

    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []


def test_delivery_tradeoff_is_proposed_not_applied(monkeypatch):
    """A physically valid move that costs delivery stays a proposal."""

    from backend.scheduler import campaign_tail as module

    segments, lots, data, config = _fixture()
    before = [
        (segment.lot_id, segment.day_idx, segment.start_min) for segment in segments
    ]
    real_score = module._score
    calls = {"n": 0}

    def degraded(candidate, *args, **kwargs):
        score = dict(real_score(candidate, *args, **kwargs))
        calls["n"] += 1
        if calls["n"] > 1:
            score["total_tardiness"] = float(score.get("total_tardiness", 0) or 0) + 1
            score["otd"] = 99.0
        return score

    monkeypatch.setattr(module, "_score", degraded)
    repaired = repair_short_runs_after_merged_campaigns(segments, lots, data, config)

    assert repaired.moves == []
    assert [item["run_id"] for item in repaired.tradeoffs] == ["RUN-SHORT"]
    assert all(item["applied"] is False for item in repaired.tradeoffs)
    assert sorted(
        (segment.lot_id, segment.day_idx, segment.start_min)
        for segment in repaired.segments
    ) == sorted(before)
    assert any("sugestão não aplicada" in w for w in campaign_tail_warnings(repaired))


def test_warnings_name_moved_reference_and_tradeoff():
    result = CampaignTailResult(
        segments=[],
        moves=[{"skus": ["JD471512-0071"]}],
        tradeoffs=[{"run_id": "R2", "skus": ["JD000-0001"], "applied": False}],
    )

    warnings = campaign_tail_warnings(result)

    assert len(warnings) == 2
    assert "JD471512-0071" in warnings[0]
    assert "JD000-0001" in warnings[1]
    assert "não aplicada" in warnings[1]

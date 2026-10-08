"""BFP112 regression (plan-melhoria §2.1): start after the setup crew frees up.

The machine is free from 10:50, but the only setup crew is busy until 11:50
with the setup of a lot that already started on another machine (a protected
reservation). The earliest legal start is setup 11:50, production 12:20 on the
same day; it must not slip to the next day's 07:00.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.scheduler import normalize_earliest_legal_plan
from backend.scheduler.types import Lot, Segment
from backend.scheduler.validation import validate_plan
from backend.types import EngineData, MachineInfo

MACHINE_FREE = 650  # 10:50
CREW_FREE = 710  # 11:50


def _config() -> FactoryConfig:
    return FactoryConfig(
        machines={
            "M1": MachineConfig("M1", "Grandes"),
            "M2": MachineConfig("M2", "Grandes"),
        },
        operators={("Grandes", "A"): 6, ("Grandes", "B"): 6},
        setup_crews_by_group={"Grandes": 1},
    )


def _data() -> EngineData:
    data = EngineData(
        ops=[],
        machines=[
            MachineInfo(id="M1", group="Grandes", day_capacity=1020),
            MachineInfo(id="M2", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[],
        client_demands={},
        workdays=[f"2026-09-{day:02d}" for day in range(1, 11)],
        n_days=10,
        holidays=[],
    )
    # Shift B of day 1 is unavailable on M1: after 15:30 there is no room,
    # so missing 11:50 means waiting for day 2.
    data.machine_blocked_intervals = {
        "M1": [{"start_day": 1, "start_min": 930, "end_day": 1, "end_min": 1440}],
    }
    return data


def _lot(lot_id: str, tool: str, *, prod_min: float, setup_min: float) -> Lot:
    return Lot(
        id=lot_id, op_id=lot_id, tool_id=tool, machine_id="M1", alt_machine_id=None,
        qty=100, prod_min=prod_min, setup_min=setup_min, edd=6, original_edd=6,
        is_twin=False, sku=f"SKU-{lot_id}", material_release_day=0,
    )


def _case(*, blocker: str):
    """M1 is busy with started work until 10:50; TARGET now starts day 2 07:00."""

    config, data = _config(), _data()
    target = _lot("TARGET", "T1", prod_min=60, setup_min=30)
    target.material_release_day = 1  # material only arrives on day 1
    # Work already started on M1 (history) occupies it until 10:50, as
    # installed by backend.plans.frozen._install_frozen_reservations.
    data.machine_blocked_intervals["M1"].append(
        {"id": "frozen-prefix-m1", "start_day": 1, "start_min": 420, "end_day": 1,
         "end_min": MACHINE_FREE},
    )
    segments = [
        Segment("TARGET", "R-TARGET", "M1", "T1", 2, 420, 510, "A", 100, 60, 30,
                sku="SKU-TARGET"),
    ]
    lots = [target]
    crew = {"start_day": 1, "start_min": MACHINE_FREE, "end_day": 1, "end_min": CREW_FREE,
            "machine_id": "M2", "tool_id": "TX", "group": "Grandes"}
    if blocker == "reservation":
        # The crew is setting up a lot already started on M2 (history).
        data.setup_crew_reservations = [{**crew, "id": "frozen-prefix-0"}]
    else:
        # The crew blocker is an ordinary plan segment on M2, which cannot
        # start earlier either (M2 busy with history until 10:50).
        data.machine_blocked_intervals["M2"] = [
            {"id": "frozen-prefix-m2", "start_day": 1, "start_min": 420, "end_day": 1,
             "end_min": MACHINE_FREE},
        ]
        other = _lot("OTHER", "TX", prod_min=100, setup_min=60)
        other.machine_id = "M2"
        other.material_release_day = 1
        lots.append(other)
        segments.append(
            Segment("OTHER", "R-OTHER", "M2", "TX", 1, MACHINE_FREE, 810, "A", 100,
                    100, 60, sku="SKU-OTHER"),
        )
    return segments, lots, data, config


def _first(segments, lot_id):
    return min(
        (s for s in segments if s.lot_id == lot_id and s.end_min > s.start_min),
        key=lambda s: (s.day_idx, s.start_min),
    )


@pytest.mark.parametrize("blocker", ["reservation", "plan_segment"])
def test_waits_for_setup_crew_instead_of_next_day(blocker):
    segments, lots, data, config = _case(blocker=blocker)
    assert validate_plan(segments, data, config, lots=lots) == []

    normalized = normalize_earliest_legal_plan(segments, lots, data, config)

    first = _first(normalized, "TARGET")
    assert (first.day_idx, first.start_min, first.setup_min) == (1, CREW_FREE, 30)
    assert first.start_min + first.setup_min == CREW_FREE + 30  # production 12:20
    assert validate_plan(normalized, data, config, lots=lots) == []
    # Starting at 11:50 is explained by the crew, not by the machine (free
    # since 10:50): the reason shown in the Gantt is now the true one.
    assert "blocked_by_setup_crew" in (first.left_shift_blockers or [])


def test_variant_with_other_identifiers_and_times():
    """Same situation, different ids and a 45 min crew wait (plan §8.2)."""

    segments, lots, data, config = _case(blocker="reservation")
    renamed = {"TARGET": "BFP900-B"}
    segments = [
        replace(s, lot_id=renamed.get(s.lot_id, s.lot_id), run_id=f"run-{renamed.get(s.lot_id, s.lot_id)}")
        for s in reversed(segments)
    ]
    for lot in lots:
        lot.id = renamed.get(lot.id, lot.id)
    data.setup_crew_reservations[0]["end_min"] = MACHINE_FREE + 45

    normalized = normalize_earliest_legal_plan(segments, lots, data, config)

    first = _first(normalized, "BFP900-B")
    assert (first.day_idx, first.start_min) == (1, MACHINE_FREE + 45)
    assert validate_plan(normalized, data, config, lots=lots) == []


def test_unrelated_historical_fragments_do_not_block_earlier_setup():
    from backend.scheduler.canonical import preserved_lot_proofs
    from backend.scheduler.improvement import Generator, Proposal, improve_plan

    segments, lots, data, config = _case(blocker="reservation")
    history = _lot("HISTORY", "TH", prod_min=120, setup_min=0)
    history.machine_id = "M2"
    chunks = [
        Segment("HISTORY", "R-HISTORY", "M2", "TH", 0, 420, 480, "A", 50, 60, 0,
                is_continuation=True),
        Segment("HISTORY", "R-HISTORY", "M2", "TH", 0, 480, 540, "A", 50, 60, 0),
    ]
    segments.extend(chunks)
    lots.append(history)
    data.preserved_lot_proofs = preserved_lot_proofs(chunks, [history])

    def compact(items, current_lots):
        return Proposal(
            normalize_earliest_legal_plan(items, current_lots, data, config, annotate=False),
            current_lots,
        )

    assert validate_plan(segments, data, config, lots=lots) == []
    improved, improved_lots, report = improve_plan(
        segments, lots, data, config,
        generators=[Generator("earliest_legal", compact)],
    )

    assert (lambda s: (s.day_idx, s.start_min))(_first(improved, "TARGET")) == (1, CREW_FREE)
    assert [s for s in improved if s.lot_id == "HISTORY"] == chunks
    assert validate_plan(improved, data, config, lots=improved_lots) == []
    assert report["moves_accepted"] >= 1


def test_protected_lot_with_an_earlier_gap_stays_fixed():
    from backend.scheduler.canonical import preserved_lot_proofs
    from backend.scheduler.gap_filling import find_gap_opportunities

    segments, lots, data, config = _case(blocker="reservation")
    history = _lot("HISTORY-GAP", "TH", prod_min=120, setup_min=30)
    history.machine_id = "M2"
    history_segment = Segment(
        "HISTORY-GAP", "R-HISTORY-GAP", "M2", "TH", 3, 420, 570,
        "A", 100, 120, 30,
    )
    history_segment.left_shift_blockers = ["historical explanation"]
    history_segment.material_release_day = 0
    history_segment.release_delay_workdays = 2
    segments.append(history_segment)
    lots.append(history)
    data.preserved_lot_proofs = preserved_lot_proofs([history_segment], [history])

    assert any(
        item.lot_id == history.id
        for item in find_gap_opportunities(segments, lots, data, config)
    )
    normalized = normalize_earliest_legal_plan(segments, lots, data, config)

    assert [s for s in normalized if s.lot_id == history.id] == [history_segment]
    assert (_first(normalized, "TARGET").day_idx, _first(normalized, "TARGET").start_min) == (
        1, CREW_FREE,
    )
    assert validate_plan(normalized, data, config, lots=lots) == []

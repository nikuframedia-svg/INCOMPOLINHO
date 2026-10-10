"""Setup transitions are judged with the started lots that a replan preserves.

A residual calculation keeps started lots out of the plan under validation and
records them in ``data.protected_mounting_segments``. Before 10/10/2026 the
validator ignored them, so a part continuing a tool that the started lot keeps
mounted was reported as "0 de 60 min de setup" (VUL115 after JDE001 on PRM042;
BFP183 after BFP110 on PRM039) and every plan for the PRM031 outage was
refused. The protected segments are evidence: they remove false conflicts and
expose real ones, never hide them.
"""

from __future__ import annotations

import copy
import gzip
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.scheduler.types import Segment
from backend.scheduler.validation import PlanValidationError, validate_plan
from backend.types import EngineData, MachineInfo

SETUP_KINDS = {"missing_tool_change_setup", "insufficient_tool_change_setup"}


def _data(protected: list[Segment]) -> EngineData:
    data = EngineData(
        ops=[],
        machines=[
            MachineInfo(id="PRM042", group="Médias", day_capacity=1020),
            MachineInfo(id="PRM039", group="Grandes", day_capacity=1020),
        ],
        twin_groups=[], client_demands={},
        workdays=[f"2026-10-{day:02d}" for day in range(5, 25)], n_days=20, holidays=[],
    )
    data.protected_mounting_segments = [asdict(segment) for segment in protected]
    return data


def _seg(lot, tool, sku, day, start, end, *, setup=0.0, machine="PRM042", run=None):
    return Segment(
        lot_id=lot, run_id=run or f"RUN_{lot}", machine_id=machine, tool_id=tool,
        day_idx=day, start_min=start, end_min=end, shift="A", qty=100,
        prod_min=float(end - start - setup), setup_min=float(setup), sku=sku,
        run_setup_min=60.0,
    )


# The started VUL115 lot (protected) on day 7; the plan continues the same
# mounted tool on day 8 without a new setup. JDE001 ran earlier, on day 4.
STARTED_VUL = _seg("LOT_VUL115_PRM042_8718696125_0", "VUL115", "8718696125", 7, 420, 529, setup=60)
JDE_EARLY = _seg("LOT_JDE001", "JDE001", "JD471512-0071", 4, 420, 600, setup=60)
VUL_NEXT = _seg("LOT_VUL115_PRM042_8718696125_1", "VUL115", "8718696125", 8, 420, 600)


def _setup_violations(violations):
    return [item for item in violations if item["kind"] in SETUP_KINDS]


def test_continuation_of_a_protected_mounted_tool_is_not_a_missing_setup():
    blind = validate_plan([JDE_EARLY, VUL_NEXT], _data([]))
    assert _setup_violations(blind), "without the started lot the predecessor is JDE001"

    violations = validate_plan([JDE_EARLY, VUL_NEXT], _data([STARTED_VUL]))
    assert _setup_violations(violations) == []


def test_same_tool_other_machine_case_bfp183_after_bfp110():
    started = _seg("LOT_BFP183_0", "BFP183", "REF183", 6, 420, 700, setup=60, machine="PRM039")
    earlier = _seg("LOT_BFP110", "BFP110", "REF110", 3, 420, 700, setup=60, machine="PRM039")
    following = _seg("LOT_BFP183_1", "BFP183", "REF183", 7, 420, 700, machine="PRM039")
    assert _setup_violations(validate_plan([earlier, following], _data([started]))) == []


def test_real_missing_setup_after_the_protected_lot_is_still_reported():
    """Another tool between the started lot and the continuation needs a setup."""
    intruder = _seg("LOT_JDE001_B", "JDE001", "JD471512-0071", 7, 600, 800, setup=60)
    violations = validate_plan([intruder, VUL_NEXT], _data([STARTED_VUL]))
    found = _setup_violations(violations)
    assert [item["lot_id"] for item in found] == [VUL_NEXT.lot_id]
    message = found[0]["message"]
    # Plain Portuguese: tool, reference, machine and day; no internal tuples.
    assert "('" not in message and "LOT_" not in message
    assert "ferramenta VUL115 (ref. 8718696125)" in message
    assert "na PRM042 depois da JDE001" in message
    assert "no dia 8 (13/10), com" in message
    assert "0 de 60 min" in message


def test_plan_segment_that_breaks_a_protected_continuation_is_reported_on_the_plan():
    """The started lot continues without setup; nothing else may be mounted between."""
    protected_next = _seg(
        STARTED_VUL.lot_id, "VUL115", "8718696125", 9, 420, 600, run=STARTED_VUL.run_id,
    )
    intruder = _seg("LOT_JDE001_C", "JDE001", "JD471512-0071", 8, 420, 600, setup=60)
    violations = validate_plan([intruder], _data([STARTED_VUL, protected_next]))
    found = _setup_violations(violations)
    assert len(found) == 1
    assert found[0]["lot_id"] == intruder.lot_id
    assert found[0]["transition"] == "protected_mounting_interrupted"
    assert "produção já iniciada" in found[0]["message"]


def test_protected_segments_alone_are_not_judged():
    """Conflicts inside the preserved history are not the new plan's violations."""
    protected_next = _seg(
        STARTED_VUL.lot_id, "VUL115", "8718696125", 9, 420, 600, run=STARTED_VUL.run_id,
    )
    other = _seg("LOT_OLD", "JDE001", "JD471512-0071", 8, 420, 600)  # no setup, protected
    assert validate_plan([], _data([STARTED_VUL, other, protected_next])) == []


def test_overlap_and_tool_conflict_with_a_protected_segment_are_reported():
    overlapping = _seg("LOT_NEW", "JDE001", "JD471512-0071", 7, 480, 700, setup=60)
    kinds = {item["kind"] for item in validate_plan([overlapping], _data([STARTED_VUL]))}
    assert "machine_overlap" in kinds

    same_tool_elsewhere = _seg(
        "LOT_ELSE", "VUL115", "8718696125", 7, 430, 520, setup=60, machine="PRM039",
    )
    conflicts = [
        item for item in validate_plan([same_tool_elsewhere], _data([STARTED_VUL]))
        if item["kind"] == "tool_conflict"
    ]
    assert [item["lot_id"] for item in conflicts] == ["LOT_ELSE"]


def test_protected_segment_already_in_the_plan_is_not_counted_twice():
    """After splicing, the full plan contains the started lot itself."""
    violations = validate_plan([JDE_EARLY, STARTED_VUL, VUL_NEXT], _data([STARTED_VUL]))
    assert not [item for item in violations if item["kind"] == "machine_overlap"]
    assert _setup_violations(violations) == []


def test_validation_error_text_has_accent_and_plural():
    assert str(PlanValidationError([{}])) == "Plano inválido: 1 conflito."
    assert str(PlanValidationError([{}, {}])) == "Plano inválido: 2 conflitos."


# ── Revision 121 (private fixture): the residual plan of a replan is valid ──

REV121 = Path(__file__).resolve().parent / "fixtures" / "private" / "rev121.json.gz"


@pytest.mark.parametrize("freeze_day", [1, 5])
def test_rev121_residual_plan_has_no_false_setup_conflicts(freeze_day):
    """Revision 121 minus its started lots, judged as a replan judges it.

    Blind to the protected segments the validator reported 3 (freeze day 1)
    and 7 (freeze day 5) false missing setups, e.g. VUL115 after JDE001 on
    PRM042 and BFP183 after BFP110 on PRM039.
    """
    if not REV121.exists():
        pytest.skip("private fixture rev121.json.gz absent")
    from backend.plans.frozen import _frozen_started_lots, _install_frozen_reservations
    from backend.plans.serialize import deserialize_snapshot

    restored = deserialize_snapshot(json.loads(gzip.decompress(REV121.read_bytes())))
    data, config, result = restored["engine_data"], restored["config"], restored["result"]
    frozen_segments, frozen_lots = _frozen_started_lots(result, freeze_day)
    assert frozen_lots
    _install_frozen_reservations(data, frozen_segments, frozen_lots, freeze_day, config)
    frozen_ids = {lot.id for lot in frozen_lots}
    segments = [segment for segment in result.segments if segment.lot_id not in frozen_ids]
    lots = [lot for lot in result.lots if lot.id not in frozen_ids]

    assert validate_plan(segments, data, config, lots=lots) == []

    blind = copy.copy(data)
    blind.protected_mounting_segments = []
    false_conflicts = _setup_violations(validate_plan(segments, blind, config, lots=lots))
    assert false_conflicts, "the fixture still exercises the started-lot predecessor"

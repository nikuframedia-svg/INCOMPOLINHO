"""Started-lot context must never hide a real setup violation (review 10/10/2026)."""

from backend.scheduler.validation import validate_plan
from tests.test_validation_protected_mounting import STARTED_VUL, _data, _seg

KINDS = {"missing_tool_change_setup", "insufficient_tool_change_setup"}


def kinds(v):
    return sorted((x["kind"], x.get("lot_id"), x.get("transition")) for x in v)


def test_c1_protected_same_tool_other_machine_then_plan_without_setup():
    # tool VUL115 runs protected on PRM039 day 7; plan puts it on PRM042 day 8 with no setup
    p = _seg("LOT_P", "VUL115", "8718696125", 7, 420, 600, setup=60, machine="PRM039")
    b = _seg("LOT_B", "VUL115", "8718696125", 8, 420, 600, machine="PRM042")
    v = validate_plan([b], _data([p]))
    assert [x for x in v if x["kind"] in KINDS and x["lot_id"] == "LOT_B"], kinds(v)


def test_c2_plan_missing_setup_before_a_later_protected_segment():
    a = _seg("LOT_A", "JDE001", "JD471512-0071", 6, 420, 600, setup=60)
    b = _seg("LOT_B", "VUL115", "8718696125", 6, 600, 800)  # no setup after JDE001
    p = _seg("LOT_P", "VUL115", "8718696125", 9, 420, 600)
    v = validate_plan([a, b], _data([p]))
    assert [x for x in v if x["kind"] in KINDS and x["lot_id"] == "LOT_B"], kinds(v)


def test_c3_phantom_bridge_stale_protected_copy():
    # Plan moved the started lot's run to day 10 (different key), leaving the protected copy on
    # day 7 as a bridge between JDE001 (day 6) and a VUL115 continuation without setup (day 8).
    a = _seg("LOT_A", "JDE001", "JD471512-0071", 6, 420, 600, setup=60)
    moved = _seg(STARTED_VUL.lot_id, "VUL115", "8718696125", 10, 420, 529, setup=60, run=STARTED_VUL.run_id)
    b = _seg("LOT_B", "VUL115", "8718696125", 8, 420, 600)
    residual = validate_plan([a, b, moved], _data([STARTED_VUL]))
    merged = validate_plan([a, b, moved], _data([]))
    assert [x for x in merged if x["kind"] in KINDS and x["lot_id"] == "LOT_B"]
    assert [x for x in residual if x["kind"] in KINDS and x["lot_id"] == "LOT_B"], kinds(residual)


def test_c4_protected_overlaps_plan_same_tool_same_machine():
    p = _seg("LOT_P", "VUL115", "8718696125", 7, 420, 600, setup=60)
    b = _seg("LOT_B", "VUL115", "8718696125", 7, 500, 700)
    v = validate_plan([b], _data([p]))
    assert any(x["kind"] == "machine_overlap" for x in v), kinds(v)


def test_c5_protected_in_downtime_not_hidden_for_plan():
    # plan segment that needs a setup after protected other tool with only partial setup
    p = _seg("LOT_P", "JDE001", "JD471512-0071", 7, 420, 600, setup=60)
    b = _seg("LOT_B", "VUL115", "8718696125", 7, 600, 700, setup=20)
    v = validate_plan([b], _data([p]))
    assert any(x["kind"] == "insufficient_tool_change_setup" and x["lot_id"] == "LOT_B" for x in v), kinds(v)


def test_c6_plan_segment_identical_key_to_protected_but_other_tool_bridge():
    # Plan contains a copy with the same key as protected (deduped) - nothing double counted
    a = _seg("LOT_A", "JDE001", "JD471512-0071", 6, 420, 600, setup=60)
    b = _seg("LOT_B", "VUL115", "8718696125", 8, 420, 600)
    v = validate_plan([a, STARTED_VUL, b], _data([STARTED_VUL]))
    assert not [x for x in v if x["kind"] in KINDS], kinds(v)
    assert not [x for x in v if x["kind"] == "machine_overlap"], kinds(v)

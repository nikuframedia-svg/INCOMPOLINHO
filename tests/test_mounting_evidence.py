"""Mounting is physical continuity, not continuity of an optimizer run ID."""

from dataclasses import replace

import pytest

from backend.scheduler.gap_filling import tool_is_mounted_at
from backend.scheduler.setup_identity import retained_setup_at, segment_setup_identity
from tests.test_manual_move import _segment


def _prep(start, *, run="CAMPAIGN", machine="M1", tool="T1", sku="SKU1", minutes=30, day=0):
    return replace(_segment(start=start, run_id=run, machine=machine, tool=tool, day=day),
                   sku=sku, end_min=start + minutes, setup_min=minutes,
                   run_setup_min=60, prod_min=0, qty=0)


@pytest.mark.parametrize("prefix", ["", "RENAMED-"])
@pytest.mark.parametrize("interruption", ["mould", "adjustment", "remote"])
def test_interrupted_preparation_cannot_be_accumulated_across_a_mounting_break(prefix, interruption):
    head = _prep(420, run=prefix + "CAMPAIGN")
    tail = _prep(510, run=prefix + "CAMPAIGN")
    if interruption == "mould":
        broken = _prep(450, run="OTHER", tool="OTHER", minutes=60)
    elif interruption == "adjustment":
        broken = _prep(450, run="OTHER", sku="OTHER-ADJUSTMENT", minutes=60)
    else:
        broken = _prep(450, run="OTHER", machine="M2", minutes=60)
    assert not retained_setup_at([tail, head, broken], "M1", segment_setup_identity(tail), 0, 540)


@pytest.mark.parametrize("gap", [0, 90])
@pytest.mark.parametrize("identity", ["reference", "family", "twins"])
def test_complete_uninterrupted_preparation_survives_run_id_changes_and_idle_time(gap, identity):
    head = _prep(420, run="FIRST")
    tail = _prep(450 + gap, run="SECOND")
    if identity == "family":
        head = replace(head, sku="PART-A", setup_family="SHARED")
        tail = replace(tail, sku="PART-B", setup_family="SHARED")
    elif identity == "twins":
        outputs = [("A", "PART-A", 10), ("B", "PART-B", 20)]
        head = replace(head, twin_outputs=outputs)
        tail = replace(tail, twin_outputs=list(reversed(outputs)))
    assert retained_setup_at([tail, head], "M1", segment_setup_identity(tail), 0, tail.end_min)


def test_complete_preparation_after_a_break_can_prove_retention():
    head = _prep(420)
    broken = _prep(450, tool="OTHER", run="OTHER", minutes=60)
    tail = _prep(510, minutes=60)
    assert retained_setup_at([head, broken, tail], "M1", segment_setup_identity(tail), 0, 570)


@pytest.mark.parametrize("case", ["remote", "incomplete", "ongoing"])
def test_diagnostic_and_allocator_require_the_same_mounting_evidence(case):
    head = _prep(420, minutes=60)
    source = _segment("NEXT", start=600, run_id="NEXT")
    if case == "remote":
        history = [head, _prep(510, machine="M2", minutes=60)]
    elif case == "incomplete":
        history = [replace(head, end_min=450, setup_min=30)]
    else:
        history = [head, _prep(510, tool="OTHER", minutes=120)]
    assert not tool_is_mounted_at([*history, source], source, 0, 600)
    assert not retained_setup_at(history, "M1", segment_setup_identity(source), 0, 600)


def test_ignored_allocation_cannot_prove_its_own_mounting():
    head = _prep(420, run="OWN", minutes=60)
    assert not retained_setup_at([head], "M1", segment_setup_identity(head), 0, 480,
                                 ignore_run_id="OWN")


def test_future_activity_does_not_erase_a_completed_mounting():
    head = _prep(420, minutes=60)
    future = _prep(600, machine="M2", run="FUTURE", minutes=60)
    assert retained_setup_at([head, future], "M1", segment_setup_identity(head), 0, 600)


def test_preparation_can_resume_after_a_closed_day_without_remounting():
    head = _prep(1400)
    tail = _prep(420, day=3, run="NEW-ID")
    assert retained_setup_at([head, tail], "M1", segment_setup_identity(tail), 3, 450)


def test_manual_exact_start_reuses_completed_preparation_with_distinct_run_ids():
    from tests.test_manual_move import _config, _engine, _lot
    from backend.plans.manual_move import _materialize_target

    data, config = _engine(), _config()
    lot = replace(_lot(), setup_min=60)
    template = replace(_segment("NEXT", run_id="NEXT"), run_setup_min=60)
    history = [_prep(420, run="FIRST"), _prep(450, run="SECOND")]
    created = _materialize_target(history, lot, template, data, config, 0, "M1", 480)
    assert [(s.start_min, s.end_min, s.setup_min, s.qty) for s in created] == [(480, 540, 0, 100)]


def test_manual_exact_start_cannot_reuse_preparation_from_before_a_mould_switch():
    from tests.test_manual_move import _config, _engine, _lot
    from backend.plans.manual_move import ManualMoveError, _materialize_target

    data, config = _engine(), _config()
    lot = replace(_lot(), setup_min=60)
    template = replace(_segment("NEXT", run_id="NEXT"), run_setup_min=60)
    history = [_prep(420), _prep(450, tool="OTHER", run="OTHER", minutes=60), _prep(510)]
    with pytest.raises(ManualMoveError):
        _materialize_target(history, lot, template, data, config, 0, "M1", 540)

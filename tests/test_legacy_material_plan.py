"""Plans of older material contracts under the current one (A5, T10; 13/10/2026).

Since material version 3 (economic lot = one production, AGENTS §2) the
whole economic lot is released with its first delivery, as plans were built
before 08/10/2026: such a plan is valid again and is never sent to
«Recalcular plano». A real material violation (production before the lot
release) stays a plain validation error.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from backend.config.types import FactoryConfig, MachineConfig
from backend.plans.serialize import planning_model_identity, serialize_result_snapshot
from backend.plans.store import LegacyMaterialPlanError, PlansStore, _assert_activatable_payload
from backend.scheduler.canonical import (
    QUANTITY_MATERIAL_VERSION,
    legacy_material_plan,
    source_contract_violations,
)
from backend.scheduler.lot_sizing import create_lots
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.scoring import compute_score
from backend.scheduler.types import ScheduleResult, Segment
from backend.scheduler.validation import PlanValidationError
from backend.types import EngineData, EOp, MachineInfo

CONFIG = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
RAW_FIELDS = ("material_quantity", "prod_min", "setup_min", "machine_id", "edd/tool")


def _scenario() -> EngineData:
    """One economic lot (32000) covering four deliveries with their own windows."""
    days = [(date(2026, 10, 7) + timedelta(days=i)).isoformat() for i in range(35)]
    demand = [0] * len(days)
    for day, qty in ((13, 5680), (16, 14400), (19, 2400), (20, 9520)):
        demand[day] = qty
    op = EOp(
        id="TOOL_MACHINE_SKU", sku="SKU", client="CLIENT", designation="Part",
        m="MACHINE", t="TOOL", pH=1500, sH=1, operators=1, eco_lot=32000, alt=None,
        stk=0, backlog=0, d=demand, oee=1.0, wip=0,
    )
    return EngineData(
        ops=[op],
        machines=[MachineInfo(id="MACHINE", group="Grandes", day_capacity=1010)],
        twin_groups=[], client_demands={}, workdays=days, n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def _payload(data, segments, lots):
    score = compute_score(segments, lots, data, config=CONFIG, include_operational_audit=False)
    result = ScheduleResult(
        segments=segments, lots=lots, score=score, time_ms=0.0, warnings=[], operator_alerts=[],
    )
    return serialize_result_snapshot(
        data, CONFIG, result, plan_revision=7,
        dataset_info={"id": "isop-legacy", "filename": "isop.xlsx"},
    )


def _blocks(lot, blocks):
    return [
        Segment(
            lot_id=lot.id, run_id="R", machine_id="MACHINE", tool_id="TOOL", day_idx=day,
            start_min=start, end_min=end, shift=shift, qty=qty,
            prod_min=float(end - start - setup), setup_min=float(setup),
            is_continuation=index > 0,
        )
        for index, (day, start, end, setup, qty, shift) in enumerate(blocks)
    ]


# The whole economic lot made from its first release day (days 6-7), as
# plans were built before 08/10/2026 and again since 13/10/2026.
EARLY_BLOCKS = [
    (6, 420, 930, 60, 11250, "A"),
    (6, 930, 1430, 0, 12500, "B"),
    (7, 420, 750, 0, 8250, "A"),
]
# The same production one workday earlier: before the lot release (day 6).
TOO_EARLY_BLOCKS = [(day - 1, *rest) for day, *rest in EARLY_BLOCKS]


def _legacy_plan(blocks=EARLY_BLOCKS):
    data = _scenario()
    lot = create_lots(data, CONFIG, quantity_material=False)[0]
    return data, _blocks(lot, blocks), [lot]


def test_legacy_plan_whole_at_its_first_release_activates_without_recalculation(tmp_path):
    data, segments, lots = _legacy_plan()
    assert not legacy_material_plan(lots, data, CONFIG)
    payload = _payload(data, segments, lots)
    _assert_activatable_payload(payload)
    store = PlansStore(str(tmp_path / "plans.db"))
    try:
        saved = store.save(
            name="Antigo", source="user", origin="isop.xlsx", note="",
            payload=payload, score=payload["score"], gate_report=None,
            is_auto=False, activate=True,
        )
        assert store.active()["id"] == saved["id"]
    finally:
        store.close()


def test_legacy_plan_before_the_lot_release_is_a_plain_validation_error():
    data, segments, lots = _legacy_plan(TOO_EARLY_BLOCKS)
    assert not legacy_material_plan(lots, data, CONFIG)
    with pytest.raises(PlanValidationError) as caught:
        _assert_activatable_payload(_payload(data, segments, lots))
    assert not isinstance(caught.value, LegacyMaterialPlanError)


def test_rebuilt_plan_of_the_same_scenario_activates(tmp_path):
    data = _scenario()
    result = schedule_all(data, config=CONFIG)
    assert not legacy_material_plan(result.lots, data, CONFIG)
    payload = _payload(data, result.segments, result.lots)
    store = PlansStore(str(tmp_path / "plans.db"))
    try:
        saved = store.save(
            name="Reconstruído", source="user", origin="isop.xlsx", note="",
            payload=payload, score=payload["score"], gate_report=None,
            is_auto=False, activate=True,
        )
        assert store.active()["id"] == saved["id"]
    finally:
        store.close()


def test_current_plan_breaking_its_material_window_is_not_called_legacy():
    """A real material violation stays a validation error, not a rebuild hint."""
    data = _scenario()
    lot = create_lots(data, CONFIG)[0]
    assert not legacy_material_plan([lot], data, CONFIG)
    segment = _blocks(lot, TOO_EARLY_BLOCKS)
    payload = _payload(data, segment, [lot])
    with pytest.raises(PlanValidationError) as caught:
        _assert_activatable_payload(payload)
    assert not isinstance(caught.value, LegacyMaterialPlanError)


def test_material_violation_messages_are_plain_portuguese():
    data, segments, lots = _legacy_plan(TOO_EARLY_BLOCKS)
    errors = source_contract_violations(
        segments, lots, data, CONFIG, require_current_material=True,
    )
    material = [item for item in errors if item["field"] == "material_quantity"]
    assert material
    for item in material:
        message = item["message"]
        assert "peças" in message and "É necessário recalcular" in message
        assert "pecas" not in message and "alem" not in message
        assert "day_idx" in item
    renamed = [replace(lot, id="RENAMED") for lot in lots]
    moved = [replace(segment, lot_id="RENAMED") for segment in segments]
    errors = source_contract_violations(
        moved, renamed, data, CONFIG, require_current_material=True,
    )
    for item in errors:
        assert not any(field in item["message"] for field in RAW_FIELDS), item["message"]
        assert "cenario" not in item["message"]


def test_material_version_comes_from_one_constant():
    data = _scenario()
    lot = create_lots(data, CONFIG)[0]
    assert {
        output["quantity_material_version"] for output in lot.output_milestones
    } == {QUANTITY_MATERIAL_VERSION}
    assert planning_model_identity()["quantity_material"] == QUANTITY_MATERIAL_VERSION


def test_material_message_names_reference_machine_and_dated_day():
    """No internal lot id; "dia N (dd/mm)"; pt-PT numbers; correct plural."""
    data, segments, lots = _legacy_plan(TOO_EARLY_BLOCKS)
    errors = source_contract_violations(
        segments, lots, data, CONFIG, require_current_material=True,
    )
    material = [item for item in errors if item["field"] == "material_quantity"]
    assert material
    for item in material:
        message = item["message"]
        assert lots[0].id not in message and "Lote " not in message
        assert message.startswith("Referência SKU (MACHINE), dia ")
        day = item["day_idx"]
        expected_date = (date(2026, 10, 7) + timedelta(days=day)).strftime("%d/%m")
        assert f"dia {day} ({expected_date})" in message


def test_material_message_singular_zero_and_thousands():
    from types import SimpleNamespace

    from backend.scheduler.canonical import _material_message

    data, _segments, lots = _legacy_plan()
    segment = SimpleNamespace(machine_id="MACHINE", day_idx=2)
    assert "só 1 peça tem material libertado" in _material_message(lots[0], segment, 1, data)
    assert "ainda não há peças" in _material_message(lots[0], segment, 0, data)
    assert "só 12 345 peças têm" in _material_message(lots[0], segment, 12345, data)
    assert "só 5680 peças têm" in _material_message(lots[0], segment, 5680, data)


def test_source_contract_message_says_loaded_isop_data():
    data, segments, lots = _legacy_plan()
    renamed = [replace(lot, id="RENAMED", prod_min=lot.prod_min + 50) for lot in lots]
    moved = [replace(segment, lot_id="RENAMED") for segment in segments]
    errors = source_contract_violations(moved, renamed, data, CONFIG)
    assert any("não coincide" in item["message"] for item in errors)
    for item in errors:
        assert "RENAMED" not in item["message"]
        if "não coincide" in item["message"]:
            assert item["message"].endswith("não coincide com os dados carregados (ISOP).")


def test_startup_restore_of_a_legacy_plan_has_no_recalculation_note():
    """The active plan is kept as saved; it no longer predates the rule."""
    import copy

    from backend.copilot.state import CopilotState
    from backend.plans.restore import restore_plan_into_state

    data, segments, lots = _legacy_plan()
    payload = _payload(data, segments, lots)
    target = CopilotState(engine_data=_scenario(), config=copy.deepcopy(CONFIG))
    restore_plan_into_state(
        {"id": "legacy", "name": "Plano ativo", "origin": "isop.xlsx", "payload": payload},
        target, approve_exceptions=True, prefer_current_config=True,
        preserve_exact=True, recover_existing=True,
    )
    assert target.segments == segments
    assert not any("Recalcular plano" in warning for warning in target.warnings)


def test_no_plan_restore_has_a_recalculation_note():
    from backend.plans.restore import legacy_material_warning

    data = _scenario()
    result = schedule_all(data, config=CONFIG)
    assert legacy_material_warning(result.lots, data, CONFIG) is None
    _data, _segments, lots = _legacy_plan()
    assert legacy_material_warning(lots, data, CONFIG) is None
    per_delivery = create_lots(data, CONFIG, quantity_material=2)
    assert legacy_material_warning(per_delivery, data, CONFIG) is None

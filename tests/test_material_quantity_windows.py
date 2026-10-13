"""Economic sizing must not release future demand with the first order."""

from datetime import date, timedelta
from dataclasses import replace

from backend.scheduler.lot_sizing import create_lots
from backend.config.types import FactoryConfig, MachineConfig
from backend.scheduler.scheduler import schedule_all
from backend.scheduler.canonical import source_contract_violations
from backend.types import EOp, EngineData, MachineInfo


def scenario():
    days = [(date(2026, 10, 7) + timedelta(days=i)).isoformat() for i in range(35)]
    demand = [0] * len(days)
    for day, qty in ((13, 5680), (16, 14400), (19, 2400), (20, 9520)):
        demand[day] = qty
    op = EOp(
        id="TOOL_MACHINE_SKU",
        sku="SKU",
        client="CLIENT",
        designation="Part",
        m="MACHINE",
        t="TOOL",
        pH=1500,
        sH=1,
        operators=1,
        eco_lot=32000,
        alt=None,
        stk=0,
        backlog=0,
        d=demand,
        oee=1.0,
        wip=0,
    )
    return EngineData(
        ops=[op],
        machines=[MachineInfo(id="MACHINE", group="Grandes", day_capacity=1010)],
        twin_groups=[],
        client_demands={},
        workdays=days,
        n_days=len(days),
        holidays=[i for i, day in enumerate(days) if date.fromisoformat(day).weekday() >= 5],
    )


def test_economic_lot_preserves_quantity_specific_release_dates():
    lots = create_lots(scenario())
    assert len(lots) == 1
    lot = lots[0]
    assert lot.qty == 32000
    assert lot.id == "LOT_TOOL_MACHINE_SKU_13"
    assert [
        (m["qty"], m["customer_delivery_day"], m["material_release_day"])
        for m in lot.output_milestones
    ] == [
        (5680, 13, 6),
        (14400, 16, 9),
        (2400, 19, 12),
        (9520, 20, 13),
    ]


def test_full_pipeline_does_not_produce_unreleased_future_quantities():
    data = scenario()
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert sum(segment.qty for segment in result.segments) == 32000
    for day, maximum in ((8, 5680), (11, 20080), (12, 22480)):
        assert sum(segment.qty for segment in result.segments if segment.day_idx <= day) <= maximum
    assert min(segment.day_idx for segment in result.segments if segment.qty > 0) == 6


def test_validator_rejects_anticipating_the_unreleased_tail():
    data = scenario()
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    for segment in result.segments:
        segment.day_idx = 6
    violations = source_contract_violations(result.segments, result.lots, data, config)
    assert any(item["field"] == "material_quantity" for item in violations)


def test_each_quantity_has_its_own_completion_not_the_end_of_the_lot():
    from backend.scheduler.material_quantities import output_completion_days
    from backend.scheduler.types import Segment

    lot = create_lots(scenario())[0]
    segments = [
        Segment(
            lot_id=lot.id,
            run_id="R",
            machine_id="MACHINE",
            tool_id="TOOL",
            day_idx=day,
            start_min=420,
            end_min=500,
            shift="A",
            qty=qty,
            prod_min=80,
        )
        for day, qty in ((6, 5680), (9, 14400), (12, 2400), (13, 9520))
    ]
    assert [
        (output["customer_delivery_day"], completed)
        for output, completed in output_completion_days(lot, segments, 35)
    ] == [
        (13, 6),
        (16, 9),
        (19, 12),
        (20, 13),
    ]


def test_waiting_for_future_material_does_not_reserve_the_machine():
    data = scenario()
    demand = [0] * data.n_days
    demand[14] = 1000  # Release on day 7, between the first lot's portions.
    other = replace(
        data.ops[0], id="OTHER_MACHINE_OTHER", sku="OTHER", t="OTHER", d=demand, eco_lot=0
    )
    data.ops.append(other)
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert min(s.day_idx for s in result.segments if s.sku == "OTHER") == 7
    assert sum(s.qty for s in result.segments if s.sku == "SKU") == 32000
    assert len([lot for lot in result.lots if lot.sku == "SKU"]) == 1


def test_legacy_snapshot_is_readable_but_early_quantity_cannot_be_committed():
    from backend.scheduler.types import Segment

    data = scenario()
    lot = create_lots(data, quantity_material=False)[0]
    segment = Segment(
        lot_id=lot.id,
        run_id="R",
        machine_id="MACHINE",
        tool_id="TOOL",
        day_idx=6,
        start_min=420,
        end_min=1430,
        shift="A",
        qty=32000,
        prod_min=lot.prod_min,
        setup_min=lot.setup_min,
    )
    assert not source_contract_violations([segment], [lot], data, FactoryConfig())
    errors = source_contract_violations(
        [segment],
        [lot],
        data,
        FactoryConfig(),
        require_current_material=True,
    )
    assert any(item["field"] == "material_quantity" for item in errors)
    lot.id = segment.lot_id = "RENAMED"
    errors = source_contract_violations(
        [segment], [lot], data, FactoryConfig(), require_current_material=True,
    )
    assert any(item["field"] == "material_quantity" for item in errors)


def test_empty_mounting_context_preserves_legacy_engine_identity():
    from dataclasses import asdict
    from backend.plans.serialize import value_fingerprint

    data = scenario()
    legacy = asdict(data)
    legacy.pop("protected_mounting_segments")
    legacy.pop("residual_lot_remainders")
    # No history boundary (AGENTS §2 rule 4, 13/10/2026) is no new key either.
    legacy.pop("history_boundary")
    assert value_fingerprint(data) == value_fingerprint(legacy)


def test_reinserting_one_material_portion_preserves_the_economic_lot():
    from backend.scheduler.alternative_repair import (
        _replace_lots, _resolve_runs, _schedule_run_earliest,
    )
    from backend.scheduler.validation import validate_plan

    # Another tool released on day 7 breaks the mounting after the first
    # portion: the economic lot runs as two physical runs (B1a campaigns).
    data = scenario()
    demand = [0] * data.n_days
    demand[14] = 1000
    data.ops.append(replace(
        data.ops[0], id="OTHER_MACHINE_OTHER", sku="OTHER", t="OTHER", d=demand, eco_lot=0,
    ))
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    runs = _resolve_runs(result.segments, result.lots, None)
    sku_runs = [run for run in runs.values() if run.tool_id == "TOOL"]
    assert sorted(lot.qty for run in sku_runs for lot in run.lots) == [5680, 26320]
    for run in sku_runs:
        fixed = [s for s in result.segments if s.run_id != run.id]
        rebound, created = _schedule_run_earliest(run, "MACHINE", fixed, data, config)
        combined = [*fixed, *created]
        lots = _replace_lots(result.lots, rebound.lots)
        assert lots == result.lots
        assert sum(s.qty for s in combined if s.sku == "SKU") == 32000
        assert all(s.lot_qty == 32000 for s in created)
        assert not validate_plan(combined, data, config, lots=lots)


def test_released_portions_continue_on_the_mounted_tool_in_one_run():
    """Rule 1 (10/10): nothing else needs the machine, so the tool stays mounted
    across the material waits: one setup, one run, portion boundaries kept."""

    data = scenario()
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert len({s.run_id for s in result.segments}) == 1
    assert sum(1 for s in result.segments if s.setup_min > 0) == 1
    # Every portion ends on a segment boundary.
    cumulative, boundaries = 0, set()
    for segment in sorted(result.segments, key=lambda s: (s.day_idx, s.start_min)):
        cumulative += segment.qty
        boundaries.add(cumulative)
    assert {5680, 20080, 22480, 32000} <= boundaries

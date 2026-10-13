"""Economic lot = one production (AGENTS §2, 13/10/2026).

The BFP082 case: one economic lot of 32 000 pieces covers the deliveries of
days 13, 16, 19 and 20. Its material is released with the first delivery
(day 6) for the whole lot; the later deliveries and the surplus inherit it.
Until 13/10 each delivery waited for its own release (per-delivery window,
material versions 1-2).
"""

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


def test_economic_lot_is_released_with_its_first_delivery():
    lots = create_lots(scenario())
    assert len(lots) == 1
    lot = lots[0]
    assert lot.qty == 32000
    assert lot.id == "LOT_TOOL_MACHINE_SKU_13"
    # Each delivery keeps its own window for traceability only.
    assert [
        (m["qty"], m["customer_delivery_day"], m["material_release_day"],
         m["delivery_material_release_day"])
        for m in lot.output_milestones
    ] == [
        (5680, 13, 6, 6),
        (14400, 16, 6, 9),
        (2400, 19, 6, 12),
        (9520, 20, 6, 13),
    ]


def test_full_pipeline_produces_the_whole_lot_from_its_release():
    data = scenario()
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert sum(segment.qty for segment in result.segments) == 32000
    assert min(segment.day_idx for segment in result.segments if segment.qty > 0) == 6
    # The later deliveries do not wait for their own windows (day 9 for 16).
    assert sum(segment.qty for segment in result.segments if segment.day_idx <= 8) > 5680


def test_validator_rejects_production_before_the_lot_release_only():
    from backend.scheduler.validation import validate_plan

    data = scenario()
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert not source_contract_violations(result.segments, result.lots, data, config)
    for segment in result.segments:
        segment.day_idx -= min(s.day_idx for s in result.segments) - 5
    violations = validate_plan(result.segments, data, config, lots=result.lots)
    assert any(item["kind"] == "setup_before_material" for item in violations)


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


def test_another_tool_never_splits_the_economic_lot():
    data = scenario()
    demand = [0] * data.n_days
    demand[14] = 1000  # Released on day 7, while the economic lot runs.
    other = replace(
        data.ops[0], id="OTHER_MACHINE_OTHER", sku="OTHER", t="OTHER", d=demand, eco_lot=0
    )
    data.ops.append(other)
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert sum(s.qty for s in result.segments if s.sku == "SKU") == 32000
    assert len([lot for lot in result.lots if lot.sku == "SKU"]) == 1
    assert sum(1 for s in result.segments if s.sku == "SKU" and s.setup_min > 0) == 1
    sku = [s for s in result.segments if s.sku == "SKU"]
    first = min((s.day_idx, s.start_min) for s in sku)
    last = max((s.day_idx, s.end_min) for s in sku)
    assert all(
        not first < (s.day_idx, s.start_min) < last for s in result.segments if s.sku == "OTHER"
    )
    # Not at the cost of the other order: it is still ready on time (day 7,
    # due day 14), before the economic lot.
    from backend.scheduler.material_quantities import delivery_portions

    (other_order,) = [
        portion for portion in delivery_portions(result.lots, result.segments, data)
        if portion.sku == "OTHER" and portion.is_demand
    ]
    assert other_order.complete
    assert other_order.customer_ready_day <= other_order.customer_delivery_day == 14


def test_legacy_snapshot_whole_at_the_first_release_stays_committable():
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
    # Material version 3 releases the whole lot on day 6, like this legacy
    # plan: it stays committable, also under another lot id.
    assert not source_contract_violations(
        [segment], [lot], data, FactoryConfig(), require_current_material=True,
    )
    lot.id = segment.lot_id = "RENAMED"
    assert not source_contract_violations(
        [segment], [lot], data, FactoryConfig(), require_current_material=True,
    )
    # One day before the lot release it is refused.
    segment.day_idx = 5
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


def test_reinserting_the_economic_lot_keeps_it_whole():
    from backend.scheduler.alternative_repair import (
        _replace_lots, _resolve_runs, _schedule_run_earliest,
    )
    from backend.scheduler.validation import validate_plan

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
    assert [lot.qty for run in sku_runs for lot in run.lots] == [32000]
    (run,) = sku_runs
    fixed = [s for s in result.segments if s.run_id != run.id]
    rebound, created = _schedule_run_earliest(run, "MACHINE", fixed, data, config)
    combined = [*fixed, *created]
    lots = _replace_lots(result.lots, rebound.lots)
    assert lots == result.lots
    assert sum(s.qty for s in combined if s.sku == "SKU") == 32000
    assert all(s.lot_qty == 32000 for s in created)
    assert not validate_plan(combined, data, config, lots=lots)


def test_the_economic_lot_is_one_run_with_one_setup():
    """Rule of 13/10: one production, one setup, from the lot release."""

    data = scenario()
    config = FactoryConfig(machines={"MACHINE": MachineConfig(id="MACHINE", group="Grandes")})
    result = schedule_all(data, config=config)
    assert len({s.run_id for s in result.segments}) == 1
    assert sum(1 for s in result.segments if s.setup_min > 0) == 1
    assert sum(s.qty for s in result.segments) == 32000

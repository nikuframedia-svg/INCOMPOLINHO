"""CTP — Capable to Promise — Spec 03 §2.

"Can we fit N more pieces of SKU X by day D?"
Uses simultaneous resource windows inside the material-to-production window.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from backend.calendar import (
    available_machine_capacity,
    available_tool_capacity,
    is_factory_workday,
)
from backend.config.planning import planning_milestones_for_op
from backend.config.shifts import ordered_shifts
from backend.config.types import FactoryConfig
from backend.scheduler.constants import DAY_CAP, DEFAULT_OEE
from backend.scheduler.jit_policy import calendar_holidays
from backend.scheduler.operators import effective_operator_capacity, segment_operator_demand
from backend.scheduler.resources import effective_oee, resolve_setup_hours
from backend.scheduler.types import Segment
from backend.types import EngineData


@dataclass(slots=True)
class CTPResult:
    feasible: bool
    sku: str
    qty_requested: int
    latest_day: int | None  # latest day to START production (JIT)
    earliest_end_day: int | None  # earliest day production can END
    machine: str | None
    confidence: str  # "high" | "medium" | "low"
    slack_min: float
    reason: str | None
    date_start: str | None = None  # real date of latest_day
    date_end: str | None = None  # real date of earliest_end_day
    required_min: float = 0.0  # total minutes needed (setup + prod)
    prod_days: int = 0  # number of production days needed
    customer_delivery_day: int | None = None
    latest_subcontract_dispatch_day: int | None = None
    production_due_day: int | None = None
    subcontract_dispatch_day: int | None = None
    internal_target_day: int | None = None
    material_reference_day: int | None = None
    material_release_day: int | None = None
    material_reference_kind: str = "customer_delivery"
    customer_delivery_date: str | None = None
    latest_subcontract_dispatch_date: str | None = None
    production_due_date: str | None = None
    subcontract_dispatch_date: str | None = None
    internal_target_date: str | None = None
    material_reference_date: str | None = None
    material_release_date: str | None = None


def compute_ctp(
    sku: str,
    qty: int,
    deadline_day: int,
    segments: list[Segment],
    engine_data: EngineData,
    config: FactoryConfig | None = None,
) -> CTPResult:
    """CTP within the material-to-production window for a customer promise."""
    day_cap = config.day_capacity_min if config else DAY_CAP
    oee_default = config.oee_default if config else DEFAULT_OEE
    workdays = getattr(engine_data, "workdays", []) or []

    def _day_to_date(d: int | None) -> str | None:
        """Map day index to real date string."""
        if d is None:
            return None
        if 0 <= d < len(workdays):
            return workdays[d]
        if workdays:
            try:
                first = date.fromisoformat(str(workdays[0])[:10])
                return (first + timedelta(days=d)).isoformat()
            except (ValueError, OverflowError):
                pass
        return None

    def _fail(
        reason: str,
        machine: str | None = None,
        *,
        milestone_values: dict[str, int | str | None] | None = None,
    ) -> CTPResult:
        values = milestone_values or {}
        return CTPResult(
            feasible=False,
            sku=sku,
            qty_requested=qty,
            latest_day=None,
            earliest_end_day=None,
            machine=machine,
            confidence="low",
            slack_min=0,
            reason=reason,
            customer_delivery_day=_optional_int(values.get("customer_delivery_day")),
            latest_subcontract_dispatch_day=_optional_int(
                values.get("latest_subcontract_dispatch_day")
            ),
            production_due_day=_optional_int(values.get("production_due_day")),
            subcontract_dispatch_day=_optional_int(
                values.get("subcontract_dispatch_day")
            ),
            internal_target_day=_optional_int(values.get("internal_target_day")),
            material_reference_day=_optional_int(
                values.get("material_reference_day")
            ),
            material_release_day=_optional_int(values.get("material_release_day")),
            material_reference_kind=str(
                values.get("material_reference_kind") or "customer_delivery"
            ),
            customer_delivery_date=_day_to_date(
                _optional_int(values.get("customer_delivery_day"))
            ),
            latest_subcontract_dispatch_date=_day_to_date(
                _optional_int(values.get("latest_subcontract_dispatch_day"))
            ),
            production_due_date=_day_to_date(
                _optional_int(values.get("production_due_day"))
            ),
            subcontract_dispatch_date=_day_to_date(
                _optional_int(values.get("subcontract_dispatch_day"))
            ),
            internal_target_date=_day_to_date(
                _optional_int(values.get("internal_target_day"))
            ),
            material_reference_date=_day_to_date(
                _optional_int(values.get("material_reference_day"))
            ),
            material_release_date=_day_to_date(
                _optional_int(values.get("material_release_day"))
            ),
        )

    matching_ops = [candidate for candidate in engine_data.ops if candidate.sku == sku]
    if not matching_ops:
        return _fail(f"SKU {sku} não encontrado")
    if len(matching_ops) > 1:
        return _fail(
            f"SKU {sku} é ambíguo: existem {len(matching_ops)} operações. "
            "Corrija os dados mestre antes de calcular a promessa."
        )
    op = matching_ops[0]

    max_backward = (
        int(op.subcontract_lead_time_days or 0)
        + int(op.subcontract_buffer_days or 0)
        + int(op.finish_buffer_days or 0)
        + 5
    )
    holidays = calendar_holidays(
        engine_data,
        -(14 + math.ceil(max_backward / 5) * 7),
        engine_data.n_days + 14,
    )
    milestones = planning_milestones_for_op(op, deadline_day, holidays)
    milestone_values = {
        "customer_delivery_day": milestones.customer_delivery_day,
        "latest_subcontract_dispatch_day": (
            milestones.latest_subcontract_dispatch_day
        ),
        "production_due_day": milestones.production_due_day,
        "subcontract_dispatch_day": milestones.subcontract_dispatch_day,
        "internal_target_day": milestones.internal_target_day,
        "material_reference_day": milestones.material_reference_day,
        "material_release_day": milestones.material_release_day,
        "material_reference_kind": milestones.material_reference_kind,
    }

    if op.pH <= 0:
        return _fail(
            "pH = 0, cadência desconhecida",
            machine=op.m,
            milestone_values=milestone_values,
        )

    def _machine_group(machine_id: str) -> str:
        configured = config.machines.get(machine_id) if config else None
        if configured is not None:
            return configured.group
        machine = next((item for item in engine_data.machines if item.id == machine_id), None)
        return str(getattr(machine, "group", "") or "default")

    machine_used: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    tool_used: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    machine_busy: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    tool_busy: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    operator_busy: dict[tuple[str, int], list[tuple[float, float, int]]] = defaultdict(list)
    setup_crew_busy: dict[tuple[str, int], list[tuple[float, float, int]]] = defaultdict(list)
    for seg in segments:
        occupied = max(
            0.0,
            float(seg.end_min - seg.start_min),
            float(seg.prod_min) + float(seg.setup_min),
        )
        machine_used[seg.machine_id][seg.day_idx] += occupied
        tool_used[seg.tool_id][seg.day_idx] += occupied
        if seg.end_min > seg.start_min:
            interval = (int(seg.start_min), int(seg.end_min))
            machine_busy[(seg.machine_id, seg.day_idx)].append(interval)
            tool_busy[(seg.tool_id, seg.day_idx)].append(interval)
        group = _machine_group(seg.machine_id)
        setup_end = seg.start_min + max(0.0, seg.setup_min)
        if seg.prod_min > 0:
            operator_busy[(group, seg.day_idx)].append(
                (setup_end, float(seg.end_min), segment_operator_demand(seg, engine_data))
            )
        if seg.setup_min > 0:
            setup_crew_busy[(group, seg.day_idx)].append(
                (float(seg.start_min), setup_end, 1)
            )

    n_days = engine_data.n_days
    first_allowed_day = max(0, milestones.material_release_day)
    production_due = milestones.production_due_day
    if production_due < first_allowed_day:
        return _fail(
            "A janela produtiva desta promessa termina antes do horizonte disponível.",
            machine=op.m,
            milestone_values=milestone_values,
        )

    shifts = ordered_shifts(config or FactoryConfig())
    operator_demand = max(1, int(op.operators or 1))

    def _daily_windows(
        machine_id: str, day_idx: int
    ) -> tuple[list[tuple[float, float, bool, bool]], float]:
        """Sweep exact events; setup needs one crew, production the full team."""
        if not is_factory_workday(day_idx, engine_data, config):
            return [], 0.0
        budget = min(
            max(
                0.0,
                available_machine_capacity(machine_id, day_idx, engine_data, config)
                - machine_used.get(machine_id, {}).get(day_idx, 0.0),
            ),
            max(
                0.0,
                available_tool_capacity(op.t, day_idx, engine_data, config)
                - tool_used.get(op.t, {}).get(day_idx, 0.0),
            ),
        )
        if budget <= 0:
            return [], 0.0
        group = _machine_group(machine_id)
        crew_count = max(0, int(config.setup_crews_by_group.get(group, 1))) if config else 1
        blocked = [
            *machine_busy.get((machine_id, day_idx), ()),
            *tool_busy.get((op.t, day_idx), ()),
            *(
                (
                    int(item.get("start_min", 0)),
                    int(item.get("end_min", 1440)),
                )
                for item in engine_data.machine_blocked_intervals.get(machine_id, [])
                if int(item.get("start_day", -1)) == day_idx
            ),
            *(
                (
                    int(item.get("start_min", 0)),
                    int(item.get("end_min", 1440)),
                )
                for item in engine_data.tool_blocked_intervals.get(op.t, [])
                if int(item.get("start_day", -1)) == day_idx
            ),
        ]
        windows: list[tuple[float, float, bool, bool]] = []
        resource_free = 0.0
        offset = float(day_idx * day_cap)
        for shift in shifts:
            shift_start, shift_end = float(shift.start_min), float(shift.end_min)
            events: dict[float, list[int]] = {
                shift_start: [0, 0, 0],
                shift_end: [0, 0, 0],
            }

            def add_event(start: float, end: float, count: int, kind: int) -> None:
                start, end = max(shift_start, start), min(shift_end, end)
                if start < end:
                    events.setdefault(start, [0, 0, 0])[kind] += count
                    events.setdefault(end, [0, 0, 0])[kind] -= count

            for start, end in blocked:
                add_event(start, end, 1, 0)
            for start, end, count in setup_crew_busy.get((group, day_idx), ()):
                add_event(start, end, count, 1)
            for start, end, count in operator_busy.get((group, day_idx), ()):
                add_event(start, end, count, 2)
            for block in engine_data.operator_blocked_intervals:
                if (
                    int(block.get("start_day", -1)) == day_idx
                    and str(block.get("group", "")) == group
                    and str(block.get("shift", "")) == shift.id
                ):
                    add_event(
                        float(block.get("start_min", 0)),
                        float(block.get("end_min", 0)),
                        max(0, int(block.get("count", 1))),
                        2,
                    )
            operators = max(
                0,
                int(effective_operator_capacity(engine_data, config, day_idx, group, shift.id)),
            )
            active = [0, 0, 0]
            minutes = sorted(events)
            for index, start in enumerate(minutes[:-1]):
                active = [value + delta for value, delta in zip(active, events[start])]
                end = minutes[index + 1]
                free = active[0] == 0
                if free:
                    resource_free += end - start
                windows.append(
                    (
                        offset + start - shift_start,
                        offset + end - shift_start,
                        free and active[1] < crew_count,
                        free and operators - active[2] >= operator_demand,
                    )
                )
            offset += shift_end - shift_start
        return windows, min(budget, resource_free)

    def _candidate_requirements(machine_id: str) -> tuple[float, float, float]:
        oee = effective_oee(op, machine_id, config) if config else (op.oee or oee_default)
        setup_hours = (
            resolve_setup_hours(op.sku, machine_id, op.sH, config)
            if config
            else (op.sH or 0.5)
        )
        prod_min = (qty / op.pH) * 60 / oee if oee > 0 else math.inf
        return setup_hours * 60, prod_min, oee

    def _find_slot(
        machine_id: str,
        setup_min: float,
        prod_min: float,
    ) -> tuple[int | None, int | None, tuple[float, float, float]]:
        last_day = min(production_due, n_days - 1)
        windows: list[tuple[float, float, bool, bool]] = []
        budgets: dict[int, float] = {}
        capacities: dict[int, tuple[float, float, float]] = {}
        for day_idx in range(first_allowed_day, last_day + 1):
            daily, budget = _daily_windows(machine_id, day_idx)
            windows.extend(daily)
            budgets[day_idx] = budget
            capacities[day_idx] = (
                budget,
                min(budget, sum(end - start for start, end, _, prod in daily if prod)),
                min(budget, sum(end - start for start, end, crew, _ in daily if crew)),
            )

        # A setup is contiguous in factory work-time and precedes production.
        # Adjacent shift fragments merge, but a busy resource breaks the span.
        setup_spans: list[tuple[float, float]] = []
        productive: list[tuple[float, float]] = []
        for start, end, crew, prod in windows:
            if crew:
                if setup_spans and abs(setup_spans[-1][1] - start) <= 1e-9:
                    setup_spans[-1] = (setup_spans[-1][0], end)
                else:
                    setup_spans.append((start, end))
            if prod:
                productive.append((start, end))

        accumulated = [0.0, 0.0, 0.0]
        for first_day in range(last_day, first_allowed_day - 1, -1):
            accumulated = [
                total + value for total, value in zip(accumulated, capacities[first_day])
            ]
            if (
                accumulated[0] + 1e-9 < setup_min + prod_min
                or accumulated[1] + 1e-9 < prod_min
                or accumulated[2] + 1e-9 < setup_min
            ):
                continue
            lower = first_day * day_cap
            candidates = set()
            for prod_start, prod_end in productive:
                if setup_min <= 0:
                    candidate = max(lower, prod_start)
                    if candidate < prod_end:
                        candidates.add(candidate)
                    continue
                for setup_start, setup_end in setup_spans:
                    candidate = max(prod_start, max(lower, setup_start) + setup_min)
                    if candidate < prod_end and candidate <= setup_end + 1e-9:
                        candidates.add(candidate)

            for production_start in sorted(candidates):
                remaining_budget = dict(budgets)
                setup_start = production_start - setup_min
                start_day = int(setup_start // day_cap)
                for day_idx in range(start_day, int(production_start // day_cap) + 1):
                    used = max(
                        0.0,
                        min(production_start, (day_idx + 1) * day_cap)
                        - max(setup_start, day_idx * day_cap),
                    )
                    remaining_budget[day_idx] -= used
                if any(value < -1e-9 for value in remaining_budget.values()):
                    continue
                remaining = prod_min
                for start, end in productive:
                    start = max(start, production_start)
                    if start >= end:
                        continue
                    day_idx = int(start // day_cap)
                    duration = min(end - start, max(0.0, remaining_budget[day_idx]))
                    if duration <= 0:
                        if start == production_start:
                            break
                        continue
                    remaining -= duration
                    remaining_budget[day_idx] -= duration
                    if remaining <= 1e-9:
                        return start_day, day_idx, tuple(accumulated)
        return None, None, tuple(accumulated)

    machines = list(dict.fromkeys([op.m, *([op.alt] if op.alt else [])]))

    for machine in machines:
        setup_min, prod_min, oee = _candidate_requirements(machine)
        if oee <= 0:
            continue
        required_min = setup_min + prod_min
        prod_days_needed = max(1, math.ceil(required_min / max(1, day_cap)))
        start_day, end_day, total_capacity = _find_slot(machine, setup_min, prod_min)
        if start_day is not None and start_day <= production_due:
            resource_capacity, operator_capacity, crew_capacity = total_capacity
            slack = min(
                resource_capacity - required_min,
                operator_capacity - prod_min,
                crew_capacity - setup_min,
            )
            confidence = (
                "high" if slack > day_cap * 0.3 else "medium" if slack > day_cap * 0.1 else "low"
            )
            return CTPResult(
                feasible=True,
                sku=sku,
                qty_requested=qty,
                latest_day=start_day,
                earliest_end_day=end_day,
                machine=machine,
                confidence=confidence,
                slack_min=max(0, slack),
                reason=None,
                date_start=_day_to_date(start_day),
                date_end=_day_to_date(end_day) if end_day is not None else None,
                required_min=round(required_min, 1),
                prod_days=prod_days_needed,
                customer_delivery_day=milestones.customer_delivery_day,
                latest_subcontract_dispatch_day=(
                    milestones.latest_subcontract_dispatch_day
                ),
                production_due_day=milestones.production_due_day,
                subcontract_dispatch_day=milestones.subcontract_dispatch_day,
                internal_target_day=milestones.internal_target_day,
                material_reference_day=milestones.material_reference_day,
                material_release_day=milestones.material_release_day,
                material_reference_kind=milestones.material_reference_kind,
                customer_delivery_date=_day_to_date(
                    milestones.customer_delivery_day
                ),
                latest_subcontract_dispatch_date=_day_to_date(
                    milestones.latest_subcontract_dispatch_day
                ),
                production_due_date=_day_to_date(milestones.production_due_day),
                subcontract_dispatch_date=_day_to_date(
                    milestones.subcontract_dispatch_day
                ),
                internal_target_date=_day_to_date(milestones.internal_target_day),
                material_reference_date=_day_to_date(
                    milestones.material_reference_day
                ),
                material_release_date=_day_to_date(milestones.material_release_day),
            )

    boundary = (
        "ao envio para subcontratação"
        if milestones.subcontract_dispatch_day is not None
        else "à entrega ao cliente"
    )
    return _fail(
        f"Sem capacidade em {' ou '.join(machines)} até {boundary} (D{production_due})",
        milestone_values=milestone_values,
    )


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def verify_ctp(
    sku, qty, deadline_day, baseline_result, engine_data, config, *, active_mutations=None
):
    """A promise is backed by the exact scenario, including all reinstalls."""
    from backend.cpo.optimizer import MODE_CONFIG
    from backend.planning_control import planning_scope

    with planning_scope(timeout_s=float(MODE_CONFIG["normal"]["time_budget_s"])):
        return _verify_ctp(sku, qty, deadline_day, baseline_result, engine_data, config,
                           active_mutations=active_mutations)


def _verify_ctp(
    sku, qty, deadline_day, baseline_result, engine_data, config, *, active_mutations=None
):
    from dataclasses import asdict

    from backend.analytics.stock_projection import build_production_by_op
    from backend.scheduler.jit_policy import add_workdays, lot_output_milestones
    from backend.simulator.simulator import Mutation, simulate
    from backend.validation import strict_int

    sku, qty, deadline_day = (
        str(sku).strip(),
        strict_int(qty, "qty"),
        strict_int(deadline_day, "deadline"),
    )
    if qty <= 0 or not 0 <= deadline_day < engine_data.n_days:
        raise ValueError("Quantidade ou prazo CTP invalido.")
    result = CTPResult(False, sku, qty, None, None, None, "low", 0.0, None)
    ops = [op for op in engine_data.ops if op.sku == sku]
    if len(ops) != 1 or ops[0].pH <= 0:
        result.reason = "Referencia inexistente, ambigua ou sem cadencia valida."
        return result, None
    op = ops[0]
    holidays = calendar_holidays(engine_data, -60, engine_data.n_days + 60)
    for field, value in asdict(planning_milestones_for_op(op, deadline_day, holidays)).items():
        if hasattr(result, field):
            setattr(result, field, value)
            date_field = field.removesuffix("_day") + "_date"
            if field.endswith("_day") and hasattr(result, date_field) and value is not None:
                setattr(
                    result,
                    date_field,
                    (
                        date.fromisoformat(str(engine_data.workdays[0])[:10])
                        + timedelta(days=value)
                    ).isoformat(),
                )
    scenario = simulate(
        engine_data, baseline_result.score,
        [Mutation("rush_order", {"sku": sku, "qty": qty, "deadline_day": deadline_day})],
        config, baseline_result=baseline_result, active_mutations=active_mutations,
    )
    before = build_production_by_op(baseline_result.segments, baseline_result.lots, engine_data)
    after = build_production_by_op(scenario.segments, scenario.lots, scenario.mutated_data)

    def ready(production, op_id, amount):
        total = 0
        for day, produced in sorted(production.get(op_id, {}).items()):
            total += produced
            if total >= amount:
                return day
        return None

    required = sum(op.d[:deadline_day + 1]) + qty
    promised_day = ready(after, op.id, required)
    regression = False
    for existing in engine_data.ops:
        accumulated = 0
        for day, demand in enumerate(existing.d):
            accumulated += max(0, demand)
            if demand <= 0:
                continue
            previous_day = ready(before, existing.id, accumulated)
            target = accumulated + (qty if existing.id == op.id and day >= deadline_day else 0)
            next_day = ready(after, existing.id, target)
            if previous_day is not None and (next_day is None or next_day > max(day, previous_day)):
                regression = True
    gate = scenario.gate_report or {}
    physical = gate.get("physical_gate_passed") is True and gate.get("apply_decision") != "blocked"
    feasible = (
        physical and promised_day is not None and promised_day <= deadline_day and not regression
    )
    result.feasible = feasible
    result.confidence = "high" if feasible else "low"
    result.slack_min = 0.0
    result.reason = None if feasible else (
        "O candidato tem conflitos fisicos." if not physical else
        "A promessa agravaria compromissos existentes." if regression else
        "O candidato nao cobre a quantidade pedida ate ao prazo."
    )
    # Allocate only the promised slice of the chronological output stream.
    # Later November demand must not inflate an October promise's duration/ETA.
    events = [
        (s.available_day, "", s.qty, s.available_day)
        for s in scenario.mutated_data.committed_supplies
        if s.op_id == op.id
    ]
    by_lot = defaultdict(list)
    for segment in scenario.segments:
        by_lot[segment.lot_id].append(segment)
    for lot in scenario.lots:
        output = next((o for o in lot_output_milestones(lot) if str(o.get("op_id")) == op.id), None)
        if output is None:
            continue
        lot_segments = by_lot[lot.id]
        if output.get("is_subcontracted"):
            day = add_workdays(max((s.day_idx for s in lot_segments), default=0),
                              int(output.get("subcontract_lead_time_days", 0) or 0), holidays)
            events.append((day, lot.id, int(output.get("qty", 0)),
                           max((s.day_idx for s in lot_segments), default=day)))
        else:
            for segment in lot_segments:
                quantity = (
                    next((q for oid, _, q in segment.twin_outputs or [] if oid == op.id), 0)
                    if segment.twin_outputs
                    else segment.qty
                )
                events.append((segment.day_idx, lot.id, quantity, segment.day_idx))
    cumulative = 0
    relevant_until = {}
    for _day, lot_id, quantity, production_day in sorted(events):
        if cumulative < required and cumulative + quantity > required - qty and lot_id:
            relevant_until[lot_id] = max(relevant_until.get(lot_id, production_day), production_day)
        cumulative += quantity
    relevant = [segment for segment in scenario.segments
                if segment.lot_id in relevant_until
                and segment.day_idx <= relevant_until[segment.lot_id]]
    run_ids = {s.run_id for s in relevant}
    last_day = max((s.day_idx for s in relevant), default=-1)
    setup_segments = [s for s in scenario.segments
                      if s.run_id in run_ids and s.setup_min > 0 and s.day_idx <= last_day]
    result.latest_day = min((s.day_idx for s in relevant), default=None)
    result.earliest_end_day = max((s.day_idx for s in relevant), default=promised_day)
    result.machine = next((s.machine_id for s in relevant), None)
    result.required_min = sum(s.prod_min for s in relevant) + sum(
        s.setup_min for s in setup_segments
    )
    result.prod_days = len({s.day_idx for s in relevant})
    for field, day in (("date_start", result.latest_day), ("date_end", result.earliest_end_day)):
        setattr(
            result,
            field,
            (
                date.fromisoformat(str(engine_data.workdays[0])[:10]) + timedelta(days=day)
            ).isoformat()
            if day is not None
            else None,
        )
    return result, scenario

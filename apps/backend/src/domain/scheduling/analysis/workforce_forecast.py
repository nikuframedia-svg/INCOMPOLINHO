"""D+1 Workforce Forecast — port of analysis/workforce-forecast.ts.

Predicts next working day workforce overload and emits
rich warnings with operational suggestions.

Window-based model: capacity varies within a shift.
Pure function — no side effects. Soft warning only — never blocks scheduling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..constants import T1
from ..types import Block, ETool, WorkforceConfig


@dataclass
class WorkforceSuggestion:
    type: str
    description: str
    op_id: str | None = None
    machine_id: str | None = None
    expected_reduction: int = 0


@dataclass
class CausingBlock:
    op_id: str
    machine_id: str
    operators: int
    sku: str


@dataclass
class WorkforceForecastWarning:
    date: str
    day_idx: int
    labor_group: str
    shift: str
    window_start: int
    window_end: int
    capacity: int
    projected_peak: int
    excess: int
    peak_shortage: int
    overload_people_minutes: int
    shortage_minutes: int
    causing_blocks: list[CausingBlock] = field(default_factory=list)
    machines: list[str] = field(default_factory=list)
    overload_window: str = ""
    suggestions: list[WorkforceSuggestion] = field(default_factory=list)


@dataclass
class CoverageMissing:
    type: str
    machine_id: str
    day_idx: int
    shift: str
    detail: str


@dataclass
class WorkforceForecastResult:
    next_working_day_idx: int = -1
    date: str = ""
    warnings: list[WorkforceForecastWarning] = field(default_factory=list)
    coverage_missing: list[CoverageMissing] = field(default_factory=list)
    has_warnings: bool = False
    has_critical: bool = False


def _find_next_working_day(workdays: list[bool], from_idx: int = 0) -> int:
    for d in range(from_idx + 1, len(workdays)):
        if workdays[d]:
            return d
    return -1


def _minute_to_shift(minute: int) -> str:
    return "X" if minute < T1 else "Y"


def _overload_window_label(start: int, end: int) -> str:
    def fmt(m: int) -> str:
        h = m // 60
        mm = m % 60
        return f"{h:02d}:{mm:02d}"
    return f"{fmt(start)}-{fmt(end)}"


def _build_suggestions(
    causing_blocks: list[CausingBlock],
    d1: int,
    workdays: list[bool],
    tool_map: dict[str, ETool],
    excess: int,
    op_tool_map: dict[str, str],
) -> list[WorkforceSuggestion]:
    suggestions: list[WorkforceSuggestion] = []
    seen_ops: set[str] = set()

    has_previous_workday = any(workdays[d] for d in range(d1 - 1, -1, -1)) if d1 > 0 else False

    for cb in causing_blocks:
        if cb.op_id in seen_ops:
            continue
        seen_ops.add(cb.op_id)

        if has_previous_workday:
            suggestions.append(WorkforceSuggestion(
                type="ADVANCE_BLOCK",
                description=f"Antecipar bloco {cb.sku} ({cb.op_id}) para dia anterior",
                op_id=cb.op_id,
                machine_id=cb.machine_id,
                expected_reduction=cb.operators,
            ))

        tool_id = op_tool_map.get(cb.op_id)
        tool = tool_map.get(tool_id) if tool_id else None
        if tool and tool.alt and tool.alt != "-":
            suggestions.append(WorkforceSuggestion(
                type="MOVE_ALT_MACHINE",
                description=f"Mover {cb.sku} para máquina alternativa {tool.alt}",
                op_id=cb.op_id,
                machine_id=tool.alt,
                expected_reduction=cb.operators,
            ))

    if causing_blocks:
        suggestions.append(WorkforceSuggestion(
            type="REPLAN_EQUIVALENT",
            description="Considerar replaneamento equivalente para reduzir carga no grupo",
            expected_reduction=max(1, excess // 2),
        ))

    suggestions.append(WorkforceSuggestion(
        type="REQUEST_REINFORCEMENT",
        description=f"Solicitar reforço de {excess} operador{'es' if excess > 1 else ''}",
        expected_reduction=excess,
    ))

    return suggestions


def _detect_coverage_missing(
    d1: int,
    config: WorkforceConfig,
    overtime_map: dict[str, dict[int, int]] | None = None,
    third_shift: bool = False,
) -> list[CoverageMissing]:
    missing: list[CoverageMissing] = []

    if overtime_map:
        for machine_id, day_map in overtime_map.items():
            extra_min = day_map.get(d1, 0)
            if not extra_min or extra_min <= 0:
                continue

            labor_group = config.machine_to_labor_group.get(machine_id)
            if not labor_group:
                missing.append(CoverageMissing(
                    type="OVERTIME",
                    machine_id=machine_id,
                    day_idx=d1,
                    shift="Y",
                    detail=(
                        f"Overtime +{extra_min} min em {machine_id} no dia {d1} "
                        f"— máquina sem grupo laboral configurado"
                    ),
                ))
            else:
                windows = config.labor_groups.get(labor_group, [])
                last_window = windows[-1] if windows else None
                if last_window and last_window.capacity == 0:
                    missing.append(CoverageMissing(
                        type="OVERTIME",
                        machine_id=machine_id,
                        day_idx=d1,
                        shift="Y",
                        detail=(
                            f"Overtime +{extra_min} min em {machine_id} no dia {d1} "
                            f"— grupo {labor_group} sem capacidade na última janela"
                        ),
                    ))

    if third_shift:
        for labor_group in config.labor_groups:
            machine_id = ""
            for mid, lg in config.machine_to_labor_group.items():
                if lg == labor_group:
                    machine_id = mid
                    break
            missing.append(CoverageMissing(
                type="THIRD_SHIFT",
                machine_id=machine_id,
                day_idx=d1,
                shift="Z",
                detail=(
                    f"3.º turno activo mas grupo {labor_group} não tem janelas Z "
                    f"configuradas — sem workforce configurada para turno nocturno"
                ),
            ))

    return missing


def compute_workforce_forecast(
    blocks: list[Block],
    workforce_config: WorkforceConfig,
    workdays: list[bool],
    dates: list[str],
    tool_map: dict[str, ETool],
    overtime_map: dict[str, dict[int, int]] | None = None,
    third_shift: bool = False,
    from_day_idx: int = 0,
) -> WorkforceForecastResult:
    """Compute D+1 workforce forecast from scheduled blocks."""
    d1 = _find_next_working_day(workdays, from_day_idx)
    if d1 == -1:
        return WorkforceForecastResult()

    date = dates[d1] if d1 < len(dates) else f"dia {d1}"

    # Build reverse map: laborGroup → machineIds
    group_machines: dict[str, set[str]] = {}
    for machine_id, labor_group in workforce_config.machine_to_labor_group.items():
        if labor_group not in group_machines:
            group_machines[labor_group] = set()
        group_machines[labor_group].add(machine_id)

    # Filter D+1 active blocks
    d1_blocks = [b for b in blocks if b.day_idx == d1 and b.type != "blocked"]

    warnings: list[WorkforceForecastWarning] = []

    for labor_group, windows in workforce_config.labor_groups.items():
        mach_set = group_machines.get(labor_group)

        for w in windows:
            if not mach_set:
                continue

            # Find blocks that overlap this window [w.start, w.end)
            window_blocks = [
                b for b in d1_blocks
                if b.machine_id in mach_set and b.start_min < w.end and b.end_min > w.start
            ]

            # Peak operators per machine in this window
            mach_peaks: dict[str, int] = {}
            for b in window_blocks:
                mach_peaks[b.machine_id] = max(mach_peaks.get(b.machine_id, 0), b.operators)

            peak_need = sum(mach_peaks.values())
            capacity = w.capacity
            excess = peak_need - capacity
            if excess <= 0:
                continue

            peak_shortage = excess
            window_duration = w.end - w.start
            overload_people_minutes = peak_shortage * window_duration
            shortage_minutes = window_duration

            # Collect causing blocks
            causing: list[CausingBlock] = []
            machines_set: set[str] = set()
            for b in window_blocks:
                if b.operators <= 0:
                    continue
                causing.append(CausingBlock(
                    op_id=b.op_id,
                    machine_id=b.machine_id,
                    operators=b.operators,
                    sku=b.sku,
                ))
                machines_set.add(b.machine_id)

            # Build opId → toolId map
            op_tool_map: dict[str, str] = {}
            for b in window_blocks:
                op_tool_map[b.op_id] = b.tool_id

            suggestions = _build_suggestions(
                causing, d1, workdays, tool_map, excess, op_tool_map,
            )

            shift = _minute_to_shift(w.start)

            warnings.append(WorkforceForecastWarning(
                date=date,
                day_idx=d1,
                labor_group=labor_group,
                shift=shift,
                window_start=w.start,
                window_end=w.end,
                capacity=capacity,
                projected_peak=peak_need,
                excess=excess,
                peak_shortage=peak_shortage,
                overload_people_minutes=overload_people_minutes,
                shortage_minutes=shortage_minutes,
                causing_blocks=causing,
                machines=list(machines_set),
                overload_window=_overload_window_label(w.start, w.end),
                suggestions=suggestions,
            ))

    coverage_missing = _detect_coverage_missing(
        d1, workforce_config, overtime_map, third_shift,
    )

    return WorkforceForecastResult(
        next_working_day_idx=d1,
        date=date,
        warnings=warnings,
        coverage_missing=coverage_missing,
        has_warnings=len(warnings) > 0,
        has_critical=len(coverage_missing) > 0,
    )


def compute_d1_workforce_risk(
    blocks: list[Block],
    config: WorkforceConfig,
    workdays: list[bool],
) -> int:
    """Compute D+1 workforce risk as total excess across all laborGroups/windows.

    Returns 0 if no excess. Used by auto-replan tiebreaker.
    """
    d1 = _find_next_working_day(workdays)
    if d1 == -1:
        return 0

    group_machines: dict[str, set[str]] = {}
    for machine_id, labor_group in config.machine_to_labor_group.items():
        if labor_group not in group_machines:
            group_machines[labor_group] = set()
        group_machines[labor_group].add(machine_id)

    d1_blocks = [b for b in blocks if b.day_idx == d1 and b.type != "blocked"]
    total_excess = 0

    for labor_group, windows in config.labor_groups.items():
        mach_set = group_machines.get(labor_group)
        if not mach_set:
            continue

        for w in windows:
            window_blocks = [
                b for b in d1_blocks
                if b.machine_id in mach_set and b.start_min < w.end and b.end_min > w.start
            ]

            mach_peaks: dict[str, int] = {}
            for b in window_blocks:
                mach_peaks[b.machine_id] = max(mach_peaks.get(b.machine_id, 0), b.operators)

            peak_need = sum(mach_peaks.values())
            excess = peak_need - w.capacity
            if excess > 0:
                total_excess += excess

    return total_excess

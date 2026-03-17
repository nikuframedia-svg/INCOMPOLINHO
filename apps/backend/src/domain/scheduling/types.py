"""Core types — port of types/*.ts.

Pydantic models for all scheduling data structures.
Accepts both camelCase (frontend/TS) and snake_case (Python internal).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Frozen enums (do NOT change) ──

InfeasibilityReason = Literal[
    "SETUP_CREW_EXHAUSTED",
    "OPERATOR_CAPACITY",
    "TOOL_CONFLICT",
    "CALCO_CONFLICT",
    "DEADLINE_VIOLATION",
    "MACHINE_DOWN",
    "CAPACITY_OVERFLOW",
    "DATA_MISSING",
    "MACHINE_PARTIAL_DOWN",
    "TOOL_DOWN_TEMPORAL",
    "SHIPPING_CUTOFF_VIOLATION",
]

RemediationType = Literal[
    "THIRD_SHIFT",
    "EXTRA_OPERATORS",
    "OVERTIME",
    "SPLIT_OPERATION",
    "ADVANCE_PRODUCTION",
    "TRANSFER_ALT_MACHINE",
    "FORMAL_RISK_ACCEPTANCE",
]

DecisionType = Literal[
    "BACKWARD_SCHEDULE",
    "LOAD_LEVEL",
    "OVERFLOW_ROUTE",
    "ADVANCE_PRODUCTION",
    "DATA_MISSING",
    "INFEASIBILITY_DECLARED",
    "DEADLINE_CONSTRAINT",
    "OPERATOR_REALLOCATION",
    "ALTERNATIVE_MACHINE",
    "TOOL_DOWN",
    "MACHINE_DOWN",
    "FAILURE_DETECTED",
    "FAILURE_MITIGATION",
    "FAILURE_UNRECOVERABLE",
    "SHIPPING_CUTOFF",
    "PRODUCTION_START",
    "CAPACITY_COMPUTATION",
    "SCORING_DECISION",
    "OPERATOR_CAPACITY_WARNING",
    "AUTO_REPLAN_ADVANCE",
    "AUTO_REPLAN_MOVE",
    "AUTO_REPLAN_SPLIT",
    "AUTO_REPLAN_OVERTIME",
    "AUTO_REPLAN_THIRD_SHIFT",
    "TWIN_VALIDATION_ANOMALY",
    "WORKFORCE_FORECAST_D1",
    "WORKFORCE_COVERAGE_MISSING",
    "LABOR_GROUP_UNMAPPED",
    "SCHEDULE_REPAIR",
]

ReplanStrategyType = Literal[
    "ADVANCE_PRODUCTION",
    "MOVE_ALT_MACHINE",
    "THIRD_SHIFT",
    "OVERTIME",
    "SPLIT_OPERATION",
]

StartReason = Literal[
    "urgency_slack_critical",
    "density_heavy_load",
    "free_window_available",
    "setup_reduction",
    "future_load_relief",
    "deficit_elimination",
]

ShiftId = Literal["X", "Y", "Z"]
BlockType = Literal["ok", "blocked", "overflow", "infeasible"]

TwinAnomalyCode = Literal[
    "self_reference",
    "one_way_link",
    "counterpart_missing",
    "machine_mismatch",
    "tool_mismatch",
    "rate_mismatch",
    "people_mismatch",
]


# ── Engine data models ──


class EMachine(BaseModel):
    model_config = {"populate_by_name": True}

    id: str
    area: str
    focus: bool = True
    man: list[int] = Field(default_factory=list)


class ETool(BaseModel):
    model_config = {"populate_by_name": True}

    id: str
    m: str  # primary machine
    alt: str = "-"  # alternative machine
    sH: float = 0.75  # setup hours
    pH: int = 100  # pieces per hour
    op: int = 1  # operators required
    lt: int = 0  # lot economic quantity
    stk: int = 0  # current stock
    mp: str | None = None  # material part code
    nm: str = ""  # tool name
    calco: str | None = None  # calco code
    setup_source: str | None = Field(None, alias="setupSource")
    oee: float | None = None  # OEE override
    skus: list[str] = Field(default_factory=list)


class EOp(BaseModel):
    model_config = {"populate_by_name": True}

    id: str
    t: str  # tool code
    m: str  # machine code
    sku: str
    nm: str = ""
    atr: int = 0  # backlog
    d: list[int] = Field(default_factory=list)  # daily demand quantities
    lt_days: int | None = Field(None, alias="ltDays")
    cl: str | None = None  # customer code
    cl_nm: str | None = Field(None, alias="clNm")
    pa: str | None = None  # parent SKU
    stk: int | None = None  # per-SKU stock
    wip: int | None = None  # per-SKU WIP
    shipping_day_idx: int | None = Field(None, alias="shippingDayIdx")
    shipping_buffer_hours: int | None = Field(None, alias="shippingBufferHours")
    twin: str | None = None  # twin SKU reference
    pH: int = 0  # pieces per hour (from tool)


class TwinAnomalyEntry(BaseModel):
    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    sku: str
    twin_sku: str = Field(alias="twinSku")
    code: str  # TwinAnomalyCode
    detail: str
    machine: str
    tool: str
    counterpart_machine: str | None = Field(None, alias="counterpartMachine")
    counterpart_tool: str | None = Field(None, alias="counterpartTool")


class TwinGroup(BaseModel):
    model_config = {"populate_by_name": True}

    op_id1: str = Field(alias="opId1")
    op_id2: str = Field(alias="opId2")
    sku1: str
    sku2: str
    machine: str
    tool: str
    pH: int
    operators: int
    lot_economic_differs: bool = Field(False, alias="lotEconomicDiffers")
    lead_time_differs: bool = Field(False, alias="leadTimeDiffers")


class TwinValidationReport(BaseModel):
    model_config = {"populate_by_name": True}

    total_twin_refs: int = Field(0, alias="totalTwinRefs")
    valid_groups: int = Field(0, alias="validGroups")
    invalid_refs: int = Field(0, alias="invalidRefs")
    anomalies: list[TwinAnomalyEntry] = Field(default_factory=list)
    by_code: dict[str, int] = Field(default_factory=dict, alias="byCode")
    twin_groups: list[TwinGroup] = Field(default_factory=list, alias="twinGroups")


class LaborWindow(BaseModel):
    start: int
    end: int
    capacity: int


class WorkforceConfig(BaseModel):
    model_config = {"populate_by_name": True}

    labor_groups: dict[str, list[LaborWindow]] = Field(default_factory=dict, alias="laborGroups")
    machine_to_labor_group: dict[str, str] = Field(
        default_factory=dict, alias="machineToLaborGroup"
    )


class EngineData(BaseModel):
    """Core engine input — port of EngineData interface."""

    model_config = {"populate_by_name": True, "arbitrary_types_allowed": True}

    machines: list[EMachine] = Field(default_factory=list)
    tools: list[ETool] = Field(default_factory=list)
    ops: list[EOp] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    dnames: list[str] = Field(default_factory=list)
    tool_map: dict[str, ETool] = Field(default_factory=dict, alias="toolMap")
    focus_ids: list[str] = Field(default_factory=list, alias="focusIds")
    workdays: list[bool] = Field(default_factory=list)
    mo: dict[str, list[int]] | None = None
    n_days: int = Field(0, alias="nDays")
    third_shift: bool = Field(False, alias="thirdShift")
    m_st: dict[str, str] = Field(default_factory=dict, alias="mSt")
    t_st: dict[str, str] = Field(default_factory=dict, alias="tSt")
    twin_groups: list[TwinGroup] = Field(default_factory=list, alias="twinGroups")
    twin_validation_report: TwinValidationReport | None = Field(None, alias="twinValidationReport")
    workforce_config: WorkforceConfig | None = Field(None, alias="workforceConfig")
    order_based: bool = Field(False, alias="orderBased")
    pre_start_days: int | None = Field(None, alias="preStartDays")


# ── Block and actions ──


class TwinOutput(BaseModel):
    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    sku: str
    qty: int


class Block(BaseModel):
    """A scheduled production block — port of Block interface."""

    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    tool_id: str = Field(alias="toolId")
    sku: str = ""
    nm: str = ""
    machine_id: str = Field(alias="machineId")
    orig_m: str = Field("", alias="origM")
    day_idx: int = Field(0, alias="dayIdx")
    edd_day: int | None = Field(None, alias="eddDay")
    qty: int = 0
    prod_min: int = Field(0, alias="prodMin")
    setup_min: int = Field(0, alias="setupMin")
    operators: int = 1
    blocked: bool = False
    reason: str | None = None
    moved: bool = False
    has_alt: bool = Field(False, alias="hasAlt")
    alt_m: str | None = Field(None, alias="altM")
    mp: str | None = None
    stk: int = 0
    lt: int = 0
    atr: int = 0
    start_min: int = Field(0, alias="startMin")
    end_min: int = Field(0, alias="endMin")
    setup_s: int | None = Field(None, alias="setupS")
    setup_e: int | None = Field(None, alias="setupE")
    type: BlockType = "ok"
    shift: ShiftId = "X"
    overflow: bool = False
    overflow_min: int | None = Field(None, alias="overflowMin")
    below_min_batch: bool = Field(False, alias="belowMinBatch")
    earliest_start: int | None = Field(None, alias="earliestStart")
    is_leveled: bool = Field(False, alias="isLeveled")
    is_advanced: bool = Field(False, alias="isAdvanced")
    advanced_by_days: int | None = Field(None, alias="advancedByDays")
    infeasibility_reason: str | None = Field(None, alias="infeasibilityReason")
    infeasibility_detail: str | None = Field(None, alias="infeasibilityDetail")
    has_data_gap: bool = Field(False, alias="hasDataGap")
    data_gap_detail: str | None = Field(None, alias="dataGapDetail")
    operator_warning: bool = Field(False, alias="operatorWarning")
    failure_event_id: str | None = Field(None, alias="failureEventId")
    effective_capacity_factor: float | None = Field(None, alias="effectiveCapacityFactor")
    latest_finish_abs: int | None = Field(None, alias="latestFinishAbs")
    start_reason: str | None = Field(None, alias="startReason")
    is_system_replanned: bool = Field(False, alias="isSystemReplanned")
    replan_strategy: str | None = Field(None, alias="replanStrategy")
    replan_decision_id: str | None = Field(None, alias="replanDecisionId")
    is_overtime: bool = Field(False, alias="isOvertime")
    overtime_min: int | None = Field(None, alias="overtimeMin")
    is_split_part: bool = Field(False, alias="isSplitPart")
    split_from_machine: str | None = Field(None, alias="splitFromMachine")
    is_twin_production: bool = Field(False, alias="isTwinProduction")
    co_production_group_id: str | None = Field(None, alias="coProductionGroupId")
    outputs: list[TwinOutput] | None = None
    freeze_status: str | None = Field(None, alias="freezeStatus")
    pre_start: bool = Field(False, alias="preStart")
    pre_start_reason: str | None = Field(None, alias="preStartReason")


class MoveAction(BaseModel):
    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    to_m: str = Field(alias="toM")


class AdvanceAction(BaseModel):
    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    advance_days: int = Field(alias="advanceDays")
    original_edd: int = Field(alias="originalEdd")
    target_edd: int | None = Field(None, alias="targetEdd")


class OvertimeAction(BaseModel):
    model_config = {"populate_by_name": True}

    machine_id: str = Field(alias="machineId")
    day_idx: int = Field(alias="dayIdx")
    extra_min: int = Field(alias="extraMin")


class SplitAction(BaseModel):
    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    fraction: float
    to_machine: str = Field(alias="toMachine")


# ── Decision entry ──


class DecisionEntry(BaseModel):
    model_config = {"populate_by_name": True}

    id: str
    timestamp: float = 0
    type: str  # DecisionType
    op_id: str | None = Field(None, alias="opId")
    tool_id: str | None = Field(None, alias="toolId")
    machine_id: str | None = Field(None, alias="machineId")
    day_idx: int | None = Field(None, alias="dayIdx")
    shift: ShiftId | None = None
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    replan_strategy: str | None = Field(None, alias="replanStrategy")
    alternatives: list[dict] | None = None
    reversible: bool = True


# ── Feasibility ──


class InfeasibilityEntry(BaseModel):
    model_config = {"populate_by_name": True}

    op_id: str = Field(alias="opId")
    tool_id: str = Field(alias="toolId")
    machine_id: str = Field(alias="machineId")
    reason: str  # InfeasibilityReason
    detail: str
    attempted_alternatives: list[str] = Field(default_factory=list, alias="attemptedAlternatives")
    suggestion: str = ""
    day_idx: int | None = Field(None, alias="dayIdx")
    shift: ShiftId | None = None


class FeasibilityReport(BaseModel):
    model_config = {"populate_by_name": True}

    total_ops: int = Field(0, alias="totalOps")
    feasible_ops: int = Field(0, alias="feasibleOps")
    infeasible_ops: int = Field(0, alias="infeasibleOps")
    entries: list[InfeasibilityEntry] = Field(default_factory=list)
    by_reason: dict[str, int] = Field(default_factory=dict, alias="byReason")
    feasibility_score: float = Field(1.0, alias="feasibilityScore")
    remediations: list[dict] = Field(default_factory=list)
    deadline_feasible: bool = Field(True, alias="deadlineFeasible")


# ── Schedule result ──


class ScheduleResult(BaseModel):
    """Output of the scheduling pipeline."""

    model_config = {"populate_by_name": True}

    blocks: list[Block] = Field(default_factory=list)
    moves: list[MoveAction] = Field(default_factory=list)
    advances: list[AdvanceAction] = Field(default_factory=list)
    decisions: list[DecisionEntry] = Field(default_factory=list)
    feasibility: FeasibilityReport | None = None
    mrp: dict | None = None
    score: dict | None = None
    overtime_actions: list[OvertimeAction] = Field(default_factory=list, alias="overtimeActions")
    split_actions: list[SplitAction] = Field(default_factory=list, alias="splitActions")

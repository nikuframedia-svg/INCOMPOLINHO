"""Scheduler types — Spec 02 §2."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Lot:
    """Production unit — output of Phase 1 (lot sizing)."""

    id: str
    op_id: str  # EOp.id de origem
    tool_id: str
    machine_id: str  # primária
    alt_machine_id: str | None
    qty: int  # peças (eco lot rounded)
    prod_min: float  # minutos de produção
    setup_min: float  # minutos de setup (do YAML)
    edd: int  # deadline (day_idx)
    is_twin: bool
    sku: str = ""
    setup_family: str = ""
    twin_outputs: list[tuple[str, str, int]] | None = None  # [(op_id, sku, qty)]
    original_edd: int | None = None
    internal_deadline: int | None = None
    delivery_day: int | None = None
    customer_delivery_day: int | None = None
    latest_subcontract_dispatch_day: int | None = None
    subcontract_dispatch_day: int | None = None
    production_due_day: int | None = None
    internal_target_day: int | None = None
    material_reference_day: int | None = None
    material_reference_kind: str = "customer_delivery"
    material_release_day: int | None = None
    output_milestones: list[dict[str, object]] | None = None
    eco_lot_isop: int | None = None
    eco_lot_effective: int | None = None
    start_buffer_days: int = 0
    finish_buffer_days: int = 0
    target_start_day: int | None = None
    min_campaign_qty: int | None = None
    min_campaign_prod_min: float | None = None
    max_group_gap_days: int | None = None
    planning_priority: int = 0
    planning_source: str = "isop"
    economic_warning: str | None = None
    is_subcontracted: bool = False
    subcontract_company_id: str | None = None
    subcontract_lead_time_days: int = 0
    subcontract_buffer_days: int = 0


@dataclass(slots=True)
class ToolRun:
    """Group of lots sharing the same tool+machine — output of Phase 2."""

    id: str
    tool_id: str
    machine_id: str
    alt_machine_id: str | None
    lots: list[Lot]  # ordered by EDD
    setup_min: float  # ONE setup for the whole group
    total_prod_min: float  # sum of prod_min
    total_min: float  # setup + prod
    edd: int  # EDD of most urgent lot
    lst: int = 0  # Latest Start Time (filled in Phase 4)
    target_start_day: int | None = None
    production_due_day: int | None = None


@dataclass(slots=True)
class Segment:
    """Scheduled block on Gantt — output of Phase 3."""

    lot_id: str
    run_id: str  # ToolRun de origem
    machine_id: str
    tool_id: str
    day_idx: int
    start_min: int  # minute in day (clock from midnight)
    end_min: int
    shift: str  # "A" or "B"
    qty: int
    prod_min: float
    # Setup minutes physically contained in this block. Normally non-zero only
    # on the first block; a shift boundary may create contiguous fragments.
    setup_min: float = 0.0
    is_continuation: bool = False
    edd: int = 0
    sku: str = ""
    setup_family: str = ""
    twin_outputs: list[tuple[str, str, int]] | None = None
    lot_qty: int = 0
    run_qty: int = 0
    run_setup_min: float = 0.0
    run_lot_count: int = 0
    original_edd: int | None = None
    internal_deadline: int | None = None
    delivery_day: int | None = None
    customer_delivery_day: int | None = None
    latest_subcontract_dispatch_day: int | None = None
    subcontract_dispatch_day: int | None = None
    production_due_day: int | None = None
    internal_target_day: int | None = None
    material_reference_day: int | None = None
    material_reference_kind: str = "customer_delivery"
    eco_lot_isop: int | None = None
    eco_lot_effective: int | None = None
    start_buffer_days: int = 0
    finish_buffer_days: int = 0
    target_start_day: int | None = None
    min_campaign_qty: int | None = None
    min_campaign_prod_min: float | None = None
    max_group_gap_days: int | None = None
    planning_priority: int = 0
    material_release_day: int | None = None
    output_milestones: list[dict[str, object]] | None = None
    release_delay_workdays: int = 0
    planning_source: str = "isop"
    economic_warning: str | None = None
    is_subcontracted: bool = False
    subcontract_company_id: str | None = None
    subcontract_lead_time_days: int = 0
    subcontract_buffer_days: int = 0
    # Reasons why the first productive block cannot be pulled further left.
    # Filled after the final physical-repair pass for Gantt/API explainability.
    left_shift_blockers: list[str] = field(default_factory=list)

    @property
    def production_start_min(self) -> float:
        """Exact setup/production boundary; round only when choosing clock slots."""
        return min(float(self.end_min), self.start_min + max(0.0, self.setup_min))


@dataclass
class MachineState:
    """Tracks machine availability during dispatch."""

    machine_id: str
    group: str
    available_at: float = 0.0  # absolute minute in scheduling timeline
    last_tool: str = ""
    last_setup_identity: tuple[str, tuple[str, ...]] | None = None
    used_per_day: dict[int, float] = field(default_factory=dict)


@dataclass
class CrewState:
    """Single setup crew — tracks when crew is free."""

    available_at: float = 0.0


@dataclass
class ToolTimeline:
    """Tracks which machine a tool is on to prevent simultaneous use.

    A physical tool (mould) is a single object: it may move between machines
    over time, but can NEVER be in two machines at once. All machines share
    ONE instance of this timeline during dispatch.
    """

    bookings: dict[str, list[tuple[float, float, str]]] = field(default_factory=dict)

    def is_available(self, tool_id: str, at_time: float, machine_id: str) -> bool:
        """Check if tool is available (not booked on another machine at this time)."""
        for start, end, booked_machine in self.bookings.get(tool_id, []):
            if booked_machine != machine_id and start <= at_time < end:
                return False
        return True

    def interval_free(self, tool_id: str, start: float, end: float, machine_id: str) -> bool:
        """Check that the WHOLE interval [start, end) is free on other machines."""
        for b_start, b_end, booked_machine in self.bookings.get(tool_id, []):
            if booked_machine == machine_id:
                continue
            if start < b_end and b_start < end:  # intervals overlap
                return False
        return True

    def next_free_after(self, tool_id: str, start: float, machine_id: str) -> float:
        """Return the earliest time >= start where the tool is free on `machine_id`.

        Skips past any booking owned by another machine that covers `start`.
        """
        moved = True
        cursor = start
        while moved:
            moved = False
            for b_start, b_end, booked_machine in self.bookings.get(tool_id, []):
                if booked_machine != machine_id and b_start <= cursor < b_end:
                    cursor = b_end
                    moved = True
        return cursor

    def previous_machine(self, tool_id: str, at_time: float) -> str | None:
        """Return the machine holding the latest completed booking before a time."""

        completed = [
            booking
            for booking in self.bookings.get(tool_id, [])
            if booking[1] <= at_time + 0.01
        ]
        if not completed:
            return None
        return max(completed, key=lambda booking: (booking[1], booking[0]))[2]

    def book(self, tool_id: str, start: float, end: float, machine_id: str) -> None:
        """Book a tool on a machine for a time range."""
        if tool_id not in self.bookings:
            self.bookings[tool_id] = []
        self.bookings[tool_id].append((start, end, machine_id))


@dataclass(slots=True)
class OperatorAlert:
    """Advisory alert when operator demand exceeds shift capacity."""

    day_idx: int
    date: str
    shift: str
    machine_group: str
    required: int
    available: int
    deficit: int


@dataclass(slots=True)
class ScheduleResult:
    """Complete scheduler output."""

    segments: list[Segment]
    lots: list[Lot]
    score: dict
    time_ms: float
    warnings: list[str]
    operator_alerts: list[OperatorAlert]
    audit_trail: object | None = None  # AuditTrail when audit=True
    study: object | None = None  # StudyResult when smart_schedule(learn=True)
    journal: list[dict] | None = None  # Spec 12: structured phase telemetry
    machine_runs: dict[str, list[ToolRun]] | None = None
    gate_report: dict | None = None
    solver_status: str | None = None
    feasibility: dict | None = None
    preserved_lot_proofs: dict[str, str] | None = None
    # Structured improvement facts (plan-melhoria §7.1). ``verified`` maps a
    # search scope to the physical signature of the state it last verified.
    improvement_report: dict | None = None

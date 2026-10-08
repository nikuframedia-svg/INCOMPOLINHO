"""Factory configuration types — Spec 09."""

from __future__ import annotations

from dataclasses import dataclass, field

# Fixed prototype material-release rule. Five working days simulate material
# availability before customer delivery for normal output and before planned
# supplier dispatch for subcontracted output.
JIT_MAX_ANTICIPATION_WORKDAYS = 5
JIT_EARLINESS_POLICY = "jit"
JIT_WINDOW_ENFORCEMENT = "hard"
PLANNING_POLICY_VERSION = "setup-families-v1"
OUT_OF_SCOPE_MACHINES = frozenset({"PRM020"})


@dataclass
class ShiftConfig:
    """Single same-calendar-day shift definition."""

    id: str
    start_min: int  # minutes from midnight (07:00 = 420)
    end_min: int  # minutes from midnight (00:00 = 1440)
    label: str = ""

    @property
    def duration_min(self) -> int:
        return max(0, self.end_min - self.start_min)


@dataclass
class MachineConfig:
    """Single machine definition."""

    id: str
    group: str
    active: bool = True
    day_capacity_min: int | None = None  # per-machine override
    oee: float | None = None  # per-machine override; None → oee_default


@dataclass
class FactoryConfig:
    """Complete factory configuration. Defaults = Incompol current values."""

    # Identity
    name: str = "Incompol"
    site: str = ""
    timezone: str = "Europe/Lisbon"

    # Shifts (defaults = Incompol: A 07:00-15:30, B 15:30-00:00)
    shifts: list[ShiftConfig] = field(
        default_factory=lambda: [
            ShiftConfig("A", 420, 930, "Manhã"),
            ShiftConfig("B", 930, 1440, "Tarde"),
        ]
    )

    # Computed from shifts
    @property
    def day_capacity_min(self) -> int:
        return sum(s.duration_min for s in self.shifts)

    @property
    def shift_a_start(self) -> int:
        return min((shift.start_min for shift in self.shifts), default=420)

    @property
    def shift_a_end(self) -> int:
        first = min(self.shifts, key=lambda shift: (shift.start_min, shift.id), default=None)
        return first.end_min if first is not None else 930

    @property
    def shift_b_end(self) -> int:
        return max((shift.end_min for shift in self.shifts), default=1440)

    # Machines
    machines: dict[str, MachineConfig] = field(default_factory=dict)

    @property
    def machine_groups(self) -> dict[str, str]:
        if self.machines:
            return {mid: m.group for mid, m in self.machines.items() if m.active}
        # Default Incompol mapping when no machines configured
        return {
            "PRM019": "Grandes",
            "PRM031": "Grandes",
            "PRM039": "Grandes",
            "PRM043": "Grandes",
            "PRM042": "Medias",
        }

    # Tools
    tools: dict[str, dict] = field(default_factory=dict)
    default_setup_hours: float = 0.5

    # Twins
    twins: dict[str, list[str]] = field(default_factory=dict)

    # Operators: (group, shift) → count
    operators: dict[tuple[str, str], int] = field(
        default_factory=lambda: {
            ("Grandes", "A"): 6,
            ("Grandes", "B"): 5,
            ("Medias", "A"): 9,
            ("Medias", "B"): 4,
        }
    )

    # Setup crews.  ``setup_crews`` is retained as a read/write compatibility
    # field for old snapshots and API clients.  New scheduling code uses the
    # capacity of the machine group.
    setup_crews: int = 1
    setup_crews_by_group: dict[str, int] = field(
        default_factory=lambda: {"Grandes": 1, "Medias": 1}
    )

    # Holidays (ISO date strings)
    holidays: list[str] = field(default_factory=list)

    # Extra workdays: ISO dates that override the automatic weekend detection
    # (e.g. open a specific Saturday). Never overrides explicit holidays.
    extra_workdays: list[str] = field(default_factory=list)

    # Persistent unavailability calendars.
    # New entries use {start_at, end_at, category, reason}; the loader migrates
    # legacy {from, to} date ranges to full-day Europe/Lisbon intervals.
    machine_unavailability: list[dict] = field(default_factory=list)
    tool_unavailability: list[dict] = field(default_factory=list)
    operator_unavailability: list[dict] = field(default_factory=list)

    # Production
    oee_default: float = 0.66
    min_prod_min: float = 1.0
    eco_lot_mode: str = "hard"
    subcontract_skus: list[str] = field(default_factory=list)
    sku_planning_rules: dict[str, dict] = field(default_factory=dict)
    subcontract_companies: list[dict] = field(default_factory=list)
    sku_subcontracts: dict[str, dict] = field(default_factory=dict)
    # Per-(sku, machine) setup-hour overrides; fallback chain is
    # (sku, machine) → per-tool op.sH → default_setup_hours.
    setup_overrides: list[dict] = field(default_factory=list)  # {sku, machine, hours}
    # References listed in one family retain the same physical adjustment.
    # Shape: {tool_id: [[sku_a, sku_b, ...], ...]}.
    setup_families: dict[str, list[list[str]]] = field(default_factory=dict)

    # Retained in the serialized contract for compatibility, but fixed by the
    # industrial JIT invariant above.
    earliness_policy: str = JIT_EARLINESS_POLICY
    material_release_days: int = JIT_MAX_ANTICIPATION_WORKDAYS
    early_window_enforcement: str = JIT_WINDOW_ENFORCEMENT

    # Scheduler tunables (base values — SchedulerParams can override)
    max_run_days: int = 4
    max_edd_gap: int = 10
    max_edd_span: int = 30
    edd_swap_tolerance: int = 5
    edd_assign_threshold: int = 5
    lst_safety_buffer: int = 2
    campaign_window: int = 15
    urgency_threshold: int = 5
    interleave_enabled: bool = True
    jit_enabled: bool = True
    jit_buffer_pct: float = 0.05
    jit_threshold: float = 95.0
    jit_max_retries: int = 15
    jit_earliness_target: float = 5.5
    auto_buffer: bool = False
    global_jit_enabled: bool = True
    # Keep the base scheduler responsive. Operational CPO modes raise this
    # budget when they need a complete diagnostic candidate.
    global_jit_time_limit_s: float = 0.4

    # VNS post-processing
    vns_enabled: bool = True
    vns_block_moves_enabled: bool = False
    vns_max_iter: int = 150

    # Business-approved CPO apply envelope. Hard gates and delivery remain non-negotiable.
    productivity_earliness_ceiling_days: float = 6.5

    # Internal CPO/LNS neighborhood controls. Empty by default; not user-tunable.
    forced_run_splits: dict[str, list[int]] = field(default_factory=dict)
    robustness_reserve_workdays: int = 0

    # Controls aggressive reordering only. Filling basic legal capacity is an
    # unconditional final invariant, even when this compatibility flag is off.
    compact_enabled: bool = False

    # Scoring weights
    weight_earliness: float = 0.40
    weight_setups: float = 0.30
    weight_balance: float = 0.30

    # Risk parameters
    risk_oee_alpha: float = 10.6
    risk_oee_beta: float = 5.5
    risk_setup_cv: float = 0.20
    risk_processing_cv: float = 0.10

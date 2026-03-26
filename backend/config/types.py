"""Factory configuration types — Spec 09."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShiftConfig:
    """Single shift definition."""

    id: str
    start_min: int  # minutes from midnight (07:00 = 420)
    end_min: int    # minutes from midnight (00:00 = 1440)
    label: str = ""

    @property
    def duration_min(self) -> int:
        if self.end_min > self.start_min:
            return self.end_min - self.start_min
        # Cross-midnight shift (e.g. 22:00-06:00)
        return (1440 - self.start_min) + self.end_min


@dataclass
class MachineConfig:
    """Single machine definition."""

    id: str
    group: str
    active: bool = True
    day_capacity_min: int | None = None  # per-machine override


@dataclass
class FactoryConfig:
    """Complete factory configuration. Defaults = Incompol current values."""

    # Identity
    name: str = "Incompol"
    site: str = ""
    timezone: str = "Europe/Lisbon"

    # Shifts (defaults = Incompol: A 07:00-15:30, B 15:30-00:00)
    shifts: list[ShiftConfig] = field(default_factory=lambda: [
        ShiftConfig("A", 420, 930, "Manhã"),
        ShiftConfig("B", 930, 1440, "Tarde"),
    ])

    # Computed from shifts
    @property
    def day_capacity_min(self) -> int:
        return sum(s.duration_min for s in self.shifts)

    @property
    def shift_a_start(self) -> int:
        return self.shifts[0].start_min if self.shifts else 420

    @property
    def shift_a_end(self) -> int:
        return self.shifts[0].end_min if self.shifts else 930

    @property
    def shift_b_end(self) -> int:
        return self.shifts[-1].end_min if len(self.shifts) > 1 else 1440

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
    operators: dict[tuple[str, str], int] = field(default_factory=lambda: {
        ("Grandes", "A"): 6,
        ("Grandes", "B"): 5,
        ("Medias", "A"): 9,
        ("Medias", "B"): 4,
    })

    # Setup crews
    setup_crews: int = 1

    # Holidays (ISO date strings)
    holidays: list[str] = field(default_factory=list)

    # Production
    oee_default: float = 0.66
    min_prod_min: float = 1.0
    eco_lot_mode: str = "hard"

    # Scheduler tunables (base values — SchedulerParams can override)
    max_run_days: int = 5
    max_edd_gap: int = 10
    edd_swap_tolerance: int = 5
    lst_safety_buffer: int = 2
    campaign_window: int = 15
    urgency_threshold: int = 5
    interleave_enabled: bool = True
    jit_enabled: bool = True
    jit_buffer_pct: float = 0.05
    jit_threshold: float = 95.0
    jit_max_retries: int = 15
    jit_earliness_target: float = 6.0
    auto_buffer: bool = True

    # VNS post-processing
    vns_enabled: bool = True
    vns_max_iter: int = 50

    # Scoring weights
    weight_earliness: float = 0.40
    weight_setups: float = 0.30
    weight_balance: float = 0.30

    # Risk parameters
    risk_oee_alpha: float = 10.6
    risk_oee_beta: float = 5.5
    risk_setup_cv: float = 0.20
    risk_processing_cv: float = 0.10

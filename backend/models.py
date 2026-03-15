"""PP1 Data Models — lean, real, no bloat."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Reference:
    """A product reference from the ISOP."""

    ref_id: str
    client_code: str
    client_name: str
    designation: str
    economic_lot: int
    lead_time_days: int
    machine: str
    tool: str
    pieces_per_hour: int
    num_people: int
    stock: int
    wip: int
    twin_ref: str | None
    # Daily demands: {date_str: quantity_needed}
    # Positive = coverage, Negative = shortage
    daily_coverage: dict = field(default_factory=dict)

    @property
    def first_shortage_date(self) -> str | None:
        """First date where coverage goes negative."""
        for dt, val in sorted(self.daily_coverage.items()):
            if val < 0:
                return dt
        return None

    @property
    def is_urgent(self) -> bool:
        """Shortage within 2 days."""
        dates = sorted(self.daily_coverage.keys())
        for dt in dates[:2]:
            if self.daily_coverage[dt] < 0:
                return True
        return False

    @property
    def total_demand(self) -> int:
        """Sum of all negative values = total unmet demand."""
        return abs(sum(v for v in self.daily_coverage.values() if v < 0))

    def demand_by_date(self, target_date: str) -> int:
        """Get cumulative coverage at a specific date."""
        return self.daily_coverage.get(target_date, 0)


@dataclass
class Machine:
    """A press machine."""

    machine_id: str
    shifts: list = field(default_factory=lambda: ["manha", "tarde"])
    hours_per_shift: float = 8.0
    available: bool = True

    @property
    def daily_capacity_hours(self) -> float:
        return len(self.shifts) * self.hours_per_shift


@dataclass
class Constraint:
    """A scheduling constraint."""

    constraint_id: str
    constraint_type: str  # "material_affinity", "sequence", "min_batch", "buffer_days"
    refs: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    reason: str = ""


@dataclass
class ScheduledJob:
    """A scheduled production job."""

    job_id: str
    ref_id: str
    machine: str
    quantity: int
    start_time: datetime
    end_time: datetime
    pieces_per_hour: int
    client_name: str
    designation: str
    priority: int = 0  # 0=normal, 1=urgent, 2=critical (atraso)
    tool: str = ""


@dataclass
class Alert:
    """A production alert."""

    alert_id: str
    ref_id: str
    client_name: str
    designation: str
    severity: str  # "red", "yellow", "info"
    message: str
    shortage_qty: int = 0
    machine: str = ""
    due_date: str = ""

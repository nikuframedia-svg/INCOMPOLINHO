"""PP1 core types — Spec 01 §1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class RawRow:
    """Raw row extracted from ISOP Excel."""

    client_id: str  # "210020"
    client_name: str  # "FAURECIA"
    sku: str  # "1064169X100"
    designation: str
    eco_lot: int  # HARD: produzir sempre este mínimo (0=sem)
    machine_id: str  # "PRM031"
    tool_id: str  # "BFP079"
    pieces_per_hour: float  # 1681.0
    operators: int  # 1
    wip: int
    backlog: int
    twin_ref: str  # SKU da gémea (vazio se coluna não existe)
    np_values: list[int]  # positivo=stock, negativo=encomenda, 0=vazio
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EOp:
    """Engine operation — the unified representation after transform."""

    id: str  # "{tool}_{machine}_{sku}"
    sku: str
    client: str  # "FAURECIA, FAUR-SIEGE, FAUREC. CZ"
    designation: str
    m: str  # machine_id
    t: str  # tool_id
    pH: float  # noqa: N815
    sH: float  # setup hours (default 0.5)  # noqa: N815
    operators: int
    eco_lot: int  # HARD (0=sem)
    alt: str | None  # máquina alternativa
    stk: int  # stock real
    backlog: int
    d: list[int]  # demanda/dia: |NP neg|, 0 nos outros
    oee: float  # 0.66
    wip: int
    # "default" = master/global value; "whatif" = set by an oee_change
    # mutation and takes precedence over per-machine OEE (resources.py).
    oee_source: str = "default"
    eco_lot_isop: int | None = None
    eco_lot_effective: int | None = None
    start_buffer_days: int = 0
    finish_buffer_days: int = 0
    min_campaign_qty: int | None = None
    min_campaign_prod_min: float | None = None
    max_group_gap_days: int | None = None
    planning_priority: int = 0
    is_subcontracted: bool = False
    subcontract_company_id: str | None = None
    subcontract_lead_time_days: int = 0
    subcontract_buffer_days: int = 0


@dataclass(slots=True)
class TwinGroup:
    """Twin pair — two SKUs produced simultaneously on the same tool+machine."""

    tool_id: str
    machine_id: str
    op_id_1: str
    op_id_2: str
    sku_1: str
    sku_2: str
    eco_lot_1: int
    eco_lot_2: int


@dataclass(slots=True)
class ClientDemandEntry:
    """Original client demand (before merge), for expedição view."""

    client: str
    sku: str
    day_idx: int
    date: str  # "2026-03-05"
    order_qty: int  # encomenda real (>= |NP|)
    np_value: int  # NP original (negativo)


@dataclass(slots=True)
class MachineInfo:
    """Machine definition."""

    id: str
    group: str  # "Grandes" ou "Medias"
    day_capacity: int  # 1020


MachineStateKind = Literal["idle", "producing", "setup", "trial", "down"]


@dataclass(slots=True)
class CurrentMachineState:
    """Observed state at the start of day 0.

    ``expected_end`` is an ISO-8601 timestamp in the factory timezone.  It may
    be omitted only for an open-ended breakdown.
    """

    machine_id: str
    status: MachineStateKind
    sku: str | None = None
    tool_id: str | None = None
    remaining_qty: int | None = None
    expected_end: str | None = None
    note: str = ""


@dataclass(slots=True)
class PlanAnchor:
    """A user-requested fixed position used while reoptimising the other lots."""

    lot_id: str
    machine_id: str
    start_at: str
    reason: str = ""
    author: str = "utilizador"


@dataclass(slots=True)
class CommittedSupply:
    """Future supply from production already in progress at horizon start.

    It remains demand until ``available_day``: the scheduler may rely on the
    quantity, but service and stock only receive it when the declared ETA is
    reached.
    """

    op_id: str
    sku: str
    qty: int
    available_at: str
    available_day: int
    machine_id: str
    tool_id: str


@dataclass(slots=True)
class EngineData:
    """Complete data contract for the scheduler."""

    ops: list[EOp]
    machines: list[MachineInfo]
    twin_groups: list[TwinGroup]
    client_demands: dict[str, list[ClientDemandEntry]]
    workdays: list[str]
    n_days: int
    holidays: list[int] = field(default_factory=list)
    # Immutable holiday baseline produced by transform(): automatic weekends
    # plus explicit master-data holidays.  Persistent factory calendars are
    # rebuilt on top of this baseline so removals are idempotent.
    calendar_base_holidays: list[int] | None = None
    # Subset of the baseline that came from explicit master-data holidays.
    # An extra workday may reopen an automatic weekend, but never one of these.
    calendar_explicit_holidays: list[int] = field(default_factory=list)
    # Calendar indices explicitly reopened by the factory configuration. This
    # includes dates beyond the imported demand horizon.
    calendar_extra_workdays: list[int] = field(default_factory=list)
    # Per-machine blocked days (for machine_down simulation)
    machine_blocked_days: dict[str, set[int]] = field(default_factory=dict)
    # Per-tool blocked days (for tool_down simulation)
    tool_blocked_days: dict[str, set[int]] = field(default_factory=dict)
    # Exact resource intervals projected to day/minute coordinates.  Each item
    # has start_day/start_min/end_day/end_min plus category/reason metadata.
    machine_blocked_intervals: dict[str, list[dict]] = field(default_factory=dict)
    tool_blocked_intervals: dict[str, list[dict]] = field(default_factory=dict)
    operator_blocked_intervals: list[dict] = field(default_factory=list)
    setup_crew_reservations: list[dict] = field(default_factory=list)
    current_machine_states: list[CurrentMachineState] = field(default_factory=list)
    input_warnings: list[str] = field(default_factory=list)
    committed_supplies: list[CommittedSupply] = field(default_factory=list)
    plan_anchors: list[PlanAnchor] = field(default_factory=list)
    preserved_lot_proofs: dict[str, str] = field(default_factory=dict)
    calendar_sources: dict[str, dict] = field(default_factory=dict)
    calendar_projection_end: int = -1
    calendar_day_offset: int = 0

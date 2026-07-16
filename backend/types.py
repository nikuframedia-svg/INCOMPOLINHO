"""PP1 core types — Spec 01 §1."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    # Per-machine blocked days (for machine_down simulation)
    machine_blocked_days: dict[str, set[int]] = field(default_factory=dict)
    # Per-tool blocked days (for tool_down simulation)
    tool_blocked_days: dict[str, set[int]] = field(default_factory=dict)

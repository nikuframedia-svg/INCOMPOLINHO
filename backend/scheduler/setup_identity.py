"""Physical setup identities for tools that can produce multiple references."""

from __future__ import annotations

from backend.config.types import FactoryConfig
from backend.scheduler.types import Lot, Segment, ToolRun

type SetupIdentity = tuple[str, tuple[str, ...]]


def configured_setup_family(
    config: FactoryConfig | None,
    tool_id: str,
    sku: str,
) -> str:
    """Return the stable family shared by compatible references, if configured."""

    if config is None:
        return ""
    reference = str(sku).strip()
    for members in config.setup_families.get(str(tool_id), []):
        normalized = tuple(
            sorted(
                {
                    str(member).strip()
                    for member in members
                    if str(member).strip()
                }
            )
        )
        if reference in normalized:
            return "|".join(normalized)
    return ""


def _solo_reference(sku: str, fallback: str, setup_family: str) -> tuple[str, ...]:
    family = str(setup_family).strip()
    if family:
        return (f"family:{family}",)
    return (str(sku or fallback).strip(),)


def _output_references(
    outputs: list[tuple[str, str, int]] | None,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(sku or op_id).strip()
                for op_id, sku, _qty in outputs or []
                if str(sku or op_id).strip()
            }
        )
    )


def lot_setup_identity(lot: Lot) -> SetupIdentity:
    """Return the mounted mould adjustment needed to produce ``lot``."""

    twin_references = _output_references(lot.twin_outputs)
    if twin_references:
        return str(lot.tool_id), twin_references
    return str(lot.tool_id), _solo_reference(
        lot.sku,
        lot.op_id,
        lot.setup_family,
    )


def run_setup_identity(run: ToolRun) -> SetupIdentity:
    """Return the common physical adjustment of every lot in a run."""

    if run.lots:
        return lot_setup_identity(run.lots[0])
    return str(run.tool_id), (str(run.id),)


def segment_setup_identity(segment: Segment) -> SetupIdentity:
    """Project a scheduled segment back to its physical setup identity."""

    twin_references = _output_references(segment.twin_outputs)
    if twin_references:
        return str(segment.tool_id), twin_references
    return str(segment.tool_id), _solo_reference(
        segment.sku,
        segment.lot_id,
        segment.setup_family,
    )


def retained_setup_at(
    segments: list[Segment],
    machine_id: str,
    identity: SetupIdentity,
    day: int,
    minute: float,
    *,
    ignore_run_id: str | None = None,
) -> bool:
    """Prove that the requested adjustment is still mounted before allocation.

    An allocation's own setup fragments cannot establish an earlier mounting.
    Activity on another machine also invalidates retention of the same mould.
    """
    point = (day, minute)
    active = [item for item in segments if item.end_min > item.start_min]
    preceding = [
        item for item in active
        if item.machine_id == machine_id
        and (ignore_run_id is None or item.run_id != ignore_run_id)
        and (item.day_idx, item.start_min) < point
    ]
    previous = max(
        preceding,
        key=lambda item: (item.day_idx, item.end_min, item.start_min),
        default=None,
    )
    if (
        previous is None
        or (previous.day_idx, previous.end_min) > point
        or segment_setup_identity(previous) != identity
    ):
        return False
    # Only work after the last physical mounting break is evidence. Logical
    # campaign IDs may survive a break or change during one continuous setup.
    last_break = max(
        (
            (item.day_idx, item.end_min)
            for item in active
            if (item.day_idx, item.start_min) < point
            and (
                (item.machine_id == machine_id
                 and segment_setup_identity(item) != identity)
                or (item.machine_id != machine_id and item.tool_id == identity[0])
            )
        ),
        default=(-1, 0.0),
    )
    evidence = [
        item for item in preceding
        if (item.day_idx, item.start_min) >= last_break
        and segment_setup_identity(item) == identity
    ]
    if any(item.prod_min > 0 for item in evidence):
        return True
    prepared = sum(max(0.0, item.setup_min) for item in evidence)
    required = max(
        (max(item.run_setup_min, item.setup_min) for item in evidence),
        default=0.0,
    )
    return required > 0 and prepared >= required - 0.01

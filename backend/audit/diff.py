"""Schedule Diff — Spec 07 §5.

Compare two schedules lot-by-lot.
"""

from __future__ import annotations

from collections import defaultdict

from backend.scheduler.types import Segment

from .types import DiffEntry, ScheduleDiff


def compute_diff(
    old_segments: list[Segment],
    new_segments: list[Segment],
    old_score: dict,
    new_score: dict,
) -> ScheduleDiff:
    """Compare two schedules lot-by-lot.

    Classifies each lot: ADDED, REMOVED, MOVED, RETIMED.
    """
    old_map = _lot_summary(old_segments)
    new_map = _lot_summary(new_segments)

    changes: list[DiffEntry] = []

    # REMOVED
    for lid in old_map:
        if lid not in new_map:
            changes.append(
                DiffEntry(
                    lot_id=lid,
                    change_type="REMOVED",
                    old_value=f"{old_map[lid][0]} dia {old_map[lid][1]}",
                    new_value=None,
                    reason="Lot removido",
                )
            )

    # ADDED
    for lid in new_map:
        if lid not in old_map:
            changes.append(
                DiffEntry(
                    lot_id=lid,
                    change_type="ADDED",
                    old_value=None,
                    new_value=f"{new_map[lid][0]} dia {new_map[lid][1]}",
                    reason="Lot novo",
                )
            )

    # MOVED / RETIMED
    for lid in old_map:
        if lid in new_map:
            old_m, old_d = old_map[lid]
            new_m, new_d = new_map[lid]

            if old_m != new_m:
                changes.append(
                    DiffEntry(
                        lot_id=lid,
                        change_type="MOVED",
                        old_value=f"{old_m} dia {old_d}",
                        new_value=f"{new_m} dia {new_d}",
                        reason=f"Mudou de {old_m} para {new_m}",
                    )
                )
            elif old_d != new_d:
                changes.append(
                    DiffEntry(
                        lot_id=lid,
                        change_type="RETIMED",
                        old_value=f"dia {old_d}",
                        new_value=f"dia {new_d}",
                        reason=f"Deslocado de dia {old_d} para dia {new_d}",
                    )
                )

    # Summary
    counts: dict[str, int] = defaultdict(int)
    for c in changes:
        counts[c.change_type] += 1

    parts = []
    if counts["ADDED"]:
        parts.append(f"{counts['ADDED']} novos")
    if counts["REMOVED"]:
        parts.append(f"{counts['REMOVED']} removidos")
    if counts["MOVED"]:
        parts.append(f"{counts['MOVED']} mudaram de máquina")
    if counts["RETIMED"]:
        parts.append(f"{counts['RETIMED']} mudaram de dia")

    return ScheduleDiff(
        summary=", ".join(parts) if parts else "Sem alterações",
        changes=changes,
        old_score=old_score,
        new_score=new_score,
    )


def _lot_summary(
    segments: list[Segment],
) -> dict[str, tuple[str, int]]:
    """Extract (machine_id, first_day_idx) per lot."""
    lots: dict[str, tuple[str, int]] = {}
    for seg in segments:
        if seg.lot_id not in lots:
            lots[seg.lot_id] = (seg.machine_id, seg.day_idx)
    return lots

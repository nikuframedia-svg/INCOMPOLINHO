"""Quantity limits released by material, independent of machine duration."""

from backend.scheduler.types import Lot, Segment


def released_quantity(lot: Lot, day: int) -> int:
    # Confirmed twin cycles share material from their controlling output.
    if lot.is_twin or not lot.output_milestones:
        return lot.qty if day >= (lot.material_release_day or 0) else 0
    return min(
        lot.qty,
        sum(
            int(output["qty"])
            for output in lot.output_milestones
            if int(output["material_release_day"]) <= day
        ),
    )


def next_release_day(lot: Lot, day: int) -> int | None:
    days = [
        int(output["material_release_day"])
        for output in lot.output_milestones or []
        if int(output["material_release_day"]) > day
    ]
    return min(days) if days else None


def output_completion_days(lot: Lot, segments: list[Segment], missing_day: int):
    """Complete each demand portion when its quantity exists, not at lot end."""
    from backend.scheduler.jit_policy import lot_demand_output_milestones

    outputs = lot_demand_output_milestones(lot)
    ordered = sorted(segments, key=lambda s: (s.day_idx, s.end_min))
    if lot.is_twin or not any(output.get("quantity_material_version") for output in outputs):
        completion = max((s.day_idx for s in ordered if s.qty > 0), default=missing_day)
        return [(output, completion) for output in outputs]
    index = 0
    produced = 0
    required = 0
    result = []
    for output in outputs:
        required += int(output["qty"])
        while produced < required and index < len(ordered):
            produced += ordered[index].qty
            index += 1
        completion = ordered[index - 1].day_idx if produced >= required and index else missing_day
        result.append((output, completion))
    return result

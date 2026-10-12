"""Plain notice when the active plan still uses an ISOP from before today.

The plan of an older ISOP is kept as it is: days before today count as
already produced (their production is planned history) and nobody is told
unless the planner notices the date. This notice only reads the plan's
calendar; it never changes the plan.
"""

from __future__ import annotations

from datetime import date, datetime

from backend.calendar import current_factory_day, is_factory_workday


def stale_isop_notice(engine_data, config, *, now: datetime | None = None) -> str | None:
    """pt-PT notice when at least one working day of the ISOP is before today.

    "Today" is the factory day of ``/api/data/today`` (first ISOP day on or
    after the current date in the factory time zone). Weekends and holidays
    before today do not count: an ISOP starting on Saturday is still current
    on Monday morning.
    """

    workdays = list(getattr(engine_data, "workdays", None) or [])
    if not workdays or config is None:
        return None
    try:
        first = date.fromisoformat(str(workdays[0])[:10])
    except ValueError:
        return None
    today_idx = current_factory_day(engine_data, config, now=now)
    past_workdays = sum(
        1
        for day_idx in range(min(today_idx, len(workdays)))
        if is_factory_workday(day_idx, engine_data, config)
    )
    if past_workdays < 1:
        return None
    isop = first.strftime("%d/%m")
    if today_idx >= len(workdays):
        # The whole ISOP is in the past: the plan has no day for today.
        return (
            f"O plano usa o ISOP de {isop}, que já não chega até hoje. "
            "Carregue o ISOP de hoje para atualizar o plano."
        )
    return (
        f"O plano usa o ISOP de {isop}. Os dias anteriores a hoje são "
        "considerados já produzidos. Carregue o ISOP de hoje para atualizar o plano."
    )

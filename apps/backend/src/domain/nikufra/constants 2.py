# Nikufra factory constants
# Shared fallback values when PP PDFs are unavailable

from datetime import date, timedelta

# Day-of-week labels (Portuguese) for the 8-day horizon
DAY_NAMES_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# Default 8-day fallback (static, used when generate_fallback_dates not viable)
FALLBACK_DAYS_LABEL = ["Seg", "Ter", "Qua", "Qui", "Sex", "Seg", "Ter", "Qua"]


def generate_fallback_dates(
    start: date | None = None, count: int = 8
) -> tuple[list[str], list[str]]:
    """Generate fallback date labels and day names when PP PDFs are unavailable.

    Skips weekends (Sat/Sun) to produce only working days.

    Returns:
        (date_labels, day_labels) — e.g. (["03/03", "04/03", ...], ["Seg", "Ter", ...])
    """
    if start is None:
        start = date.today()

    dates: list[date] = []
    current = start
    while len(dates) < count:
        if current.weekday() < 5:  # Mon-Fri
            dates.append(current)
        current += timedelta(days=1)

    date_labels = [d.strftime("%d/%m") for d in dates]
    day_labels = [DAY_NAMES_PT[d.weekday()] for d in dates]
    return date_labels, day_labels

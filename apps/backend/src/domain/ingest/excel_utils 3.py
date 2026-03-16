# Shared Excel parsing utilities
# Used by: isop_parser.py, planning/ingest_excel.py

from datetime import date, datetime
from typing import Any


def normalize_string(value: Any) -> str | None:
    """Normalize cell value to stripped string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value).strip()
    return str(value).strip() if value else None


def normalize_code(value: Any) -> str | None:
    """Normalize code cell: strip + uppercase. Returns None if empty."""
    normalized = normalize_string(value)
    return normalized.upper() if normalized else None


def normalize_code_or_empty(value: Any) -> str:
    """Normalize code cell: strip + uppercase. Returns '' if empty."""
    result = normalize_code(value)
    return result if result is not None else ""


def parse_numeric(value: Any, default: float = 0.0) -> float:
    """Parse numeric cell, handling Portuguese comma decimals."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_numeric_optional(value: Any, default: float | None = None) -> float | None:
    """Parse numeric cell, returning None when value is absent."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return default
    return default


def parse_integer(value: Any, default: int = 0) -> int:
    """Parse integer cell value."""
    return int(parse_numeric(value, float(default)))


def parse_integer_optional(value: Any, default: int | None = None) -> int | None:
    """Parse integer cell, returning None when value is absent."""
    num = parse_numeric_optional(value)
    return int(num) if num is not None else default


def parse_date_cell(value: Any) -> date | None:
    """Convert an Excel cell to a date object.

    Handles: datetime, date, and string formats
    (%Y-%m-%d, %d/%m/%Y, %d/%m/%y, %d/%m).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d/%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None

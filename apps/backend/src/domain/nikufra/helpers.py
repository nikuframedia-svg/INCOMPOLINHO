"""Shared helper functions for ISOP parsing.

Low-level utilities: string normalization, numeric parsing, date parsing,
red cell detection. Used by column_mapper, row_extractor, and isop_parser.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from openpyxl.cell import Cell

# ═══════════════════════════════════════════════════════════════
#  String / numeric helpers
# ═══════════════════════════════════════════════════════════════


def _normalize_code(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def _normalize_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_numeric(value: Any, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", ".").strip()
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return fallback
    return fallback


def _parse_integer(value: Any, fallback: int = 1) -> int:
    return round(_parse_numeric(value, float(fallback)))


# ═══════════════════════════════════════════════════════════════
#  Date helpers
# ═══════════════════════════════════════════════════════════════


def _format_date(d: date) -> str:
    return d.strftime("%d/%m")


def _parse_date_cell(value: Any) -> date | None:
    """Parse a date cell from Excel -- handles datetime, date, numeric serial, strings."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # Excel serial date: days since 1899-12-30
        try:
            serial = int(value)
            if serial < 1 or serial > 200000:
                return None
            base = datetime(1899, 12, 30)
            return (base + timedelta(days=serial)).date()
        except (ValueError, OverflowError):
            return None
    if isinstance(value, str):
        s = value.strip()
        # ISO: YYYY-MM-DD
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        # DD/MM/YYYY
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        # DD/MM/YY
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2})$", s)
        if m:
            yr = int(m.group(3))
            yr = yr + 2000 if yr < 70 else yr + 1900
            return date(yr, int(m.group(2)), int(m.group(1)))
        # DD/MM (assume current year)
        m = re.match(r"^(\d{1,2})/(\d{1,2})$", s)
        if m:
            return date(date.today().year, int(m.group(2)), int(m.group(1)))
    return None


# ═══════════════════════════════════════════════════════════════
#  Red cell detection
# ═══════════════════════════════════════════════════════════════


def _is_red_color(rgb: str | None) -> bool:
    """Detect red tones: high R, low G and B."""
    if not rgb or not isinstance(rgb, str):
        return False
    hex_str = rgb[-6:] if len(rgb) >= 6 else rgb
    if len(hex_str) != 6:
        return False
    try:
        r = int(hex_str[0:2], 16)
        g = int(hex_str[2:4], 16)
        b = int(hex_str[4:6], 16)
        return r > 180 and g < 100 and b < 100
    except ValueError:
        return False


def _is_cell_red_highlighted(cell: Cell) -> bool:
    """Check if a cell has red fill or red font color."""
    try:
        # Check fill color
        if cell.fill and cell.fill.fgColor and cell.fill.fgColor.rgb:
            rgb = str(cell.fill.fgColor.rgb)
            if _is_red_color(rgb):
                return True
        if cell.fill and cell.fill.bgColor and cell.fill.bgColor.rgb:
            rgb = str(cell.fill.bgColor.rgb)
            if _is_red_color(rgb):
                return True
        # Check font color
        if cell.font and cell.font.color and cell.font.color.rgb:
            rgb = str(cell.font.color.rgb)
            if _is_red_color(rgb):
                return True
    except (AttributeError, TypeError):
        pass
    return False

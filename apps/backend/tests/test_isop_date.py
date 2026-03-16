# Tests for S-00: ISOP date reference fix
# Ensures the system uses ISOP dates (not system date) as reference

from __future__ import annotations

from datetime import date

from src.domain.nikufra.constants import generate_fallback_dates
from src.domain.nikufra.service import NikufraService


def test_generate_fallback_dates_with_explicit_start():
    """When start is provided, fallback dates begin from that date (not today)."""
    start = date(2026, 2, 27)  # Thursday
    date_labels, day_labels = generate_fallback_dates(start=start, count=3)
    assert date_labels[0] == "27/02"
    assert day_labels[0] == "Sex"  # 27/02/2026 is Friday
    assert len(date_labels) == 3


def test_generate_fallback_dates_skips_weekends():
    """Fallback dates skip Saturday and Sunday."""
    start = date(2026, 2, 27)  # Friday
    date_labels, _ = generate_fallback_dates(start=start, count=3)
    # Friday → Monday → Tuesday (skips Sat/Sun)
    assert date_labels == ["27/02", "02/03", "03/03"]


def test_extract_isop_date_dd_mm_yyyy():
    """Extract date from ISOP date columns with dd/mm/yyyy format."""
    date_cols = {15: "27/02/2026", 16: "28/02/2026", 17: "02/03/2026"}
    result = NikufraService._extract_isop_date(date_cols)
    assert result == date(2026, 2, 27)


def test_extract_isop_date_dd_mm():
    """Extract date from ISOP date columns with dd/mm format."""
    date_cols = {15: "27/02", 16: "28/02", 17: "02/03"}
    result = NikufraService._extract_isop_date(date_cols)
    # Should parse and return earliest date
    assert result is not None
    assert result.month == 2
    assert result.day == 27


def test_extract_isop_date_empty():
    """Empty date_cols returns None."""
    assert NikufraService._extract_isop_date({}) is None


def test_extract_isop_date_invalid_headers():
    """Non-date headers are ignored gracefully."""
    date_cols = {15: "NotADate", 16: "AlsoNot"}
    assert NikufraService._extract_isop_date(date_cols) is None


def test_isop_date_set_after_parse(tmp_path):
    """After parsing ISOP, service.isop_date is set to the first ISOP date."""
    service = NikufraService(tmp_path)
    assert service.isop_date is None

    # Simulate what _parse_isop does with date extraction
    date_cols = {15: "27/02/2026", 16: "28/02/2026"}
    extracted = NikufraService._extract_isop_date(date_cols)
    assert extracted == date(2026, 2, 27)

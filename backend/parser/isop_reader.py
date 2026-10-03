"""ISOP Excel parser — Spec 01 §2.

Reads ISOP Excel files with dynamic header detection and column mapping.
Supports multiple ISOP formats (completo, 17/03, 27/02).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from backend.types import RawRow
from backend.validation import finite_float, strict_int

logger = logging.getLogger(__name__)

# --- Column mapping by header name (NOT position) ---

COLUMN_MAP: dict[str, str] = {
    "Cliente": "client_id",
    "Nome": "client_name",
    "Produto Acabado": "produto_acabado",
    "Referência Artigo": "sku",
    "Designação": "designation",
    "Lote Económico": "eco_lot",
    "Máquina": "machine_id",
    "Máquina alternativa": "alt_machine",
    "Ferramenta": "tool_id",
    "Tp.Setup": "setup_hours",
    "Peças/H": "pieces_per_hour",
    "Nº Pessoas": "operators",
    "Pessoas": "operators",
    "Qtd Exp": "qty_exp",
    "WIP": "wip",
    "ATRASO": "backlog",
    "Peça Gémea": "twin_ref",
}

IGNORE: set[str] = {"Prz.Fabrico", "STOCK-A"}


# --- Header detection ---


def _find_header_row(ws) -> int:
    """Find the header row by scanning for 'Cliente' in column A."""
    for row in range(1, 21):
        val = ws.cell(row=row, column=1).value
        if val is not None and str(val).strip() == "Cliente":
            return row
    raise ValueError("Header row not found: no cell with 'Cliente' in column A (rows 1-20)")


# --- Dynamic column mapping ---


def _build_column_map(ws, header_row: int) -> tuple[dict[str, int], int | None, bool]:
    """Build column index map from header names.

    Returns:
        (col_map, first_date_col, has_twin)
    """
    col_map: dict[str, int] = {}
    first_date_col: int | None = None
    has_twin = False

    for col in range(1, ws.max_column + 1):
        val = ws.cell(row=header_row, column=col).value
        if val is None:
            continue

        # Date columns: datetime objects or date-like values
        if isinstance(val, datetime):
            if first_date_col is None:
                first_date_col = col
            continue

        header = str(val).strip()
        if header in IGNORE:
            continue

        if header in COLUMN_MAP:
            field_name = COLUMN_MAP[header]
            col_map[field_name] = col
            if header == "Peça Gémea":
                has_twin = True

    return col_map, first_date_col, has_twin


# --- Date extraction ---


def _extract_dates(ws, header_row: int, first_date_col: int) -> list[str]:
    """Extract workday dates from header row (ISO format strings)."""
    dates: list[str] = []
    for col in range(first_date_col, ws.max_column + 1):
        val = ws.cell(row=header_row, column=col).value
        if isinstance(val, datetime):
            dates.append(val.strftime("%Y-%m-%d"))
        else:
            break
    return dates


# --- Safe value helpers ---


def _safe_int(val) -> int:
    if val is None or val == "":
        return 0
    return strict_int(val)


def _safe_float(val) -> float:
    if val is None or val == "":
        return 0.0
    return finite_float(val)


def _get(ws, row: int, col_map: dict[str, int], field: str, default=None):
    """Get cell value by field name from column map."""
    col = col_map.get(field)
    if col is None:
        return default
    val = ws.cell(row=row, column=col).value
    return val if val is not None else default


# --- Stock and demand extraction ---


def extract_stock_and_demand(np_values: list[int]) -> tuple[int, list[int]]:
    """Extract stock and demand from NP values.

    Stock = last positive value before first negative.
    Demand = abs(negative values), 0 elsewhere.
    """
    stk = 0
    demand: list[int] = []
    found_negative = False

    for val in np_values:
        if val > 0 and not found_negative:
            stk = val
            demand.append(0)
        elif val < 0:
            found_negative = True
            demand.append(abs(val))
        else:
            demand.append(0)

    return stk, demand


# --- Main reader ---


def read_isop(path: str | Path) -> tuple[list[RawRow], list[str], bool]:
    """Read ISOP Excel file.

    Args:
        path: Path to .xlsx file.

    Returns:
        (rows, workdays, has_twin_column)
        - rows: list of RawRow (one per ISOP line)
        - workdays: list of date strings ("2026-03-05")
        - has_twin_column: whether "Peça Gémea" column exists
    """
    try:
        wb = load_workbook(str(path), data_only=True)
    except (BadZipFile, InvalidFileException, OSError) as exc:
        raise ValueError(
            "O ficheiro não é um Excel .xlsx válido ou está corrompido."
        ) from exc
    try:
        ws = wb.active

        header_row = _find_header_row(ws)
        col_map, first_date_col, has_twin = _build_column_map(ws, header_row)

        if first_date_col is None:
            raise ValueError("No date columns found in ISOP header")

        workdays = _extract_dates(ws, header_row, first_date_col)
        n_dates = len(workdays)

        if n_dates == 0:
            raise ValueError("No workdays extracted from ISOP header")

        # data_only loses the distinction between an empty cell and an
        # unevaluated formula. Stream the formula view once, retaining only
        # coordinates, never an additional materialized workbook.
        formulas: set[str] = set()
        source = load_workbook(str(path), data_only=False, read_only=True)
        try:
            for cells in source[ws.title].iter_rows(min_row=header_row + 1):
                for cell in cells:
                    if cell.data_type == "f":
                        formulas.add(cell.coordinate)
        finally:
            source.close()

        def number(row: int, col: int | None, field: str, default=0, *, fractional=False):
            if col is None:
                return default
            cell = ws.cell(row=row, column=col)
            value = cell.value
            origin = f"{ws.title}!{cell.coordinate} ({field})"
            if value is None or value == "":
                if cell.coordinate in formulas:
                    raise ValueError(
                        f"{origin}: formula sem valor calculado. Recalcule e guarde o Excel."
                    )
                return default
            return finite_float(value, origin) if fractional else strict_int(value, origin)

        rows: list[RawRow] = []

        for row_idx in range(header_row + 1, ws.max_row + 1):
            sku = _get(ws, row_idx, col_map, "sku")
            if not sku or str(sku).strip() == "":
                continue

            machine = str(_get(ws, row_idx, col_map, "machine_id", "")).strip()

            # Extract NP values from date columns
            np_values: list[int] = []
            for col in range(first_date_col, first_date_col + n_dates):
                np_values.append(number(row_idx, col, "stock/procura"))

            # Defaults belong only to empty cells, never to indeterminate or
            # explicitly invalid cadence. Preserve their source in the DQA.
            ph_col = col_map.get("pieces_per_hour")
            ph = number(row_idx, ph_col, "pieces_per_hour", 1.0, fractional=True)
            origin = (
                f"{ws.title}!{ws.cell(row=row_idx, column=ph_col).coordinate}"
                if ph_col
                else ws.title
            )
            warnings = []
            if ph <= 0:
                raise ValueError(f"{origin} (pieces_per_hour): a cadencia deve ser positiva.")
            if ph_col is None or ws.cell(row=row_idx, column=ph_col).value in (None, ""):
                warnings.append(f"{origin} (pieces_per_hour): vazio; valor por omissao 1.0.")
            operators = number(row_idx, col_map.get("operators"), "operators", 1)
            if operators < 1:
                column = col_map.get("operators")
                coordinate = ws.cell(row=row_idx, column=column).coordinate if column else ""
                raise ValueError(f"{ws.title}!{coordinate} (operators): deve ser >= 1.")

            rows.append(
                RawRow(
                    client_id=str(_get(ws, row_idx, col_map, "client_id", "")).strip(),
                    client_name=str(_get(ws, row_idx, col_map, "client_name", "")).strip(),
                    sku=str(sku).strip(),
                    designation=str(_get(ws, row_idx, col_map, "designation", "")).strip(),
                    eco_lot=number(row_idx, col_map.get("eco_lot"), "eco_lot"),
                    machine_id=machine,
                    tool_id=str(_get(ws, row_idx, col_map, "tool_id", "")).strip(),
                    pieces_per_hour=ph,
                    operators=operators,
                    wip=number(row_idx, col_map.get("wip"), "wip"),
                    backlog=number(row_idx, col_map.get("backlog"), "backlog"),
                    twin_ref=(
                        str(_get(ws, row_idx, col_map, "twin_ref", "")).strip()
                        if has_twin
                        else ""
                    ),
                    np_values=np_values,
                    warnings=warnings,
                )
            )

        logger.info(
            "Parsed ISOP: %d rows, %d workdays, twin_col=%s",
            len(rows),
            n_dates,
            has_twin,
        )

        return rows, workdays, has_twin
    finally:
        wb.close()

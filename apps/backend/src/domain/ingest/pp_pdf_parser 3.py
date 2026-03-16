# PP PDF Parser
# Parses PP_PG1.pdf and PP_PG2.pdf production plans from Nikufra factory

import re
from dataclasses import dataclass, field
from pathlib import Path

from ...core.logging import get_logger
from ..nikufra.constants import FALLBACK_DAYS_LABEL, generate_fallback_dates

logger = get_logger(__name__)


@dataclass
class PPOperation:
    """A single production operation parsed from a PP PDF."""

    sku: str
    name: str
    tool_code: str
    machine: str
    pcs_per_hour: int
    lot_economic_qty: int
    atraso: int  # backlog
    daily_qty: list[int]  # qty per day (8 days)
    setup_hours: float
    operators: int
    components: str = ""
    stock: int = 0


@dataclass
class PPMachineBlock:
    """A machine block with MAN minutes and operations."""

    machine_id: str
    area: str
    man_minutes: list[int]  # MAN minutes per day (8 days)
    operations: list[PPOperation] = field(default_factory=list)


@dataclass
class PPPDFData:
    """Combined data from PP PDF files."""

    dates: list[str]  # ["02/02", "03/02", ...]
    days_label: list[str]  # ["Seg", "Ter", ...]
    mo_load: dict[str, list[float]]  # area -> daily MO values
    machines: list[PPMachineBlock]
    all_operations: list[PPOperation] = field(default_factory=list)


def _parse_numeric(value: str, default: int = 0) -> int:
    """Parse a numeric string, handling Portuguese decimal comma."""
    if not value:
        return default
    value = value.strip().replace(" ", "")
    # Remove thousand separators
    value = value.replace(".", "")
    # Handle comma decimals
    if "," in value:
        value = value.replace(",", ".")
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default


def _parse_float(value: str, default: float = 0.0) -> float:
    """Parse a float string with Portuguese formatting."""
    if not value:
        return default
    value = value.strip().replace(" ", "")
    if "," in value:
        value = value.replace(",", ".")
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _extract_pcs_per_hour(text: str) -> int:
    """Extract pcs/H value from text like '1923 pcs/H'."""
    m = re.search(r"(\d+)\s*pcs/H", text)
    return int(m.group(1)) if m else 0


def _extract_man_minutes(text: str) -> tuple[int, float]:
    """Extract MAN minutes and MO from text like '254 m/0,5'."""
    m = re.search(r"(\d+)\s*m/(\d+[.,]\d+)", text)
    if m:
        return int(m.group(1)), _parse_float(m.group(2))
    # Try just minutes
    m = re.search(r"(\d+)\s*m", text)
    if m:
        return int(m.group(1)), 0.0
    return 0, 0.0


class PPPDFParser:
    """Parser for Nikufra PP production plan PDFs.

    The PDFs have a fixed structure per page:
    - Header: title, MRP date, column headers
    - Area line with M.O. load values
    - Machine blocks: machine ID, MAN line, operation rows
    - Operations: SKU, lot qty, tool, components, qty, ATRASO, daily quantities
    - Description line: name, pcs/H rate

    Each operation spans 2 text lines:
    Line 1: SKU  LOT_QTY  TOOL  COMP_CODE  QTY  ATRASO  D1  D2  ...  D8
    Line 2: Description  RATE pcs/H  [additional fields]
    """

    DAYS_LABEL = FALLBACK_DAYS_LABEL

    def __init__(self, pdf_path: Path, area: str):
        self.pdf_path = pdf_path
        self.area = area  # PG1 or PG2

    def parse(self) -> PPPDFData:
        """Parse the PP PDF and return structured data."""
        import pdfplumber

        logger.info(f"Parsing PP PDF: {self.pdf_path} (area={self.area})")

        pdf = pdfplumber.open(str(self.pdf_path))
        dates: list[str] = []
        mo_values: list[float] = []
        machines: list[PPMachineBlock] = []
        current_machine: PPMachineBlock | None = None

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = text.split("\n")

            for line_idx, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue

                # Extract dates from header row
                if line.startswith("ARTIGO") and "ATRASO" in line:
                    date_matches = re.findall(r"(\d{2}/\d{2})/\d{2}", line)
                    if date_matches and not dates:
                        dates = date_matches

                # Extract M.O. values from area line
                if "M.O. ->" in line:
                    mo_match = re.findall(r"(\d+[.,]\d+)", line.split("M.O. ->")[1])
                    if mo_match:
                        mo_values = [_parse_float(v) for v in mo_match]

                # Detect machine block start
                machine_match = re.match(r"^(PRM\d{3}|PRH\d{3})\s+MAN", line)
                if machine_match:
                    machine_id = machine_match.group(1)
                    current_machine = PPMachineBlock(
                        machine_id=machine_id,
                        area=self.area,
                        man_minutes=[0] * 8,
                    )
                    machines.append(current_machine)
                    # Parse MAN minutes from same/next line
                    man_text = line[len(machine_match.group(0)) :]
                    if not man_text.strip():
                        # MAN values on next line
                        if line_idx + 1 < len(lines):
                            man_text = lines[line_idx + 1]
                    self._parse_man_line(current_machine, man_text)
                    continue

                # Detect standalone machine line (no MAN on same line)
                machine_only = re.match(r"^(PRM\d{3}|PRH\d{3})\s*$", line)
                if machine_only:
                    machine_id = machine_only.group(1)
                    current_machine = PPMachineBlock(
                        machine_id=machine_id,
                        area=self.area,
                        man_minutes=[0] * 8,
                    )
                    machines.append(current_machine)
                    continue

                # Detect MAN line for current machine
                if current_machine and re.match(r"^\d+\s*m/", line):
                    self._parse_man_line(current_machine, line)
                    continue

                # Detect operation line (starts with SKU pattern)
                if current_machine and self._is_operation_line(line):
                    op = self._parse_operation(line, lines, line_idx, current_machine.machine_id)
                    if op:
                        current_machine.operations.append(op)

        pdf.close()

        # Collect all operations
        all_ops = []
        for m in machines:
            all_ops.extend(m.operations)

        return PPPDFData(
            dates=dates if dates else generate_fallback_dates()[0],
            days_label=self.DAYS_LABEL,
            mo_load={self.area: mo_values},
            machines=machines,
            all_operations=all_ops,
        )

    def _parse_man_line(self, machine: PPMachineBlock, text: str) -> None:
        """Parse MAN minute values from text like '254 m/0,5 970 m/2,0'."""
        # Find all "NNN m/X.X" patterns
        pattern = re.findall(r"(\d+)\s*m/\d+[.,]\d+", text)
        if not pattern:
            return

        # Map values to day positions based on their position in text
        # The values appear only for non-zero days
        all_positions = list(re.finditer(r"(\d+)\s*m/(\d+[.,]\d+)", text))
        if not all_positions:
            return

        # Simple approach: values appear left-to-right for days with production
        # We need to figure out which days have values
        # Since the PDF table is aligned, non-zero values appear at column positions
        # For now, use a heuristic: spread values across days
        values = [int(m.group(1)) for m in all_positions]

        # Try to determine day positions from x-coordinates
        # Fallback: assign left-to-right to available slots
        day_idx = 0
        for val in values:
            while day_idx < 8 and machine.man_minutes[day_idx] != 0:
                day_idx += 1
            if day_idx < 8:
                machine.man_minutes[day_idx] = val
                day_idx += 1

    def _is_operation_line(self, line: str) -> bool:
        """Check if a line starts an operation (SKU pattern)."""
        # SKU patterns: 10xxxxxXnnn, 3xxxxxxnnn, CF..., 68..., F0..., TP..., E1...
        return bool(
            re.match(
                r"^(\d{7}X\d{3}|\d{10}(\.\d+)?|[A-Z]{2}\d{3}[A-Z0-9]|"
                r"\d{10}\.\d+|[A-Z]\d{4,}|TP\d|E\d{4}|F\d{5})",
                line,
            )
        )

    def _parse_operation(
        self,
        line: str,
        all_lines: list[str],
        line_idx: int,
        machine_id: str,
    ) -> PPOperation | None:
        """Parse an operation from the current line and its description line."""
        # Split line into tokens
        tokens = line.split()
        if len(tokens) < 3:
            return None

        sku = tokens[0]

        # Try to extract: lot_qty, tool_code, components, qty_pieces, atraso, daily_qty
        # The format varies but generally:
        # SKU  LOT_QTY  TOOL  COMP  QTY  ATRASO  D1 D2 D3 D4 D5 D6 D7 D8
        lot_qty = 0
        tool_code = ""
        atraso = 0
        daily_qty = [0] * 8
        components = ""
        stock = 0

        # Find tool code (BFP/VUL/MIC/DYE/EBR/HAN/JDE/JTE/LEC pattern)
        tool_idx = -1
        for i, tok in enumerate(tokens):
            if re.match(r"^(BFP|VUL|MIC|DYE|EBR|HAN|JDE|JTE|LEC)\d{3}", tok):
                tool_code = tok
                tool_idx = i
                break

        if tool_idx < 0:
            return None  # Can't identify tool

        # Lot qty is between SKU and tool
        if tool_idx >= 2:
            lot_qty = _parse_numeric(tokens[1])

        # After tool: components code, qty_pieces, atraso, daily values
        remaining = tokens[tool_idx + 1 :]

        # Find component code (EMP/BF/IC/VL/MAN pattern or just a code)
        comp_idx = 0
        for i, tok in enumerate(remaining):
            if re.match(r"^(EMP|BF|IC|VL|MAN)\d*", tok):
                components = tok
                comp_idx = i + 1
                break

        # After components: numeric values
        numerics = []
        for tok in remaining[comp_idx:]:
            val = _parse_numeric(tok, -1)
            if val >= 0:
                numerics.append(val)

        # First numeric after component is qty_pieces (total stock/WIP)
        # Second is ATRASO
        # Then 8 daily values
        if len(numerics) >= 2:
            stock = numerics[0]
            atraso = numerics[1]
            daily_qty = (numerics[2:10] + [0] * 8)[:8]
        elif len(numerics) == 1:
            atraso = numerics[0]

        # Look at next line for description + pcs/H
        name = ""
        pcs_per_hour = 0
        operators = 1
        setup_hours = 0.0

        if line_idx + 1 < len(all_lines):
            desc_line = all_lines[line_idx + 1].strip()
            # Skip if it's another operation or machine
            if not self._is_operation_line(desc_line) and not re.match(
                r"^(PRM|PRH)\d{3}", desc_line
            ):
                pcs_per_hour = _extract_pcs_per_hour(desc_line)
                # Name is everything before the rate
                rate_match = re.search(r"\d+\s*pcs/H", desc_line)
                if rate_match:
                    name = desc_line[: rate_match.start()].strip()
                else:
                    name = desc_line[:40].strip()

                # Check for additional daily values on desc line
                desc_nums = re.findall(r"\b(\d{3,})\b", desc_line)
                # These might be lot qty entries on second line

        # Get setup time from TOOLS data (will be cross-referenced in service)
        return PPOperation(
            sku=sku,
            name=name,
            tool_code=tool_code,
            machine=machine_id,
            pcs_per_hour=pcs_per_hour,
            lot_economic_qty=lot_qty,
            atraso=atraso,
            daily_qty=daily_qty,
            setup_hours=setup_hours,
            operators=operators,
            components=components,
            stock=stock,
        )


def parse_pp_pdfs(
    pg1_path: Path,
    pg2_path: Path,
) -> PPPDFData:
    """Parse both PP PDFs and combine results."""
    pg1_data = PPPDFParser(pg1_path, "PG1").parse()
    pg2_data = PPPDFParser(pg2_path, "PG2").parse()

    # Merge
    combined = PPPDFData(
        dates=pg1_data.dates or pg2_data.dates,
        days_label=pg1_data.days_label,
        mo_load={**pg1_data.mo_load, **pg2_data.mo_load},
        machines=pg1_data.machines + pg2_data.machines,
        all_operations=pg1_data.all_operations + pg2_data.all_operations,
    )

    logger.info(
        f"Parsed PP PDFs: {len(combined.machines)} machines, "
        f"{len(combined.all_operations)} operations"
    )
    return combined

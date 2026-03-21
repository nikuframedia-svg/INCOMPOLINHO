"""Input Validator — validates NikufraData before transform.

Catches bad data at system boundary (ISOP parse output).
Drops invalid jobs with journal entries instead of crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .journal import Journal, JournalSeverity, JournalStep


class ValidationError(Exception):
    """Raised when input validation fails fatally (no valid jobs)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Input validation failed: {'; '.join(errors)}")


@dataclass
class ValidatedJob:
    """A single validated operation/job."""

    id: str
    machine_id: str
    tool_id: str
    sku: str
    nm: str
    pH: float
    d: list[float | None]
    atr: float = 0
    twin: str | None = None
    cl: str | None = None
    eco: float = 0
    alt: str | None = None
    sH: float = 0.75
    op: int = 1


@dataclass
class ValidatedRequest:
    """Validated pipeline input."""

    jobs: list[ValidatedJob]
    dates: list[str]
    dnames: list[str]
    machines: set[str]
    dropped: list[dict[str, Any]] = field(default_factory=list)


class InputValidator:
    """Validates NikufraData operations before scheduling."""

    def __init__(self, journal: Journal) -> None:
        self._journal = journal

    def validate(self, nikufra_data: dict[str, Any]) -> ValidatedRequest:
        """Validate and clean NikufraData. Drops invalid ops with journal entries."""
        self._journal.step(JournalStep.VALIDATE_INPUT, "Starting input validation")

        operations = nikufra_data.get("operations", [])
        dates = nikufra_data.get("dates", [])
        dnames = nikufra_data.get("days_label", nikufra_data.get("dnames", []))

        if not operations:
            raise ValidationError(["No operations in NikufraData"])

        if not dates:
            raise ValidationError(["No dates in NikufraData — workdays undefined"])

        # Collect valid machines
        machines_raw = nikufra_data.get("machines", [])
        known_machines: set[str] = set()
        for m in machines_raw:
            mid = m.get("id", "") if isinstance(m, dict) else str(m)
            if mid:
                known_machines.add(mid)

        # Also collect machines from operations
        for op in operations:
            m = op.get("m", "")
            if m:
                known_machines.add(m)

        valid_jobs: list[ValidatedJob] = []
        dropped: list[dict[str, Any]] = []

        for op in operations:
            op_id = op.get("id", "")
            reasons: list[str] = []

            # Required fields
            machine_id = op.get("m", "")
            tool_id = op.get("t", "")
            sku = op.get("sku", "")

            if not machine_id:
                reasons.append("missing machine_id")
            if not tool_id:
                reasons.append("missing tool_id")
            if not sku:
                reasons.append("missing sku")

            # Rate validation
            pH = op.get("pH", 0)
            if not isinstance(pH, (int, float)) or pH <= 0:
                reasons.append(f"invalid pH={pH}")

            # Demand validation — at least one non-null value
            d = op.get("d", [])
            has_demand = any(
                v is not None and isinstance(v, (int, float)) and v != 0
                for v in d
            )
            atr = op.get("atr", 0)
            if not has_demand and (not isinstance(atr, (int, float)) or atr <= 0):
                reasons.append("no demand (all d[] null/zero and atr<=0)")

            # Orphan machine check
            if machine_id and known_machines and machine_id not in known_machines:
                reasons.append(f"orphan machine_id={machine_id}")

            if reasons:
                self._journal.drop(
                    JournalStep.VALIDATE_INPUT,
                    f"Dropped op {op_id}: {'; '.join(reasons)}",
                    metadata={"op_id": op_id, "reasons": reasons},
                )
                dropped.append({"op_id": op_id, "reasons": reasons})
                continue

            valid_jobs.append(ValidatedJob(
                id=op_id,
                machine_id=machine_id,
                tool_id=tool_id,
                sku=sku,
                nm=op.get("nm", sku),
                pH=float(pH),
                d=d,
                atr=float(atr) if isinstance(atr, (int, float)) else 0,
                twin=op.get("twin"),
                cl=op.get("cl"),
                eco=float(op.get("eco", op.get("lt", 0)) or 0),
                alt=op.get("alt", "-"),
                sH=float(op.get("sH", op.get("s", 0.75)) or 0.75),
                op=int(op.get("op", 1) or 1),
            ))

        if not valid_jobs:
            raise ValidationError([
                f"All {len(operations)} operations dropped during validation. "
                f"First drop: {dropped[0] if dropped else 'unknown'}"
            ])

        # Twin bidirectional check
        twin_map: dict[str, str] = {}
        for job in valid_jobs:
            if job.twin:
                twin_map[job.sku] = job.twin

        for sku, twin_ref in twin_map.items():
            if twin_ref not in twin_map:
                self._journal.warn(
                    JournalStep.VALIDATE_INPUT,
                    f"Twin {sku}→{twin_ref} is unidirectional (partner not found)",
                    metadata={"sku": sku, "twin_ref": twin_ref},
                )

        self._journal.info(
            JournalStep.VALIDATE_INPUT,
            f"Validated {len(valid_jobs)} jobs, dropped {len(dropped)}",
            metadata={"valid": len(valid_jobs), "dropped": len(dropped)},
        )

        return ValidatedRequest(
            jobs=valid_jobs,
            dates=dates,
            dnames=dnames,
            machines=known_machines,
            dropped=dropped,
        )

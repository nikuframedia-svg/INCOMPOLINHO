# Data Quality Assessment — TrustIndex Engine
# Conforme CLAUDE.md: TI = 0.15·C + 0.20·V + 0.15·F + 0.20·K + 0.15·P + 0.15·A
# Gates: ≥0.90 Full Auto | ≥0.70 Monitoring | ≥0.50 Suggestion | <0.50 Manual
from __future__ import annotations

import math
from datetime import UTC, datetime

from .schemas import DimensionScore, TrustIndexResult

# Máquinas válidas (conforme CLAUDE.md — PRM020 FORA DE USO)
VALID_MACHINES = {"PRM019", "PRM031", "PRM039", "PRM042", "PRM043"}

# Campos obrigatórios nas linhas ISOP: C(SKU), G(Máquina), H(Ferramenta), I(Peças/H)
REQUIRED_FIELDS = ["sku", "machine", "tool", "pcs_per_hour"]


class DQAEngine:
    """
    Avalia qualidade dos dados ISOP e calcula TrustIndex.

    TI = 0.15·C + 0.20·V + 0.15·F + 0.20·K + 0.15·P + 0.15·A

    C = Completeness, V = Validity, F = Freshness
    K = Consistency, P = Precision, A = Accuracy
    """

    WEIGHTS = {
        "completeness": 0.15,
        "validity": 0.20,
        "freshness": 0.15,
        "consistency": 0.20,
        "precision": 0.15,
        "accuracy": 0.15,
    }

    GATES = [
        (0.90, "full_auto", "Automation level: full autonomous scheduling"),
        (0.70, "monitoring", "Automation level: schedule with monitoring"),
        (0.50, "suggestion", "Automation level: suggestions only"),
        (0.0, "manual", "Automation level: manual planning required"),
    ]

    # Freshness: half-life em dias (score = exp(-λ·days))
    FRESHNESS_HALF_LIFE_DAYS = 3.0

    def assess_isop(self, file_data: dict) -> TrustIndexResult:
        """
        Avaliar qualidade de dados ISOP.

        file_data deve conter:
        - rows: list[dict] com campos sku, machine, tool, pcs_per_hour, twin, ...
        - file_date: str ISO date do ficheiro
        """
        rows = file_data.get("rows", [])
        file_date_str = file_data.get("file_date")
        total_rows = len(rows)

        if total_rows == 0:
            return TrustIndexResult(
                score=0.0,
                gate="manual",
                dimensions=[],
                issues=["No data rows found"],
                total_rows=0,
                assessed_at=datetime.now(UTC).isoformat(),
            )

        # Calcular cada dimensão
        completeness = self._assess_completeness(rows)
        validity = self._assess_validity(rows)
        freshness = self._assess_freshness(file_date_str)
        consistency = self._assess_consistency(rows)
        precision = self._assess_precision(rows)
        accuracy = self._assess_accuracy(rows)

        dimensions_raw = {
            "completeness": completeness,
            "validity": validity,
            "freshness": freshness,
            "consistency": consistency,
            "precision": precision,
            "accuracy": accuracy,
        }

        # Construir dimensões com pesos
        dimensions = []
        total_score = 0.0
        all_issues = []

        for name, (score, issues) in dimensions_raw.items():
            weight = self.WEIGHTS[name]
            weighted = score * weight
            total_score += weighted
            all_issues.extend(issues)
            dimensions.append(
                DimensionScore(
                    name=name,
                    score=round(score, 4),
                    weight=weight,
                    weighted_score=round(weighted, 4),
                    issues=issues,
                )
            )

        # Determinar gate
        gate = "manual"
        for threshold, gate_name, _ in self.GATES:
            if total_score >= threshold:
                gate = gate_name
                break

        return TrustIndexResult(
            score=round(total_score, 4),
            gate=gate,
            dimensions=dimensions,
            issues=all_issues,
            total_rows=total_rows,
            assessed_at=datetime.now(UTC).isoformat(),
        )

    def _assess_completeness(self, rows: list[dict]) -> tuple[float, list[str]]:
        """% linhas com todos os campos obrigatórios preenchidos."""
        issues = []
        if not rows:
            return 0.0, ["No rows to assess"]

        complete = 0
        for row in rows:
            if all(row.get(f) not in (None, "", 0) for f in REQUIRED_FIELDS):
                complete += 1

        score = complete / len(rows)
        missing = len(rows) - complete
        if missing > 0:
            issues.append(
                f"{missing}/{len(rows)} rows missing required fields (sku, machine, tool, pcs_per_hour)"
            )
        return score, issues

    def _assess_validity(self, rows: list[dict]) -> tuple[float, list[str]]:
        """% valores dentro de ranges válidos."""
        issues = []
        if not rows:
            return 0.0, ["No rows to assess"]

        valid = 0
        for row in rows:
            is_valid = True
            # Peças/H deve ser > 0
            ph = row.get("pcs_per_hour", 0)
            if not isinstance(ph, (int, float)) or ph <= 0:
                is_valid = False

            # Máquina deve existir
            machine = row.get("machine", "")
            if machine and machine not in VALID_MACHINES:
                is_valid = False

            if is_valid:
                valid += 1

        score = valid / len(rows)
        invalid = len(rows) - valid
        if invalid > 0:
            issues.append(f"{invalid}/{len(rows)} rows with invalid values")
        return score, issues

    def _assess_freshness(self, file_date_str: str | None) -> tuple[float, list[str]]:
        """Decay exponencial: score = exp(-λ·days), λ = ln(2)/half_life."""
        issues = []
        if not file_date_str:
            return 0.0, ["File date not provided"]

        try:
            file_date = datetime.fromisoformat(file_date_str)
            if file_date.tzinfo is None:
                file_date = file_date.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            days = (now - file_date).total_seconds() / 86400
        except (ValueError, TypeError):
            return 0.0, [f"Invalid file date: {file_date_str}"]

        if days < 0:
            days = 0

        decay_lambda = math.log(2) / self.FRESHNESS_HALF_LIFE_DAYS
        score = math.exp(-decay_lambda * days)

        if days > 7:
            issues.append(f"Data is {days:.0f} days old (>7 days)")
        elif days > 3:
            issues.append(f"Data is {days:.1f} days old (>3 days)")

        return score, issues

    def _assess_consistency(self, rows: list[dict]) -> tuple[float, list[str]]:
        """Gémeas referem-se mutuamente? Máquinas existem?"""
        issues = []
        if not rows:
            return 0.0, ["No rows to assess"]

        checks = 0
        passed = 0

        # Build SKU→twin map
        sku_twin_map = {}
        for row in rows:
            sku = row.get("sku")
            twin = row.get("twin")
            if sku:
                sku_twin_map[sku] = twin

        # Check twin bidirectionality
        for sku, twin in sku_twin_map.items():
            if twin:
                checks += 1
                if sku_twin_map.get(twin) == sku:
                    passed += 1
                else:
                    issues.append(f"Twin mismatch: {sku} → {twin} but {twin} does not point back")

        # Check machines exist
        for row in rows:
            machine = row.get("machine")
            if machine:
                checks += 1
                if machine in VALID_MACHINES:
                    passed += 1
                else:
                    issues.append(f"Unknown machine: {machine}")

        if checks == 0:
            return 1.0, []

        score = passed / checks
        return score, issues

    def _assess_precision(self, rows: list[dict]) -> tuple[float, list[str]]:
        """Cadências são inteiros? Quantidades são positivas?"""
        issues = []
        if not rows:
            return 0.0, ["No rows to assess"]

        checks = 0
        passed = 0

        for row in rows:
            ph = row.get("pcs_per_hour")
            if ph is not None:
                checks += 1
                if isinstance(ph, (int, float)) and ph == int(ph) and ph > 0:
                    passed += 1
                elif isinstance(ph, (int, float)) and ph <= 0:
                    issues.append(f"Non-positive pcs_per_hour: {ph}")

        if checks == 0:
            return 1.0, []

        score = passed / checks
        return score, issues

    def _assess_accuracy(self, rows: list[dict]) -> tuple[float, list[str]]:
        """Duplicados de SKU? Referências inválidas?"""
        issues = []
        if not rows:
            return 0.0, ["No rows to assess"]

        # Check SKU duplicates (same SKU + machine = potential duplicate)
        seen = set()
        duplicates = 0
        for row in rows:
            key = (row.get("sku"), row.get("machine"))
            if key[0] and key in seen:
                duplicates += 1
            seen.add(key)

        if duplicates > 0:
            issues.append(f"{duplicates} duplicate SKU+machine combinations")

        # Score: penalise duplicates
        dup_ratio = duplicates / len(rows) if rows else 0
        score = max(0.0, 1.0 - dup_ratio * 2)  # Each dup penalises 2x

        return score, issues

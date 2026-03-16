# Data Quality Assessment — Pydantic schemas

from pydantic import BaseModel


class DimensionScore(BaseModel):
    """Score individual de uma dimensão DQA."""

    name: str
    score: float
    weight: float
    weighted_score: float
    issues: list[str]


class TrustIndexResult(BaseModel):
    """Resultado da avaliação DQA / TrustIndex."""

    score: float
    gate: str  # full_auto | monitoring | suggestion | manual
    dimensions: list[DimensionScore]
    issues: list[str]
    total_rows: int
    assessed_at: str


class GateInfo(BaseModel):
    """Informação sobre um gate."""

    threshold: float
    name: str
    description: str

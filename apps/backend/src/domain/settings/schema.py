"""Settings schema — Pydantic V2 model for all 41 scheduling settings.

Mirrors frontend SettingsState (settings-types.ts).
Supports partial updates via Optional fields.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────


class DispatchRule(str, Enum):
    EDD = "EDD"
    CR = "CR"
    WSPT = "WSPT"
    SPT = "SPT"
    ATCS = "ATCS"
    AUTO = "AUTO"


class MOStrategy(str, Enum):
    cyclic = "cyclic"
    nominal = "nominal"
    custom = "custom"


class OptimizationProfile(str, Enum):
    balanced = "balanced"
    otd = "otd"
    setup = "setup"
    custom = "custom"


class DemandSemantics(str, Enum):
    daily = "daily"
    cumulative_np = "cumulative_np"
    raw_np = "raw_np"


class SolverObjective(str, Enum):
    weighted_tardiness = "weighted_tardiness"
    makespan = "makespan"
    tardiness = "tardiness"


class PreStartStrategy(str, Enum):
    auto = "auto"
    manual = "manual"


class RuleActionType(str, Enum):
    set_priority = "set_priority"
    boost_priority = "boost_priority"
    flag_night_shift = "flag_night_shift"
    alert = "alert"
    require_approval = "require_approval"
    block = "block"


# ── L4/L3/L2 sub-models ───────────────────────────────────────


class VersionEntry(BaseModel):
    v: int
    ts: str
    expression: str


class ConceptDefinition(BaseModel):
    id: str
    question: str = ""
    label: str = ""
    expression: str = ""
    variables: list[str] = Field(default_factory=list)
    version: int = 1
    versions: list[VersionEntry] = Field(default_factory=list)


class FormulaConfig(BaseModel):
    id: str
    label: str = ""
    description: str = ""
    expression: str = ""
    variables: list[str] = Field(default_factory=list)
    version: int = 1
    versions: list[VersionEntry] = Field(default_factory=list)


class RuleAction(BaseModel):
    type: RuleActionType
    value: Any = ""


class RuleVersionEntry(BaseModel):
    v: int
    ts: str
    query: Any = None
    action: RuleAction | None = None


class RuleConfig(BaseModel):
    id: str
    name: str = ""
    active: bool = True
    query: Any = None  # react-querybuilder format (JSON)
    action: RuleAction | None = None
    version: int = 1
    versions: list[RuleVersionEntry] = Field(default_factory=list)


# ── Weight profiles ────────────────────────────────────────────

WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "balanced": {
        "wTardiness": 100,
        "wSetupCount": 10,
        "wSetupTime": 1.0,
        "wSetupBalance": 30,
        "wChurn": 5,
        "wOverflow": 50,
        "wBelowMinBatch": 5,
        "wCapacityVariance": 20,
        "wSetupDensity": 15,
    },
    "otd": {
        "wTardiness": 200,
        "wSetupCount": 5,
        "wSetupTime": 0.5,
        "wSetupBalance": 10,
        "wChurn": 2,
        "wOverflow": 80,
        "wBelowMinBatch": 2,
        "wCapacityVariance": 10,
        "wSetupDensity": 5,
    },
    "setup": {
        "wTardiness": 30,
        "wSetupCount": 50,
        "wSetupTime": 5,
        "wSetupBalance": 40,
        "wChurn": 3,
        "wOverflow": 20,
        "wBelowMinBatch": 1,
        "wCapacityVariance": 10,
        "wSetupDensity": 25,
    },
}


# ── Main settings model ───────────────────────────────────────


class SettingsModel(BaseModel):
    """All 41 scheduling settings — mirrors frontend SettingsState."""

    # §1: Shifts
    shiftXStart: str = "07:00"
    shiftChange: str = "15:30"
    shiftYEnd: str = "24:00"
    oee: float = Field(default=0.66, ge=0.0, le=1.0)
    thirdShiftDefault: bool = False

    # §2: Dispatch
    dispatchRule: DispatchRule = DispatchRule.EDD
    bucketWindowDays: int = Field(default=5, ge=1, le=30)
    maxEddGapDays: int = Field(default=5, ge=1, le=30)
    defaultSetupHours: float = Field(default=0.75, ge=0.0, le=8.0)

    # §3: Optimization weights
    optimizationProfile: OptimizationProfile = OptimizationProfile.balanced
    wTardiness: float = Field(default=100, ge=0)
    wSetupCount: float = Field(default=10, ge=0)
    wSetupTime: float = Field(default=1.0, ge=0)
    wSetupBalance: float = Field(default=30, ge=0)
    wChurn: float = Field(default=5, ge=0)
    wOverflow: float = Field(default=50, ge=0)
    wBelowMinBatch: float = Field(default=5, ge=0)
    wCapacityVariance: float = Field(default=20, ge=0)
    wSetupDensity: float = Field(default=15, ge=0)

    # §4: MO strategy
    moStrategy: MOStrategy = MOStrategy.nominal
    moNominalPG1: int = Field(default=3, ge=0, le=20)
    moNominalPG2: int = Field(default=4, ge=0, le=20)
    moCustomPG1: int = Field(default=3, ge=0, le=20)
    moCustomPG2: int = Field(default=4, ge=0, le=20)

    # §5: Overflow & capacity
    altUtilThreshold: float = Field(default=0.95, ge=0.0, le=1.0)
    maxAutoMoves: int = Field(default=50, ge=0, le=200)
    maxOverflowIter: int = Field(default=3, ge=1, le=10)
    otdTolerance: float = Field(default=1.0, ge=0.0, le=1.0)
    loadBalanceThreshold: float = Field(default=0.15, ge=0.0, le=1.0)

    # §5b: Auto-replan & demand
    enableAutoReplan: bool = False
    enableShippingCutoff: bool = False
    autoReplanConfig: dict[str, Any] = Field(default_factory=dict)
    demandSemantics: DemandSemantics = DemandSemantics.raw_np

    # §5c: Server solver
    useServerSolver: bool = True
    usePythonScheduler: bool = True
    serverSolverTimeLimit: int = Field(default=60, ge=5, le=300)
    serverSolverObjective: SolverObjective = SolverObjective.weighted_tardiness

    # §5d: Pre-start buffer
    preStartBufferDays: int = Field(default=5, ge=0, le=30)
    preStartStrategy: PreStartStrategy = PreStartStrategy.auto

    # §5e: Client tiers
    clientTiers: dict[str, int] = Field(default_factory=dict)

    # §6: MRP
    serviceLevel: int = Field(default=95, ge=90, le=99)
    coverageThresholdDays: int = Field(default=3, ge=1, le=30)
    abcThresholdA: float = Field(default=0.8, ge=0.0, le=1.0)
    abcThresholdB: float = Field(default=0.95, ge=0.0, le=1.0)
    xyzThresholdX: float = Field(default=0.5, ge=0.0, le=2.0)
    xyzThresholdY: float = Field(default=1.0, ge=0.0, le=2.0)

    # §7: L2/L3/L4 configurable logic
    definitions: list[ConceptDefinition] = Field(default_factory=list)
    formulas: list[FormulaConfig] = Field(default_factory=list)
    rules: list[RuleConfig] = Field(default_factory=list)

    model_config = {"use_enum_values": True}


class SettingsUpdate(BaseModel):
    """Partial update model — all fields optional."""

    shiftXStart: str | None = None
    shiftChange: str | None = None
    shiftYEnd: str | None = None
    oee: float | None = None
    thirdShiftDefault: bool | None = None
    dispatchRule: DispatchRule | None = None
    bucketWindowDays: int | None = None
    maxEddGapDays: int | None = None
    defaultSetupHours: float | None = None
    optimizationProfile: OptimizationProfile | None = None
    wTardiness: float | None = None
    wSetupCount: float | None = None
    wSetupTime: float | None = None
    wSetupBalance: float | None = None
    wChurn: float | None = None
    wOverflow: float | None = None
    wBelowMinBatch: float | None = None
    wCapacityVariance: float | None = None
    wSetupDensity: float | None = None
    moStrategy: MOStrategy | None = None
    moNominalPG1: int | None = None
    moNominalPG2: int | None = None
    moCustomPG1: int | None = None
    moCustomPG2: int | None = None
    altUtilThreshold: float | None = None
    maxAutoMoves: int | None = None
    maxOverflowIter: int | None = None
    otdTolerance: float | None = None
    loadBalanceThreshold: float | None = None
    enableAutoReplan: bool | None = None
    enableShippingCutoff: bool | None = None
    autoReplanConfig: dict[str, Any] | None = None
    demandSemantics: DemandSemantics | None = None
    useServerSolver: bool | None = None
    usePythonScheduler: bool | None = None
    serverSolverTimeLimit: int | None = None
    serverSolverObjective: SolverObjective | None = None
    preStartBufferDays: int | None = None
    preStartStrategy: PreStartStrategy | None = None
    clientTiers: dict[str, int] | None = None
    serviceLevel: int | None = None
    coverageThresholdDays: int | None = None
    abcThresholdA: float | None = None
    abcThresholdB: float | None = None
    xyzThresholdX: float | None = None
    xyzThresholdY: float | None = None
    definitions: list[ConceptDefinition] | None = None
    formulas: list[FormulaConfig] | None = None
    rules: list[RuleConfig] | None = None

    model_config = {"use_enum_values": True}

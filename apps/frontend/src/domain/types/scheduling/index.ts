// ═══════════════════════════════════════════════════════════
//  domain/types/scheduling — Canonical scheduling type definitions
//  Moved from lib/scheduling-core/types/
// ═══════════════════════════════════════════════════════════

// ── Blocks ──
export type {
  AdvanceAction,
  Block,
  DayLoad,
  MoveAction,
  OvertimeAction,
  ReplanStrategyType,
  SplitAction,
  TwinOutput,
  ZoneShiftDemand,
} from './blocks.js';
// ── Compat types (stubs from deleted modules) ──
export type {
  ATCSParams,
  AutoReplanAction,
  AutoReplanConfig,
  AutoReplanResult,
  CoverageAuditResult,
  CoverageAuditRow,
  DecisionKind,
  DecisionSeverity,
  FullReplanInput,
  FullReplanResult,
  GridResult,
  LateDeliveryAnalysis,
  LateDeliveryEntry,
  MatchUpInput,
  MatchUpResult,
  MoveableOp,
  OptimizationInput,
  OptimizationSetup,
  PartialReplanInput,
  PartialReplanResult,
  QuickValidateResult,
  ReplanActionDetail,
  ReplanDispatchInput,
  ReplanDispatchResult,
  ReplanEventType,
  ReplanLayer,
  ReplanProposal,
  ReplanSimulation,
  RightShiftInput,
  RightShiftResult,
  RiskCell,
  RiskGridData,
  RiskLevel,
  RiskRow,
  RiskValidationInput,
  ROPConfig,
  SAConfig,
  SAInput,
  SAResult,
  ScheduleAllInput,
  ScheduleAllResult,
  ScheduleValidationReport,
  ScheduleViolation,
  SchedulingConfig,
  SchedulingContext,
  SchedulingStrategy,
  ScoringJob,
  SupplyPriority,
  SupplyPriorityConfig,
  TransformConfig,
  TwinValidationInput,
  UserReplanChoice,
  WorkforceDemandResult,
  WorkforceForecastInput,
} from './compat.js';
// ── Constants ──
export {
  DAY_CAP,
  DEFAULT_OEE,
  S0,
  S1,
  S2,
  T1,
} from './constants.js';
// ── Constraints ──
export type { ConstraintConfig, ConstraintMode, ConstraintName } from './constraints.js';
export { DEFAULT_CONSTRAINT_CONFIG } from './constraints.js';
// ── Core (Nikufra types) ──
export type {
  MasterISOPData,
  MasterToolRecord,
  NikufraCustomer,
  NikufraData,
  NikufraHistoryEvent,
  NikufraMachine,
  NikufraMOLoad,
  NikufraOperation,
  NikufraTool,
} from './core.js';
// ── Decisions ──
export type {
  AlternativeAction,
  DecisionEntry,
  DecisionSummary,
  DecisionType,
} from './decisions.js';
// ── Engine ──
export type {
  EMachine,
  EngineData,
  EOp,
  ETool,
} from './engine.js';
// ── Failure ──
export type {
  DayShiftCapacity,
  DayShiftStatus,
  FailureEvent,
  FailureSeverity,
  ImpactedBlock,
  ImpactReport,
  ReplanResult,
  ResourceTimeline,
  ShiftId,
} from './failure.js';
// ── Infeasibility ──
export type {
  FeasibilityReport,
  InfeasibilityEntry,
  InfeasibilityReason,
  RemediationProposal,
  RemediationType,
} from './infeasibility.js';
export { createEmptyFeasibilityReport, finalizeFeasibilityReport } from './infeasibility.js';
// ── KPIs ──
export type {
  CoverageAudit,
  CoverageEntry,
  DispatchRule,
  ObjectiveWeights,
  OptResult,
  ValidationReport,
  Violation,
  ViolationSeverity,
} from './kpis.js';
// ── Legacy ──
export type { AreaCaps, Decision, ObjectiveProfile, OpDay } from './legacy.js';
// ── MRP ──
export type {
  ActionMessage,
  ActionMessagesSummary,
  CoverageCell,
  CoverageMatrixResult,
  CoverageMatrixSkuResult,
  CoverageSkuCell,
  CTPInput,
  CTPResult,
  CTPSkuInput,
  MRPDayBucket,
  MRPRecord,
  MRPResult,
  MRPSkuRecord,
  MRPSkuSummary,
  MRPSkuViewRecord,
  MRPSkuViewResult,
  MRPSummary,
  RCCPEntry,
  ROPResult,
  ROPSkuResult,
  ROPSkuSummary,
  ROPSummary,
  ServiceLevel,
  WhatIfDelta,
  WhatIfMutation,
  WhatIfResult,
} from './mrp.js';
// ── Plan State ──
export type {
  MachineLoadEntry,
  PlanningKPIs,
  PlanningMachine,
  PlanningOperation,
  PlanningTool,
  PlanState,
  ScheduleSlot,
} from './plan-state.js';
// ── Scoring ──
export type {
  CapacityLogEntry,
  DeficitEvolution,
  OperationScore,
  ScoreWeights,
  WorkContent,
} from './scoring.js';
export { DEFAULT_SCORE_WEIGHTS } from './scoring.js';
// ── Shipping ──
export type { OperationDeadline, ShippingCutoffConfig } from './shipping.js';
export { DEFAULT_SHIPPING_CUTOFF } from './shipping.js';
// ── Transparency ──
export type {
  FailureJustification,
  OrderJustification,
  StartReason,
  TransparencyReport,
} from './transparency.js';
// ── Twin ──
export type {
  TwinAnomalyCode,
  TwinAnomalyEntry,
  TwinGroup,
  TwinValidationReport,
} from './twin.js';
// ── Workforce ──
export type {
  LaborWindow,
  WorkforceConfig,
  WorkforceCoverageMissing,
  WorkforceForecast,
  WorkforceForecastWarning,
  WorkforceSuggestion,
} from './workforce.js';
export { DEFAULT_WORKFORCE_CONFIG } from './workforce.js';

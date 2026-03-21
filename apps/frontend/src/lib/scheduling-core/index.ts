// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Scheduling Core (Slim)
//  Types + Pure utilities only. Zero scheduling logic.
//  All scheduling done by backend CP-SAT solver.
// ═══════════════════════════════════════════════════════════

// ── Constants ──
export {
  DAY_CAP,
  DEFAULT_OEE,
  S0,
  S1,
  S2,
  T1,
} from './constants.js';

// ── Analysis (score weights only) ──
export type { ScoreWeights } from './analysis/score-schedule.js';
export { DEFAULT_WEIGHTS as DEFAULT_SCORE_WEIGHTS } from './analysis/score-schedule.js';

// ── Failures (resource timeline builder — pure data transform) ──
export {
  buildResourceTimelines,
  deriveLegacyStatus,
  getCapacityFactor,
  isFullyDown,
  legacyStatusToFailureEvents,
} from './failures/failure-timeline.js';

// ── MRP (pure computation — no scheduling) ──
export { computeActionMessages } from './mrp/mrp-actions.js';
export { computeCoverageMatrixSku } from './mrp/mrp-coverage-sku.js';
export { computeCTP } from './mrp/mrp-ctp.js';
export { computeCTPSku } from './mrp/mrp-ctp-sku.js';
export { computeMRP } from './mrp/mrp-engine.js';
export type { ROPConfig } from './mrp/mrp-rop.js';
export { computeCoverageMatrix, computeROP, DEFAULT_ROP_CONFIG } from './mrp/mrp-rop.js';
export { computeROPSku } from './mrp/mrp-rop-sku.js';
export { computeMRPSkuView } from './mrp/mrp-sku-view.js';
export { computeWhatIf } from './mrp/mrp-what-if.js';
export type { SupplyPriority, SupplyPriorityConfig } from './mrp/supply-priority.js';
export { computeSupplyPriority, DEFAULT_SUPPLY_PRIORITY_CONFIG } from './mrp/supply-priority.js';

// ── Replan (layer chooser — pure function) ──
export type {
  ReplanDispatchInput,
  ReplanDispatchResult,
  ReplanLayer,
} from './replan/replan-dispatcher.js';
export {
  chooseLayer,
  LAYER_THRESHOLD_1,
  LAYER_THRESHOLD_2,
} from './replan/replan-dispatcher.js';

// ── Types ──
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
} from './types/blocks.js';
export type { ConstraintConfig, ConstraintMode, ConstraintName } from './types/constraints.js';
export { DEFAULT_CONSTRAINT_CONFIG } from './types/constraints.js';
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
} from './types/core.js';
export type {
  AlternativeAction,
  DecisionEntry,
  DecisionSummary,
  DecisionType,
} from './types/decisions.js';
export type {
  EMachine,
  EngineData,
  EOp,
  ETool,
} from './types/engine.js';
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
} from './types/failure.js';
export type {
  FeasibilityReport,
  InfeasibilityEntry,
  InfeasibilityReason,
  RemediationProposal,
  RemediationType,
} from './types/infeasibility.js';
export { createEmptyFeasibilityReport, finalizeFeasibilityReport } from './types/infeasibility.js';
export type {
  CoverageAudit,
  CoverageEntry,
  DispatchRule,
  ObjectiveWeights,
  OptResult,
  ValidationReport,
  Violation,
  ViolationSeverity,
} from './types/kpis.js';
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
} from './types/mrp.js';
export type {
  MachineLoadEntry,
  PlanningKPIs,
  PlanningMachine,
  PlanningOperation,
  PlanningTool,
  PlanState,
  ScheduleSlot,
} from './types/plan-state.js';
export type {
  CapacityLogEntry,
  DeficitEvolution,
  OperationScore,
  WorkContent,
} from './types/scoring.js';
export type { OperationDeadline, ShippingCutoffConfig } from './types/shipping.js';
export { DEFAULT_SHIPPING_CUTOFF } from './types/shipping.js';
export type {
  FailureJustification,
  OrderJustification,
  StartReason,
  TransparencyReport,
} from './types/transparency.js';
export type {
  TwinAnomalyCode,
  TwinAnomalyEntry,
  TwinGroup,
  TwinValidationReport,
} from './types/twin.js';
export type {
  LaborWindow,
  WorkforceConfig,
  WorkforceCoverageMissing,
  WorkforceForecast,
  WorkforceForecastWarning,
  WorkforceSuggestion,
} from './types/workforce.js';
export { DEFAULT_WORKFORCE_CONFIG } from './types/workforce.js';

// ── Compat types (from deleted modules — pure type stubs) ──
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
  ReplanEventType,
  ReplanProposal,
  ReplanSimulation,
  RightShiftInput,
  RightShiftResult,
  RiskCell,
  RiskGridData,
  RiskLevel,
  RiskRow,
  RiskValidationInput,
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
  TransformConfig,
  TwinValidationInput,
  UserReplanChoice,
  WorkforceDemandResult,
  WorkforceForecastInput,
} from './types/compat.js';

// ── Utilities (pure functions) ──
export {
  getBlockProductionForOp,
  getBlockQtyForOp,
  getBlocksForOp,
} from './utils/block-production.js';
export { C, TC, tci } from './utils/colors.js';
export {
  fmtMin,
  fromAbs,
  getShift,
  getShiftEnd,
  getShiftStart,
  inferWorkdaysFromLabels,
  padMoArray,
  toAbs,
} from './utils/time.js';

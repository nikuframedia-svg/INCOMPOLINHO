// ═══════════════════════════════════════════════════════════
//  INCOMPOL Web App — Engine Shim Layer
//  Single import point for ALL scheduling types + utilities.
//  Re-exports from scheduling-core (the TRUTH).
//  ALL consumers in the web app MUST import from here.
// ═══════════════════════════════════════════════════════════

// ── Re-export ALL types from scheduling-core ──
export type {
  ActionMessage,
  ActionMessagesSummary,
  AdvanceAction,
  AlternativeAction,
  ATCSParams,
  AutoReplanAction,
  AutoReplanConfig,
  AutoReplanResult,
  Block,
  CapacityLogEntry,
  ConstraintConfig,
  ConstraintMode,
  ConstraintName,
  CoverageAudit,
  CoverageAuditResult,
  CoverageAuditRow,
  CoverageCell,
  CoverageEntry,
  CoverageMatrixResult,
  CoverageMatrixSkuResult,
  CoverageSkuCell,
  CTPInput,
  CTPResult,
  CTPSkuInput,
  DayLoad,
  DayShiftCapacity,
  DayShiftStatus,
  DecisionEntry,
  DecisionKind,
  DecisionSeverity,
  DecisionSummary,
  DecisionType,
  DeficitEvolution,
  DispatchRule,
  EMachine,
  EngineData,
  EOp,
  ETool,
  FailureEvent,
  FailureJustification,
  FailureSeverity,
  FeasibilityReport,
  FullReplanInput,
  FullReplanResult,
  GridResult,
  ImpactedBlock,
  ImpactReport,
  InfeasibilityEntry,
  InfeasibilityReason,
  LaborWindow,
  LateDeliveryAnalysis,
  LateDeliveryEntry,
  MachineLoadEntry,
  MasterISOPData,
  MasterToolRecord,
  MatchUpInput,
  MatchUpResult,
  MoveAction,
  MoveableOp,
  MRPDayBucket,
  MRPRecord,
  MRPResult,
  MRPSkuRecord,
  MRPSkuSummary,
  MRPSkuViewRecord,
  MRPSkuViewResult,
  MRPSummary,
  NikufraCustomer,
  NikufraData,
  NikufraHistoryEvent,
  NikufraMachine,
  NikufraMOLoad,
  NikufraOperation,
  NikufraTool,
  ObjectiveWeights,
  OperationDeadline,
  OperationScore,
  OptimizationInput,
  OptimizationSetup,
  OptResult,
  OrderJustification,
  OvertimeAction,
  PartialReplanInput,
  PartialReplanResult,
  PlanningKPIs,
  PlanningMachine,
  PlanningOperation,
  PlanningTool,
  PlanState,
  QuickValidateResult,
  RCCPEntry,
  RemediationProposal,
  RemediationType,
  ReplanActionDetail,
  ReplanDispatchInput,
  ReplanDispatchResult,
  ReplanEventType,
  ReplanLayer,
  ReplanProposal,
  ReplanResult,
  ReplanSimulation,
  ReplanStrategyType,
  ResourceTimeline,
  RightShiftInput,
  RightShiftResult,
  RiskCell,
  RiskGridData,
  RiskLevel,
  RiskRow,
  RiskValidationInput,
  ROPConfig,
  ROPResult,
  ROPSkuResult,
  ROPSkuSummary,
  ROPSummary,
  SAConfig,
  SAInput,
  SAResult,
  ScheduleAllInput,
  ScheduleAllResult,
  ScheduleSlot,
  ScheduleValidationReport,
  ScheduleViolation,
  SchedulingConfig,
  SchedulingContext,
  SchedulingStrategy,
  ScoringJob,
  ScoreWeights,
  ServiceLevel,
  ShiftId,
  ShippingCutoffConfig,
  SplitAction,
  StartReason,
  SupplyPriority,
  SupplyPriorityConfig,
  TransformConfig,
  TransparencyReport,
  TwinAnomalyCode,
  TwinAnomalyEntry,
  TwinGroup,
  TwinOutput,
  TwinValidationInput,
  TwinValidationReport,
  UserReplanChoice,
  ValidationReport,
  Violation,
  ViolationSeverity,
  WhatIfDelta,
  WhatIfMutation,
  WhatIfResult,
  WorkContent,
  WorkforceConfig,
  WorkforceCoverageMissing,
  WorkforceDemandResult,
  WorkforceForecast,
  WorkforceForecastInput,
  WorkforceForecastWarning,
  WorkforceSuggestion,
  ZoneShiftDemand,
} from './scheduling-core/index.js';

// ── Re-export constants ──
export {
  DAY_CAP,
  DEFAULT_OEE,
  S0,
  S1,
  S2,
  T1,
} from './scheduling-core/index.js';

// ── Re-export defaults ──
export {
  DEFAULT_CONSTRAINT_CONFIG,
  DEFAULT_ROP_CONFIG,
  DEFAULT_SCORE_WEIGHTS,
  DEFAULT_SHIPPING_CUTOFF,
  DEFAULT_SUPPLY_PRIORITY_CONFIG,
  DEFAULT_WORKFORCE_CONFIG,
} from './scheduling-core/index.js';

// ── Re-export runtime values (infeasibility) ──
export {
  createEmptyFeasibilityReport,
  finalizeFeasibilityReport,
} from './scheduling-core/index.js';

// ── Re-export pure functions (MRP — no scheduling) ──
export {
  computeActionMessages,
  computeCoverageMatrix,
  computeCoverageMatrixSku,
  computeCTP,
  computeCTPSku,
  computeMRP,
  computeMRPSkuView,
  computeROP,
  computeROPSku,
  computeSupplyPriority,
  computeWhatIf,
} from './scheduling-core/index.js';

// ── Re-export pure functions (failures — data transform) ──
export {
  buildResourceTimelines,
  deriveLegacyStatus,
  getCapacityFactor,
  isFullyDown,
  legacyStatusToFailureEvents,
} from './scheduling-core/index.js';

// ── Re-export pure functions (replan layer chooser) ──
export {
  chooseLayer,
  LAYER_THRESHOLD_1,
  LAYER_THRESHOLD_2,
} from './scheduling-core/index.js';

// ── Re-export pure utilities ──
export {
  fmtMin,
  fromAbs,
  getBlockProductionForOp,
  getBlockQtyForOp,
  getBlocksForOp,
  getShift,
  getShiftEnd,
  getShiftStart,
  inferWorkdaysFromLabels,
  padMoArray,
  tci,
  toAbs,
} from './scheduling-core/index.js';

// ── Color bridge: C and TC resolve CSS vars instead of hardcoded hex ──
export { C, TC } from '../theme/color-bridge';

// ── Legacy types for web app ──

export interface Decision {
  id: string;
  opId: string;
  type: 'replan' | 'blocked';
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  desc: string;
  reasoning: string[];
  impact: Record<string, unknown> | null;
  action: MoveAction | null;
}

export interface AreaCaps {
  PG1: number;
  PG2: number;
}

export interface OpDay {
  pg1: number;
  pg2: number;
  total: number;
}

export interface ObjectiveProfile {
  id: string;
  label: string;
  weights: Record<string, number>;
}

// ── Backwards-compatible helper ──

import type { MoveAction, ZoneShiftDemand } from './scheduling-core/index.js';

export function opsByDayFromWorkforce(wfd: ZoneShiftDemand[], nDays: number): OpDay[] {
  const result: OpDay[] = Array.from({ length: nDays }, () => ({ pg1: 0, pg2: 0, total: 0 }));
  for (const e of wfd) {
    if (e.dayIdx < 0 || e.dayIdx >= nDays) continue;
    if (e.laborGroup === 'Grandes') {
      result[e.dayIdx].pg1 = Math.max(result[e.dayIdx].pg1, e.peakNeed);
    } else {
      result[e.dayIdx].pg2 = Math.max(result[e.dayIdx].pg2, e.peakNeed);
    }
  }
  for (const r of result) r.total = r.pg1 + r.pg2;
  return result;
}

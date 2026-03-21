// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Decision Registry Types
//  Per Normative Spec §10: Every scheduling decision is tracked.
//  Operator pool is ADVISORY (warning only, never blocks).
//  All other constraints are HARD.
//  No 'DEFAULT_VALUE' — no data invention allowed.
// ═══════════════════════════════════════════════════════════

export type DecisionType =
  | 'BACKWARD_SCHEDULE' // Start date computed from Prz.Fabrico
  | 'LOAD_LEVEL' // Block moved for load balancing
  | 'OVERFLOW_ROUTE' // Operation routed to alternative machine
  | 'ADVANCE_PRODUCTION' // Production advanced to earlier days (same machine)
  | 'DATA_MISSING' // Essential data not available (setup, MO, pH)
  | 'INFEASIBILITY_DECLARED' // Operation declared infeasible
  | 'DEADLINE_CONSTRAINT' // Deadline influenced scheduling order
  | 'OPERATOR_REALLOCATION' // Pool operators borrowed from other area
  | 'ALTERNATIVE_MACHINE' // Rerouted to alt machine (overflow or down)
  | 'TOOL_DOWN' // Tool marked as down
  | 'MACHINE_DOWN' // Machine marked as down
  | 'FAILURE_DETECTED' // Temporal failure event affected scheduling
  | 'FAILURE_MITIGATION' // Block rerouted to alt machine due to failure
  | 'FAILURE_UNRECOVERABLE' // Block could not be rescheduled (no alternative)
  | 'SHIPPING_CUTOFF' // Shipping deadline computed for operation
  | 'PRODUCTION_START' // Production start time decided by scoring
  | 'CAPACITY_COMPUTATION' // OEE/capacity log for an operation
  | 'SCORING_DECISION' // Score computed for operation ordering
  | 'OPERATOR_CAPACITY_WARNING' // Operator capacity exceeded (advisory only)
  | 'AUTO_REPLAN_ADVANCE' // Production advanced by auto-replan
  | 'AUTO_REPLAN_MOVE' // Alt machine move by auto-replan
  | 'AUTO_REPLAN_SPLIT' // Operation split between machines by auto-replan
  | 'AUTO_REPLAN_OVERTIME' // Overtime added by auto-replan
  | 'AUTO_REPLAN_THIRD_SHIFT' // 3rd shift activated by auto-replan
  | 'TWIN_VALIDATION_ANOMALY' // Twin piece validation failed
  | 'WORKFORCE_FORECAST_D1' // D+1 workforce overload warning
  | 'WORKFORCE_COVERAGE_MISSING' // Overtime/3rd shift without workforce configured
  | 'LABOR_GROUP_UNMAPPED' // Machine not mapped to any labor group
  | 'SCHEDULE_REPAIR'; // Post-scheduling violation repair (setup overlap or overcapacity)

/** An alternative action the user could choose instead of the system's decision */
export interface AlternativeAction {
  description: string;
  /** The type of action needed to implement this alternative */
  actionType: import('../types/blocks.js').ReplanStrategyType | 'FORMAL_RISK_ACCEPTANCE';
  /** Structured parameters for the alternative (depends on actionType) */
  params: Record<string, unknown>;
}

export interface DecisionEntry {
  id: string;
  timestamp: number;
  type: DecisionType;
  opId?: string;
  toolId?: string;
  machineId?: string;
  dayIdx?: number;
  shift?: 'X' | 'Y' | 'Z';
  detail: string;
  metadata: Record<string, unknown>;
  /** If this decision was made by auto-replan, the strategy that created it */
  replanStrategy?: import('../types/blocks.js').ReplanStrategyType;
  /** Alternative actions the user could take instead */
  alternatives?: AlternativeAction[];
  /** Whether this decision can be undone by the user */
  reversible?: boolean;
}

export interface DecisionSummary {
  total: number;
  dataMissing: number;
  infeasibilities: number;
  loadLevelMoves: number;
  overflowRoutes: number;
  advanceProductions: number;
  backwardSchedules: number;
  deadlineConstraints: number;
  operatorReallocations: number;
  failureDetected: number;
  failureMitigations: number;
  failureUnrecoverable: number;
  shippingCutoffs: number;
  productionStarts: number;
  capacityComputations: number;
  scoringDecisions: number;
  operatorCapacityWarnings: number;
  autoReplanAdvance: number;
  autoReplanMove: number;
  autoReplanSplit: number;
  autoReplanOvertime: number;
  autoReplanThirdShift: number;
  autoReplanTotal: number;
  twinValidationAnomalies: number;
  workforceForecastD1: number;
  workforceCoverageMissing: number;
}

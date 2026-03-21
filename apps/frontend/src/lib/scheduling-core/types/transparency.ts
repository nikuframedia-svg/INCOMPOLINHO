// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Industrial Transparency Types
//  Per-order justification for auditable scheduling decisions
// ═══════════════════════════════════════════════════════════

import type { ZoneShiftDemand } from './blocks.js';
import type { CapacityLogEntry } from './scoring.js';
import type { TwinValidationReport } from './twin.js';
import type { WorkforceForecast } from './workforce.js';

/** Reason why production was started at a given time */
export type StartReason =
  | 'urgency_slack_critical' // Slack < 1 day — must start now
  | 'density_heavy_load' // High density: >50% of available capacity needed
  | 'free_window_available' // Machine has a free window, nothing more urgent
  | 'setup_reduction' // Started to reduce setup changes
  | 'future_load_relief' // Anticipating to smooth future load
  | 'deficit_elimination'; // Deficit already exists (backlog)

/**
 * Justification for a feasible (scheduled) operation.
 * Explains WHY production starts when it does.
 */
export interface OrderJustification {
  opId: string;
  /** Initial stock available for this SKU */
  initialStock: number;
  /** Initial deficit (demand already unmet at day 0) */
  initialDeficit: number;
  /** Daily deficit evolution across horizon */
  deficitEvolution: number[];
  /** Pieces per hour */
  pH: number;
  /** Effective OEE applied */
  oee: number;
  /** Resulting daily capacity in pieces */
  capacityPcsPerDay: number;
  /** Production hours allocated per day */
  allocatedHoursPerDay: number;
  /** Which shifts are used each day */
  shiftsUsedPerDay: ('X' | 'Y' | 'Z')[][];
  /** Why production starts at the chosen time */
  startReason: StartReason;
  /** Whether the operation was feasibly scheduled */
  feasible: true;
  /** Total pieces produced */
  totalProduced: number;
  /** Total demand (backlog + daily) */
  totalDemand: number;
  /** Whether this operation's production comes from twin co-production */
  isTwinProduction?: boolean;
  /** Twin partner SKU (when twin co-production) */
  twinPartnerSku?: string;
  /** Per-SKU output breakdown (when twin co-production) */
  twinOutputs?: Array<{ sku: string; qty: number }>;
}

/**
 * Justification for an infeasible (failed) operation.
 * Explains WHY production cannot meet the deadline.
 */
export interface FailureJustification {
  opId: string;
  /** Constraints that were violated */
  constraintsViolated: string[];
  /** Absolute minute where scheduling becomes impossible */
  firstImpossibleMoment: number;
  /** Missing capacity in hours to complete the operation */
  missingCapacityHours: number;
  /** Missing capacity in pieces */
  missingCapacityPieces: number;
  /** Concrete suggestions for resolution */
  suggestions: string[];
}

/**
 * Complete transparency report for a scheduling run.
 * Provides industrial-grade audit trail.
 */
export interface TransparencyReport {
  /** Justifications for feasible operations */
  orderJustifications: OrderJustification[];
  /** Justifications for infeasible operations */
  failureJustifications: FailureJustification[];
  /** Capacity computation log */
  capacityLog: CapacityLogEntry[];
  /** Twin validation report (when twin references exist in data) */
  twinValidationReport?: TwinValidationReport;
  /** Workforce demand warnings per zone/shift/day (overloaded entries) */
  workforceWarnings?: ZoneShiftDemand[];
  /** D+1 workforce forecast */
  workforceForecast?: WorkforceForecast;
}

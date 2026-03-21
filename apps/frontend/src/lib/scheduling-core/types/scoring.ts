// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Scoring & Work Content Types
//  Deterministic scoring for production ordering
// ═══════════════════════════════════════════════════════════

/**
 * Work content computation for a single operation.
 * Pure capacity calculation: how much production time is needed.
 */
export interface WorkContent {
  opId: string;
  /** Total quantity to produce (backlog + sum of daily demand) */
  totalQty: number;
  /** Pieces per hour for this tool */
  pH: number;
  /** Effective OEE applied */
  oee: number;
  /** Where the OEE value came from */
  oeeSource: 'tool' | 'default';
  /** Work content in hours = totalQty / (pH * OEE) */
  workContentHours: number;
  /** Work content in minutes */
  workContentMin: number;
  /** Estimated working days required (workContentMin / DAY_CAP) */
  daysRequired: number;
}

/**
 * Deficit evolution for a single operation across the horizon.
 * Tracks stock - cumulative demand per day.
 */
export interface DeficitEvolution {
  opId: string;
  /** Daily deficit values: negative = deficit, positive = surplus */
  dailyDeficit: number[];
  /** First day where deficit occurs (-1 if never) */
  firstDeficitDay: number;
  /** Maximum deficit across horizon (positive number = worst shortfall) */
  maxDeficit: number;
  /** Initial stock (from operation stk + wip, or tool stock) */
  initialStock: number;
}

/**
 * Scored operation with composite priority for scheduling order.
 */
export interface OperationScore {
  opId: string;
  /** Slack time in minutes: time between earliest possible finish and deadline */
  slackTimeMin: number;
  /** Deficit at deadline: pieces short if not produced by deadline */
  deficitAtDeadline: number;
  /** Days until deadline from current scheduling position */
  deadlineProximityDays: number;
  /** Total work content in hours */
  workContentHours: number;
  /** Density: workContentHours / available machine-hours before deadline */
  density: number;
  /** Final composite score (higher = schedule first) */
  compositeScore: number;
  /** Human-readable justification for the score */
  justification: string;
}

/**
 * Structured capacity log entry for transparency.
 */
export interface CapacityLogEntry {
  opId: string;
  toolId: string;
  machineId: string;
  oeeValue: number;
  oeeSource: 'tool' | 'default';
  piecesPerHour: number;
  /** Available production hours per day (DAY_CAP / 60) */
  availableHoursPerDay: number;
  /** Resulting capacity in pieces per day = pH * OEE * hoursPerDay */
  resultingCapacityPcsPerDay: number;
  workContentHours: number;
  daysRequired: number;
}

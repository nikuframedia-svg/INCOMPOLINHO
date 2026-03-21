// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Failure Event Types (Avarias)
//  Temporal model for equipment failures.
//
//  A failure is an operational EVENT, not a visual attribute.
//  It has: affected resource, start, estimated end, severity,
//  impact on scheduled jobs, and cascading replanning.
// ═══════════════════════════════════════════════════════════

// ── Severity ─────────────────────────────────────────────

/** 'total' = complete stop (0%), 'partial' = reduced capacity, 'degraded' = lower OEE */
export type FailureSeverity = 'total' | 'partial' | 'degraded';

// ── Shift ID ─────────────────────────────────────────────

export type ShiftId = 'X' | 'Y' | 'Z';

// ── Core failure event ───────────────────────────────────

export interface FailureEvent {
  id: string;
  /** Type of affected resource */
  resourceType: 'machine' | 'tool';
  /** Machine or tool ID (e.g. "PRM019", "BFP079") */
  resourceId: string;
  /** Day index when failure begins */
  startDay: number;
  /** Shift when failure begins (null = start of day) */
  startShift: ShiftId | null;
  /** Day index when failure is expected to end (inclusive) */
  endDay: number;
  /** Shift when failure ends (null = end of day) */
  endShift: ShiftId | null;
  /** Severity classification */
  severity: FailureSeverity;
  /**
   * Fraction of normal capacity AVAILABLE during the failure.
   *   total:    0.0
   *   partial:  0.1 – 0.7
   *   degraded: 0.7 – 0.9
   */
  capacityFactor: number;
  /** Human-readable description (e.g. "Motor principal queimado") */
  description?: string;
}

// ── Derived per-day-per-shift status ─────────────────────

export type DayShiftStatus = 'running' | 'down' | 'partial' | 'degraded';

export interface DayShiftCapacity {
  status: DayShiftStatus;
  /** 1.0 = full capacity, 0.0 = no capacity */
  capacityFactor: number;
  /** Which failure event(s) affect this slot (traceability) */
  failureIds: string[];
}

/**
 * Per-resource timeline: indexed as [dayIndex][shift] → DayShiftCapacity.
 * Length = nDays.  Each entry covers shifts X, Y, Z.
 */
export type ResourceTimeline = Array<Record<ShiftId, DayShiftCapacity>>;

// ── Impact analysis ──────────────────────────────────────

export interface ImpactedBlock {
  opId: string;
  toolId: string;
  sku: string;
  machineId: string;
  dayIdx: number;
  shift: ShiftId;
  /** Quantity originally scheduled */
  scheduledQty: number;
  /** Quantity at risk due to failure */
  qtyAtRisk: number;
  /** Production minutes at risk */
  minutesAtRisk: number;
  /** Can this be rerouted to alt machine? */
  hasAlternative: boolean;
  altMachine: string | null;
}

export interface ImpactReport {
  /** The failure event being analysed */
  failureEvent: FailureEvent;
  /** All scheduled blocks affected by this failure */
  impactedBlocks: ImpactedBlock[];
  /** Aggregate summary */
  summary: {
    totalBlocksAffected: number;
    totalQtyAtRisk: number;
    totalMinutesAtRisk: number;
    blocksWithAlternative: number;
    blocksWithoutAlternative: number;
    /** Unique operations affected */
    opsAffected: number;
    /** Unique SKUs affected */
    skusAffected: number;
  };
  /** Day-by-day breakdown */
  dailyImpact: Array<{
    dayIdx: number;
    qtyAtRisk: number;
    minutesAtRisk: number;
    blocksAffected: number;
  }>;
}

// ── Cascading replan result ──────────────────────────────

export interface ReplanResult {
  /** Impact reports for each failure event */
  impacts: ImpactReport[];
  /** Auto-generated moves to mitigate failures */
  mitigationMoves: Array<{ opId: string; fromM: string; toM: string }>;
  /** Blocks that could NOT be rescheduled (no alternative, no capacity) */
  unrecoverableBlocks: ImpactedBlock[];
}

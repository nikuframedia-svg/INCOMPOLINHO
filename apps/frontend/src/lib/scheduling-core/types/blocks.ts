// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Block & Scheduling Output Types
//  Per Normative Spec: blocks can be 'infeasible' with a formal reason.
//  Operator pool is ADVISORY (warning only, never blocks).
// ═══════════════════════════════════════════════════════════

import type { InfeasibilityReason } from './infeasibility.js';

/** Output entry for twin co-production blocks */
export interface TwinOutput {
  opId: string;
  sku: string;
  qty: number;
}

/** Types of auto-replan strategies */
export type ReplanStrategyType =
  | 'ADVANCE_PRODUCTION'
  | 'MOVE_ALT_MACHINE'
  | 'THIRD_SHIFT'
  | 'OVERTIME'
  | 'SPLIT_OPERATION';

/** A scheduled work block — one contiguous production run on a machine */
export interface Block {
  opId: string;
  toolId: string;
  sku: string;
  nm: string;
  machineId: string;
  origM: string;
  dayIdx: number;
  /** Day index of the deadline (EDD) for this block's demand bucket */
  eddDay?: number;
  qty: number;
  prodMin: number;
  setupMin: number;
  operators: number;
  blocked: boolean;
  reason: string | null;
  moved: boolean;
  hasAlt: boolean;
  altM: string | null;
  mp?: string;
  stk: number;
  lt: number;
  atr: number;
  startMin: number;
  endMin: number;
  setupS: number | null;
  setupE: number | null;
  /** Block type: 'ok' = scheduled, 'blocked' = machine/tool down,
   *  'overflow' = capacity exceeded, 'infeasible' = hard constraint failed */
  type: 'ok' | 'blocked' | 'overflow' | 'infeasible';
  shift: 'X' | 'Y' | 'Z';
  overflow?: boolean;
  overflowMin?: number;
  belowMinBatch?: boolean;
  /** Day index from backward scheduling (Prz.Fabrico) */
  earliestStart?: number;
  /** Was this block moved by load leveling */
  isLeveled?: boolean;
  /** Was this block's production advanced ahead of original demand schedule */
  isAdvanced?: boolean;
  /** Number of working days production was advanced by */
  advancedByDays?: number;
  /** If type='infeasible', the reason why */
  infeasibilityReason?: InfeasibilityReason;
  /** If type='infeasible', human-readable detail */
  infeasibilityDetail?: string;
  /** Whether data was missing for this block (MO, setup time, etc.) */
  hasDataGap?: boolean;
  /** Description of what data is missing */
  dataGapDetail?: string;
  /** Operator capacity exceeded on this block's day/shift (warning only) */
  operatorWarning?: boolean;
  /** If blocked/degraded due to a temporal failure, the failure event ID */
  failureEventId?: string;
  /** Effective capacity factor during this block's time slot (1.0 = normal) */
  effectiveCapacityFactor?: number;
  /** Latest finish time in absolute minutes — from shipping cutoff pipeline */
  latestFinishAbs?: number;
  /** Reason why production was started at this time — from scoring pipeline */
  startReason?: import('./transparency.js').StartReason;
  /** Whether this block was created/modified by the auto-replan system */
  isSystemReplanned?: boolean;
  /** Which auto-replan strategy created this block */
  replanStrategy?: ReplanStrategyType;
  /** Decision ID linking to the DecisionRegistry entry for this replan action */
  replanDecisionId?: string;
  /** Whether this block resulted from an overtime allocation */
  isOvertime?: boolean;
  /** Overtime minutes allocated for this block */
  overtimeMin?: number;
  /** Whether this block is part of a split operation */
  isSplitPart?: boolean;
  /** Original operation's machine before split */
  splitFromMachine?: string;
  /** Whether this block is a twin co-production run (produces 2 SKUs simultaneously) */
  isTwinProduction?: boolean;
  /** Unique ID linking twin co-production blocks (canonical key: [sku1,sku2].sort().join('|')) */
  coProductionGroupId?: string;
  /** Per-SKU output breakdown for twin co-production (each SKU gets its actual demand) */
  outputs?: TwinOutput[];
  /** Freeze zone for layered replanning:
   *  'frozen' = do not move (0-5 days),
   *  'slushy' = adjust timing only (5d-2wk),
   *  'liquid' = fully reschedulable */
  freezeStatus?: 'frozen' | 'slushy' | 'liquid';
  /** True if this block is scheduled in the pre-start window (before ISOP D0) */
  preStart?: boolean;
  /** Reason for pre-start scheduling */
  preStartReason?: string;
}

/** Operation reassignment to alternative machine */
export interface MoveAction {
  opId: string;
  toM: string;
}

/** Production advancement — schedule operation earlier to resolve overflow */
export interface AdvanceAction {
  opId: string;
  /** Number of working days to advance the EDD */
  advanceDays: number;
  /** Original EDD before advancement */
  originalEdd: number;
  /** When set, only advance buckets whose pre-advance EDD matches this value */
  targetEdd?: number;
}

/** Overtime activation for a specific machine/day */
export interface OvertimeAction {
  machineId: string;
  dayIdx: number;
  /** Extra minutes beyond normal shifts */
  extraMin: number;
}

/** Split operation — part of an operation moved to another machine */
export interface SplitAction {
  opId: string;
  /** Fraction of production to move to alt machine (0.0 - 1.0) */
  fraction: number;
  /** Target machine for the split portion */
  toMachine: string;
}

/** Per-machine per-day load summary */
export interface DayLoad {
  prod: number;
  setup: number;
  ops: number;
  pcs: number;
  blk: number;
}

/** Workforce demand entry: peak concurrent operators per labor group per window */
export interface ZoneShiftDemand {
  laborGroup: string;
  shift: 'X' | 'Y' | 'Z';
  dayIdx: number;
  /** Window start minute */
  windowStart: number;
  /** Window end minute */
  windowEnd: number;
  /** Peak concurrent operator need in this group/window/day */
  peakNeed: number;
  /** Configured capacity for this group/window */
  capacity: number;
  /** Whether peak demand exceeds capacity */
  overloaded: boolean;
  /** Peak shortage: max(0, peakNeed - capacity) */
  peakShortage: number;
  /** Excess operators × window duration with blocks (people-minutes) */
  overloadPeopleMinutes: number;
  /** Total minutes within window where capacity exceeded */
  shortageMinutes: number;
}

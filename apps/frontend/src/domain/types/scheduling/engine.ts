// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Engine Internal Types
//  Used by the scheduling engine during computation
// ═══════════════════════════════════════════════════════════

import type { ResourceTimeline } from './failure.js';
import type { TwinGroup, TwinValidationReport } from './twin.js';
import type { WorkforceConfig } from './workforce.js';

/** Engine Machine — internal representation */
export interface EMachine {
  id: string;
  area: string;
  focus: boolean;
}

/** Engine Tool — internal representation with short property names */
export interface ETool {
  id: string;
  m: string; // primary machine
  alt: string; // alternative machine (or "-")
  sH: number; // setup hours
  pH: number; // pieces per hour
  op: number; // operators required
  lt: number; // lot economic quantity
  stk: number; // current stock
  mp?: string; // material part code
  nm: string; // tool name (first SKU name)
  calco?: string; // calco code for uniqueness constraint
  /** Where the setup time value came from */
  setupSource?: 'isop' | 'master' | 'default';
  /** OEE override per tool (uses DEFAULT_OEE if absent) */
  oee?: number;
}

/** Engine Operation — internal representation */
export interface EOp {
  id: string;
  t: string; // tool code
  m: string; // machine code
  sku: string;
  nm: string;
  atr: number; // backlog
  d: number[]; // daily demand quantities
  /** Prz.Fabrico: working days before delivery to START production */
  ltDays?: number;
  /** Customer code */
  cl?: string;
  /** Customer name */
  clNm?: string;
  /** Parent SKU */
  pa?: string;
  /** Per-SKU current stock (from PlanningOperation.stock) */
  stk?: number;
  /** Per-SKU WIP (from PlanningOperation.wip) */
  wip?: number;
  /** Shipping day index (last day with demand) — set by shipping cutoff pipeline */
  shippingDayIdx?: number;
  /** Shipping buffer hours for this operation — set by shipping cutoff pipeline */
  shippingBufferHours?: number;
  /** Peça Gémea SKU reference */
  twin?: string;
}

/** Per-client demand for a SKU — preserved before multi-client merge */
export interface ClientDemandEntry {
  clientCode: string;
  clientName: string;
  sku: string;
  d: number[];
}
/** Complete engine data — input for scheduling */
export interface EngineData {
  machines: EMachine[];
  tools: ETool[];
  ops: EOp[];
  dates: string[];
  dnames: string[];
  toolMap: Record<string, ETool>;
  focusIds: string[];
  workdays: boolean[];
  mo?: { PG1: number[]; PG2: number[]; poolPG1?: number[]; poolPG2?: number[] };
  nDays: number;
  thirdShift?: boolean;
  /** Per-machine temporal capacity timelines (derived from FailureEvent[]) */
  machineTimelines?: Record<string, ResourceTimeline>;
  /** Per-tool temporal capacity timelines (derived from FailureEvent[]) */
  toolTimelines?: Record<string, ResourceTimeline>;
  /**
   * Machine status map: machineId -> 'running'.
   * All machines default to 'running'. PlanState.machineStatus is deliberately
   * ignored: ISOP red cells do NOT indicate unavailability.
   * Use FailureEvent[] for explicit temporal unavailability.
   */
  mSt: Record<string, string>;
  /**
   * Tool status map: toolId -> 'running'.
   * All tools default to 'running'. PlanState.toolStatus is deliberately
   * ignored: ISOP red cells do NOT indicate unavailability.
   * Use FailureEvent[] for explicit temporal unavailability.
   */
  tSt: Record<string, string>;
  /** Validated twin groups (operationally credible pairs only) */
  twinGroups?: TwinGroup[];
  /** Twin validation report (anomalies + stats) */
  twinValidationReport?: TwinValidationReport;
  /** Workforce zone configuration (replaces MO PG1/PG2 for operator capacity) */
  workforceConfig?: WorkforceConfig;
  /** When true, op.d contains order-based demand (one order per day).
   *  Activates per-order bucketing in demand-grouper (no lot economic, no accumulation). */
  orderBased?: boolean;
  /** Number of pre-start days prepended before ISOP D0.
   *  Days 0.._preStartDays-1 are synthetic pre-production days. */
  _preStartDays?: number;
  /** Per-client demand breakdown (keyed by SKU, preserved before multi-client merge) */
  clientDemands?: Record<string, ClientDemandEntry[]>;
}

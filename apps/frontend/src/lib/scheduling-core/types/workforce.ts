// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Workforce Labor Group Configuration
//  Per-window operator capacity model (Grandes / Medias).
//
//  Time windows reflect the "turno geral" (07:00-16:00) overlap:
//    Window 1: 07:00-15:30 (turno A + turno geral)
//    Window 2: 15:30-16:00 (turno B + turno geral overlap)
//    Window 3: 16:00-00:00 (turno B only)
//
//  Pure types + defaults — no side effects.
// ═══════════════════════════════════════════════════════════

/** A time window with operator capacity */
export interface LaborWindow {
  /** Start minute from midnight */
  start: number;
  /** End minute from midnight */
  end: number;
  /** Maximum concurrent operators available in this window */
  capacity: number;
}

/** Complete workforce configuration */
export interface WorkforceConfig {
  /** Labor group definitions: laborGroupId → array of time windows */
  laborGroups: Record<string, LaborWindow[]>;
  /** Machine → labor group mapping */
  machineToLaborGroup: Record<string, string>;
}

/**
 * Default workforce configuration for Nikufra factory.
 *
 * Grandes (PRM019, PRM031, PRM039, PRM043):
 *   07:00-15:30 = 6 (5 turno A + 1 turno geral)
 *   15:30-16:00 = 6 (5 turno B + 1 turno geral overlap)
 *   16:00-00:00 = 5 (5 turno B)
 *
 * Medias (PRM042):
 *   07:00-15:30 = 9 (5 turno A + 4 turno geral)
 *   15:30-16:00 = 8 (4 turno B + 4 turno geral overlap)
 *   16:00-00:00 = 4 (4 turno B)
 */
// ── D+1 Forecast Types ────────────────────────────────────

/** Suggestion to mitigate a D+1 workforce overload */
export interface WorkforceSuggestion {
  type: 'ADVANCE_BLOCK' | 'MOVE_ALT_MACHINE' | 'REPLAN_EQUIVALENT' | 'REQUEST_REINFORCEMENT';
  description: string;
  opId?: string;
  machineId?: string;
  /** Expected reduction in peak operators */
  expectedReduction: number;
}

/** Warning for D+1 workforce overload in a specific labor group/window */
export interface WorkforceForecastWarning {
  date: string;
  dayIdx: number;
  laborGroup: string;
  shift: 'X' | 'Y';
  /** Window start minute */
  windowStart: number;
  /** Window end minute */
  windowEnd: number;
  capacity: number;
  projectedPeak: number;
  /** Excess operators (peak - capacity), always > 0 */
  excess: number;
  /** Peak shortage: max(0, peakNeed - capacity) */
  peakShortage: number;
  /** Excess operators × window duration with blocks (people-minutes) */
  overloadPeopleMinutes: number;
  /** Total minutes within window where capacity exceeded */
  shortageMinutes: number;
  causingBlocks: Array<{ opId: string; machineId: string; operators: number; sku: string }>;
  machines: string[];
  /** Overload window description */
  overloadWindow: string;
  suggestions: WorkforceSuggestion[];
}

/** Critical warning: overtime/3rd shift without configured workforce */
export interface WorkforceCoverageMissing {
  type: 'OVERTIME' | 'THIRD_SHIFT';
  machineId: string;
  dayIdx: number;
  shift: 'X' | 'Y' | 'Z';
  detail: string;
}

/** Complete D+1 workforce forecast */
export interface WorkforceForecast {
  nextWorkingDayIdx: number;
  date: string;
  warnings: WorkforceForecastWarning[];
  coverageMissing: WorkforceCoverageMissing[];
  hasWarnings: boolean;
  hasCritical: boolean;
}

// ── Defaults ──────────────────────────────────────────────

import { S0, S1, T1, TG_END } from '../constants.js';

export const DEFAULT_WORKFORCE_CONFIG: WorkforceConfig = {
  laborGroups: {
    Grandes: [
      { start: S0, end: T1, capacity: 6 }, // 07:00-15:30: 5 turno A + 1 geral
      { start: T1, end: TG_END, capacity: 6 }, // 15:30-16:00: 5 turno B + 1 geral overlap
      { start: TG_END, end: S1, capacity: 5 }, // 16:00-00:00: 5 turno B
    ],
    Medias: [
      { start: S0, end: T1, capacity: 9 }, // 07:00-15:30: 5 turno A + 4 geral
      { start: T1, end: TG_END, capacity: 8 }, // 15:30-16:00: 4 turno B + 4 geral overlap
      { start: TG_END, end: S1, capacity: 4 }, // 16:00-00:00: 4 turno B
    ],
  },
  machineToLaborGroup: {
    PRM019: 'Grandes',
    PRM031: 'Grandes',
    PRM039: 'Grandes',
    PRM043: 'Grandes',
    PRM042: 'Medias',
  },
};

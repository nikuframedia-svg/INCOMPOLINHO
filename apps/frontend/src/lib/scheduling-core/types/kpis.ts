// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — KPI & Validation Types
// ═══════════════════════════════════════════════════════════

import type { Block, MoveAction, ZoneShiftDemand } from './blocks.js';

export interface OptResult {
  score: number;
  otd: number;
  otdDelivery: number;
  produced: number;
  totalDemand: number;
  lostPcs: number;
  setupCount: number;
  setupMin: number;
  peakOps: number;
  overOps: number;
  overflows: number;
  capUtil: number;
  capVar: number;
  tardinessDays: number;
  setupByShift: { X: number; Y: number; Z: number };
  capByMachine: Record<
    string,
    {
      days: Array<{ prod: number; setup: number; pcs: number; ops: number; util: number }>;
    }
  >;
  /** Workforce demand entries per zone × shift × day */
  workforceDemand: ZoneShiftDemand[];
  moves: MoveAction[];
  blocks: Block[];
  label: string;
  /** True when schedule covers all demand with zero tardiness */
  deadlineFeasible: boolean;
}

export type ViolationSeverity = 'critical' | 'high' | 'medium' | 'low';

export interface Violation {
  id: string;
  type: string;
  severity: ViolationSeverity;
  machine: string;
  dayIdx: number;
  detail: string;
  suggestion?: string;
}

export interface ValidationReport {
  violations: Violation[];
  isValid: boolean;
  operatorPoolOk: boolean;
  constraintsClear: boolean;
}

/** Per-operation demand coverage */
export interface CoverageEntry {
  opId: string;
  toolId: string;
  sku: string;
  nm: string;
  machineId: string;
  totalDemand: number;
  produced: number;
  coveragePct: number;
  status: 'fullyCovered' | 'partiallyCovered' | 'zeroCovered' | 'noDemand';
  reason: 'ok' | 'blocked' | 'overflow' | 'rate_zero' | 'no_demand';
}

export interface CoverageAudit {
  entries: CoverageEntry[];
  summary: {
    total: number;
    fullyCovered: number;
    partiallyCovered: number;
    zeroCovered: number;
    noDemand: number;
    avgCoverage: number;
  };
}

/** Dispatch rule selection */
export type DispatchRule = 'EDD' | 'CR' | 'WSPT' | 'SPT' | 'ATCS';

/** Optimization weight profile */
export interface ObjectiveWeights {
  wTardiness: number;
  wSetupCount: number;
  wSetupTime: number;
  wSetupBalance: number;
  wChurn: number;
  wOverflow: number;
  wBelowMinBatch: number;
}

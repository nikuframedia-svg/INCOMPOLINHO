/**
 * settings-config.ts — Config readers for engine, MRP, and transform.
 *
 * These functions read from the Zustand store (non-React context)
 * and return typed config objects for consumption by scheduling/MRP logic.
 */

import type {
  DemandSemantics,
  DispatchRule,
  MOStrategy,
  ServiceLevelOption,
} from './settings-types';
import { useSettingsStore } from './useSettingsStore';

// ── Engine Config ──

export interface EngineConfig {
  S0: number;
  T1: number;
  S1: number;
  S2: number;
  OEE: number;
  DAY_CAP: number;
  BUCKET_WINDOW: number;
  MAX_EDD_GAP: number;
  ALT_UTIL_THRESHOLD: number;
  MAX_AUTO_MOVES: number;
  MAX_ITER: number;
  OTD_TOLERANCE: number;
  LOAD_BALANCE_THRESHOLD: number;
  weights: {
    tardiness: number;
    setup_count: number;
    setup_time: number;
    setup_balance: number;
    churn: number;
    overflow: number;
    below_min_batch: number;
    capacity_variance: number;
    setup_density: number;
  };
  dispatchRule: DispatchRule;
  thirdShiftDefault: boolean;
}

/** Parse HH:MM string → minutes from midnight */
function parseTime(t: string): number {
  const [h, m] = t.split(':').map(Number);
  return (h || 0) * 60 + (m || 0);
}

/**
 * Read all engine-relevant settings from the store.
 * Called from NikufraEngine (non-React context) at the start of each computation.
 */
export function getEngineConfig(): EngineConfig {
  const s = useSettingsStore.getState();
  const S0 = parseTime(s.shiftXStart);
  const T1 = parseTime(s.shiftChange);
  const S1 = parseTime(s.shiftYEnd);
  const S2 = S1 + S0;
  const OEE = s.oee;
  const DAY_CAP = S1 - S0;
  return {
    S0,
    T1,
    S1,
    S2,
    OEE,
    DAY_CAP,
    BUCKET_WINDOW: s.bucketWindowDays,
    MAX_EDD_GAP: s.maxEddGapDays,
    ALT_UTIL_THRESHOLD: s.altUtilThreshold,
    MAX_AUTO_MOVES: s.maxAutoMoves,
    MAX_ITER: s.maxOverflowIter,
    OTD_TOLERANCE: s.otdTolerance,
    LOAD_BALANCE_THRESHOLD: s.loadBalanceThreshold,
    weights: {
      tardiness: s.wTardiness,
      setup_count: s.wSetupCount,
      setup_time: s.wSetupTime,
      setup_balance: s.wSetupBalance,
      churn: s.wChurn,
      overflow: s.wOverflow,
      below_min_batch: s.wBelowMinBatch,
      capacity_variance: s.wCapacityVariance,
      setup_density: s.wSetupDensity,
    },
    dispatchRule: s.dispatchRule,
    thirdShiftDefault: s.thirdShiftDefault,
  };
}

// ── MRP Config ──

export interface MRPConfig {
  serviceLevel: ServiceLevelOption;
  coverageDays: number;
  abcA: number;
  abcB: number;
  xyzX: number;
  xyzY: number;
}

export function getMRPConfig(): MRPConfig {
  const s = useSettingsStore.getState();
  return {
    serviceLevel: s.serviceLevel,
    coverageDays: s.coverageThresholdDays,
    abcA: s.abcThresholdA,
    abcB: s.abcThresholdB,
    xyzX: s.xyzThresholdX,
    xyzY: s.xyzThresholdY,
  };
}

// ── Transform Config ──

export interface TransformConfigFromSettings {
  moStrategy: MOStrategy;
  moNominalPG1: number;
  moNominalPG2: number;
  moCustomPG1: number;
  moCustomPG2: number;
  demandSemantics: DemandSemantics;
}

export function getTransformConfig(): TransformConfigFromSettings {
  const s = useSettingsStore.getState();
  return {
    moStrategy: s.moStrategy,
    moNominalPG1: s.moNominalPG1,
    moNominalPG2: s.moNominalPG2,
    moCustomPG1: s.moCustomPG1,
    moCustomPG2: s.moCustomPG2,
    demandSemantics: s.demandSemantics,
  };
}

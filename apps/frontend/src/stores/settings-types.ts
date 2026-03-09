/**
 * settings-types.ts — Types, interfaces, and preset profiles for settings store.
 */

import type { AutoReplanConfig } from '../lib/engine';

// ── Types ──

/** MO padding strategy for horizons beyond the fixture's 8-day window */
export type MOStrategy = 'cyclic' | 'nominal' | 'custom';

/** Dispatch rule for scheduling heuristic */
export type DispatchRule = 'EDD' | 'CR' | 'WSPT' | 'SPT' | 'ATCS';

/** Optimisation preset profile */
export type OptimizationProfile = 'balanced' | 'otd' | 'setup' | 'custom';

/** MRP service level percentile */
export type ServiceLevelOption = 90 | 95 | 99;

/** Demand semantics for PlanningOperation.daily_qty interpretation */
export type DemandSemantics = 'daily' | 'cumulative_np' | 'raw_np';

// ── Preset weight profiles ──

export const WEIGHT_PROFILES: Record<
  Exclude<OptimizationProfile, 'custom'>,
  {
    wTardiness: number;
    wSetupCount: number;
    wSetupTime: number;
    wSetupBalance: number;
    wChurn: number;
    wOverflow: number;
    wBelowMinBatch: number;
    wCapacityVariance: number;
    wSetupDensity: number;
  }
> = {
  balanced: {
    wTardiness: 100,
    wSetupCount: 10,
    wSetupTime: 1.0,
    wSetupBalance: 30,
    wChurn: 5,
    wOverflow: 50,
    wBelowMinBatch: 5,
    wCapacityVariance: 20,
    wSetupDensity: 15,
  },
  otd: {
    wTardiness: 200,
    wSetupCount: 5,
    wSetupTime: 0.5,
    wSetupBalance: 10,
    wChurn: 2,
    wOverflow: 80,
    wBelowMinBatch: 2,
    wCapacityVariance: 10,
    wSetupDensity: 5,
  },
  setup: {
    wTardiness: 30,
    wSetupCount: 50,
    wSetupTime: 5,
    wSetupBalance: 40,
    wChurn: 3,
    wOverflow: 20,
    wBelowMinBatch: 1,
    wCapacityVariance: 10,
    wSetupDensity: 25,
  },
};

// ── Actions interface ──

export interface SettingsActions {
  setShifts: (xStart: string, change: string, yEnd: string) => void;
  setOEE: (v: number) => void;
  setThirdShiftDefault: (v: boolean) => void;
  setDispatchRule: (r: DispatchRule) => void;
  setBucketWindowDays: (d: number) => void;
  setMaxEddGapDays: (d: number) => void;
  setDefaultSetupHours: (h: number) => void;
  setOptimizationProfile: (p: OptimizationProfile) => void;
  setWeight: (key: string, val: number) => void;
  setMOStrategy: (strategy: MOStrategy) => void;
  setMONominal: (pg1: number, pg2: number) => void;
  setMOCustom: (pg1: number, pg2: number) => void;
  setAltUtilThreshold: (v: number) => void;
  setMaxAutoMoves: (v: number) => void;
  setMaxOverflowIter: (v: number) => void;
  setOTDTolerance: (v: number) => void;
  setLoadBalanceThreshold: (v: number) => void;
  setEnableAutoReplan: (v: boolean) => void;
  setEnableShippingCutoff: (v: boolean) => void;
  setAutoReplanConfig: (cfg: Partial<AutoReplanConfig>) => void;
  setDemandSemantics: (v: DemandSemantics) => void;
  setServiceLevel: (v: ServiceLevelOption) => void;
  setCoverageThresholdDays: (v: number) => void;
  setABCThresholds: (a: number, b: number) => void;
  setXYZThresholds: (x: number, y: number) => void;
}

// ── State interface ──

export interface SettingsState {
  shiftXStart: string;
  shiftChange: string;
  shiftYEnd: string;
  oee: number;
  thirdShiftDefault: boolean;
  dispatchRule: DispatchRule;
  bucketWindowDays: number;
  maxEddGapDays: number;
  defaultSetupHours: number;
  optimizationProfile: OptimizationProfile;
  wTardiness: number;
  wSetupCount: number;
  wSetupTime: number;
  wSetupBalance: number;
  wChurn: number;
  wOverflow: number;
  wBelowMinBatch: number;
  wCapacityVariance: number;
  wSetupDensity: number;
  moStrategy: MOStrategy;
  moNominalPG1: number;
  moNominalPG2: number;
  moCustomPG1: number;
  moCustomPG2: number;
  altUtilThreshold: number;
  maxAutoMoves: number;
  maxOverflowIter: number;
  otdTolerance: number;
  loadBalanceThreshold: number;
  enableAutoReplan: boolean;
  enableShippingCutoff: boolean;
  autoReplanConfig: Partial<AutoReplanConfig>;
  demandSemantics: DemandSemantics;
  serviceLevel: ServiceLevelOption;
  coverageThresholdDays: number;
  abcThresholdA: number;
  abcThresholdB: number;
  xyzThresholdX: number;
  xyzThresholdY: number;
  actions: SettingsActions;
}

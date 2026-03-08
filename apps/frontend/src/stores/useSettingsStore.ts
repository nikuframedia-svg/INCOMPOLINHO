/**
 * useSettingsStore — Persisted scheduling & system settings.
 *
 * Stores user preferences that affect how NikufraEngine, MRP engine,
 * and supply priority compute schedules and analytics.
 *
 * Organised in 6 logical sections:
 *  §1 Turnos & Capacidade — shift times, OEE, 3rd shift
 *  §2 Regras de Planeamento — dispatch rule, bucket window, EDD gap, default setup
 *  §3 Perfil de Optimização — 7 score weights + 3 presets
 *  §4 Capacidade de Operadores (M.O.) — strategy, PG1/PG2 nominal/custom
 *  §5 Overflow & Routing — alt threshold, max moves, iterations, OTD tolerance, load balance
 *  §6 MRP & Supply — service level, coverage, ABC/XYZ thresholds
 *
 * Persisted via localStorage ('pp1-settings') so settings survive page reloads.
 * All setters call invalidateScheduleCache() to trigger recomputation.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { invalidateScheduleCache } from '../hooks/useScheduleData';
import type { AutoReplanConfig } from '../lib/engine';

// ── Types ──────────────────────────────────────────────────────

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

// ── Preset weight profiles ─────────────────────────────────────

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

// ── Actions interface ─────────────────────────────────────────

export interface SettingsActions {
  // §1
  setShifts: (xStart: string, change: string, yEnd: string) => void;
  setOEE: (v: number) => void;
  setThirdShiftDefault: (v: boolean) => void;
  // §2
  setDispatchRule: (r: DispatchRule) => void;
  setBucketWindowDays: (d: number) => void;
  setMaxEddGapDays: (d: number) => void;
  setDefaultSetupHours: (h: number) => void;
  // §3
  setOptimizationProfile: (p: OptimizationProfile) => void;
  setWeight: (key: string, val: number) => void;
  // §4
  setMOStrategy: (strategy: MOStrategy) => void;
  setMONominal: (pg1: number, pg2: number) => void;
  setMOCustom: (pg1: number, pg2: number) => void;
  // §5
  setAltUtilThreshold: (v: number) => void;
  setMaxAutoMoves: (v: number) => void;
  setMaxOverflowIter: (v: number) => void;
  setOTDTolerance: (v: number) => void;
  setLoadBalanceThreshold: (v: number) => void;
  // §5b
  setEnableAutoReplan: (v: boolean) => void;
  setEnableShippingCutoff: (v: boolean) => void;
  setAutoReplanConfig: (cfg: Partial<AutoReplanConfig>) => void;
  setDemandSemantics: (v: DemandSemantics) => void;
  // §6
  setServiceLevel: (v: ServiceLevelOption) => void;
  setCoverageThresholdDays: (v: number) => void;
  setABCThresholds: (a: number, b: number) => void;
  setXYZThresholds: (x: number, y: number) => void;
}

// ── State interface ───────────────────────────────────────────

interface SettingsState {
  // ── §1 Turnos & Capacidade ──
  shiftXStart: string;
  shiftChange: string;
  shiftYEnd: string;
  oee: number;
  thirdShiftDefault: boolean;

  // ── §2 Regras de Planeamento ──
  dispatchRule: DispatchRule;
  bucketWindowDays: number;
  maxEddGapDays: number;
  defaultSetupHours: number;

  // ── §3 Perfil de Optimização ──
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

  // ── §4 Capacidade de Operadores — M.O. ──
  moStrategy: MOStrategy;
  moNominalPG1: number;
  moNominalPG2: number;
  moCustomPG1: number;
  moCustomPG2: number;

  // ── §5 Overflow & Routing ──
  altUtilThreshold: number;
  maxAutoMoves: number;
  maxOverflowIter: number;
  otdTolerance: number;
  loadBalanceThreshold: number;

  // ── §5b Auto-Replan & Pipeline ──
  enableAutoReplan: boolean;
  enableShippingCutoff: boolean;
  autoReplanConfig: Partial<AutoReplanConfig>;
  demandSemantics: DemandSemantics;

  // ── §6 MRP & Supply ──
  serviceLevel: ServiceLevelOption;
  coverageThresholdDays: number;
  abcThresholdA: number;
  abcThresholdB: number;
  xyzThresholdX: number;
  xyzThresholdY: number;

  // ── Actions ──
  actions: SettingsActions;
}

// ── Store ──────────────────────────────────────────────────────

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      // ── §1 Defaults ──
      shiftXStart: '07:00',
      shiftChange: '15:30',
      shiftYEnd: '24:00',
      oee: 0.66,
      thirdShiftDefault: false,

      // ── §2 Defaults ──
      dispatchRule: 'EDD',
      bucketWindowDays: 5,
      maxEddGapDays: 5,
      defaultSetupHours: 0.75,

      // ── §3 Defaults (balanced profile) ──
      optimizationProfile: 'balanced',
      wTardiness: 100,
      wSetupCount: 10,
      wSetupTime: 1.0,
      wSetupBalance: 30,
      wChurn: 5,
      wOverflow: 50,
      wBelowMinBatch: 5,
      wCapacityVariance: 20,
      wSetupDensity: 15,

      // ── §4 Defaults ──
      moStrategy: 'nominal',
      moNominalPG1: 3,
      moNominalPG2: 4,
      moCustomPG1: 3,
      moCustomPG2: 4,

      // ── §5 Defaults ──
      altUtilThreshold: 0.95,
      maxAutoMoves: 50,
      maxOverflowIter: 3,
      otdTolerance: 1.0,
      loadBalanceThreshold: 0.15,

      // ── §5b Defaults ──
      enableAutoReplan: false,
      enableShippingCutoff: false,
      autoReplanConfig: {},
      demandSemantics: 'raw_np' as DemandSemantics,

      // ── §6 Defaults ──
      serviceLevel: 95,
      coverageThresholdDays: 3,
      abcThresholdA: 0.8,
      abcThresholdB: 0.95,
      xyzThresholdX: 0.5,
      xyzThresholdY: 1.0,

      // ── Actions ──
      actions: {
        // §1
        setShifts: (xStart, change, yEnd) => {
          set({ shiftXStart: xStart, shiftChange: change, shiftYEnd: yEnd });
          invalidateScheduleCache();
        },
        setOEE: (v) => {
          set({ oee: v });
          invalidateScheduleCache();
        },
        setThirdShiftDefault: (v) => {
          set({ thirdShiftDefault: v });
          invalidateScheduleCache();
        },

        // §2
        setDispatchRule: (r) => {
          set({ dispatchRule: r });
          invalidateScheduleCache();
        },
        setBucketWindowDays: (d) => {
          set({ bucketWindowDays: d });
          invalidateScheduleCache();
        },
        setMaxEddGapDays: (d) => {
          set({ maxEddGapDays: d });
          invalidateScheduleCache();
        },
        setDefaultSetupHours: (h) => {
          set({ defaultSetupHours: h });
          invalidateScheduleCache();
        },

        // §3
        setOptimizationProfile: (p) => {
          if (p !== 'custom') {
            const w = WEIGHT_PROFILES[p];
            set({
              optimizationProfile: p,
              wTardiness: w.wTardiness,
              wSetupCount: w.wSetupCount,
              wSetupTime: w.wSetupTime,
              wSetupBalance: w.wSetupBalance,
              wChurn: w.wChurn,
              wOverflow: w.wOverflow,
              wBelowMinBatch: w.wBelowMinBatch,
              wCapacityVariance: w.wCapacityVariance,
              wSetupDensity: w.wSetupDensity,
            });
          } else {
            set({ optimizationProfile: 'custom' });
          }
          invalidateScheduleCache();
        },
        setWeight: (key, val) => {
          const valid = [
            'wTardiness',
            'wSetupCount',
            'wSetupTime',
            'wSetupBalance',
            'wChurn',
            'wOverflow',
            'wBelowMinBatch',
            'wCapacityVariance',
            'wSetupDensity',
          ];
          if (valid.includes(key)) {
            set({ [key]: val, optimizationProfile: 'custom' } as Partial<SettingsState>);
            invalidateScheduleCache();
          }
        },

        // §4
        setMOStrategy: (strategy) => {
          set({ moStrategy: strategy });
          invalidateScheduleCache();
        },
        setMONominal: (pg1, pg2) => {
          set({ moNominalPG1: pg1, moNominalPG2: pg2 });
          invalidateScheduleCache();
        },
        setMOCustom: (pg1, pg2) => {
          set({ moCustomPG1: pg1, moCustomPG2: pg2 });
          invalidateScheduleCache();
        },

        // §5
        setAltUtilThreshold: (v) => {
          set({ altUtilThreshold: v });
          invalidateScheduleCache();
        },
        setMaxAutoMoves: (v) => {
          set({ maxAutoMoves: v });
          invalidateScheduleCache();
        },
        setMaxOverflowIter: (v) => {
          set({ maxOverflowIter: v });
          invalidateScheduleCache();
        },
        setOTDTolerance: (v) => {
          set({ otdTolerance: v });
          invalidateScheduleCache();
        },
        setLoadBalanceThreshold: (v) => {
          set({ loadBalanceThreshold: v });
          invalidateScheduleCache();
        },

        // §5b
        setEnableAutoReplan: (v) => {
          set({ enableAutoReplan: v });
          invalidateScheduleCache();
        },
        setEnableShippingCutoff: (v) => {
          set({ enableShippingCutoff: v });
          invalidateScheduleCache();
        },
        setAutoReplanConfig: (cfg) => {
          set({ autoReplanConfig: cfg });
          invalidateScheduleCache();
        },
        setDemandSemantics: (v) => {
          set({ demandSemantics: v });
          invalidateScheduleCache();
        },

        // §6
        setServiceLevel: (v) => {
          set({ serviceLevel: v });
          invalidateScheduleCache();
        },
        setCoverageThresholdDays: (v) => {
          set({ coverageThresholdDays: v });
          invalidateScheduleCache();
        },
        setABCThresholds: (a, b) => {
          set({ abcThresholdA: a, abcThresholdB: b });
          invalidateScheduleCache();
        },
        setXYZThresholds: (x, y) => {
          set({ xyzThresholdX: x, xyzThresholdY: y });
          invalidateScheduleCache();
        },
      },
    }),
    {
      name: 'pp1-settings',
      partialize: ({ actions: _, ...data }) => data,
    },
  ),
);

// ── Atomic selector hooks ─────────────────────────────────────

export const useSettingsActions = () => useSettingsStore((s) => s.actions);
export const useDemandSemantics = () => useSettingsStore((s) => s.demandSemantics);
export const useThirdShiftDefault = () => useSettingsStore((s) => s.thirdShiftDefault);

// ── Helper: read engine config from store (for non-React callers) ──

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

/** Read MRP-relevant settings from the store */
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

/** Read transform config for INCOMPOL PLAN's transformPlanState() */
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

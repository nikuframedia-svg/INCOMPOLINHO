/**
 * useSettingsStore — Persisted scheduling & system settings.
 *
 * Stores user preferences that affect how NikufraEngine, MRP engine,
 * and supply priority compute schedules and analytics.
 *
 * Persisted via localStorage ('pp1-settings') so settings survive page reloads.
 * All setters call invalidateScheduleCache() to trigger recomputation.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { invalidateScheduleCache } from '../hooks/useScheduleData';
import type { DemandSemantics, SettingsState } from './settings-types';
import { WEIGHT_PROFILES } from './settings-types';

export type { EngineConfig, MRPConfig, TransformConfigFromSettings } from './settings-config';
export { getEngineConfig, getMRPConfig, getTransformConfig } from './settings-config';
// Re-export types and config for backward compatibility
export type {
  DemandSemantics,
  DispatchRule,
  MOStrategy,
  OptimizationProfile,
  ServiceLevelOption,
  SettingsActions,
  SettingsState,
} from './settings-types';
export { WEIGHT_PROFILES } from './settings-types';

// ── Store ──

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

// ── Atomic selector hooks ──

export const useSettingsActions = () => useSettingsStore((s) => s.actions);
export const useDemandSemantics = () => useSettingsStore((s) => s.demandSemantics);
export const useThirdShiftDefault = () => useSettingsStore((s) => s.thirdShiftDefault);

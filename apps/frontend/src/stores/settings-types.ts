/**
 * settings-types.ts — Types, interfaces, and preset profiles for settings store.
 */

import type { RuleGroupType } from 'react-querybuilder';
import type { AutoReplanConfig } from '@/domain/types/scheduling';

// ── Types ──

/** MO padding strategy for horizons beyond the fixture's 8-day window */
export type MOStrategy = 'cyclic' | 'nominal' | 'custom';

/** Dispatch rule for scheduling heuristic. AUTO delegates to UCB1 bandit. */
export type DispatchRule = 'EDD' | 'CR' | 'WSPT' | 'SPT' | 'ATCS' | 'AUTO';

/** Optimisation preset profile */
export type OptimizationProfile = 'balanced' | 'otd' | 'setup' | 'custom';

/** MRP service level percentile */
export type ServiceLevelOption = 90 | 95 | 99;

/** Demand semantics for PlanningOperation.daily_qty interpretation */
export type DemandSemantics = 'daily' | 'cumulative_np' | 'raw_np';

/** Server solver objective */
export type SolverObjective = 'weighted_tardiness' | 'makespan' | 'tardiness';

/** Pre-start buffer strategy */
export type PreStartStrategy = 'auto' | 'manual';

// ── L4: Concept Definitions ──

export interface ConceptDefinition {
  id: string;
  question: string;
  label: string;
  expression: string;
  variables: string[];
  version: number;
  versions: Array<{ v: number; ts: string; expression: string }>;
}

// ── L3: Custom Formulas ──

export interface FormulaConfig {
  id: string;
  label: string;
  description: string;
  expression: string;
  variables: string[];
  version: number;
  versions: Array<{ v: number; ts: string; expression: string }>;
}

// ── L2: Rules ──

export type RuleActionType =
  | 'set_priority'
  | 'boost_priority'
  | 'flag_night_shift'
  | 'alert'
  | 'require_approval'
  | 'block';

export interface RuleAction {
  type: RuleActionType;
  value: string | number;
}

export interface RuleConfig {
  id: string;
  name: string;
  active: boolean;
  query: RuleGroupType;
  action: RuleAction;
  version: number;
  versions: Array<{ v: number; ts: string; query: RuleGroupType; action: RuleAction }>;
}

// ── Configurable Logic (L2+L3+L4) ──

export interface ConfigurableLogic {
  definitions: ConceptDefinition[];
  formulas: FormulaConfig[];
  rules: RuleConfig[];
}

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
  setUseServerSolver: (v: boolean) => void;
  setUsePythonScheduler: (v: boolean) => void;
  setServerSolverTimeLimit: (v: number) => void;
  setServerSolverObjective: (v: SolverObjective) => void;
  setPreStartBufferDays: (v: number) => void;
  setPreStartStrategy: (v: PreStartStrategy) => void;
  setClientTier: (code: string, tier: number) => void;
  // L2/L3/L4 configurable logic
  updateDefinition: (updated: ConceptDefinition) => void;
  updateFormula: (updated: FormulaConfig) => void;
  updateRule: (updated: RuleConfig) => void;
  addRule: (rule: RuleConfig) => void;
  deleteRule: (id: string) => void;
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
  useServerSolver: boolean;
  usePythonScheduler: boolean;
  serverSolverTimeLimit: number;
  serverSolverObjective: SolverObjective;
  preStartBufferDays: number;
  preStartStrategy: PreStartStrategy;
  /** Client priority tiers: client code → 1-5 (1=highest priority). Default 3. */
  clientTiers: Record<string, number>;
  // L2/L3/L4 configurable logic
  definitions: ConceptDefinition[];
  formulas: FormulaConfig[];
  rules: RuleConfig[];
  actions: SettingsActions;
}

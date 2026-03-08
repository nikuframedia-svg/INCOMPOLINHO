/**
 * useConfigPreview — Manages preview state for scheduling config changes.
 *
 * Holds candidate weights, policy, constraints, and comparison KPIs.
 * Scenarios are saved configurations with their KPI snapshots.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// ── Types ──

export type PolicyId = 'max_otd' | 'min_setups' | 'balanced' | 'urgent' | 'custom';

export interface ConfigWeights {
  otd: number;
  setup: number;
  utilization: number;
}

export interface ConfigConstraints {
  setupCrew: boolean;
  toolTimeline: boolean;
  calcoTimeline: boolean;
  operatorPool: boolean;
}

export interface KPISnapshot {
  otdPct: number;
  avgTardinessDays: number;
  totalSetupMin: number;
  utilizationPct: number;
  overflowCount: number;
}

export interface SavedScenario {
  id: string;
  name: string;
  createdAt: string;
  weights: ConfigWeights;
  policy: PolicyId;
  frozenHorizonDays: number;
  lotMode: 'strict' | 'relaxed';
  constraints: ConfigConstraints;
  kpis: KPISnapshot;
}

// ── State ──

interface ConfigPreviewState {
  // Current editing state
  weights: ConfigWeights;
  policy: PolicyId;
  frozenHorizonDays: number;
  lotMode: 'strict' | 'relaxed';
  constraints: ConfigConstraints;

  // Preview KPIs (null = not yet computed)
  previewKpis: KPISnapshot | null;
  isComputing: boolean;

  // Saved scenarios
  scenarios: SavedScenario[];
  selectedScenarioId: string | null;

  // Actions
  setWeights: (w: ConfigWeights) => void;
  setWeight: (key: keyof ConfigWeights, val: number) => void;
  setPolicy: (p: PolicyId) => void;
  setFrozenHorizonDays: (d: number) => void;
  setLotMode: (m: 'strict' | 'relaxed') => void;
  setConstraint: (key: keyof ConfigConstraints, val: boolean) => void;
  setPreviewKpis: (kpis: KPISnapshot | null) => void;
  setIsComputing: (v: boolean) => void;
  saveScenario: (name: string, kpis: KPISnapshot) => void;
  deleteScenario: (id: string) => void;
  selectScenario: (id: string | null) => void;
  loadScenario: (id: string) => void;
  resetToDefaults: () => void;
}

// ── Policy weight presets ──

export const POLICY_WEIGHTS: Record<Exclude<PolicyId, 'custom'>, ConfigWeights> = {
  max_otd: { otd: 90, setup: 5, utilization: 5 },
  min_setups: { otd: 30, setup: 60, utilization: 10 },
  balanced: { otd: 50, setup: 30, utilization: 20 },
  urgent: { otd: 80, setup: 10, utilization: 10 },
};

const DEFAULT_WEIGHTS: ConfigWeights = { otd: 70, setup: 20, utilization: 10 };
const DEFAULT_CONSTRAINTS: ConfigConstraints = {
  setupCrew: true,
  toolTimeline: true,
  calcoTimeline: true,
  operatorPool: true,
};

let nextId = 1;

export const useConfigPreview = create<ConfigPreviewState>()(
  persist(
    (set, get) => ({
      weights: { ...DEFAULT_WEIGHTS },
      policy: 'balanced',
      frozenHorizonDays: 5,
      lotMode: 'relaxed' as const,
      constraints: { ...DEFAULT_CONSTRAINTS },
      previewKpis: null,
      isComputing: false,
      scenarios: [],
      selectedScenarioId: null,

      setWeights: (w) => set({ weights: w, policy: 'custom', previewKpis: null }),
      setWeight: (key, val) => {
        const current = get().weights;
        set({ weights: { ...current, [key]: val }, policy: 'custom', previewKpis: null });
      },
      setPolicy: (p) => {
        if (p === 'custom') {
          set({ policy: 'custom' });
        } else {
          set({ weights: { ...POLICY_WEIGHTS[p] }, policy: p, previewKpis: null });
        }
      },
      setFrozenHorizonDays: (d) => set({ frozenHorizonDays: d, previewKpis: null }),
      setLotMode: (m) => set({ lotMode: m, previewKpis: null }),
      setConstraint: (key, val) => {
        const current = get().constraints;
        set({ constraints: { ...current, [key]: val }, previewKpis: null });
      },
      setPreviewKpis: (kpis) => set({ previewKpis: kpis }),
      setIsComputing: (v) => set({ isComputing: v }),
      saveScenario: (name, kpis) => {
        const state = get();
        const scenario: SavedScenario = {
          id: `sc_${Date.now()}_${nextId++}`,
          name,
          createdAt: new Date().toISOString(),
          weights: { ...state.weights },
          policy: state.policy,
          frozenHorizonDays: state.frozenHorizonDays,
          lotMode: state.lotMode,
          constraints: { ...state.constraints },
          kpis,
        };
        set({ scenarios: [...state.scenarios, scenario] });
      },
      deleteScenario: (id) => {
        set((s) => ({
          scenarios: s.scenarios.filter((sc) => sc.id !== id),
          selectedScenarioId: s.selectedScenarioId === id ? null : s.selectedScenarioId,
        }));
      },
      selectScenario: (id) => set({ selectedScenarioId: id }),
      loadScenario: (id) => {
        const sc = get().scenarios.find((s) => s.id === id);
        if (!sc) return;
        set({
          weights: { ...sc.weights },
          policy: sc.policy,
          frozenHorizonDays: sc.frozenHorizonDays,
          lotMode: sc.lotMode,
          constraints: { ...sc.constraints },
          previewKpis: null,
        });
      },
      resetToDefaults: () =>
        set({
          weights: { ...DEFAULT_WEIGHTS },
          policy: 'balanced',
          frozenHorizonDays: 5,
          lotMode: 'relaxed',
          constraints: { ...DEFAULT_CONSTRAINTS },
          previewKpis: null,
        }),
    }),
    {
      name: 'pp1-config-preview',
      partialize: ({ isComputing: _, previewKpis: _p, ...data }) => data,
    },
  ),
);

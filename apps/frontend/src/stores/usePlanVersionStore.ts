// ═══════════════════════════════════════════════════════════
//  Plan Version Store — Versioned plan persistence (WS2)
//  Zustand + persist middleware · localStorage-backed
// ═══════════════════════════════════════════════════════════

import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

// Re-use engine types via import — these are exported from NikufraEngine
import type { Block, Decision, MoveAction, OptResult } from '../lib/engine';

export interface PlanVersionKPIs {
  otd: number;
  otdDelivery: number;
  setupCount: number;
  setupMin: number;
  tardinessDays: number;
  capUtil: number;
}

export interface PlanVersionParams {
  machineStatus: Record<string, string>;
  toolStatus: Record<string, string>;
  areaCaps: { PG1: number; PG2: number };
  moves: MoveAction[];
  seed: number;
}

export interface PlanVersion {
  id: string;
  timestamp: string;
  label: string;
  blocks: Block[];
  decisions: Decision[];
  score: number;
  kpis: PlanVersionKPIs;
  params: PlanVersionParams;
  parentId: string | null;
  branchLabel?: string;
  isFavorite?: boolean;
}

export interface PlanVersionActions {
  init: (hash: string) => void;
  savePlan: (
    result: OptResult,
    decisions: Decision[],
    params: PlanVersionParams,
    label: string,
  ) => string;
  commitPlan: (id: string) => void;
  getBaseline: () => PlanVersion | null;
  getCurrent: () => PlanVersion | null;
  getVersion: (id: string) => PlanVersion | null;
  listVersions: () => PlanVersion[];
  setBranchLabel: (id: string, branchLabel: string) => void;
  setFavorite: (id: string, isFavorite: boolean) => void;
  clear: () => void;
}

function generateId(): string {
  const arr = new Uint8Array(8);
  crypto.getRandomValues(arr);
  return Array.from(arr, (b) => b.toString(16).padStart(2, '0')).join('');
}

interface PlanVersionState {
  versions: PlanVersion[];
  currentId: string | null;
  baselineId: string | null;
  snapshotHash: string | null;
  actions: PlanVersionActions;
}

export const usePlanVersionStore = create<PlanVersionState>()(
  persist(
    (set, get) => ({
      versions: [],
      currentId: null,
      baselineId: null,
      snapshotHash: null,

      actions: {
        init: (hash: string) => {
          const state = get();
          if (state.snapshotHash === hash) return;
          set({
            versions: [],
            currentId: null,
            baselineId: null,
            snapshotHash: hash,
          });
        },

        savePlan: (result, decisions, params, label) => {
          const id = generateId();
          const state = get();
          const version: PlanVersion = {
            id,
            timestamp: new Date().toISOString(),
            label,
            blocks: result.blocks,
            decisions,
            score: result.score,
            kpis: {
              otd: result.otd,
              otdDelivery: result.otdDelivery,
              setupCount: result.setupCount,
              setupMin: result.setupMin,
              tardinessDays: result.tardinessDays,
              capUtil: result.capUtil,
            },
            params,
            parentId: state.currentId,
          };
          const updated = [...state.versions, version];
          const trimmed = updated.length > 20 ? updated.slice(-20) : updated;
          set({ versions: trimmed });

          if (!state.baselineId) {
            set({ baselineId: id });
          }

          return id;
        },

        commitPlan: (id: string) => {
          const state = get();
          const exists = state.versions.find((v) => v.id === id);
          if (!exists) return;
          set({ currentId: id });
        },

        getBaseline: () => {
          const state = get();
          if (!state.baselineId) return null;
          return state.versions.find((v) => v.id === state.baselineId) ?? null;
        },

        getCurrent: () => {
          const state = get();
          if (!state.currentId) return null;
          return state.versions.find((v) => v.id === state.currentId) ?? null;
        },

        getVersion: (id: string) => {
          return get().versions.find((v) => v.id === id) ?? null;
        },

        listVersions: () => {
          return get().versions;
        },

        setBranchLabel: (id: string, branchLabel: string) => {
          set({
            versions: get().versions.map((v) =>
              v.id === id ? { ...v, branchLabel: branchLabel || undefined } : v,
            ),
          });
        },

        setFavorite: (id: string, isFavorite: boolean) => {
          set({
            versions: get().versions.map((v) => (v.id === id ? { ...v, isFavorite } : v)),
          });
        },

        clear: () => {
          set({ versions: [], currentId: null, baselineId: null });
        },
      },
    }),
    {
      name: 'pp1-plan-versions',
      storage: createJSONStorage(() => localStorage),
      partialize: ({ actions: _, ...data }) => data,
    },
  ),
);

// ── Atomic selector hooks ─────────────────────────────────────

export const usePlanVersions = () => usePlanVersionStore((s) => s.versions);
export const useCurrentPlanId = () => usePlanVersionStore((s) => s.currentId);
export const usePlanVersionActions = () => usePlanVersionStore((s) => s.actions);

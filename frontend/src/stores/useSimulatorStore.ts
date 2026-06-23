import { create } from "zustand";
import type { MutationInput, SimulateResponse, CTPResult } from "../api/types";

interface SimulatorState {
  mutations: (MutationInput & { _key: number })[];
  result: SimulateResponse | null;
  ctpResult: CTPResult | null;
  nextKey: number;

  setMutations: (m: (MutationInput & { _key: number })[]) => void;
  setResult: (r: SimulateResponse | null) => void;
  setCtpResult: (r: CTPResult | null) => void;
  addMutation: () => void;
  removeMutation: (key: number) => void;
  updateMutationType: (key: number, type: string) => void;
  updateMutationParam: (key: number, paramKey: string, value: string) => void;
  clear: () => void;
}

export const useSimulatorStore = create<SimulatorState>((set, get) => ({
  mutations: [],
  result: null,
  ctpResult: null,
  nextKey: 0,

  setMutations: (m) => set({ mutations: m, nextKey: m.length ? Math.max(...m.map((x) => x._key)) + 1 : 0 }),
  setResult: (r) => set({ result: r }),
  setCtpResult: (r) => set({ ctpResult: r }),

  addMutation: () => {
    const { mutations, nextKey } = get();
    set({
      mutations: [...mutations, { type: "", params: {}, _key: nextKey }],
      nextKey: nextKey + 1,
    });
  },

  removeMutation: (key) => set((s) => ({
    mutations: s.mutations.filter((m) => m._key !== key),
  })),

  updateMutationType: (key, type) => set((s) => ({
    mutations: s.mutations.map((m) => m._key === key ? { ...m, type, params: {} } : m),
  })),

  updateMutationParam: (key, paramKey, value) => set((s) => ({
    mutations: s.mutations.map((m) =>
      m._key === key ? { ...m, params: { ...m.params, [paramKey]: value } } : m,
    ),
  })),

  clear: () => set({ mutations: [], result: null, ctpResult: null, nextKey: 0 }),
}));

import { create } from "zustand";
import type { MutationInput, SimulateResponse, CTPResult, CTPRequest } from "../api/types";

interface SimulatorState {
  mutations: (MutationInput & { _key: number })[];
  result: SimulateResponse | null;
  resultMutations: MutationInput[] | null;
  ctpResult: CTPResult | null;
  ctpRequest: CTPRequest | null;
  ctpInput: { sku: string; qty: string; deadline: string };
  generation: number;
  ctpGeneration: number;
  nextKey: number;

  setMutations: (m: (MutationInput & { _key: number })[]) => void;
  setResult: (r: SimulateResponse | null) => void;
  setCtpResult: (r: CTPResult | null) => void;
  setCtpInput: (field: "sku" | "qty" | "deadline", value: string) => void;
  beginSimulation: () => number;
  acceptSimulation: (generation: number, result: SimulateResponse, mutations: MutationInput[]) => boolean;
  beginCtp: () => number;
  acceptCtp: (generation: number, result: CTPResult, request: CTPRequest) => boolean;
  cancelRequests: () => void;
  invalidatePreviews: () => void;
  addMutation: () => void;
  removeMutation: (key: number) => void;
  updateMutationType: (key: number, type: string) => void;
  updateMutationParam: (key: number, paramKey: string, value: string) => void;
  clear: () => void;
}

export const useSimulatorStore = create<SimulatorState>((set, get) => ({
  mutations: [],
  result: null,
  resultMutations: null,
  ctpResult: null,
  ctpRequest: null,
  ctpInput: { sku: "", qty: "", deadline: "" },
  generation: 0,
  ctpGeneration: 0,
  nextKey: 0,

  setMutations: (m) => set((s) => ({ mutations: m, result: null, resultMutations: null, generation: s.generation + 1 })),
  setResult: (r) => set((s) => ({ result: r, resultMutations: null, generation: s.generation + 1 })),
  setCtpResult: (r) => set((s) => ({ ctpResult: r, ctpRequest: null, ctpGeneration: s.ctpGeneration + 1 })),
  setCtpInput: (field, value) => set((s) => ({
    ctpInput: { ...s.ctpInput, [field]: value },
    ctpResult: null, ctpRequest: null, ctpGeneration: s.ctpGeneration + 1,
  })),
  beginSimulation: () => {
    const generation = get().generation + 1;
    set({ generation, result: null, resultMutations: null });
    return generation;
  },
  acceptSimulation: (generation, result, mutations) => {
    if (generation !== get().generation) return false;
    set({ result, resultMutations: mutations });
    return true;
  },
  beginCtp: () => {
    const generation = get().ctpGeneration + 1;
    set({ ctpGeneration: generation, ctpResult: null, ctpRequest: null });
    return generation;
  },
  acceptCtp: (generation, ctpResult, ctpRequest) => {
    if (generation !== get().ctpGeneration) return false;
    set({ ctpResult, ctpRequest });
    return true;
  },
  cancelRequests: () => set((s) => ({ generation: s.generation + 1, ctpGeneration: s.ctpGeneration + 1 })),
  invalidatePreviews: () => set((s) => ({
    result: null, resultMutations: null, ctpResult: null, ctpRequest: null,
    generation: s.generation + 1, ctpGeneration: s.ctpGeneration + 1,
  })),

  addMutation: () => {
    const { mutations, nextKey } = get();
    set({
      mutations: [...mutations, { type: "", params: {}, _key: nextKey }],
      nextKey: nextKey + 1,
      result: null,
      resultMutations: null,
      generation: get().generation + 1,
    });
  },

  removeMutation: (key) => set((s) => ({
    mutations: s.mutations.filter((m) => m._key !== key),
    result: null,
    resultMutations: null,
    generation: s.generation + 1,
  })),

  updateMutationType: (key, type) => set((s) => ({
    mutations: s.mutations.map((m) => m._key === key ? { ...m, type, params: {} } : m),
    result: null,
    resultMutations: null,
    generation: s.generation + 1,
  })),

  updateMutationParam: (key, paramKey, value) => set((s) => ({
    mutations: s.mutations.map((m) =>
      m._key === key ? { ...m, params: { ...m.params, [paramKey]: value } } : m,
    ),
    result: null,
    resultMutations: null,
    generation: s.generation + 1,
  })),

  clear: () => set((s) => ({
    mutations: [], result: null, resultMutations: null, ctpResult: null, ctpRequest: null,
    ctpInput: { sku: "", qty: "", deadline: "" }, nextKey: 0,
    generation: s.generation + 1, ctpGeneration: s.ctpGeneration + 1,
  })),
}));

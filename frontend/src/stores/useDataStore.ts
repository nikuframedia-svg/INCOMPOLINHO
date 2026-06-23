import { create } from "zustand";
import { getScore, getSegments, getLots, getConfig, getLearning, simulateApply, revertSimulation, revertConfig, canRevert as fetchCanRevert, getActiveMutations } from "../api/endpoints";
import type { Score, Segment, Lot, FactoryConfig, LearningInfo, MutationInput, RevertKind, SimulateApplyResponse } from "../api/types";

interface DataState {
  score: Score | null;
  segments: Segment[] | null;
  lots: Lot[] | null;
  config: FactoryConfig | null;
  learning: LearningInfo | null;

  // Simulation state
  isSimulated: boolean;
  activeMutations: MutationInput[];
  activeSimulationSummary: string[];
  simulationSummary: string[];
  canRevert: boolean;
  canRevertSimulation: boolean;
  canRevertConfig: boolean;
  revertKind: RevertKind;

  refreshAll: () => Promise<void>;
  applySimulation: (mutations: MutationInput[]) => Promise<SimulateApplyResponse>;
  revert: () => Promise<void>;
  clear: () => void;
}

export const useDataStore = create<DataState>((set, get) => ({
  score: null,
  segments: null,
  lots: null,
  config: null,
  learning: null,

  isSimulated: false,
  activeMutations: [],
  activeSimulationSummary: [],
  simulationSummary: [],
  canRevert: false,
  canRevertSimulation: false,
  canRevertConfig: false,
  revertKind: null,

  refreshAll: async () => {
    const results = await Promise.allSettled([
      getScore(),
      getSegments(),
      getLots(),
      getConfig(),
      getLearning(),
      fetchCanRevert(),
      getActiveMutations(),
    ]);
    const canRevertVal = results[5].status === "fulfilled" ? results[5].value.can_revert : false;
    const revertKind = results[5].status === "fulfilled" ? results[5].value.kind : null;
    const canRevertSimulation = results[5].status === "fulfilled" ? results[5].value.can_revert_simulation : false;
    const canRevertConfig = results[5].status === "fulfilled" ? results[5].value.can_revert_config : false;
    // Source of truth for "simulation active" is the backend's applied
    // mutations — survives a preset/recalculate that reschedules in place.
    const simActive = results[6].status === "fulfilled" ? results[6].value.active : false;
    const activeMutations = results[6].status === "fulfilled" ? results[6].value.mutations : [];
    const activeSimulationSummary = results[6].status === "fulfilled" ? results[6].value.summary : [];
    set({
      score: results[0].status === "fulfilled" ? results[0].value : null,
      segments: results[1].status === "fulfilled" ? results[1].value : null,
      lots: results[2].status === "fulfilled" ? results[2].value : null,
      config: results[3].status === "fulfilled" ? results[3].value : null,
      learning: results[4].status === "fulfilled" ? results[4].value : null,
      canRevert: canRevertVal,
      canRevertSimulation,
      canRevertConfig,
      revertKind,
      isSimulated: simActive,
      activeMutations,
      activeSimulationSummary,
      simulationSummary: simActive ? activeSimulationSummary : [],
    });
  },

  applySimulation: async (mutations) => {
    const resp = await simulateApply(mutations);
    if (resp.status === "invalid") {
      const details = Object.entries(resp.plan_violations ?? resp.hard_gate_violations ?? {})
        .map(([key, value]) => `${key}=${value}`)
        .join(", ");
      throw new Error(`Plano invalido${details ? `: ${details}` : ""}`);
    }
    await get().refreshAll();
    set({
      isSimulated: true,
      activeMutations: mutations,
      activeSimulationSummary: resp.summary,
      simulationSummary: resp.summary,
      canRevert: resp.can_revert,
      canRevertSimulation: true,
      revertKind: "simulation",
    });
    return resp;
  },

  revert: async () => {
    const kind = get().revertKind;
    if (kind === "config") await revertConfig();
    else await revertSimulation();
    await get().refreshAll();
  },

  clear: () => set({
    score: null, segments: null, lots: null, config: null, learning: null,
    isSimulated: false,
    activeMutations: [],
    activeSimulationSummary: [],
    simulationSummary: [],
    canRevert: false,
    canRevertSimulation: false,
    canRevertConfig: false,
    revertKind: null,
  }),
}));

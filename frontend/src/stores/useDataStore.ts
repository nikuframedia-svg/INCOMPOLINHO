import { create } from "zustand";
import { getPlanView, simulateApply, revertSimulation } from "../api/endpoints";
import type { CandidateIdentity, Score, GateReport, Segment, Lot, FactoryConfig, LearningInfo, CapacityResponse, BlockedDaysResponse, ManualEdit, MutationInput, SimulateApplyResponse, PlacementReason } from "../api/types";
import { commitPlanRevision } from "../lib/planRevision";
import { candidateMatchesPlan } from "../lib/previewCandidate";
import { useSimulatorStore } from "./useSimulatorStore";
import { ACTIVE_DATASET_KEY, useAppStore } from "./useAppStore";
import { assertRefreshed, refreshAfterCommit } from "../lib/refreshOutcome";
import type { RefreshOutcome } from "../lib/refreshOutcome";

let refreshGeneration = 0;
let latestRefresh: { generation: number; promise: Promise<RefreshOutcome> } | null = null;

interface DataState {
  datasetId: string | null;
  planRevision: number | null;
  score: Score | null;
  gateReport: GateReport | null;
  segments: Segment[] | null;
  placementReasons: Record<string, PlacementReason>;
  lots: Lot[] | null;
  config: FactoryConfig | null;
  learning: LearningInfo | null;
  capacity: CapacityResponse | null;
  workdays: string[];
  blockedDays: BlockedDaysResponse | null;

  // Simulation state
  isSimulated: boolean;
  activeMutations: MutationInput[];
  simulationSummary: string[];
  canRevert: boolean;
  manualEdits: ManualEdit[];

  refreshAll: (options?: { strict?: boolean }) => Promise<RefreshOutcome>;
  applySimulation: (mutations: MutationInput[], approval: { reason: string; author: string } | undefined, candidate: CandidateIdentity) => Promise<SimulateApplyResponse>;
  revert: () => Promise<void>;
  clear: () => void;
}

export const useDataStore = create<DataState>((set, get) => ({
  datasetId: null,
  planRevision: null,
  score: null,
  gateReport: null,
  segments: null,
  placementReasons: {},
  lots: null,
  config: null,
  learning: null,
  capacity: null,
  workdays: [],
  blockedDays: null,

  isSimulated: false,
  activeMutations: [],
  simulationSummary: [],
  canRevert: false,
  manualEdits: [],

  refreshAll: (options) => {
    // A refresh overtaken by a newer one reports the newer one's outcome:
    // the screen ends up showing the latest plan either way (07/10/2026: a
    // background check overtook the refresh after a save and the planner saw
    // "Erro" although the change was saved and then displayed).
    const generation = ++refreshGeneration;
    // Only a refresh started after this one may answer for it; a generation
    // bumped by clear() has no newer refresh and stays "superseded".
    const latestOutcome = (): Promise<RefreshOutcome> | RefreshOutcome =>
      latestRefresh && latestRefresh.generation > generation ? latestRefresh.promise : "superseded";
    const run = async (): Promise<RefreshOutcome> => {
      try {
        const snapshot = await getPlanView();
        if (generation !== refreshGeneration) return await latestOutcome();
        if (!snapshot.dataset_id || !Number.isInteger(snapshot.plan_revision)
          || !Array.isArray(snapshot.active_mutations) || !Array.isArray(snapshot.manual_edits)
          || typeof snapshot.can_revert !== "boolean" || !("learning" in snapshot)) {
          throw new Error("Resposta do plano incompleta.");
        }
        const current = get();
        if (current.datasetId === snapshot.dataset_id && current.planRevision !== null
          && snapshot.plan_revision < current.planRevision) return "superseded";
        const changed = current.datasetId !== snapshot.dataset_id || current.planRevision !== snapshot.plan_revision;
        if (changed) useSimulatorStore.getState().invalidatePreviews();
        commitPlanRevision(snapshot.plan_revision, snapshot.dataset_id);
        set({
          datasetId: snapshot.dataset_id, planRevision: snapshot.plan_revision,
          score: snapshot.score, gateReport: snapshot.gate_report,
          segments: snapshot.segments, placementReasons: snapshot.placement_reasons ?? {},
          lots: snapshot.lots, config: snapshot.config,
          learning: snapshot.learning, capacity: snapshot.capacity,
          workdays: snapshot.workdays, blockedDays: snapshot.blocked_days,
          canRevert: snapshot.can_revert, isSimulated: snapshot.active_mutations.length > 0,
          activeMutations: snapshot.active_mutations, manualEdits: snapshot.manual_edits,
          ...(changed || snapshot.active_mutations.length === 0 ? { simulationSummary: [] } : {}),
        });
        if (snapshot.dataset) {
          try { sessionStorage.setItem(ACTIVE_DATASET_KEY, snapshot.dataset.id); } catch { /* Storage can be disabled. */ }
          const app = useAppStore.getState();
          app.setDataset(snapshot.dataset);
          app.setTrust(snapshot.dataset.trust_score, snapshot.dataset.trust_gate);
          app.setHasData(true);
        }
        return "updated";
      } catch {
        // Keep the previous coherent display, including its mutation/revert state.
        if (generation !== refreshGeneration) return await latestOutcome();
        if (options?.strict) assertRefreshed("failed");
        return "failed";
      }
    };
    const promise = run();
    latestRefresh = { generation, promise };
    return promise;
  },

  applySimulation: async (mutations, approval, candidate) => {
    if (!candidateMatchesPlan(candidate, get().datasetId, get().planRevision)) {
      throw new Error("O plano mudou desde a simulação. Simula novamente.");
    }
    const resp = await simulateApply(mutations, approval, candidate);
    if (useSimulatorStore.getState().result?.candidate_id === candidate.candidate_id) {
      useSimulatorStore.getState().setResult(null);
    }
    assertRefreshed(await refreshAfterCommit(() => get().refreshAll()), true);
    if (get().datasetId === candidate.dataset_id && get().planRevision === resp.plan_revision) {
      set({ simulationSummary: resp.summary });
    }
    return resp;
  },

  revert: async () => {
    await revertSimulation();
    useSimulatorStore.getState().invalidatePreviews();
    assertRefreshed(await refreshAfterCommit(() => get().refreshAll()), true);
  },

  clear: () => {
    ++refreshGeneration;
    commitPlanRevision(0);
    useSimulatorStore.getState().clear();
    set({
    datasetId: null, planRevision: null,
    score: null, gateReport: null, segments: null, placementReasons: {},
    lots: null, config: null, learning: null, capacity: null,
    workdays: [], blockedDays: null,
    isSimulated: false, activeMutations: [], simulationSummary: [], canRevert: false, manualEdits: [],
    });
  },
}));

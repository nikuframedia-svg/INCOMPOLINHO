import { create } from "zustand";
import { ApiError } from "../api/client";
import {
  approveLoadJob, AUTOMATIC_LOAD_APPROVAL, cancelLoadJob, confirmPreparedISOP, getHealth, getLoadJob, uploadISOP,
} from "../api/endpoints";
import type { LoadJob, LoadJobResponse } from "../api/types";
import { ACTIVE_DATASET_KEY, useAppStore } from "./useAppStore";
import { useDataStore } from "./useDataStore";
import { assertRefreshed, refreshAfterCommit } from "../lib/refreshOutcome";
import { approvalReasonSentence, decisionReasons } from "../lib/gateApproval";

export const ACTIVE_LOAD_KEY = "pp1ActiveLoadJobId";
export const TERMINAL_LOAD_STATES = new Set(["applied", "blocked", "failed", "cancelled", "stale"]);

export function loadWarnings(job: LoadJob): string[] {
  // One dictionary for every screen; robustness is informative only and old
  // jobs may still list it as a reason.
  const gate = job.gate_report ?? job.result?.gate_report;
  const gateWarnings = gate ? decisionReasons(gate).map(approvalReasonSentence) : [];
  return [...(job.result?.state_warnings ?? []), ...gateWarnings];
}

function storedId(): string | null {
  try { return sessionStorage.getItem(ACTIVE_LOAD_KEY); } catch { return null; }
}

function rememberId(id: string | null) {
  try {
    if (id) sessionStorage.setItem(ACTIVE_LOAD_KEY, id);
    else sessionStorage.removeItem(ACTIVE_LOAD_KEY);
  } catch { /* Current-page tracking remains available when storage is disabled. */ }
}

interface LoadState {
  jobId: string | null;
  job: LoadJob | null;
  completion: LoadJob | null;
  isOpen: boolean;
  actionPending: boolean;
  connectionLost: boolean;
  missing: boolean;
  error: string | null;
  existingJobId: string | null;
  refreshing: boolean;
  refreshError: string | null;
  receivedAt: number;
  open: () => void;
  hide: () => void;
  reset: (chooseFile?: boolean) => void;
  resume: () => void;
  followExisting: () => void;
  start: (file: File) => Promise<void>;
  retryUpload: () => Promise<void>;
  confirm: () => Promise<void>;
  approve: () => Promise<void>;
  cancel: () => Promise<void>;
  refreshApplied: () => Promise<void>;
}

let timer: ReturnType<typeof setTimeout> | null = null;
let polling = false;
let generation = 0;
let retryMs = 1000;
let retainedFile: File | null = null;
let attemptedRefresh: string | null = null;

export function stopLoadPolling() {
  generation += 1;
  if (timer !== null) clearTimeout(timer);
  timer = null;
  polling = false;
}

function schedulePoll(delay = 1000) {
  const { jobId, job } = useLoadStore.getState();
  if (!jobId || (job && TERMINAL_LOAD_STATES.has(job.status)) || timer !== null || polling) return;
  timer = setTimeout(() => { timer = null; void poll(); }, delay);
}

function acceptJob(response: LoadJobResponse, id: string) {
  const job = response?.job;
  if (!job || job.id !== id || ![
    "preparing", "prepared", "queued", "running", "awaiting_approval", ...TERMINAL_LOAD_STATES,
  ].includes(job.status)) {
    throw new ApiError(200, "O servidor devolveu um estado de carregamento inesperado.", { code: "invalid_response" });
  }
  useLoadStore.setState({ job, receivedAt: Date.now(), connectionLost: false, missing: false });
  retryMs = 1000;
  if (job.status === "applied" && attemptedRefresh !== id) {
    attemptedRefresh = id;
    void useLoadStore.getState().refreshApplied();
  }
}

function transportFailure(failure: unknown): boolean {
  if (!(failure instanceof ApiError)) return failure instanceof TypeError;
  return failure.status === 0 || [408, 502, 503, 504, 524].includes(failure.status)
    || (failure.detail as { code?: string } | undefined)?.code === "invalid_response";
}

async function poll() {
  const id = useLoadStore.getState().jobId;
  if (!id) return;
  const currentGeneration = generation;
  polling = true;
  try {
    const response = await getLoadJob(id);
    if (generation !== currentGeneration || useLoadStore.getState().jobId !== id) return;
    acceptJob(response, id);
  } catch (failure) {
    if (generation !== currentGeneration || useLoadStore.getState().jobId !== id) return;
    if (failure instanceof ApiError && failure.status === 404) {
      stopLoadPolling();
      rememberId(null);
      useLoadStore.setState({
        jobId: null,
        job: null,
        missing: true,
        connectionLost: false,
        error: "O carregamento anterior já não existe. Seleciona o ficheiro para iniciar um novo.",
      });
    } else {
      useLoadStore.setState({ connectionLost: true });
    }
    retryMs = Math.min(5000, retryMs * 2);
  } finally {
    if (generation === currentGeneration) {
      polling = false;
      schedulePoll(retryMs);
    }
  }
}

async function mutate(action: (job: LoadJob) => Promise<LoadJobResponse>) {
  const state = useLoadStore.getState();
  if (!state.job || state.actionPending) return;
  const id = state.job.id;
  useLoadStore.setState({ actionPending: true, error: null });
  // Ignore any GET that began before this command and could otherwise put a
  // cancelled/applied job back into the "running" state in the browser.
  stopLoadPolling();
  try {
    const response = await action(state.job);
    if (useLoadStore.getState().jobId === id) acceptJob(response, id);
  } catch (failure) {
    if (useLoadStore.getState().jobId !== id) return;
    if (transportFailure(failure)) useLoadStore.setState({ connectionLost: true });
    else useLoadStore.setState({ error: failure instanceof Error ? failure.message : "Não foi possível concluir o pedido." });
  } finally {
    if (useLoadStore.getState().jobId === id) {
      useLoadStore.setState({ actionPending: false });
      schedulePoll(0);
    }
  }
}

const initialId = storedId();

export const useLoadStore = create<LoadState>((set, get) => ({
  jobId: initialId, job: null, completion: null, isOpen: Boolean(initialId), actionPending: false,
  connectionLost: false, missing: false, error: null, existingJobId: null,
  refreshing: false, refreshError: null, receivedAt: Date.now(),
  open: () => { set({ isOpen: true }); get().resume(); },
  hide: () => set({ isOpen: false }),
  reset: (chooseFile = false) => {
    if (get().job && !TERMINAL_LOAD_STATES.has(get().job!.status)) return;
    stopLoadPolling();
    rememberId(null);
    retainedFile = null;
    attemptedRefresh = null;
    retryMs = 1000;
    set({ jobId: null, job: null, completion: null, isOpen: chooseFile, actionPending: false,
      connectionLost: false, missing: false, error: null, existingJobId: null,
      refreshing: false, refreshError: null });
  },
  resume: () => {
    const id = get().jobId ?? storedId();
    if (!id) return;
    if (!get().jobId) set({ jobId: id, isOpen: true });
    schedulePoll(0);
  },
  followExisting: () => {
    const id = get().existingJobId;
    if (!id) return;
    stopLoadPolling();
    rememberId(id);
    set({ jobId: id, job: null, error: null, existingJobId: null, missing: false });
    schedulePoll(0);
  },
  start: async (file) => {
    if (get().actionPending || (get().job && !TERMINAL_LOAD_STATES.has(get().job!.status))) return;
    const id = crypto.randomUUID();
    retainedFile = file;
    stopLoadPolling();
    rememberId(id); // Persist BEFORE sending: even a lost 202 can be recovered.
    set({ jobId: id, job: null, completion: null, isOpen: true, actionPending: true, error: null,
      connectionLost: false, missing: false, existingJobId: null, refreshError: null });
    try {
      let expectedRevision = useDataStore.getState().planRevision;
      if (expectedRevision === null) {
        const health = await getHealth();
        if (!health.has_data) expectedRevision = health.plan_revision;
        else {
          assertRefreshed(await useDataStore.getState().refreshAll());
          expectedRevision = useDataStore.getState().planRevision;
        }
      }
      if (expectedRevision === null) {
        throw new Error("Não foi possível confirmar a revisão atual do plano. Atualiza os dados e tenta novamente.");
      }
      const response = await uploadISOP(file, id, expectedRevision);
      if (get().jobId === id) acceptJob(response, id);
    } catch (failure) {
      if (get().jobId !== id) return;
      if (transportFailure(failure)) set({ connectionLost: true });
      else {
        const existingJobId = failure instanceof ApiError
          ? (failure.detail as { job_id?: string } | undefined)?.job_id ?? null : null;
        stopLoadPolling();
        rememberId(null);
        set({ jobId: null, job: null, actionPending: false,
          error: failure instanceof Error ? failure.message : "Não foi possível enviar o ISOP.",
          existingJobId, missing: false });
      }
    } finally {
      if (get().jobId === id) {
        set({ actionPending: false });
        schedulePoll(0);
      }
    }
  },
  retryUpload: async () => { if (retainedFile) await get().start(retainedFile); },
  confirm: () => mutate((job) => confirmPreparedISOP(job.id, job.base_revision)),
  approve: () => mutate((job) => approveLoadJob(job.id, job.base_revision, AUTOMATIC_LOAD_APPROVAL)),
  cancel: () => mutate((job) => cancelLoadJob(job.id)),
  refreshApplied: async () => {
    const id = get().jobId;
    if (!id || get().refreshing || get().job?.status !== "applied") return;
    set({ refreshing: true, refreshError: null });
    try {
      assertRefreshed(await refreshAfterCommit(() => useDataStore.getState().refreshAll()), true);
      if (get().jobId !== id) return;
      const app = useAppStore.getState();
      const dataset = app.dataset;
      if (!dataset || dataset.id !== useDataStore.getState().datasetId) throw new Error("Identidade do plano inconsistente.");
      try { sessionStorage.setItem(ACTIVE_DATASET_KEY, dataset.id); } catch { /* optional */ }
      const completion = get().job;
      get().reset();
      set({ completion });
    } catch {
      if (get().jobId === id) set({ refreshError: "O plano foi carregado, mas não foi possível atualizar os dados do ecrã. Podes tentar atualizar novamente." });
    } finally {
      if (get().jobId === id) set({ refreshing: false });
    }
  },
}));

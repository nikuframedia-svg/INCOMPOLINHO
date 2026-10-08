import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LoadJob, LoadResponse } from "../src/api/types";
import { useAppStore } from "../src/stores/useAppStore";
import { useDataStore } from "../src/stores/useDataStore";

const mocks = vi.hoisted(() => ({
  uploadISOP: vi.fn(), prepareISOP: vi.fn(), confirmPreparedISOP: vi.fn(), getLoadJob: vi.fn(),
  approveLoadJob: vi.fn(), cancelLoadJob: vi.fn(), getHealth: vi.fn(),
}));
vi.mock("../src/api/endpoints", async (importOriginal) => ({
  ...await importOriginal<typeof import("../src/api/endpoints")>(), ...mocks,
}));

import { UploadZone } from "../src/components/ui/UploadZone";
import { ACTIVE_LOAD_KEY, loadWarnings, stopLoadPolling, useLoadStore } from "../src/stores/useLoadStore";
import { ApiError } from "../src/api/client";

const loaded = {
  status: "ok", n_ops: 1, n_segments: 1, time_ms: 151000,
  score: { otd: 100, otd_d: 100, tardy_count: 0, setups: 1 },
  trust_index: { score: 100, gate: "full_auto" }, journal_summary: null, learning: null,
  dataset: { id: "new-data", filename: "isop.xlsx", uploaded_at: "2026-09-08T09:00:00Z",
    n_ops: 1, n_segments: 1, trust_score: 100, trust_gate: "full_auto", otd: 100, tardy_count: 0 },
} as LoadResponse;

function job(status: LoadJob["status"] = "prepared"): LoadJob {
  return {
    id: "1a45e6d2-8f18-4405-9b6d-547ae6aeb815", filename: "isop.xlsx", status,
    phase: status, message: status === "running" ? "A calcular o plano…" : "O ficheiro está pronto para calcular.",
    created_at: "2026-09-08T09:00:00Z", updated_at: "2026-09-08T09:00:00Z",
    started_at: null, elapsed_ms: 0, timings_ms: {}, base_revision: 7,
    prepared: { status: "prepared", token: "token", expected_revision: 7, filename: "isop.xlsx",
      n_ops: 1, trust_index: { score: 100, gate: "full_auto" }, machines: [], references: [], tools: [], next_step: "confirm" },
    gate_report: null, error: null, result: status === "applied" ? loaded : null,
  };
}

let serverJob: LoadJob;
const originalRefresh = useDataStore.getState().refreshAll;
async function refreshAppliedFixture() {
  useDataStore.setState({ datasetId: loaded.dataset.id, planRevision: 8 });
  useAppStore.setState({ dataset: loaded.dataset, hasData: true });
  return "updated" as const;
}

beforeEach(() => {
  serverJob = job();
  mocks.getLoadJob.mockImplementation(async () => ({ job: serverJob }));
  mocks.uploadISOP.mockImplementation(async (_file, id) => {
    expect(sessionStorage.getItem(ACTIVE_LOAD_KEY)).toBe(id);
    serverJob = { ...serverJob, id, status: "running", message: "A calcular o plano…" };
    return { job: serverJob };
  });
  mocks.confirmPreparedISOP.mockImplementation(async () => {
    serverJob = { ...serverJob, status: "running", phase: "optimization", message: "A calcular o plano…" };
    return { job: serverJob };
  });
  mocks.cancelLoadJob.mockImplementation(async () => {
    serverJob = { ...serverJob, status: "cancelled", message: "Carregamento cancelado." };
    return { job: serverJob };
  });
  mocks.approveLoadJob.mockImplementation(async () => {
    serverJob = { ...serverJob, status: "applied", result: loaded };
    return { job: serverJob };
  });
  mocks.getHealth.mockResolvedValue({ has_data: true, dataset: loaded.dataset, plan_revision: 7 });
  useDataStore.setState({ planRevision: 7, refreshAll: vi.fn().mockImplementation(refreshAppliedFixture) });
});

afterEach(() => {
  cleanup();
  stopLoadPolling();
  useLoadStore.setState({ job: null });
  useLoadStore.getState().reset();
  sessionStorage.clear();
  localStorage.clear();
  useDataStore.getState().clear();
  useDataStore.setState({ refreshAll: originalRefresh });
  useAppStore.setState({ hasData: false, isUploading: false, trustScore: null, trustGate: null, dataset: null, accessMode: "edit" });
  vi.resetAllMocks();
  vi.useRealTimers();
});

async function chooseFile() {
  fireEvent.change(screen.getByLabelText("Ficheiro ISOP"), {
    target: { files: [new File(["fixture"], "isop.xlsx")] },
  });
  await screen.findByText("A atualizar o plano…");
}

function recover(status: LoadJob["status"]) {
  serverJob = job(status);
  sessionStorage.setItem(ACTIVE_LOAD_KEY, serverJob.id);
  useLoadStore.setState({ jobId: serverJob.id, isOpen: true, job: null });
}

async function showApproval(reasons = ["delivery_risk"]) {
  recover("awaiting_approval");
  serverJob.gate_report = {
    status: "best_effort", apply_decision: "approval_required", requires_approval: true,
    approval_reasons: reasons, physical_gate_passed: true, coverage_gate_passed: true, metrics: {},
  } as LoadJob["gate_report"];
  render(<UploadZone />);
  await screen.findByText("O ficheiro está pronto para atualizar o plano.");
}

describe("UploadZone", () => {
  it("selecionar o ficheiro inicia a atualização sem confirmações", async () => {
    render(<UploadZone />);
    await chooseFile();
    expect(mocks.uploadISOP).toHaveBeenCalledTimes(1);
    expect(mocks.uploadISOP).toHaveBeenCalledWith(expect.any(File), expect.any(String), 7);
    expect(mocks.prepareISOP).not.toHaveBeenCalled();
    expect(mocks.confirmPreparedISOP).not.toHaveBeenCalled();
    expect(screen.queryByText(/Confirmar carregamento/)).toBeNull();
    expect(screen.queryByText(/Motivo da aprovação/)).toBeNull();
    expect(useAppStore.getState().blockingRequests).toBe(0);
  });

  it("obtém uma revisão coerente antes de enviar quando o ecrã ainda não a carregou", async () => {
    const refreshAll = vi.fn().mockImplementation(async () => {
      useDataStore.setState({ planRevision: 11 });
      return "updated" as const;
    });
    useDataStore.setState({ planRevision: null, refreshAll });
    render(<UploadZone />);
    await chooseFile();
    expect(refreshAll).toHaveBeenCalledWith();
    expect(mocks.uploadISOP).toHaveBeenCalledWith(expect.any(File), expect.any(String), 11);
  });

  it("abandona uma referência expirada e permite iniciar um carregamento novo", async () => {
    vi.useFakeTimers();
    const expired = "341ba880-afe0-44df-8744-368c6db12267";
    sessionStorage.setItem(ACTIVE_LOAD_KEY, expired);
    useLoadStore.setState({ jobId: expired, job: null, isOpen: true });
    mocks.getLoadJob.mockRejectedValue(new ApiError(404, "missing"));
    useLoadStore.getState().resume();
    await vi.advanceTimersByTimeAsync(0);
    expect(useLoadStore.getState().jobId).toBeNull();
    expect(sessionStorage.getItem(ACTIVE_LOAD_KEY)).toBeNull();
    expect(useLoadStore.getState().missing).toBe(true);
    await vi.advanceTimersByTimeAsync(10000);
    expect(mocks.getLoadJob).toHaveBeenCalledTimes(1);
  });

  it("liberta o formulário quando o servidor rejeita o envio antes de criar tarefa", async () => {
    mocks.uploadISOP.mockRejectedValueOnce(new ApiError(409, "O plano mudou entretanto.", {
      code: "stale_revision", current_revision: 12,
    }));
    render(<UploadZone />);
    fireEvent.change(screen.getByLabelText("Ficheiro ISOP"), {
      target: { files: [new File(["fixture"], "isop.xlsx")] },
    });
    await screen.findByRole("alert");
    expect(useLoadStore.getState().jobId).toBeNull();
    expect(useLoadStore.getState().actionPending).toBe(false);
    expect(sessionStorage.getItem(ACTIVE_LOAD_KEY)).toBeNull();
    expect(screen.getByLabelText("Ficheiro ISOP")).toBeTruthy();
  });

  it("recupera a tarefa após atualizar a página, mesmo com um plano ativo", async () => {
    recover("running");
    useAppStore.setState({ hasData: true, dataset: { ...loaded.dataset, id: "old" } });
    render(<UploadZone />);
    await screen.findByText("A atualizar o plano…");
    expect(mocks.getLoadJob).toHaveBeenCalledWith(serverJob.id);
    expect(mocks.prepareISOP).not.toHaveBeenCalled();
    expect(mocks.confirmPreparedISOP).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Ver plano atual" })).toBeTruthy();
  });

  it("atualiza o candidato guardado uma única vez com aceitação automática", async () => {
    await showApproval();
    const button = screen.getByRole("button", { name: "Atualizar plano" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(useAppStore.getState().dataset?.id).toBe("new-data"));
    expect(mocks.approveLoadJob).toHaveBeenCalledTimes(1);
    expect(mocks.approveLoadJob).toHaveBeenCalledWith(serverJob.id, 7, {
      reason: "Aceitação automática das exceções permitidas no carregamento do ISOP.", author: "sistema",
    });
    expect(mocks.confirmPreparedISOP).not.toHaveBeenCalled();
    expect(mocks.uploadISOP).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(ACTIVE_LOAD_KEY)).toBeNull();
    expect(useLoadStore.getState().completion?.gate_report?.approval_reasons).toEqual(["delivery_risk"]);
  });

  it("impede atualizar o candidato em modo Consulta", async () => {
    useAppStore.setState({ accessMode: "view" });
    await showApproval();
    const button = screen.getByRole<HTMLButtonElement>("button", { name: "Atualizar plano" });
    expect(button.disabled).toBe(true);
    fireEvent.click(button);
    expect(mocks.approveLoadJob).not.toHaveBeenCalled();
  });

  it("um bloqueio mostra a causa e não oferece aprovação", async () => {
    const previousDataset = { ...loaded.dataset, id: "previous-plan" };
    useAppStore.setState({ hasData: true, dataset: previousDataset });
    recover("blocked");
    serverJob.error = { code: "plan_blocked", message: "Existem conflitos de máquinas." };
    serverJob.gate_report = { status: "invalid_physics", apply_decision: "blocked", requires_approval: false,
      approval_reasons: [], metrics: {} } as unknown as LoadJob["gate_report"];
    render(<UploadZone />);
    await screen.findByText("Existem conflitos de máquinas.");
    expect(screen.queryByRole("button", { name: "Atualizar plano" })).toBeNull();
    expect(useAppStore.getState().dataset).toEqual(previousDataset);
    expect(mocks.approveLoadJob).not.toHaveBeenCalled();
    expect(useDataStore.getState().refreshAll).not.toHaveBeenCalled();
    expect(useLoadStore.getState().completion).toBeNull();
  });

  it("cancelar não permite que uma resposta GET antiga volte a mostrar o cálculo", async () => {
    recover("running");
    useLoadStore.setState({ job: serverJob });
    let release: (value: { job: LoadJob }) => void = () => {};
    const oldJob = { ...serverJob };
    mocks.getLoadJob.mockReturnValue(new Promise((resolve) => { release = resolve; }));
    render(<UploadZone />);
    await waitFor(() => expect(mocks.getLoadJob).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Cancelar carregamento" }));
    await screen.findByText("Carregamento cancelado.");
    await act(async () => release({ job: oldJob }));
    expect(useLoadStore.getState().job?.status).toBe("cancelled");
    expect(mocks.cancelLoadJob).toHaveBeenCalledTimes(1);
  });

  it("uma falha ao atualizar o ecrã não é tratada como falha de importação", async () => {
    recover("applied");
    const refreshAll = vi.fn().mockRejectedValueOnce(new Error("network")).mockImplementation(refreshAppliedFixture);
    useDataStore.setState({ refreshAll });
    render(<UploadZone />);
    await screen.findByText(/O plano foi carregado, mas não foi possível atualizar/);
    expect(sessionStorage.getItem(ACTIVE_LOAD_KEY)).toBe(serverJob.id);
    fireEvent.click(screen.getByRole("button", { name: "Atualizar dados do ecrã" }));
    await waitFor(() => expect(sessionStorage.getItem(ACTIVE_LOAD_KEY)).toBeNull());
    expect(refreshAll).toHaveBeenCalledTimes(2);
    expect(refreshAll).toHaveBeenCalledWith();
    expect(mocks.prepareISOP).not.toHaveBeenCalled();
    expect(mocks.confirmPreparedISOP).not.toHaveBeenCalled();
  });

  it("recupera uma resposta perdida do envio sem importar novamente", async () => {
    mocks.uploadISOP.mockImplementation(async (_file, id) => {
      serverJob = { ...serverJob, id, status: "applied", result: loaded };
      throw new ApiError(524, "timeout", { code: "timeout" });
    });
    render(<UploadZone />);
    fireEvent.change(screen.getByLabelText("Ficheiro ISOP"), {
      target: { files: [new File(["fixture"], "isop.xlsx")] },
    });
    await waitFor(() => expect(useAppStore.getState().dataset?.id).toBe("new-data"));
    expect(mocks.uploadISOP).toHaveBeenCalledTimes(1);
    expect(mocks.confirmPreparedISOP).not.toHaveBeenCalled();
  });

  it("usa polling progressivo durante uma falha de rede e retoma a mesma tarefa", async () => {
    vi.useFakeTimers();
    recover("running");
    mocks.getLoadJob.mockRejectedValueOnce(new ApiError(0, "network", { code: "network" }))
      .mockRejectedValueOnce(new ApiError(524, "timeout", { code: "timeout" }))
      .mockResolvedValue({ job: serverJob });
    useLoadStore.getState().resume();
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.getLoadJob).toHaveBeenCalledTimes(1);
    expect(useLoadStore.getState().connectionLost).toBe(true);
    await vi.advanceTimersByTimeAsync(1999);
    expect(mocks.getLoadJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(mocks.getLoadJob).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4000);
    expect(mocks.getLoadJob).toHaveBeenCalledTimes(3);
    expect(useLoadStore.getState().connectionLost).toBe(false);
    expect(useLoadStore.getState().jobId).toBe(serverJob.id);
  });
});

it("does not turn legacy robustness reasons into load warnings", () => {
  const job = {
    gate_report: { approval_reasons: ["robustness_not_evaluated", "robustness_below_threshold", "delivery_risk"] },
    result: { state_warnings: [] },
  } as unknown as LoadJob;
  expect(loadWarnings(job)).toEqual(["Há lotes que acabam depois do prazo de produção."]);
});

it("uses the shared plain dictionary for every load warning, never a raw code", () => {
  const job = {
    gate_report: { approval_reasons: [
      "jit_window_blocked", "material_release_blocked", "long_production", "operational_sequence_review", "novo_motivo",
    ] },
    result: { state_warnings: ["Aviso do ISOP."] },
  } as unknown as LoadJob;
  expect(loadWarnings(job)).toEqual([
    "Aviso do ISOP.",
    "Há produções marcadas antes de o material estar disponível.",
    "Há mudanças de ferramenta marcadas antes de o material chegar.",
    "Há produções seguidas acima do limite de dias.",
    "A ordem de produção tem pontos a rever.",
    "Existe uma exceção de planeamento a rever.",
  ]);
});

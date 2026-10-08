import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  startManualMovePreview: vi.fn(), getManualMovePreview: vi.fn(), cancelManualMovePreview: vi.fn(), applyManualMove: vi.fn(),
  getPlanView: vi.fn(), simulateApply: vi.fn(), revertSimulation: vi.fn(),
}));
vi.mock("../src/api/endpoints", () => mocks);
import { MoveLotModal } from "../src/components/MoveLotModal";
import { useDataStore } from "../src/stores/useDataStore";
import { useAppStore } from "../src/stores/useAppStore";
import { ApiError } from "../src/api/client";

const gate = { status: "applicable", apply_decision: "auto_applicable", physical_gate_passed: true, requires_approval: false };
const result = { requires_confirmation: false, delivery_warnings: [], gate_report: gate,
  delta: { otd_before: 100, otd_after: 100, otd_d_before: 100, otd_d_after: 100,
    setups_before: 1, setups_after: 1, tardy_before: 0, tardy_after: 0, earliness_before: 1, earliness_after: 1 } };
const ready = { id: "move-job", status: "ready", dataset_id: "d1", base_revision: 21, progress: 100, message: "Ready", result };
const props = { segment: { machine_id: "M1", start_min: 420, setup_min: 30 } as never,
  lot: { id: "lot", machine_id: "M1", alt_machine_id: "M2", edd: 1 } as never,
  workdays: ["2026-09-17", "2026-09-18"], initialTargetDay: 1, onClose: vi.fn(), onApplied: vi.fn() };

beforeEach(() => {
  vi.resetAllMocks();
  useDataStore.getState().clear();
  useDataStore.setState({ datasetId: "d1", planRevision: 21 });
  useAppStore.setState({ accessMode: "edit" });
  mocks.startManualMovePreview.mockResolvedValue({ job: ready });
  mocks.cancelManualMovePreview.mockResolvedValue({ job: { ...ready, status: "cancelled" } });
  mocks.applyManualMove.mockResolvedValue(result);
  mocks.getPlanView.mockResolvedValue({ dataset_id: "d1", plan_revision: 22, score: {}, gate_report: gate, config: {},
    segments: [], lots: [], workdays: [], capacity: {}, blocked_days: {}, learning: null, active_mutations: [], manual_edits: [], can_revert: true });
});
afterEach(() => { cleanup(); vi.useRealTimers(); useDataStore.getState().clear(); useAppStore.setState({ accessMode: "edit" }); });

async function preview() {
  render(<MoveLotModal {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  return screen.findByRole<HTMLButtonElement>("button", { name: "Aplicar movimento" });
}


it.each(["setup", "continuation"])("uses the whole lot's production start when opening from %s", (fragment) => {
  const setup = { lot_id: "lot", machine_id: "M1", day_idx: 0,
    start_min: 1400, setup_min: 30, prod_min: 0 };
  const production = { lot_id: "lot", machine_id: "M1", day_idx: 1,
    start_min: 420, setup_min: 0, prod_min: 60 };
  const continuation = { ...production, day_idx: 2, start_min: 930 };
  useDataStore.setState({ segments: [continuation, setup, production] as never });
  render(<MoveLotModal {...props} segment={(fragment === "setup" ? setup : continuation) as never} />);
  expect((screen.getByLabelText("Início exato da produção") as HTMLInputElement).value).toBe("07:00");
});

it("preserves an explicit dropped production time over the lot's default", () => {
  useDataStore.setState({ segments: [{ lot_id: "lot", day_idx: 1,
    start_min: 420, setup_min: 0, prod_min: 60 }] as never });
  render(<MoveLotModal {...props} initialTargetStartMin={600} />);
  expect((screen.getByLabelText("Início exato da produção") as HTMLInputElement).value).toBe("10:00");
});

it("does not describe a physically valid but operationally blocked move as safe or allow apply", async () => {
  mocks.startManualMovePreview.mockResolvedValue({ job: { ...ready, result: { ...result,
    gate_report: { ...gate, status: "operational_sequence_blocked", apply_decision: "blocked" } } } });
  const apply = await preview();
  expect(apply.disabled).toBe(true);
  expect(screen.queryByText(/Movimento fisicamente válido/)).toBeNull();
  expect(screen.getByRole("alert").textContent).toMatch(/bloqueado/);
  fireEvent.click(apply);
  expect(mocks.applyManualMove).not.toHaveBeenCalled();
});

it("applies the ready preview id with its explicit base revision", async () => {
  fireEvent.click(await preview());
  await waitFor(() => expect(props.onApplied).toHaveBeenCalledTimes(1));
  expect(mocks.applyManualMove).toHaveBeenCalledWith(expect.objectContaining({ preview_job_id: "move-job", expected_revision: 21, lot_id: "lot", target_day: 1, target_machine: "M1", target_start_min: 450 }));
});

it("shows a partial complete-plan improvement without creating another apply block", async () => {
  mocks.startManualMovePreview.mockResolvedValue({ job: { ...ready, result: { ...result,
    gate_report: { ...gate, improvement: {
      contract_version: 1, status: "partial", stop_reason: "search_limit",
      moves_accepted: 1, accepted_by_scope: { earliest_legal: 1 },
    } },
  } } });
  const apply = await preview();
  expect(screen.getByText(/A melhoria automática parou antes de rever todas as hipóteses/)).toBeTruthy();
  expect(apply.disabled).toBe(false);
});

it("invalidates the ready preview when the target changes", async () => {
  await preview();
  fireEvent.change(screen.getByLabelText("Máquina"), { target: { value: "M2" } });
  expect(screen.queryByRole("button", { name: "Aplicar movimento" })).toBeNull();
  expect(mocks.applyManualMove).not.toHaveBeenCalled();
});

it("disables an otherwise applicable move when the plan base changes", async () => {
  const apply = await preview();
  act(() => useDataStore.setState({ planRevision: 22 }));
  expect(apply.disabled).toBe(true);
  expect(screen.getByRole("alert").textContent).toMatch(/plano mudou/);
});

it("refreshes a rejected origin without retrying apply or losing the request", async () => {
  mocks.applyManualMove.mockRejectedValueOnce(new ApiError(409, "O plano mudou", {
    code: "stale_preview", current_revision: 22,
  }));
  fireEvent.click(await preview());
  await screen.findByText(/Não foi possível aplicar o movimento/);
  await waitFor(() => expect(useDataStore.getState().planRevision).toBe(22));
  expect(screen.queryByRole("button", { name: "Aplicar movimento" })).toBeNull();
  expect((screen.getByLabelText("Dia exato") as HTMLSelectElement).value).toBe("1");
  expect((screen.getByLabelText("Início exato da produção") as HTMLInputElement).value).toBe("07:30");
  expect((screen.getByLabelText("Máquina") as HTMLSelectElement).value).toBe("M1");
  expect(mocks.applyManualMove).toHaveBeenCalledTimes(1);
  mocks.startManualMovePreview.mockResolvedValue({ job: { ...ready, base_revision: 22 } });
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  const apply = await screen.findByRole<HTMLButtonElement>("button", { name: "Aplicar movimento" });
  expect(apply.disabled).toBe(false);
  fireEvent.click(apply);
  await waitFor(() => expect(props.onApplied).toHaveBeenCalledTimes(1));
  expect(mocks.applyManualMove).toHaveBeenLastCalledWith(expect.objectContaining({ expected_revision: 22 }));
});

it("does not discard a valid candidate on an approval refusal", async () => {
  mocks.applyManualMove.mockRejectedValue(new ApiError(409, "Falta aprovação", {
    requires_confirmation: true,
  }));
  fireEvent.click(await preview());
  await screen.findByText(/Falta aprovação/);
  expect(screen.getByRole("button", { name: "Aplicar movimento" })).toBeTruthy();
  expect(mocks.getPlanView).not.toHaveBeenCalled();
  expect(mocks.applyManualMove).toHaveBeenCalledTimes(1);
});

it("allows preview in read-only mode while blocking apply", async () => {
  useAppStore.setState({ accessMode: "view" });
  expect((await preview()).disabled).toBe(true);
  expect(mocks.startManualMovePreview).toHaveBeenCalledTimes(1);
});

it("cancels a job whose start response arrives after unmount", async () => {
  let resolve!: (value: unknown) => void;
  mocks.startManualMovePreview.mockReturnValue(new Promise((done) => { resolve = done; }));
  const view = render(<MoveLotModal {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  view.unmount();
  await act(async () => { resolve({ job: ready }); });
  expect(mocks.cancelManualMovePreview).toHaveBeenCalledWith("move-job");
  expect(mocks.applyManualMove).not.toHaveBeenCalled();
});

it("recovers a transient poll failure without throwing away the server job", async () => {
  vi.useFakeTimers();
  mocks.startManualMovePreview.mockResolvedValue({ job: { ...ready, status: "running", result: null } });
  mocks.getManualMovePreview.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ job: ready });
  render(<MoveLotModal {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(screen.getByText(/Ligação interrompida/)).toBeTruthy();
  await act(async () => { await vi.advanceTimersByTimeAsync(900); });
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Aplicar movimento" }).disabled).toBe(false);
  expect(mocks.cancelManualMovePreview).not.toHaveBeenCalled();
});

it("shows a timed-out verification as inconclusive without allowing apply", async () => {
  mocks.startManualMovePreview.mockResolvedValue({ job: {
    ...ready, status: "failed", result: null,
    message: "Verificação inconclusiva",
    error: "A verificação atingiu o limite de tempo. Não foi demonstrada a impossibilidade do movimento; o plano não foi alterado.",
  } });
  render(<MoveLotModal {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  expect(await screen.findByText(/Não foi demonstrada a impossibilidade/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Aplicar movimento" })).toBeNull();
  expect(mocks.applyManualMove).not.toHaveBeenCalled();
  expect(useDataStore.getState().planRevision).toBe(21);
});

it("clears the previous request's failure when editing the target", async () => {
  mocks.startManualMovePreview.mockResolvedValue({ job: {
    ...ready, status: "failed", result: null,
    error: "Não foi demonstrada a impossibilidade do movimento.",
  } });
  render(<MoveLotModal {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  expect(await screen.findByText(/Não foi demonstrada a impossibilidade/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Início exato da produção"), { target: { value: "11:40" } });
  expect(screen.queryByText(/Não foi demonstrada a impossibilidade/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Aplicar movimento" })).toBeNull();
  expect(mocks.applyManualMove).not.toHaveBeenCalled();
  expect(useDataStore.getState().planRevision).toBe(21);
});

it("does not present a bounded search failure as proven physical impossibility", async () => {
  mocks.startManualMovePreview.mockResolvedValue({ job: {
    ...ready, status: "failed", result: null,
    message: "Verificação inconclusiva",
    error: "A pesquisa de reorganização e a tentativa mantendo os restantes lotes fixos não produziram um candidato completo válido. Não foi demonstrada a impossibilidade do movimento; o plano não foi alterado.",
  } });
  render(<MoveLotModal {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "Verificar riscos" }));
  expect(await screen.findByText(/Não foi demonstrada a impossibilidade/)).toBeTruthy();
  expect(screen.queryByText(/Não há capacidade física/)).toBeNull();
  expect(screen.queryByRole("button", { name: "Aplicar movimento" })).toBeNull();
  expect(mocks.applyManualMove).not.toHaveBeenCalled();
  expect(useDataStore.getState().planRevision).toBe(21);
});

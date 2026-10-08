import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CTPResult, SimulateResponse } from "../src/api/types";

const mocks = vi.hoisted(() => ({
  simulate: vi.fn(), simulateApply: vi.fn(), checkCTP: vi.fn(), applyCTP: vi.fn(),
  getPlanView: vi.fn(), getOps: vi.fn(), getWorkdays: vi.fn(), getScenarios: vi.fn(),
  saveScenario: vi.fn(), applySavedScenario: vi.fn(), revertSimulation: vi.fn(), prompt: vi.fn(),
}));
vi.mock("../src/api/endpoints", () => mocks);
vi.mock("../src/components/ui/confirmContext", () => ({ useConfirm: () => ({ prompt: mocks.prompt }) }));
import { SimulatorPanel } from "../src/pages/SimulatorPage";
import { useSimulatorStore } from "../src/stores/useSimulatorStore";
import { useDataStore } from "../src/stores/useDataStore";
import { useAppStore } from "../src/stores/useAppStore";
import { ApiError } from "../src/api/client";
import { approvalImpactMessage } from "../src/lib/gateApproval";

const identity = { candidate_id: "c1", dataset_id: "d1", base_revision: 21, input_fingerprint: "in", candidate_fingerprint: "out" };
const mutations = [{ type: "machine_down", params: { machine_id: "M1", start: "0", end: "1" } }];
const gate = { status: "applicable", apply_decision: "auto_applicable", physical_gate_passed: true, requires_approval: false, approval_reasons: [] };
const preview = { ...identity, summary: ["Verified scenario"], segments: [], gate_report: gate,
  delta: { otd_before: 100, otd_after: 99, otd_d_before: 100, otd_d_after: 99, setups_before: 1, setups_after: 1,
    tardy_before: 0, tardy_after: 1, earliness_before: 1, earliness_after: 1 } } as SimulateResponse;
const ctp = { ...identity, sku: "SKU", qty_requested: 10, feasible: true, latest_day: null, earliest_end_day: null,
  machine: "M1", confidence: "high", slack_min: 100, required_min: 10, prod_days: 1 } as CTPResult;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { resolve, promise };
}
const snapshot = { dataset_id: "d1", plan_revision: 22, score: {}, gate_report: gate, config: {}, segments: [], lots: [],
  workdays: [], capacity: {}, blocked_days: {}, learning: null, active_mutations: mutations, manual_edits: [], can_revert: true };

beforeEach(() => {
  vi.resetAllMocks();
  useDataStore.getState().clear();
  useDataStore.setState({ datasetId: "d1", planRevision: 21, config: { machines: { M1: { active: true } } } as never });
  useAppStore.setState({ accessMode: "edit" });
  mocks.getOps.mockResolvedValue([{ sku: "SKU", demand: [0, 10] }]);
  mocks.getWorkdays.mockResolvedValue(["2026-09-17", "2026-09-18"]);
  mocks.getScenarios.mockResolvedValue({ scenarios: [] });
  mocks.getPlanView.mockResolvedValue(snapshot);
  mocks.simulate.mockResolvedValue(preview);
  mocks.simulateApply.mockResolvedValue({ plan_revision: 22, summary: [] });
  mocks.checkCTP.mockResolvedValue(ctp);
  mocks.applyCTP.mockResolvedValue({ status: "applied" });
  mocks.prompt.mockResolvedValue("reviewed");
  useSimulatorStore.getState().setMutations([{ ...mutations[0], _key: 1 }]);
});
afterEach(() => { cleanup(); useDataStore.getState().clear(); useAppStore.setState({ accessMode: "edit" }); });

it("keeps robustness out of the approval dialog, even for legacy reasons", () => {
  const message = approvalImpactMessage({
    apply_decision: "approval_required",
    requires_approval: true,
    approval_reasons: ["robustness_not_evaluated", "robustness_below_threshold", "delivery_risk"],
    metrics: {
      tardy_count: 5,
      robustness_evaluated_samples: 0,
      robustness_success_probability_pct: 0,
    },
  } as never);

  expect(message).not.toMatch(/robustez/i);
  expect(message).toContain("Requer decisão do planeador por: há lotes que acabam depois do prazo de produção.");
  expect(message).toContain("Impacto previsto: 5 lotes acabam depois do prazo de produção.");
});

async function simulatePreview() {
  render(<SimulatorPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Simular" }));
  return screen.findByRole("button", { name: "Aplicar no Gantt" });
}
async function verifyCTP() {
  render(<SimulatorPanel />);
  await screen.findByRole("option", { name: "SKU", selected: false });
  fireEvent.change(screen.getByRole("combobox", { name: "SKU da promessa" }), { target: { value: "SKU" } });
  fireEvent.change(screen.getByPlaceholderText("Quantidade"), { target: { value: "10" } });
  fireEvent.change(screen.getByPlaceholderText("Entrega cliente (dia)"), { target: { value: "1" } });
  fireEvent.click(screen.getByRole("button", { name: "Verificar" }));
  return screen.findByRole("button", { name: "Aplicar ao Gantt" });
}

it("applies the verified mutation snapshot and keeps the same candidate through approval", async () => {
  mocks.simulateApply.mockRejectedValueOnce(new ApiError(409, "approval", { gate_report: { ...gate, apply_decision: "approval_required", requires_approval: true } }));
  fireEvent.click(await simulatePreview());
  await waitFor(() => expect(mocks.simulateApply).toHaveBeenCalledTimes(2));
  expect(mocks.simulateApply.mock.calls[0]).toEqual([mutations, undefined, preview]);
  expect(mocks.simulateApply.mock.calls[1]).toEqual([mutations, { reason: "reviewed", author: "planeador" }, preview]);
  await waitFor(() => expect(useSimulatorStore.getState().result).toBeNull());
});

it.each(["edit", "clear", "unmount"])("does not resurrect a delayed simulation after %s", async (action) => {
  const pending = deferred<SimulateResponse>();
  mocks.simulate.mockReturnValue(pending.promise);
  const view = render(<SimulatorPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Simular" }));
  act(() => {
    if (action === "edit") useSimulatorStore.getState().updateMutationParam(1, "end", "2");
    if (action === "clear") useSimulatorStore.getState().clear();
    if (action === "unmount") view.unmount();
  });
  await act(async () => { pending.resolve(preview); });
  expect(useSimulatorStore.getState().result).toBeNull();
});

it("clears a previously verified simulation when a recheck fails", async () => {
  await simulatePreview();
  mocks.simulate.mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "Simular" }));
  await screen.findByText(/offline/);
  expect(screen.queryByRole("button", { name: "Aplicar no Gantt" })).toBeNull();
});

it("will not apply a cached preview against a different dataset", async () => {
  await simulatePreview();
  act(() => { useDataStore.setState({ datasetId: "d2" }); });
  const apply = screen.getByRole<HTMLButtonElement>("button", { name: "Aplicar no Gantt" });
  expect(apply.disabled).toBe(true);
  fireEvent.click(apply);
  expect(mocks.simulateApply).not.toHaveBeenCalled();
});

it("does not erase draft edits made while apply was in flight", async () => {
  const pending = deferred<unknown>();
  mocks.simulateApply.mockReturnValue(pending.promise);
  fireEvent.click(await simulatePreview());
  act(() => useSimulatorStore.getState().updateMutationParam(1, "end", "3"));
  await act(async () => { pending.resolve({ plan_revision: 22, summary: [] }); });
  expect(useSimulatorStore.getState().mutations[0].params.end).toBe("3");
});

it("invalidates the CTP card when the quantity changes", async () => {
  await verifyCTP();
  fireEvent.change(screen.getByPlaceholderText("Quantidade"), { target: { value: "100" } });
  expect(screen.queryByRole("button", { name: "Aplicar ao Gantt" })).toBeNull();
  expect(useSimulatorStore.getState().ctpRequest).toBeNull();
  expect(mocks.applyCTP).not.toHaveBeenCalled();
});

it("clears the CTP card on failed verification and rejects a late response after editing", async () => {
  await verifyCTP();
  mocks.checkCTP.mockRejectedValueOnce(new Error("offline"));
  fireEvent.click(screen.getByRole("button", { name: "Verificar" }));
  await screen.findByText(/offline/);
  expect(screen.queryByRole("button", { name: "Aplicar ao Gantt" })).toBeNull();
  const pending = deferred<CTPResult>();
  mocks.checkCTP.mockReturnValueOnce(pending.promise);
  fireEvent.click(screen.getByRole("button", { name: "Verificar" }));
  fireEvent.change(screen.getByPlaceholderText("Quantidade"), { target: { value: "100" } });
  await act(async () => { pending.resolve(ctp); });
  expect(useSimulatorStore.getState().ctpResult).toBeNull();
});

it("uses the verified CTP request for approval and consumes it across remount", async () => {
  mocks.applyCTP.mockRejectedValueOnce(new ApiError(409, "approval", { gate_report: { ...gate, requires_approval: true } }));
  fireEvent.click(await verifyCTP());
  await waitFor(() => expect(mocks.applyCTP).toHaveBeenCalledTimes(2));
  expect(mocks.applyCTP.mock.calls[0]).toEqual(["SKU", 10, 1, undefined, ctp]);
  expect(mocks.applyCTP.mock.calls[1]).toEqual(["SKU", 10, 1, { reason: "reviewed", author: "planeador" }, ctp]);
  await waitFor(() => expect(useSimulatorStore.getState().ctpResult).toBeNull());
  cleanup();
  render(<SimulatorPanel />);
  expect(screen.queryByRole("button", { name: "Aplicar ao Gantt" })).toBeNull();
});

it("allows simulation in read-only mode but disables applying and saving it", async () => {
  useAppStore.setState({ accessMode: "view" });
  const apply = await simulatePreview() as HTMLButtonElement;
  expect(apply.disabled).toBe(true);
  fireEvent.change(screen.getByRole("textbox", { name: "Nome para guardar o cenário" }), { target: { value: "Scenario" } });
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Guardar cenário" }).disabled).toBe(true);
});

it("keeps a blocked result visible and allows saving it as a scenario", async () => {
  mocks.simulate.mockResolvedValueOnce({
    ...preview,
    summary: ["Resultado inviável disponível para análise"],
    gate_report: {
      ...gate,
      status: "operational_sequence_blocked",
      apply_decision: "blocked",
      physical_gate_passed: true,
    },
  });
  mocks.saveScenario.mockResolvedValueOnce({
    status: "saved",
    scenario: { id: "blocked-scenario", name: "Cenário limite" },
  });

  render(<SimulatorPanel />);
  fireEvent.click(screen.getByRole("button", { name: "Simular" }));

  expect(await screen.findByText("Resultado inviável disponível para análise")).toBeTruthy();
  const apply = screen.getByRole<HTMLButtonElement>("button", {
    name: "Resultado não aplicável ao plano",
  });
  expect(apply.disabled).toBe(true);

  fireEvent.change(screen.getByRole("textbox", { name: "Nome para guardar o cenário" }), {
    target: { value: "Cenário limite" },
  });
  const save = screen.getByRole<HTMLButtonElement>("button", { name: "Guardar cenário" });
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  await waitFor(() => expect(mocks.saveScenario).toHaveBeenCalledWith(
    "Cenário limite",
    "",
    mutations,
    expect.objectContaining({ candidate_id: "c1", candidate_fingerprint: "out" }),
  ));
});

it("preserves a scenario name edited while the verified candidate is being saved", async () => {
  await simulatePreview();
  const save = deferred<unknown>();
  mocks.saveScenario.mockReturnValue(save.promise);
  const name = screen.getByRole<HTMLInputElement>("textbox", { name: "Nome para guardar o cenário" });
  fireEvent.change(name, { target: { value: "Submitted" } });
  fireEvent.click(screen.getByRole("button", { name: "Guardar cenário" }));
  fireEvent.change(name, { target: { value: "Next scenario" } });
  await act(async () => save.resolve({ scenario: { id: "saved", name: "Submitted" } }));
  expect(name.value).toBe("Next scenario");
  expect(mocks.saveScenario).toHaveBeenCalledWith("Submitted", "", mutations, preview);
});

it("keeps a saved scenario conflict visible without retrying or discarding the draft", async () => {
  mocks.getScenarios.mockResolvedValue({ scenarios: [{ id: "saved", name: "Saved", gate_status: "applicable" }] });
  mocks.applySavedScenario.mockRejectedValue(new ApiError(409, "stale scenario"));
  render(<SimulatorPanel />);
  fireEvent.click(await screen.findByRole("button", { name: "Aplicar como realidade" }));
  await screen.findByText(/stale scenario/);
  expect(mocks.applySavedScenario).toHaveBeenCalledTimes(1);
  expect(useSimulatorStore.getState().mutations).toHaveLength(1);
});

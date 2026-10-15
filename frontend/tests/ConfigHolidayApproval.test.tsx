// NOK #5 (07/10/2026): adding a non-working day must ask for a justification
// and apply the presented candidate, instead of failing with an alert.
// Since 16/10/2026 the day goes to the pending list and «Aplicar» starts one
// replan job; only a candidate that needs approval asks for the justification.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import type { FactoryConfig } from "../src/api/types";

const mocks = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getOps: vi.fn().mockResolvedValue([]),
  getCatalog: vi.fn().mockResolvedValue({ source_policy: {}, machines: [], tools: [], references: [] }),
  getReplans: vi.fn().mockResolvedValue({ jobs: [] }),
  getTrust: vi.fn().mockResolvedValue(null),
  getPlanView: vi.fn(),
  startReplan: vi.fn(),
  getReplan: vi.fn(),
  applyReplan: vi.fn(),
  cancelReplan: vi.fn().mockResolvedValue({ job: { id: "job", status: "cancelled" } }),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/endpoints")>()),
  ...mocks,
}));

import { ConfigPage } from "../src/pages/ConfigPage";
import { ConfirmProvider } from "../src/components/ui/ConfirmProvider";
import { useDataStore } from "../src/stores/useDataStore";
import { useConfigDraftStore } from "../src/stores/useConfigDraftStore";

const config: FactoryConfig = {
  plan_revision: 1,
  name: "Nikufra",
  site: "Fábrica",
  timezone: "Europe/Lisbon",
  shifts: [
    { id: "A", label: "Turno A", start_min: 360, end_min: 840, duration_min: 480 },
  ],
  day_capacity_min: 960,
  machines: {},
  tools: {},
  twins: [],
  operators: {},
  holidays: [],
  extra_workdays: [],
  unavailability: { machines: [], tools: [], operators: [] },
  setup_overrides: [],
  setup_families: {},
  earliness_policy: "jit",
  material_release_days: 5,
  early_window_enforcement: "soft",
  oee_default: 0.8,
  subcontract_skus: [],
  sku_planning_rules: {},
  subcontract_companies: [],
  sku_subcontracts: {},
  setup_crews: 1,
  setup_crews_by_group: {},
  jit_enabled: true,
  jit_buffer_pct: 0,
  jit_threshold: 0,
  jit_max_retries: 1,
  jit_earliness_target: 5,
  max_edd_gap: 0,
  max_edd_span: 0,
  edd_swap_tolerance: 0,
  edd_assign_threshold: 0,
  campaign_window: 0,
  urgency_threshold: 0,
  interleave_enabled: false,
  auto_buffer: false,
  vns_enabled: false,
  vns_max_iter: 0,
  compact_enabled: false,
  weight_earliness: 0,
  weight_setups: 0,
  weight_balance: 0,
  eco_lot_mode: "soft",
};

const approvalJob = {
  id: "job", status: "ready", progress: 100, warnings: [], base_revision: 1,
  message: "Candidato pronto", reason: "Dia sem produção", created_at: new Date().toISOString(),
  result: {
    score: { otd: 97, tardy_count: 9 }, n_segments: 10,
    gate_report: {
      status: "best_effort", apply_decision: "approval_required", requires_approval: true,
      approval_reasons: ["delivery_risk", "long_production"], metrics: { tardy_count: 9 },
    },
  },
};

beforeEach(() => {
  mocks.getConfig.mockResolvedValue(config);
  mocks.getPlanView.mockResolvedValue({ dataset_id: "d1", plan_revision: 2, config, score: {}, gate_report: {},
    lots: [], segments: [], workdays: [], blocked_days: {}, capacity: {}, learning: null,
    active_mutations: [], manual_edits: [], can_revert: false });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  useConfigDraftStore.getState().discard();
  useDataStore.getState().clear();
});

async function addDay(date = "2026-12-24") {
  render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Calendário" }));
  const input = document.querySelector<HTMLInputElement>('input[type="date"]')!;
  fireEvent.change(input, { target: { value: date } });
  fireEvent.click(screen.getByRole("button", { name: "Adicionar dia" }));
  expect(mocks.startReplan).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
}

it("pede justificação e aplica o candidato apresentado", async () => {
  mocks.startReplan.mockResolvedValue({ job: approvalJob });
  mocks.applyReplan.mockResolvedValue({ job: { ...approvalJob, status: "completed" } });

  await addDay();
  const dialog = await screen.findByRole("dialog");

  expect(mocks.startReplan).toHaveBeenCalledWith(expect.objectContaining({
    config_updates: { holiday_additions: ["2026-12-24"] },
  }));
  expect(within(dialog).getByText("Aplicar plano com exceções?")).toBeTruthy();
  expect(dialog.textContent).toContain("há lotes que acabam depois do prazo de produção");
  expect(mocks.applyReplan).not.toHaveBeenCalled();
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Fecho de Natal acordado" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar e aplicar" }));

  await waitFor(() => expect(mocks.applyReplan).toHaveBeenCalledWith(
    "job", { reason: "Fecho de Natal acordado", author: "planeador" }, 1,
  ));
  expect(mocks.applyReplan).toHaveBeenCalledTimes(1);
  expect(mocks.startReplan).toHaveBeenCalledTimes(1);
});

it("cancelar não aplica nada", async () => {
  mocks.startReplan.mockResolvedValue({ job: approvalJob });
  const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);

  await addDay();
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: /Cancelar/ }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(mocks.applyReplan).not.toHaveBeenCalled();
  expect(alert).not.toHaveBeenCalled();
  // The day stays in the list.
  expect(screen.getByText("Dia sem produção: 24/12/2026")).toBeTruthy();
});

it("uma recusa mostra as causas na página, sem alerta do browser (15/10/2026)", async () => {
  mocks.startReplan.mockRejectedValueOnce(new ApiError(400, "Plano inválido: 1 conflito.", {
    code: "invalid_plan",
    message: "Plano inválido: 1 conflito.",
    causes: ["Procura e lotes não reconciliam: 43940 peça(s) em falta face à procura."],
  }));
  const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);

  await addDay("2026-12-07");

  expect(await screen.findByText("Erro: Plano inválido: 1 conflito.")).toBeTruthy();
  expect(screen.getByText("Porquê:")).toBeTruthy();
  expect(screen.getByText(/43940 peça\(s\) em falta/)).toBeTruthy();
  expect(alert).not.toHaveBeenCalled();
  expect(screen.getByText("Dia sem produção: 07/12/2026")).toBeTruthy();
});

it("um cálculo que falha mostra as causas e mantém a lista", async () => {
  mocks.startReplan.mockResolvedValue({ job: { ...approvalJob, status: "running", result: null } });
  mocks.getReplan.mockResolvedValue({ job: {
    ...approvalJob, status: "failed", result: null, code: "invalid_plan",
    message: "Plano inválido: 1 conflito.",
    causes: ["A PRM042 não tem capacidade para a encomenda de 09/12."],
  } });

  await addDay();

  expect(await screen.findByText("A PRM042 não tem capacidade para a encomenda de 09/12.", {}, { timeout: 4000 })).toBeTruthy();
  expect(mocks.applyReplan).not.toHaveBeenCalled();
  expect(screen.getByText("Dia sem produção: 24/12/2026")).toBeTruthy();
  expect(useConfigDraftStore.getState().applying).toBe(false);
});

// NOK #5 (07/10/2026): adding a non-working day must ask for a justification
// and apply the presented candidate, instead of failing with an alert.
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
  addHoliday: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/endpoints")>()),
  ...mocks,
}));

import { ConfigPage } from "../src/pages/ConfigPage";
import { ConfirmProvider } from "../src/components/ui/ConfirmProvider";
import { useDataStore } from "../src/stores/useDataStore";

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
  max_run_days: 4,
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

const approvalRequired = () => new ApiError(409, "O candidato exige aprovação explícita", {
  message: "O candidato exige aprovação explícita: delivery_risk, long_production.",
  gate_report: {
    requires_approval: true, apply_decision: "approval_required",
    approval_reasons: ["delivery_risk", "long_production"], metrics: { tardy_count: 9 },
  },
});

beforeEach(() => {
  mocks.getConfig.mockResolvedValue(config);
  mocks.getPlanView.mockResolvedValue({ dataset_id: "d1", plan_revision: 2, config, score: {}, gate_report: {},
    lots: [], segments: [], workdays: [], blocked_days: {}, capacity: {}, learning: null,
    active_mutations: [], manual_edits: [], can_revert: false });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  useDataStore.getState().clear();
});

async function addDay() {
  render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
  fireEvent.click(await screen.findByRole("button", { name: "Calendário" }));
  const input = document.querySelector<HTMLInputElement>('input[type="date"]')!;
  fireEvent.change(input, { target: { value: "2026-12-24" } });
  fireEvent.click(screen.getByRole("button", { name: "Adicionar dia" }));
  return screen.findByRole("dialog");
}

it("pede justificação e aplica o candidato apresentado", async () => {
  mocks.addHoliday.mockRejectedValueOnce(approvalRequired()).mockResolvedValueOnce({ status: "ok" });

  const dialog = await addDay();

  expect(within(dialog).getByText("Aplicar alteração com exceções?")).toBeTruthy();
  expect(dialog.textContent).toContain("há lotes que acabam depois do prazo de produção");
  expect(mocks.addHoliday).toHaveBeenCalledTimes(1);
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Fecho de Natal acordado" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar e aplicar" }));

  await waitFor(() => expect(mocks.addHoliday).toHaveBeenLastCalledWith(
    "2026-12-24", { reason: "Fecho de Natal acordado", author: "planeador" },
  ));
  expect(mocks.addHoliday).toHaveBeenCalledTimes(2);
});

it("cancelar não aplica nada", async () => {
  mocks.addHoliday.mockRejectedValueOnce(approvalRequired());
  const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);

  const dialog = await addDay();
  fireEvent.click(within(dialog).getByRole("button", { name: /Cancelar/ }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(mocks.addHoliday).toHaveBeenCalledTimes(1);
  expect(alert).not.toHaveBeenCalled();
});

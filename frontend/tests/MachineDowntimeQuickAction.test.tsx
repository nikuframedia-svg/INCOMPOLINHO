// Gantt «Parar máquina» (16/10/2026): «Aplicar paragem» first shows the
// impact in one confirmation; only «Aplicar» applies exactly that candidate.
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { FactoryConfig, SimulateResponse } from "../src/api/types";

const mocks = vi.hoisted(() => ({ simulate: vi.fn() }));

vi.mock("../src/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/endpoints")>()),
  ...mocks,
}));

import { MachineDowntimeQuickAction } from "../src/components/MachineDowntimeQuickAction";
import { ConfirmProvider } from "../src/components/ui/ConfirmProvider";
import { useDataStore } from "../src/stores/useDataStore";

const candidate = {
  candidate_id: "cand-1",
  dataset_id: "d1",
  base_revision: 7,
  input_fingerprint: "in",
  candidate_fingerprint: "out",
  score_baseline: {},
  score_scenario: {},
  delta: {
    otd_before: 100, otd_after: 98, otd_d_before: 100, otd_d_after: 99,
    setups_before: 178, setups_after: 181, earliness_before: 3, earliness_after: 3,
    tardy_before: 1, tardy_after: 3,
  },
  time_ms: 10,
  summary: [],
  segments: [],
  lots: [],
  gate_report: { metrics: { orders_late: 2 } },
} as unknown as SimulateResponse;

const applySimulation = vi.fn();

beforeEach(() => {
  mocks.simulate.mockResolvedValue(candidate);
  applySimulation.mockResolvedValue({ status: "ok" });
  useDataStore.setState({
    datasetId: "d1",
    planRevision: 7,
    config: { machines: { PRM031: { group: "Grandes", active: true, day_capacity_min: null, oee: null } } } as unknown as FactoryConfig,
    gateReport: { metrics: { orders_late: 1 } } as never,
    activeMutations: [],
    applySimulation,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function openStoppage() {
  const onApplied = vi.fn();
  render(
    <ConfirmProvider>
      <MachineDowntimeQuickAction currentDay={0} workdays={["2026-10-19", "2026-10-20"]} onApplied={onApplied} />
    </ConfirmProvider>,
  );
  fireEvent.change(screen.getByLabelText("Máquina a parar"), { target: { value: "PRM031" } });
  fireEvent.click(screen.getByRole("button", { name: "Aplicar paragem" }));
  return onApplied;
}

it("mostra o impacto antes de aplicar e aplica exatamente o candidato simulado", async () => {
  const onApplied = openStoppage();

  const dialog = await screen.findByRole("dialog");
  expect(mocks.simulate).toHaveBeenCalledWith([{ type: "machine_down", params: { machine_id: "PRM031", start: 0, end: 0 } }]);
  expect(applySimulation).not.toHaveBeenCalled();
  expect(within(dialog).getByText("Aplicar paragem de PRM031?")).toBeTruthy();
  expect(within(dialog).getByText("Encomendas atrasadas")).toBeTruthy();
  expect(within(dialog).getByText("1 → 2")).toBeTruthy();
  expect(within(dialog).getByText("Setups")).toBeTruthy();
  expect(within(dialog).getByText("178 → 181")).toBeTruthy();

  fireEvent.click(within(dialog).getByRole("button", { name: "Aplicar" }));

  await waitFor(() => expect(applySimulation).toHaveBeenCalledWith(
    [{ type: "machine_down", params: { machine_id: "PRM031", start: 0, end: 0 } }],
    undefined,
    candidate,
  ));
  await waitFor(() => expect(onApplied).toHaveBeenCalledWith([0, 0]));
});

it("cancelar não aplica nada", async () => {
  const onApplied = openStoppage();

  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));

  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(applySimulation).not.toHaveBeenCalled();
  expect(onApplied).not.toHaveBeenCalled();
});

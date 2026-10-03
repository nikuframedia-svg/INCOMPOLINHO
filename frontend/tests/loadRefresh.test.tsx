import { afterEach, expect, it, vi } from "vitest";

vi.mock("../src/api/endpoints", () => ({
  getPlanView: vi.fn().mockResolvedValue({
    plan_revision: 1, score: { otd: 100 }, gate_report: {}, segments: [], lots: [],
    dataset_id: "dataset-1", active_mutations: [], manual_edits: [], can_revert: false, learning: null,
    config: {}, capacity: {}, workdays: ["2026-03-16"],
    blocked_days: {
      workdays: ["2026-03-16"], holidays: [], machine_blocks: [], tool_blocks: [],
      machine_intervals: [], tool_intervals: [], inactive_machines: [],
    },
  }),
  getLearning: vi.fn().mockResolvedValue({}),
  getManualEdits: vi.fn().mockResolvedValue({ edits: [] }),
  canRevert: vi.fn().mockResolvedValue({ can_revert: false }),
  getActiveMutations: vi.fn().mockResolvedValue({ active: false, mutations: [] }),
  getWorkdays: vi.fn().mockResolvedValue(["2026-03-16"]),
  getBlockedDays: vi.fn().mockResolvedValue({
    workdays: ["2026-03-16"], holidays: [], machine_blocks: [], tool_blocks: [],
    machine_intervals: [], tool_intervals: [], inactive_machines: [],
  }),
  simulateApply: vi.fn(), revertSimulation: vi.fn(),
}));

import { getPlanView } from "../src/api/endpoints";
import { useDataStore } from "../src/stores/useDataStore";
import type { Score } from "../src/api/types";

afterEach(() => { useDataStore.getState().clear(); });

it("mantém os dados anteriores se uma leitura essencial falhar depois do carregamento", async () => {
  const oldScore = { otd: 91 } as Score;
  useDataStore.setState({ score: oldScore });
  vi.mocked(getPlanView).mockRejectedValueOnce(new Error("network"));
  await expect(useDataStore.getState().refreshAll({ strict: true })).rejects.toThrow(/atualizar os dados/);
  expect(useDataStore.getState().score).toBe(oldScore);
  vi.mocked(getPlanView).mockResolvedValueOnce({
    plan_revision: 2,
    dataset_id: "dataset-1", active_mutations: [], manual_edits: [], can_revert: false, learning: null,
    score: { otd: 100 } as Score,
    gate_report: {}, segments: [], lots: [], config: {}, capacity: {},
    workdays: ["2026-03-16"],
    blocked_days: {
      workdays: ["2026-03-16"], holidays: [], machine_blocks: [], tool_blocks: [],
      machine_intervals: [], tool_intervals: [], inactive_machines: [],
    },
  } as never);
  await useDataStore.getState().refreshAll({ strict: true });
  expect(useDataStore.getState().score?.otd).toBe(100);
});

it("não publica uma fotografia parcial quando a leitura atómica falha", async () => {
  vi.mocked(getPlanView).mockRejectedValueOnce(new Error("network"));
  await expect(useDataStore.getState().refreshAll()).resolves.toBe("failed");
  expect(useDataStore.getState().score).toBeNull();
  expect(useDataStore.getState().segments).toBeNull();
});

it("renova o calendário no mesmo ciclo dos dados do plano", async () => {
  await useDataStore.getState().refreshAll({ strict: true });

  expect(useDataStore.getState().workdays).toEqual(["2026-03-16"]);
  expect(useDataStore.getState().blockedDays?.workdays).toEqual(["2026-03-16"]);
});

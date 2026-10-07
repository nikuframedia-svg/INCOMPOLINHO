// False "Erro: Aplicado; ecrã por atualizar" after a saved change (07/10/2026).
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getPlanView: vi.fn() }));
vi.mock("../src/api/endpoints", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/endpoints")>()),
  ...mocks,
}));

import { useDataStore } from "../src/stores/useDataStore";
import {
  assertRefreshed,
  isAppliedRefreshError,
  RefreshError,
  refreshAfterCommit,
} from "../src/lib/refreshOutcome";

const view = (revision: number) => ({
  dataset_id: "d1", plan_revision: revision, config: {}, score: {}, gate_report: {},
  lots: [], segments: [], workdays: [], blocked_days: {}, capacity: {}, learning: null,
  active_mutations: [], manual_edits: [], can_revert: false,
});

beforeEach(() => useDataStore.getState().clear());
afterEach(() => vi.clearAllMocks());

it("a refresh overtaken by a newer one reports the newer outcome", async () => {
  let releaseFirst!: (value: unknown) => void;
  mocks.getPlanView
    .mockReturnValueOnce(new Promise((resolve) => { releaseFirst = resolve; }))
    .mockResolvedValueOnce(view(8));

  const afterSave = useDataStore.getState().refreshAll();
  const background = useDataStore.getState().refreshAll();
  expect(await background).toBe("updated");
  releaseFirst(view(8));

  expect(await afterSave).toBe("updated");
  expect(() => assertRefreshed("updated", true)).not.toThrow();
  expect(useDataStore.getState().planRevision).toBe(8);
});

it("retries only the read after a saved change", async () => {
  const refresh = vi.fn()
    .mockResolvedValueOnce("failed")
    .mockResolvedValueOnce("updated");

  expect(await refreshAfterCommit(refresh, [0, 0])).toBe("updated");
  expect(refresh).toHaveBeenCalledTimes(2);
});

it("reports a saved change with a stale screen without calling it an error", async () => {
  const refresh = vi.fn().mockResolvedValue("failed");

  const outcome = await refreshAfterCommit(refresh, [0, 0]);
  expect(refresh).toHaveBeenCalledTimes(3);
  let error: unknown;
  try { assertRefreshed(outcome, true); } catch (caught) { error = caught; }
  expect(error).toBeInstanceOf(RefreshError);
  expect(isAppliedRefreshError(error)).toBe(true);
  expect((error as Error).message).toContain("A alteração foi guardada");
  expect((error as Error).message).not.toMatch(/^Erro/);
});

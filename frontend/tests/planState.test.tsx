import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { CTPResult, PlanView, SimulateResponse } from "../src/api/types";

vi.mock("../src/api/endpoints", () => ({
  getPlanView: vi.fn(), simulateApply: vi.fn(), revertSimulation: vi.fn(),
  getLearning: vi.fn(), getActiveMutations: vi.fn(), getManualEdits: vi.fn(), canRevert: vi.fn(),
}));
import * as api from "../src/api/endpoints";
import { useDataStore } from "../src/stores/useDataStore";
import { useSimulatorStore } from "../src/stores/useSimulatorStore";
import { getPlanRevision } from "../src/lib/planRevision";

const mutations = [{ type: "machine_down", params: { machine_id: "M1", start: 2, end: 2 } }];
const candidate = { candidate_id: "c1", dataset_id: "d1", base_revision: 21, input_fingerprint: "input", candidate_fingerprint: "result" } as SimulateResponse;
function snapshot(revision: number, extra: Partial<PlanView> = {}): PlanView {
  return { dataset_id: "d1", plan_revision: revision, score: { otd: revision }, gate_report: {}, config: {},
    segments: [], lots: [], workdays: [], blocked_days: {}, capacity: {}, learning: null,
    active_mutations: [], manual_edits: [], can_revert: false, ...extra } as PlanView;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => { useDataStore.getState().clear(); vi.resetAllMocks(); });
afterEach(() => { useDataStore.getState().clear(); });

it("ignores late refreshes and advances the command revision only with the accepted snapshot", async () => {
  const old = deferred<PlanView>();
  vi.mocked(api.getPlanView).mockReturnValueOnce(old.promise).mockResolvedValueOnce(snapshot(22));
  const first = useDataStore.getState().refreshAll();
  expect(await useDataStore.getState().refreshAll()).toBe("updated");
  old.resolve(snapshot(21));
  // The overtaken refresh reports the newer outcome; its old data is ignored.
  expect(await first).toBe("updated");
  expect(useDataStore.getState().planRevision).toBe(22);
  expect(useDataStore.getState().score?.otd).toBe(22);
  expect(getPlanRevision()).toBe(22);
});

it("does not resurrect cleared data or previews from a pending read", async () => {
  const pending = deferred<PlanView>();
  vi.mocked(api.getPlanView).mockReturnValueOnce(pending.promise);
  const refresh = useDataStore.getState().refreshAll();
  useDataStore.getState().clear();
  pending.resolve(snapshot(21));
  await refresh;
  expect(useDataStore.getState().datasetId).toBeNull();
  expect(useDataStore.getState().score).toBeNull();
  expect(getPlanRevision()).toBe(0);
});

it("reads all displayed flags and learning from one PlanView, without auxiliary reads", async () => {
  const learning = { source: "same revision" } as never;
  const manual_edits = [{ id: "move" }] as never;
  vi.mocked(api.getPlanView).mockResolvedValue(snapshot(21, { active_mutations: mutations, can_revert: true, manual_edits, learning }));
  await useDataStore.getState().refreshAll({ strict: true });
  expect(useDataStore.getState()).toMatchObject({ isSimulated: true, activeMutations: mutations, canRevert: true, manualEdits: manual_edits, learning });
  for (const fn of [api.getLearning, api.getActiveMutations, api.getManualEdits, api.canRevert]) expect(fn).not.toHaveBeenCalled();
});

it("keeps the complete old snapshot on network or incomplete-response failure", async () => {
  vi.mocked(api.getPlanView).mockResolvedValueOnce(snapshot(21, { active_mutations: mutations, can_revert: true }));
  await useDataStore.getState().refreshAll();
  const old = useDataStore.getState();
  vi.mocked(api.getPlanView).mockRejectedValueOnce(new Error("offline"));
  await expect(useDataStore.getState().refreshAll({ strict: true })).rejects.toThrow();
  expect(useDataStore.getState()).toBe(old);
  vi.mocked(api.getPlanView).mockResolvedValueOnce({ plan_revision: 22, score: { otd: 100 } } as PlanView);
  await expect(useDataStore.getState().refreshAll({ strict: true })).rejects.toThrow();
  expect(useDataStore.getState()).toBe(old);
});

it("revert preserves the prior nonempty mutations restored by the backend", async () => {
  vi.mocked(api.getPlanView).mockResolvedValue(snapshot(22, { active_mutations: mutations, can_revert: false }));
  await useDataStore.getState().revert();
  expect(api.revertSimulation).toHaveBeenCalledTimes(1);
  expect(useDataStore.getState()).toMatchObject({ isSimulated: true, activeMutations: mutations, canRevert: false });
});

it("does not overwrite a newer authoritative snapshot with an older apply response", async () => {
  useDataStore.setState({ datasetId: "d1", planRevision: 21 });
  vi.mocked(api.simulateApply).mockResolvedValue({ plan_revision: 22, can_revert: true, mutations, summary: ["old apply"] } as never);
  vi.mocked(api.getPlanView).mockResolvedValue(snapshot(23));
  await useDataStore.getState().applySimulation(mutations, undefined, candidate);
  expect(api.simulateApply).toHaveBeenCalledWith(mutations, undefined, candidate);
  expect(useDataStore.getState()).toMatchObject({ planRevision: 23, isSimulated: false, activeMutations: [], canRevert: false, simulationSummary: [] });
});

it("rejects a candidate from another dataset before sending apply", async () => {
  useDataStore.setState({ datasetId: "other", planRevision: 21 });
  await expect(useDataStore.getState().applySimulation(mutations, undefined, candidate)).rejects.toThrow(/plano mudou/);
  expect(api.simulateApply).not.toHaveBeenCalled();
});

it("reports an acknowledged apply followed by a failed refresh without applying twice", async () => {
  useDataStore.setState({ datasetId: "d1", planRevision: 21 });
  const generation = useSimulatorStore.getState().beginSimulation();
  useSimulatorStore.getState().acceptSimulation(generation, candidate, mutations);
  vi.mocked(api.simulateApply).mockResolvedValue({ plan_revision: 22, summary: [] } as never);
  vi.mocked(api.getPlanView).mockRejectedValue(new Error("offline"));
  vi.useFakeTimers();
  const applied = expect(useDataStore.getState().applySimulation(mutations, undefined, candidate)).rejects.toThrow(/A alteração foi guardada/);
  await vi.runAllTimersAsync();
  await applied;
  vi.useRealTimers();
  expect(api.simulateApply).toHaveBeenCalledTimes(1);
  expect(api.getPlanView).toHaveBeenCalledTimes(3);
  expect(useDataStore.getState().planRevision).toBe(21);
  expect(useSimulatorStore.getState().result).toBeNull();
});

it("invalidates previews when the plan base changes while preserving the draft", async () => {
  useDataStore.setState({ datasetId: "d1", planRevision: 21 });
  useSimulatorStore.getState().setMutations([{ ...mutations[0], _key: 1 }]);
  const generation = useSimulatorStore.getState().beginSimulation();
  useSimulatorStore.getState().acceptSimulation(generation, candidate, mutations);
  vi.mocked(api.getPlanView).mockResolvedValue(snapshot(22));
  await useDataStore.getState().refreshAll();
  expect(useSimulatorStore.getState().result).toBeNull();
  expect(useSimulatorStore.getState().mutations).toHaveLength(1);
});

it("retains a verified candidate across reads of the same base and lifecycle cleanup", async () => {
  useDataStore.setState({ datasetId: "d1", planRevision: 21 });
  const generation = useSimulatorStore.getState().beginSimulation();
  useSimulatorStore.getState().acceptSimulation(generation, candidate, mutations);
  useSimulatorStore.getState().cancelRequests();
  vi.mocked(api.getPlanView).mockResolvedValue(snapshot(21));
  await useDataStore.getState().refreshAll();
  expect(useSimulatorStore.getState().result).toBe(candidate);
  expect(useSimulatorStore.getState().acceptSimulation(generation, candidate, mutations)).toBe(false);
});

it.each(["edit", "clear", "unmount"])("rejects a delayed simulation response after %s", (action) => {
  const store = useSimulatorStore.getState();
  store.setMutations([{ ...mutations[0], _key: 1 }]);
  const generation = store.beginSimulation();
  if (action === "edit") store.updateMutationParam(1, "start", "3");
  if (action === "clear") store.clear();
  if (action === "unmount") store.cancelRequests();
  expect(store.acceptSimulation(generation, candidate, mutations)).toBe(false);
  expect(useSimulatorStore.getState().result).toBeNull();
});

it("binds CTP input and rejects an old response after input changes", () => {
  const store = useSimulatorStore.getState();
  store.setCtpInput("qty", "10");
  const generation = store.beginCtp();
  store.setCtpInput("qty", "100");
  expect(store.acceptCtp(generation, candidate as unknown as CTPResult, { sku: "SKU", qty: 10, deadline: 3 })).toBe(false);
  expect(useSimulatorStore.getState().ctpInput.qty).toBe("100");
  expect(useSimulatorStore.getState().ctpResult).toBeNull();
});

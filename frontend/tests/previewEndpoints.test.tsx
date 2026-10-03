import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, get, post } from "../src/api/client";
import { applyCTP, applyReplan, getConfig, getJournal, getPlanView, simulateApply, startReplan } from "../src/api/endpoints";
import { commitPlanRevision, getPlanRevision } from "../src/lib/planRevision";
import { useAppStore } from "../src/stores/useAppStore";

const candidate = { candidate_id: "candidate-a", dataset_id: "dataset-a", base_revision: 21, input_fingerprint: "input", candidate_fingerprint: "result" };
const mutations = [{ type: "machine_down", params: { machine_id: "M1", start: 2, end: 2 } }];
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => { localStorage.clear(); commitPlanRevision(99); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear(); commitPlanRevision(0); });

it("applies the exact simulation candidate at its own revision with a stable retry id", async () => {
  const fetch = vi.fn().mockResolvedValue(response({}));
  vi.stubGlobal("fetch", fetch);
  await simulateApply(mutations, undefined, candidate);
  fetch.mockResolvedValue(response({}));
  await simulateApply(mutations, { reason: "reviewed", author: "planner" }, candidate);
  const first = JSON.parse(fetch.mock.calls[0][1].body);
  const second = JSON.parse(fetch.mock.calls[1][1].body);
  expect(first).toMatchObject({ ...candidate, expected_revision: 21, mutations, approve_exceptions: false });
  expect(second).toMatchObject({ ...first, approve_exceptions: true, approval_reason: "reviewed", approval_author: "planner" });
  expect(first.request_id).toBeTruthy();
  expect(second.request_id).toBe(first.request_id);
});

it("binds CTP apply and its approval retry to the original request and candidate", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({})));
  vi.stubGlobal("fetch", fetch);
  await applyCTP("SKU", 10, 4, undefined, candidate);
  await applyCTP("SKU", 10, 4, { reason: "reviewed", author: "planner" }, candidate);
  const bodies = fetch.mock.calls.map(([, init]) => JSON.parse(init.body));
  for (const body of bodies) expect(body).toMatchObject({ ...candidate, expected_revision: 21, sku: "SKU", qty: 10, deadline: 4 });
  expect(bodies[0].request_id).toBe(bodies[1].request_id);
});

it("does not retry or rebase a stale configuration command", async () => {
  const fetch = vi.fn().mockResolvedValue(response({ detail: { code: "stale", current_revision: 100, message: "stale" } }, 409));
  vi.stubGlobal("fetch", fetch);
  await expect(startReplan({ reason: "shifts", config_updates: { shifts: [] }, expected_revision: 21 })).rejects.toMatchObject({ status: 409 });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetch.mock.calls[0][1].body).expected_revision).toBe(21);
  expect(getPlanRevision()).toBe(99);
});

it("uses an explicit replan base and never lets auxiliary reads replace the command revision", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({ plan_revision: 5 })));
  vi.stubGlobal("fetch", fetch);
  await getConfig();
  await getPlanView();
  expect(getPlanRevision()).toBe(99);
  await applyReplan("job", undefined, 21);
  expect(JSON.parse(fetch.mock.calls[2][1].body).expected_revision).toBe(21);
});

it("binds journal reads to the accepted dataset and revision", async () => {
  commitPlanRevision(21, "dataset-a");
  const fetch = vi.fn().mockResolvedValue(new Response("[]", {
    headers: { "X-Dataset-Id": "dataset-a", "X-Plan-Revision": "21" },
  }));
  vi.stubGlobal("fetch", fetch);
  await getJournal();
  const headers = new Headers(fetch.mock.calls[0][1].headers);
  expect(headers.get("X-Dataset-Id")).toBe("dataset-a");
  expect(headers.get("X-Plan-Revision")).toBe("21");
  expect(getPlanRevision()).toBe(21);
});

it("allows only exact preview routes and their cancellation in read-only mode", async () => {
  localStorage.setItem("pp1AccessMode", "view");
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({})));
  vi.stubGlobal("fetch", fetch);
  for (const path of ["simulate", "ctp", "plan/move-preview", "plan/move-preview-jobs", "plan/move-preview-jobs/job/cancel", "subcontracts/preview", "skus/SKU/planning/preview"]) {
    await expect(post(`/api/data/${path}`, {}, { blocking: false })).resolves.toEqual({});
  }
  const allowedCount = fetch.mock.calls.length;
  for (const path of ["simulate-apply", "ctp-apply", "plan/move-apply", "plan/move-preview-jobs/job/apply", "plan/move-preview-jobs/job/cancel/extra", "anything/preview", "replan-jobs/job/cancel"]) {
    await expect(post(`/api/data/${path}`, {})).rejects.toMatchObject({ status: 403 });
  }
  expect(fetch).toHaveBeenCalledTimes(allowedCount);
});

it("bounds default reads and releases the blocking overlay after an action timeout", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", vi.fn((_url, init) => new Promise((_resolve, reject) => {
    init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  })));
  const read = expect(get("/api/test")).rejects.toMatchObject({ detail: { code: "timeout" } });
  await vi.advanceTimersByTimeAsync(15_000);
  await read;
  const action = expect(post("/api/test", {})).rejects.toBeInstanceOf(ApiError);
  await vi.advanceTimersByTimeAsync(120_000);
  await action;
  expect(useAppStore.getState().blockingRequests).toBe(0);
});

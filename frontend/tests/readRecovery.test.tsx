import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { del, get, post, put, upload } from "../src/api/client";
import { getRisk } from "../src/api/endpoints";
import { commitPlanRevision } from "../src/lib/planRevision";
import { useAppStore } from "../src/stores/useAppStore";

const response = (body: unknown, status = 200, headers?: HeadersInit) =>
  new Response(JSON.stringify(body), { status, headers });
function observe<T>(promise: Promise<T>): Promise<T> {
  void promise.catch(() => undefined);
  return promise;
}

beforeEach(() => { vi.useFakeTimers(); localStorage.clear(); commitPlanRevision(0); });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear(); commitPlanRevision(0); });

it("recovers a failed read without a page reload or blocking overlay", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(response({ ok: true }));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(get("/api/read")).resolves.toEqual({ ok: true }));
  await vi.advanceTimersByTimeAsync(200);
  await result;
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(useAppStore.getState().blockingRequests).toBe(0);
  expect(vi.getTimerCount()).toBe(0);
});

it.each([502, 503, 504, 524])("recovers a transient HTTP %s, with at most three attempts", async (status) => {
  const fetch = vi.fn().mockImplementationOnce(() => Promise.resolve(response({}, status)))
    .mockImplementationOnce(() => Promise.resolve(response({}, status)))
    .mockResolvedValueOnce(response({ ok: true }));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(get("/api/read")).resolves.toEqual({ ok: true }));
  await vi.advanceTimersByTimeAsync(600);
  await result;
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(vi.getTimerCount()).toBe(0);
});

it("recovers a connection lost while reading the body", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response(new ReadableStream({
    start(controller) { controller.error(new TypeError("Body connection lost")); },
  }))).mockResolvedValueOnce(response({ ok: true }));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(get("/api/read")).resolves.toEqual({ ok: true }));
  await vi.advanceTimersByTimeAsync(200);
  await result;
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("stops after three network failures and does not claim recovery is still in progress", async () => {
  const fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(get("/api/read")).rejects.toMatchObject({
    status: 0, detail: { code: "network" },
    message: "Não foi possível ligar ao servidor. Tenta novamente dentro de instantes.",
  }));
  await vi.advanceTimersByTimeAsync(600);
  await result;
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(vi.getTimerCount()).toBe(0);
});

it("includes recovery backoff in the original timeout and cleans up its timer", async () => {
  const fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(get("/api/read", { timeoutMs: 150 })).rejects.toMatchObject({ detail: { code: "timeout" } }));
  await vi.advanceTimersByTimeAsync(150);
  await result;
  await vi.advanceTimersByTimeAsync(1000);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it("does not reset the deadline for a second request or body read", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockImplementationOnce((_url, init) => Promise.resolve(new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('{"ok":'));
        init.signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")));
      },
    }))));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(get("/api/read", { timeoutMs: 500 })).rejects.toMatchObject({ detail: { code: "timeout" } }));
  await vi.advanceTimersByTimeAsync(500);
  await result;
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][1].signal).toBe(fetch.mock.calls[0][1].signal);
  expect(vi.getTimerCount()).toBe(0);
});

it("keeps the captured plan identity when retrying, rather than rebasing", async () => {
  commitPlanRevision(21, "dataset-a");
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(response({ ok: true }, 200, { "X-Dataset-Id": "dataset-a", "X-Plan-Revision": "21" }));
  vi.stubGlobal("fetch", fetch);
  const result = observe(expect(getRisk()).resolves.toEqual({ ok: true }));
  commitPlanRevision(22, "dataset-b");
  await vi.advanceTimersByTimeAsync(200);
  await result;
  for (const [, init] of fetch.mock.calls) {
    expect(init.headers).toMatchObject({ "X-Dataset-Id": "dataset-a", "X-Plan-Revision": "21" });
  }
});

it.each([400, 403, 409, 422])("never retries HTTP %s", async (status) => {
  const fetch = vi.fn().mockResolvedValue(response({ detail: { message: "Rejected" } }, status));
  vi.stubGlobal("fetch", fetch);
  await expect(get("/api/read")).rejects.toMatchObject({ status });
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it("does not retry a successful response belonging to a different revision", async () => {
  const fetch = vi.fn().mockResolvedValue(response({}, 200, { "X-Dataset-Id": "dataset-a", "X-Plan-Revision": "22" }));
  vi.stubGlobal("fetch", fetch);
  await expect(get("/api/read", { planIdentity: { datasetId: "dataset-a", planRevision: 21 } }))
    .rejects.toMatchObject({ status: 409, detail: { code: "stale_revision" } });
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("does not retry malformed successful responses", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("<html>proxy</html>", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  await expect(get("/api/read")).rejects.toMatchObject({ detail: { code: "invalid_response" } });
  expect(fetch).toHaveBeenCalledTimes(1);
});

const writes = [
  { name: "apply", run: () => post("/api/data/simulate-apply", { request_id: "stable" }) },
  { name: "preview", run: () => post("/api/data/simulate", {}) },
  { name: "put", run: () => put("/api/data/config", {}) },
  { name: "delete", run: () => del("/api/data/plans/old") },
  { name: "upload", run: () => upload("/api/data/load", new File(["test"], "test.xlsx")) },
];

for (const write of writes) {
  it.each(["network", "proxy"])(`never repeats ${write.name} after a %s failure`, async (failure) => {
    const fetch = vi.fn();
    if (failure === "network") fetch.mockRejectedValue(new TypeError("Failed to fetch"));
    else fetch.mockImplementation(() => Promise.resolve(response({}, 503)));
    vi.stubGlobal("fetch", fetch);
    await expect(write.run()).rejects.toMatchObject({ status: failure === "network" ? 0 : 503 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().blockingRequests).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });
}

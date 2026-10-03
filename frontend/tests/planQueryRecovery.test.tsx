import { StrictMode } from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RiskPage } from "../src/pages/RiskPage";
import { useDataStore } from "../src/stores/useDataStore";
import { commitPlanRevision } from "../src/lib/planRevision";

function responseFor(url: string, revision: string, health = 88) {
  const body = url.endsWith("/risk") ? {
    health_score: health, critical_count: 0, bottleneck: null, lot_risks: [],
    machine_risks: [], top_risks: [], heatmap: [],
  } : url.endsWith("/late") ? { analyses: [], by_cause: {}, tardy_count: 0 } : null;
  return new Response(JSON.stringify(body), {
    headers: { "X-Dataset-Id": "dataset-a", "X-Plan-Revision": revision },
  });
}

beforeEach(() => {
  vi.useFakeTimers(); localStorage.clear();
  useDataStore.setState({ datasetId: "dataset-a", planRevision: 21 });
  commitPlanRevision(21, "dataset-a");
});
afterEach(() => {
  cleanup(); useDataStore.getState().clear(); vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear();
});

it("renders the real risk page after a transient network failure in StrictMode", async () => {
  let riskAttempts = 0;
  const fetch = vi.fn(async (url: string, init: RequestInit) => {
    expect(init.method ?? "GET").toBe("GET");
    if (url.endsWith("/risk") && ++riskAttempts <= 2) throw new TypeError("Failed to fetch");
    return responseFor(url, "21");
  });
  vi.stubGlobal("fetch", fetch);
  render(<StrictMode><RiskPage /></StrictMode>);
  await act(async () => { await vi.advanceTimersByTimeAsync(600); });
  expect(screen.getByText("88")).toBeTruthy();
  expect(screen.queryByText(/Não foi possível ligar/)).toBeNull();
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/risk"))).toHaveLength(4);
  expect(vi.getTimerCount()).toBe(0);
});

it("discards recovered reads from the old plan after a revision change", async () => {
  const fetch = vi.fn(async (url: string, init: RequestInit) => {
    const revision = new Headers(init.headers).get("X-Plan-Revision")!;
    if (url.endsWith("/risk") && revision === "21"
      && fetch.mock.calls.filter(([u, i]) => u.endsWith("/risk") && new Headers(i.headers).get("X-Plan-Revision") === "21").length === 1) {
      throw new TypeError("Failed to fetch");
    }
    return responseFor(url, revision, revision === "21" ? 91 : 12);
  });
  vi.stubGlobal("fetch", fetch);
  render(<RiskPage />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  act(() => { commitPlanRevision(22, "dataset-a"); useDataStore.setState({ planRevision: 22 }); });
  await act(async () => { await vi.advanceTimersByTimeAsync(600); });
  expect(screen.getByText("12")).toBeTruthy();
  expect(screen.queryByText("91")).toBeNull();
  expect(fetch.mock.calls.filter(([url]) => url.endsWith("/risk"))).toHaveLength(3);
  expect(vi.getTimerCount()).toBe(0);
});

it("does not resurrect a query after unmount or clearing the dataset", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockImplementation(async (url: string) => responseFor(url, "21"));
  vi.stubGlobal("fetch", fetch);
  const { unmount } = render(<RiskPage />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  unmount(); useDataStore.getState().clear();
  await act(async () => { await vi.advanceTimersByTimeAsync(600); });
  expect(screen.queryByText("88")).toBeNull();
  expect(useDataStore.getState().datasetId).toBeNull();
  expect(useDataStore.getState().planRevision).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

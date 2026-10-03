import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { RobustnessJob } from "../src/api/types";

const api = vi.hoisted(() => ({ getLatestRobustnessRun: vi.fn(), getRobustnessRun: vi.fn(), startRobustnessRun: vi.fn(), cancelRobustnessRun: vi.fn() }));
vi.mock("../src/api/endpoints", () => api);
import { RobustnessPanel } from "../src/components/RobustnessPanel";
import { useDataStore } from "../src/stores/useDataStore";
import { useAppStore } from "../src/stores/useAppStore";

const job = (status: string) => ({ id: "j1", status, progress: 35, result: null } as RobustnessJob);
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  useDataStore.setState({ datasetId: "d1", planRevision: 1 });
  useAppStore.setState({ accessMode: "edit" });
  api.getLatestRobustnessRun.mockResolvedValue({ job: job("running") });
});
afterEach(() => { cleanup(); vi.useRealTimers(); useDataStore.getState().clear(); });
async function mount() { await act(async () => { render(<StrictMode><RobustnessPanel /></StrictMode>); }); }

it("polls sequentially and cannot revive a cancelled job with a late GET", async () => {
  const late = deferred<{ job: RobustnessJob }>();
  api.getRobustnessRun.mockReturnValue(late.promise);
  api.cancelRobustnessRun.mockResolvedValue({ job: job("cancelled") });
  await mount();
  await act(async () => vi.advanceTimersByTimeAsync(750));
  await act(async () => vi.advanceTimersByTimeAsync(3000));
  expect(api.getRobustnessRun).toHaveBeenCalledTimes(1);
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancelar" })));
  await act(async () => late.resolve({ job: job("running") }));
  expect(screen.getByRole("button", { name: "Executar" })).toBeTruthy();
});

it("discards old-plan responses and recovers correctly in StrictMode", async () => {
  const late = deferred<{ job: RobustnessJob }>();
  api.getRobustnessRun.mockReturnValue(late.promise);
  await mount();
  await act(async () => vi.advanceTimersByTimeAsync(750));
  api.getLatestRobustnessRun.mockResolvedValue({ job: null });
  await act(async () => useDataStore.setState({ planRevision: 2 }));
  await act(async () => late.resolve({ job: job("running") }));
  expect(screen.getByRole("button", { name: "Executar" })).toBeTruthy();
});

it("does not start twice while the POST is pending", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: null });
  const pending = deferred<{ job: RobustnessJob }>();
  api.startRobustnessRun.mockReturnValue(pending.promise);
  await mount();
  act(() => {
    const start = screen.getByRole("button", { name: "Executar" });
    fireEvent.click(start); fireEvent.click(start);
  });
  expect(api.startRobustnessRun).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve({ job: job("running") }));
});

it("reports failed cancellation and reconciles a completed job", async () => {
  api.cancelRobustnessRun.mockRejectedValue(new Error("offline"));
  api.getRobustnessRun.mockResolvedValue({ job: job("completed") });
  await mount();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Cancelar" })));
  expect(screen.getByText(/Não foi possível confirmar o cancelamento/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Executar" })).toBeTruthy();
});

it("keeps Consulta permissions unchanged", async () => {
  useAppStore.setState({ accessMode: "view" });
  await mount();
  const cancel = screen.getByRole<HTMLButtonElement>("button", { name: "Cancelar" });
  expect(cancel.disabled).toBe(true);
  fireEvent.click(cancel);
  expect(api.cancelRobustnessRun).not.toHaveBeenCalled();
});

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

it("labels the automatic job as information with the 10 working-day horizon", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: {
    ...job("completed"), trigger: "auto", plan_revision: 1, horizon_workdays: 10, model_version: 5,
    result: {
      model_version: 5, success_definition: "no_additional_tardy_lots", baseline_tardy_count: 1,
      success_probability_pct: 88, otd_p95: 97, additional_tardy_p95: 1, tardy_p95: 2,
      total_tardiness_cvar95: 3, worst_scenarios: [], horizon_workdays: 10,
    },
  } as unknown as RobustnessJob });
  await mount();
  expect(screen.getByText("Robustez (informativo): não altera o plano nem pede aprovação")).toBeTruthy();
  expect(screen.getByText(/Cálculo automático da revisão 1/)).toBeTruthy();
  expect(screen.getByText(/próximos 10 dias úteis/)).toBeTruthy();
  expect(screen.getByText("88.0%")).toBeTruthy();
  expect(screen.queryByText(/limite/i)).toBeNull();
  expect(screen.getByRole("button", { name: "Executar" })).toBeTruthy();
});

it("hides a job computed for another plan revision", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: { ...job("completed"), trigger: "auto", plan_revision: 0 } });
  await mount();
  expect(screen.queryByText(/Cálculo automático/)).toBeNull();
  expect(screen.getByText("Ainda sem resultado para esta revisão do plano.")).toBeTruthy();
});

it("picks up the automatic job when it is queued just after the commit", async () => {
  // StrictMode runs the effect twice: both first reads see no job yet.
  api.getLatestRobustnessRun.mockResolvedValueOnce({ job: null }).mockResolvedValueOnce({ job: null })
    .mockResolvedValue({ job: { ...job("queued"), trigger: "auto", plan_revision: 1, horizon_workdays: 10 } });
  api.getRobustnessRun.mockResolvedValue({ job: { ...job("queued"), trigger: "auto", plan_revision: 1, horizon_workdays: 10 } });
  await mount();
  expect(screen.getByText("Ainda sem resultado para esta revisão do plano.")).toBeTruthy();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByText(/Cálculo automático da revisão 1/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Cancelar" })).toBeTruthy();
});

const v5Result = (extra: Record<string, unknown>) => ({
  model_version: 5, success_definition: "no_additional_tardy_lots", baseline_tardy_count: 0,
  success_probability_pct: 92, otd_p95: 98, additional_tardy_p95: 1, tardy_p95: 1,
  total_tardiness_cvar95: 2, worst_scenarios: [], horizon_workdays: 10,
  horizon_start_date: "2026-10-08", horizon_end_date: "2026-10-21", horizon_lot_count: 7,
  ...extra,
});
const autoJob = (result: Record<string, unknown>, extra: Partial<RobustnessJob> = {}) => ({
  ...job("completed"), trigger: "auto", plan_revision: 1, horizon_workdays: 10, model_version: 5,
  result: v5Result(result), ...extra,
} as unknown as RobustnessJob);

it("asks for the automatic job and shows the window as dates with the delivery count", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: autoJob({}) });
  await mount();
  expect(api.getLatestRobustnessRun).toHaveBeenCalledWith("auto");
  expect(screen.getByText(/de 08\/10 a 21\/10 \(10 dias úteis\)/)).toBeTruthy();
  expect(screen.getByText(/7 entregas nestes dias/)).toBeTruthy();
  expect(screen.getByText("92.0%")).toBeTruthy();
  expect(screen.getByText("Robustez (informativo): não altera o plano nem pede aprovação")).toBeTruthy();
});

it("says there is nothing to measure when the window has no deliveries, never 100%", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: autoJob({
    horizon_lot_count: 0, no_deliveries_in_window: true, success_probability_pct: null,
  }) });
  await mount();
  expect(screen.getByText("Sem entregas nos próximos 10 dias úteis — nada a medir.")).toBeTruthy();
  expect(screen.queryByText(/100\.0%/)).toBeNull();
  expect(screen.queryByText("Cenários sem novos atrasos")).toBeNull();
  expect(screen.getByText(/de 08\/10 a 21\/10/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Executar" })).toBeTruthy();
});

it("treats a zero lot count as an empty window even without the flag", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: autoJob({ horizon_lot_count: 0, success_probability_pct: 100 }) });
  await mount();
  expect(screen.getByText(/nada a medir/)).toBeTruthy();
  expect(screen.queryByText("100.0%")).toBeNull();
});

it("shows a dash instead of crashing when the percentage is null", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: autoJob({ success_probability_pct: null }) });
  await mount();
  expect(screen.getByText("Cenários sem novos atrasos")).toBeTruthy();
  expect(screen.getByText("—")).toBeTruthy();
});

it("retries a stale job until the fresh automatic job appears", async () => {
  api.getLatestRobustnessRun.mockResolvedValueOnce({ job: autoJob({}, { stale: true }) })
    .mockResolvedValueOnce({ job: autoJob({}, { stale: true }) })
    .mockResolvedValue({ job: autoJob({ success_probability_pct: 77 }) });
  await mount();
  expect(screen.getByText("Ainda sem resultado para esta revisão do plano.")).toBeTruthy();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByText("77.0%")).toBeTruthy();
});

it("stops asking after three tries when no job belongs to this revision", async () => {
  api.getLatestRobustnessRun.mockResolvedValue({ job: autoJob({}, { plan_revision: 0 }) });
  await mount();
  const firstCalls = api.getLatestRobustnessRun.mock.calls.length; // StrictMode mounts twice
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(api.getLatestRobustnessRun.mock.calls.length - firstCalls).toBe(2);
  expect(screen.getByText("Ainda sem resultado para esta revisão do plano.")).toBeTruthy();
});

it("follows the new analysis after a new day instead of showing yesterday's window", async () => {
  api.getLatestRobustnessRun
    .mockResolvedValueOnce({ job: autoJob({}), refreshing: true })
    .mockResolvedValueOnce({ job: autoJob({}), refreshing: true })
    .mockResolvedValue({ job: autoJob({ horizon_start_date: "2026-10-09", horizon_end_date: "2026-10-22" }) });
  await mount();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByText(/de 09\/10 a 22\/10/)).toBeTruthy();
});

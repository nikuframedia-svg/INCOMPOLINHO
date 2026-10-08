import { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDataStore } from "../src/stores/useDataStore";
import { commitPlanRevision } from "../src/lib/planRevision";
import type { CapacityResponse, FactoryConfig, JournalEntry, LateDeliveryReport } from "../src/api/types";

const endpoints = vi.hoisted(() => ({
  getCapacity: vi.fn(), getLateDeliveries: vi.fn(), getJournal: vi.fn(), getConfig: vi.fn(),
}));
vi.mock("../src/api/endpoints", () => endpoints);

import { CapacityView } from "../src/components/CapacityView";
import { LateDeliveriesModal } from "../src/components/LateDeliveriesModal";
import { JournalPage } from "../src/pages/JournalPage";
import { RulesPage } from "../src/pages/RulesPage";

function capacity(marker: string, granularity = "day"): CapacityResponse {
  return { granularity, items: [{ machine_id: marker, bucket: "0", label: "2026-11-02",
    date_from: "2026-11-02", date_to: "2026-11-02", day_indices: [0], cap_min: 510,
    setup_min: 0, prod_min: 60, load_min: 60, util_pct: 11.8, overload: false, n_setups: 0,
  }], operators: [] } as CapacityResponse;
}

const cases = [
  { name: "capacity", load: endpoints.getCapacity, component: () => <CapacityView />,
    response: capacity, marker: (name: string) => name },
  { name: "late deliveries", load: endpoints.getLateDeliveries,
    component: () => <LateDeliveriesModal onClose={() => {}} />,
    response: (name: string) => ({ tardy_count: 0, avg_delay: 0, worst_machine: null,
      suggestion: name, analyses: [], by_cause: {} } as LateDeliveryReport), marker: (name: string) => name },
  { name: "journal", load: endpoints.getJournal, component: () => <JournalPage />,
    response: (name: string) => [{ message: name, step: "validation", severity: "info", elapsed_ms: 1 } as JournalEntry],
    marker: (name: string) => name },
  { name: "rules", load: endpoints.getConfig, component: () => <RulesPage />,
    response: (name: string) => ({ setup_crews_by_group: { Grandes: 1 }, day_capacity_min: name === "old" ? 111 : 222,
      max_run_days: 4, eco_lot_mode: "hard", twins: [], campaign_window: 5 } as unknown as FactoryConfig),
    marker: (name: string) => name === "old" ? "111 min" : "222 min" },
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.resetAllMocks();
  useDataStore.setState({ datasetId: "dataset-a", planRevision: 21 });
  commitPlanRevision(21, "dataset-a");
});
afterEach(() => { cleanup(); useDataStore.getState().clear(); });

describe.each(cases)("$name revision consistency", ({ load, component, response, marker }) => {
  it.each(["revision", "dataset"])("invalidates visible values after a %s change", async (change) => {
    load.mockResolvedValue(response("old"));
    render(<StrictMode>{component()}</StrictMode>);
    await screen.findByText(marker("old"));
    const next = deferred<unknown>();
    load.mockReturnValue(next.promise);
    act(() => { useDataStore.setState(change === "revision" ? { planRevision: 22 } : { datasetId: "dataset-b" }); });
    expect(screen.queryByText(marker("old"))).toBeNull();
    await act(async () => { next.resolve(response("new")); });
    await screen.findByText(marker("new"));
  });

  it("ignores an old response after the new plan has loaded", async () => {
    const old = deferred<unknown>();
    load.mockReturnValue(old.promise);
    render(component());
    load.mockResolvedValue(response("new"));
    act(() => { useDataStore.setState({ planRevision: 22 }); });
    await screen.findByText(marker("new"));
    await act(async () => { old.resolve(response("old")); });
    expect(screen.queryByText(marker("old"))).toBeNull();
    expect(screen.getByText(marker("new"))).toBeTruthy();
  });

  it("ignores a failure of the old request after a dataset change", async () => {
    const old = deferred<unknown>();
    load.mockReturnValue(old.promise);
    render(component());
    load.mockResolvedValue(response("new"));
    act(() => { useDataStore.setState({ datasetId: "dataset-b" }); });
    await screen.findByText(marker("new"));
    await act(async () => { old.reject(new Error("old request failed")); });
    expect(screen.queryByText(/old request failed/)).toBeNull();
    expect(screen.getByText(marker("new"))).toBeTruthy();
  });
});

it("keeps the selected granularity while refreshing the plan and ignores delayed daily data", async () => {
  const daily = deferred<CapacityResponse>();
  endpoints.getCapacity.mockImplementation((mode) => mode === "day" ? daily.promise : Promise.resolve(capacity("week-old", "week")));
  render(<CapacityView />);
  fireEvent.click(screen.getByRole("button", { name: "Semana" }));
  await screen.findByText("week-old");
  endpoints.getCapacity.mockResolvedValue(capacity("week-new", "week"));
  act(() => { useDataStore.setState({ planRevision: 22 }); });
  await screen.findByText("week-new");
  expect(endpoints.getCapacity).toHaveBeenLastCalledWith("week");
  await act(async () => { daily.resolve(capacity("day-old")); });
  expect(screen.queryByText("day-old")).toBeNull();
});

it("clears a previous failure when a new revision loads successfully", async () => {
  endpoints.getCapacity.mockRejectedValue(new Error("old capacity error"));
  render(<CapacityView />);
  await screen.findByText(/old capacity error/);
  endpoints.getCapacity.mockResolvedValue(capacity("recovered"));
  act(() => { useDataStore.setState({ planRevision: 22 }); });
  await screen.findByText("recovered");
  expect(screen.queryByText(/old capacity error/)).toBeNull();
});

it("shows positive work with zero capacity as an inconsistency, not closed or zero percent", async () => {
  const value = capacity("M1");
  Object.assign(value.items[0], { cap_min: 0, util_pct: null, overload: true });
  value.operators = [{ bucket: "0", date_from: "2026-11-02", date_to: "2026-11-02", group: "Grandes", shift: "A",
    capacity_operator_min: 0, load_operator_min: 60, util_pct: null, overload: true } as CapacityResponse["operators"][number]];
  endpoints.getCapacity.mockResolvedValue(value);
  render(<CapacityView />);
  await waitFor(() => { expect(screen.getAllByText("Sem capacidade")).toHaveLength(2); });
  expect(screen.queryByText("Fechado")).toBeNull();
  expect(screen.queryByText("0%")).toBeNull();
});

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CapacityResponse } from "../src/api/types";

const endpointMocks = vi.hoisted(() => ({
  getCapacity: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return {
    ...actual,
    ...endpointMocks,
  };
});

import { CapacityView } from "../src/components/CapacityView";

const dayResponse = {
  granularity: "day",
  items: [
    {
      machine_id: "M1",
      bucket: "0",
      label: "2026-03-16",
      date_from: "2026-03-16",
      date_to: "2026-03-16",
      day_indices: [0],
      cap_min: 960,
      setup_min: 0,
      prod_min: 0,
      load_min: 0,
      util_pct: 0,
      overload: false,
      n_setups: 0,
      workday_count: 1,
    },
  ],
  operators: [],
} as CapacityResponse;

const weekResponse = {
  granularity: "week",
  items: [
    {
      machine_id: "M1",
      bucket: "2026-W12",
      label: "2026-W12",
      date_from: "2026-03-16",
      date_to: "2026-03-20",
      day_indices: [0, 1, 2, 3, 4],
      cap_min: 4800,
      setup_min: 60,
      prod_min: 1800,
      load_min: 1860,
      util_pct: 38.8,
      overload: false,
      n_setups: 1,
      workday_count: 5,
    },
  ],
  operators: [
    {
      bucket: "2026-W12",
      date_from: "2026-03-16",
      date_to: "2026-03-20",
      group: "Grandes",
      shift: "A",
      capacity_operator_min: 2880,
      load_operator_min: 900,
      util_pct: 31.3,
      overload: false,
      workday_count: 5,
    },
  ],
} as CapacityResponse;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("CapacityView", () => {
  it("mostra a legenda operacional e os dias úteis semanais", async () => {
    endpointMocks.getCapacity.mockImplementation((granularity: "day" | "week") => (
      Promise.resolve(granularity === "week" ? weekResponse : dayResponse)
    ));

    render(<CapacityView />);

    expect(await screen.findByText(/cinzento: sem carga/)).toBeTruthy();
    expect(screen.getByText(/carga > capacidade/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Semana" }));

    await waitFor(() => {
      expect(screen.getAllByText("2026-W12 · 5d").length).toBeGreaterThan(0);
    });
  });
});

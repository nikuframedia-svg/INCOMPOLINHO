import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const endpointMocks = vi.hoisted(() => ({
  getRisk: vi.fn(),
  getLateDeliveries: vi.fn(),
  getWorkforce: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return {
    ...actual,
    ...endpointMocks,
  };
});

import { RiskPage } from "../src/pages/RiskPage";
import { useDataStore } from "../src/stores/useDataStore";

afterEach(() => {
  cleanup();
  useDataStore.getState().clear();
  vi.clearAllMocks();
});

describe("RiskPage", () => {
  it("invalidates all analytics on revision change and discards an older response", async () => {
    let finishOld!: (value: unknown) => void;
    const minimal = { critical_count: 0, bottleneck: null, lot_risks: [], machine_risks: [], top_risks: [], heatmap: [] };
    endpointMocks.getRisk.mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve; }))
      .mockResolvedValueOnce({ ...minimal, health_score: 12 });
    endpointMocks.getLateDeliveries.mockResolvedValue({ analyses: [], by_cause: {}, tardy_count: 0 });
    endpointMocks.getWorkforce.mockResolvedValue(null);
    useDataStore.setState({ datasetId: "d1", planRevision: 1 });
    render(<RiskPage />);
    act(() => useDataStore.setState({ planRevision: 2 }));
    expect(await screen.findByText("12")).toBeTruthy();
    await act(async () => finishOld({ ...minimal, health_score: 91 }));
    expect(screen.queryByText("91")).toBeNull();
    expect(endpointMocks.getRisk).toHaveBeenCalledTimes(2);
  });

  it("does not display zero utilization for positive load on a closed resource", async () => {
    endpointMocks.getRisk.mockResolvedValue({ health_score: 0, critical_count: 1, bottleneck: "M1", lot_risks: [], machine_risks: [], top_risks: [],
      heatmap: [{ machine_id: "M1", day_idx: 0, utilization: null, load_min: 240, capacity_min: 0, risk_level: "critical" }] });
    endpointMocks.getLateDeliveries.mockResolvedValue({ analyses: [], by_cause: {}, tardy_count: 0 });
    endpointMocks.getWorkforce.mockResolvedValue(null);
    render(<RiskPage />);
    expect(await screen.findByTitle(/Inconsistência: carga sem capacidade/)).toHaveProperty("textContent", "!");
  });

  it("mostra valores no heatmap e mantém detalhe em tooltip", async () => {
    endpointMocks.getRisk.mockResolvedValue({
      health_score: 88,
      critical_count: 0,
      bottleneck: null,
      lot_risks: [],
      machine_risks: [],
      top_risks: [],
      heatmap: [{
        machine_id: "M1",
        day_idx: 2,
        utilization: 0.75,
        load_min: 765,
        capacity_min: 1020,
        min_slack_min: 360,
        risk_level: "medium",
      }],
    });
    endpointMocks.getLateDeliveries.mockResolvedValue({ analyses: [], by_cause: {}, tardy_count: 0 });
    endpointMocks.getWorkforce.mockResolvedValue(null);

    render(<RiskPage />);

    expect(await screen.findByText("Mapa de risco")).toBeTruthy();
    expect(screen.getByText("75")).toBeTruthy();
    expect(screen.getByTitle(/Carga: 765 min/)).toBeTruthy();
  });
});

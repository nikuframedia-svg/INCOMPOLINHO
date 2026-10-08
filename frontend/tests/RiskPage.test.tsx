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
    expect(screen.getByTitle(/Risco: Médio/)).toBeTruthy();
    expect(screen.queryByTitle(/medium/)).toBeNull();
  });

  it("mostra o nível dos riscos principais em português", async () => {
    endpointMocks.getRisk.mockResolvedValue({
      health_score: 70,
      critical_count: 1,
      bottleneck: null,
      lot_risks: [],
      machine_risks: [],
      top_risks: [
        { lot_id: "L1", sku: "SKU-A", machine_id: "M1", edd: 3, slack: -1, slack_days: -1, risk_level: "critical", status: "late" },
        { lot_id: "L2", sku: "SKU-B", machine_id: "M2", edd: 4, slack: 2, slack_days: 2, risk_level: "high" },
        { lot_id: "L3", sku: "SKU-C", machine_id: "M3", edd: 5, slack: 0, slack_days: 0, risk_level: "critical", status: "at_limit" },
        { lot_id: "L4", sku: "SKU-D", machine_id: "M4", edd: 6, slack: 1, slack_days: 1, risk_level: "low", status: "short_slack" },
      ],
      heatmap: [],
    });
    endpointMocks.getLateDeliveries.mockResolvedValue({ analyses: [], by_cause: {}, tardy_count: 0 });
    endpointMocks.getWorkforce.mockResolvedValue(null);

    render(<RiskPage />);

    expect(await screen.findByText("Riscos principais")).toBeTruthy();
    expect(screen.getByText("Atrasado")).toBeTruthy();
    expect(screen.getByText("Alto")).toBeTruthy();
    expect(screen.queryByText("critical")).toBeNull();
    expect(screen.queryByText("high")).toBeNull();
  });

  it("folga negativa aparece como atraso e a cor segue o estado", async () => {
    endpointMocks.getRisk.mockResolvedValue({
      health_score: 70,
      critical_count: 1,
      bottleneck: null,
      lot_risks: [],
      machine_risks: [],
      top_risks: [
        { lot_id: "L1", sku: "SKU-A", machine_id: "M1", edd: 3, slack: -1, slack_days: -1, risk_level: "high", status: "late" },
        { lot_id: "L2", sku: "SKU-B", machine_id: "M2", edd: 4, slack: -3, slack_days: -3, risk_level: "critical", status: "late" },
        { lot_id: "L3", sku: "SKU-C", machine_id: "M3", edd: 5, slack: 0, slack_days: 0, risk_level: "critical", status: "at_limit" },
        { lot_id: "L4", sku: "SKU-D", machine_id: "M4", edd: 6, slack: 1, slack_days: 1, risk_level: "critical", status: "short_slack" },
        { lot_id: "L5", sku: "SKU-E", machine_id: "M5", edd: 6, slack: 2, slack_days: 2, risk_level: "low", status: "short_slack" },
      ],
      heatmap: [],
    });
    endpointMocks.getLateDeliveries.mockResolvedValue({ analyses: [], by_cause: {}, tardy_count: 0 });
    endpointMocks.getWorkforce.mockResolvedValue(null);

    render(<RiskPage />);

    expect(await screen.findByText("Riscos principais")).toBeTruthy();
    expect(screen.getByText("1 dia de atraso")).toBeTruthy();
    expect(screen.getByText("3 dias de atraso")).toBeTruthy();
    expect(screen.getByText("Folga: 0 dias")).toBeTruthy();
    expect(screen.getByText("Folga: 1 dia")).toBeTruthy();
    expect(screen.getByText("Folga: 2 dias")).toBeTruthy();
    expect(document.body.textContent ?? "").not.toMatch(/Folga: -|\(s\)/);

    const late = screen.getAllByText("Atrasado");
    expect(late.every((node) => node.style.color === "rgb(194, 65, 12)")).toBe(true);
    expect(screen.getByText("No limite").style.color).toBe("rgb(202, 134, 12)");
    expect(screen.getAllByText("Folga curta").every((node) => node.style.color === "rgb(161, 98, 7)")).toBe(true);
  });
});

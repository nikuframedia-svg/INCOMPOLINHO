import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StockProjection, StockSummary } from "../src/api/types";

const endpointMocks = vi.hoisted(() => ({
  getStockSummary: vi.fn(),
  getStockDetail: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return {
    ...actual,
    ...endpointMocks,
  };
});

import { formatStockoutLabel } from "../src/lib/stockDates";
import { StockPage } from "../src/pages/StockPage";

const compactDays = [
  { day: 0, date: "2026-08-17", stock: -100, demand: 100, produced: 0, workday: true },
  { day: 1, date: "2026-08-18", stock: -100, demand: 0, produced: 0, workday: true },
  { day: 4, date: "2026-08-21", stock: -100, demand: 0, produced: 0, workday: true },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("StockPage", () => {
  it("formata a data de rutura nos dias 0, 1 e 4 e mantém o fallback", () => {
    expect(formatStockoutLabel(0, compactDays)).toBe("esgota dia 0 (17-Ago)");
    expect(formatStockoutLabel(1, compactDays)).toBe("esgota dia 1 (18-Ago)");
    expect(formatStockoutLabel(4, compactDays)).toBe("esgota dia 4 (21-Ago)");
    expect(formatStockoutLabel(2, compactDays)).toBe("esgota dia 2");
    expect(formatStockoutLabel(1, [{ day: 1 }])).toBe("esgota dia 1");
    expect(formatStockoutLabel(1, [{ ...compactDays[1], date: "data-invalida" }])).toBe(
      "esgota dia 1",
    );
  });

  it("usa a mesma data na grelha e no resumo do modal", async () => {
    const summary: StockSummary = {
      op_id: "OP-1",
      sku: "TP042173-0040-2",
      client: "JOAO DEUS",
      machine: "PRM042",
      tool: "JDE002",
      initial_stock: 0,
      stockout_day: 1,
      coverage_days: 1,
      total_demand: 100,
      total_produced: 0,
      days: compactDays,
    };
    const detail: StockProjection = {
      ...summary,
      days: compactDays.map((day) => ({
        day_idx: day.day,
        date: day.date,
        demand: day.demand,
        produced: day.produced,
        cum_demand: day.demand,
        cum_produced: day.produced,
        stock: day.stock,
        machine: null,
      })),
    };
    endpointMocks.getStockSummary.mockResolvedValue([summary]);
    endpointMocks.getStockDetail.mockResolvedValue(detail);

    render(<StockPage />);

    expect(await screen.findByText("esgota dia 1 (18-Ago)")).toBeTruthy();
    fireEvent.click(screen.getByText("TP042173-0040-2"));

    await waitFor(() => {
      expect(screen.getAllByText("esgota dia 1 (18-Ago)")).toHaveLength(2);
    });
  });

  it("mostra entradas e saídas diárias junto ao saldo de stock", async () => {
    const summary: StockSummary = {
      op_id: "OP-1",
      sku: "SKU-MOVIMENTOS",
      client: "CLIENTE",
      machine: "PRM039",
      tool: "T1",
      initial_stock: 0,
      stockout_day: null,
      coverage_days: 10,
      total_demand: 23_400,
      total_produced: 610,
      days: [
        {
          day: 0,
          date: "2026-08-17",
          stock: 1_000,
          demand: 23_400,
          produced: 610,
          workday: true,
        },
        {
          day: 1,
          date: "2026-08-18",
          stock: 1_000,
          demand: 0,
          produced: 0,
          workday: true,
        },
      ],
    };
    endpointMocks.getStockSummary.mockResolvedValue([summary]);

    render(<StockPage />);

    expect(await screen.findByText("+610")).toBeTruthy();
    expect(screen.getByText("-23.4k")).toBeTruthy();
    expect(screen.getByLabelText("Saída de stock: 23,400")).toBeTruthy();
    expect(screen.queryByText("-0")).toBeNull();
  });
});

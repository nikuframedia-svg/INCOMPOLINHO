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
import { stockCellTitle } from "../src/lib/stockSubcontract";
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

  describe("referências subcontratadas", () => {
    const back = {
      qty: 7_680, stamped_from_day: 3, stamped_to_day: 3,
      stamped_from_date: "2026-10-12", stamped_to_date: "2026-10-12", machines: ["PRM043"],
    };
    const sentDay = {
      day: 3, date: "2026-10-12", stock: -100, demand: 0, produced: 0, workday: true, subcontract_sent: 7_680,
    };
    const returnDay = {
      day: 8, date: "2026-10-19", stock: 7_580, demand: 0, produced: 7_680, workday: true,
      subcontract_returns: [back],
    };

    it("explica no tooltip o envio e a volta da subcontratação", () => {
      expect(stockCellTitle(sentDay).split("\n")).toEqual([
        "Stock: -100", "Procura: 0", "Produção: 0", `Enviado para subcontratação: ${(7_680).toLocaleString()}`,
      ]);
      expect(stockCellTitle(returnDay).split("\n")).toEqual([
        `Stock: ${(7_580).toLocaleString()}`, "Procura: 0",
        `Volta da subcontratação: ${(7_680).toLocaleString()} (estampadas a 12/10 na PRM043)`,
      ]);
    });

    it("mostra vários dias e máquinas de estampagem e a produção da casa à parte", () => {
      const title = stockCellTitle({
        ...returnDay, produced: 7_700,
        subcontract_returns: [{
          ...back, stamped_from_day: 2, stamped_from_date: "2026-10-09", machines: ["PRM019", "PRM043"],
        }],
      });
      expect(title.split("\n").slice(2)).toEqual([
        "Produção: 20",
        `Volta da subcontratação: ${(7_680).toLocaleString()} (estampadas de 09/10 a 12/10 na PRM019 e PRM043)`,
      ]);
      expect(stockCellTitle({ ...returnDay, subcontract_returns: [{ ...back, stamped_from_date: "", stamped_to_date: "" }] }))
        .toContain("(estampadas a dia 3 na PRM043)");
    });

    it("sem dados de subcontratação mantém o tooltip antigo", () => {
      expect(stockCellTitle({ stock: 5, demand: 1, produced: 6, workday: true }))
        .toBe("Stock: 5\nProcura: 1\nProdução: 6");
      expect(stockCellTitle({ stock: 5, demand: 0, produced: 0, workday: false })).toBe("Fim-de-semana / Feriado");
    });

    it("marca na grelha o dia de envio e o dia de volta, com legenda", async () => {
      const summary: StockSummary = {
        op_id: "OP-SUB", sku: "CF589MMA1A02.20", client: "CLIENTE", machine: "PRM043", tool: "JTE001",
        initial_stock: 0, stockout_day: null, coverage_days: 10, total_demand: 7_680, total_produced: 7_680,
        subcontract_company_id: "SUB", days: [sentDay, returnDay],
      };
      endpointMocks.getStockSummary.mockResolvedValue([summary]);

      const view = render(<StockPage />);

      const sent = await screen.findByLabelText(`Enviado para subcontratação: ${(7_680).toLocaleString()}`);
      expect(sent.textContent).toBe(`↗${(7_680).toLocaleString()}`);
      const returned = screen.getByLabelText(`Volta da subcontratação: ${(7_680).toLocaleString()}`);
      expect(returned.textContent).toBe(`↩+${(7_680).toLocaleString()}`);
      // The return is not shown twice as in-house production.
      expect(screen.queryByText(/^\+7/)).toBeNull();
      expect(view.container.querySelector('[title*="estampadas a 12/10 na PRM043"]')).toBeTruthy();
      expect(screen.getByText("Volta da subcontratação (entra no stock)")).toBeTruthy();
      expect(screen.getByText("Enviado para subcontratação (ainda não conta)")).toBeTruthy();
    });
  });
});

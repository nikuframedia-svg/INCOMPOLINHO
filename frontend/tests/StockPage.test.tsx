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
import { stockCellTitle, subcontractBadgeTitle } from "../src/lib/stockCell";
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
    // Made on 12/10 for a delivery on 19/10: shown like any other reference.
    const producedDay = { day: 3, date: "2026-10-12", stock: 7_680, demand: 0, produced: 7_680, workday: true };
    const deliveryDay = { day: 8, date: "2026-10-19", stock: 0, demand: 7_680, produced: 0, workday: true };
    const summary: StockSummary = {
      op_id: "OP-SUB", sku: "CF589MMA1A02.20", client: "CLIENTE", machine: "PRM043", tool: "JTE001",
      initial_stock: 0, stockout_day: null, coverage_days: 10, total_demand: 7_680, total_produced: 7_680,
      subcontract_company_id: "SUBCONTRATO", subcontract_due_workdays: 5, days: [producedDay, deliveryDay],
    };

    it("tooltip do dia só com stock, procura e produção", () => {
      expect(stockCellTitle(producedDay).split("\n")).toEqual([
        `Stock: ${(7_680).toLocaleString()}`, "Procura: 0", `Produção: ${(7_680).toLocaleString()}`,
      ]);
      expect(stockCellTitle({ stock: 5, demand: 0, produced: 0, workday: false })).toBe("Fim-de-semana / Feriado");
    });

    it("mostra a produção no dia em que é feita e a saída no dia da entrega, sem setas", async () => {
      endpointMocks.getStockSummary.mockResolvedValue([summary]);

      const view = render(<StockPage />);

      expect(await screen.findByText(`+${(7_680).toLocaleString()}`)).toBeTruthy();
      expect(screen.getByLabelText(`Saída de stock: ${(7_680).toLocaleString()}`)).toBeTruthy();
      expect(view.container.textContent).not.toMatch(/[↗↩]/);
      expect(screen.queryByText(/subcontratação/i)).toBeNull();
      expect(view.container.querySelector('[title*="subcontratação"]')).toBeNull();
    });

    it("marca a referência com um S e explica a regra dos 5 dias úteis", async () => {
      endpointMocks.getStockSummary.mockResolvedValue([summary, { ...summary, op_id: "OP-CASA", sku: "CASA", subcontract_company_id: null, subcontract_due_workdays: null }]);

      render(<StockPage />);

      const badge = await screen.findByText("S");
      expect(badge.getAttribute("title")).toBe("Subcontratada: produção acabada 5 dias úteis antes da entrega.");
      expect(screen.getAllByText("S")).toHaveLength(1);
      expect(subcontractBadgeTitle(1)).toBe("Subcontratada: produção acabada 1 dia útil antes da entrega.");
      expect(subcontractBadgeTitle(undefined)).toBe("Subcontratada: produção acabada antes da entrega.");
    });

    it("produção depois do prazo: a entrega fica a vermelho mesmo com stock", async () => {
      endpointMocks.getStockSummary.mockResolvedValue([{ ...summary, stockout_day: 8 }]);

      const view = render(<StockPage />);

      expect(await screen.findByText(/esgota dia 8/)).toBeTruthy();
      const cells = [...view.container.querySelectorAll<HTMLElement>("[title^='Stock:']")];
      const late = cells.find((cell) => cell.title.includes(`Procura: ${(7_680).toLocaleString()}`));
      const made = cells.find((cell) => cell.title.includes(`Produção: ${(7_680).toLocaleString()}`));
      expect(late?.style.background).not.toBe("transparent");
      expect(made?.style.background).toBe("transparent");
    });
  });
});

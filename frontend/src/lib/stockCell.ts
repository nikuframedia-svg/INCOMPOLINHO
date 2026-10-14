import type { StockDayCompact } from "../api/types";

export const NON_WORKDAY_TITLE = "Fim-de-semana / Feriado";

/** Tooltip of a stock cell: stock, demand and production of the day. */
export function stockCellTitle(day: Pick<StockDayCompact, "stock" | "demand" | "produced" | "workday">): string {
  if (!day.workday) return NON_WORKDAY_TITLE;
  return [
    `Stock: ${day.stock.toLocaleString()}`,
    `Procura: ${day.demand.toLocaleString()}`,
    `Produção: ${day.produced.toLocaleString()}`,
  ].join("\n");
}

/**
 * Tooltip of the «S» next to a subcontracted reference. The working days
 * come from the server (subcontract lead time plus buffer); older servers
 * omit them.
 */
export function subcontractBadgeTitle(dueWorkdays: number | null | undefined): string {
  if (dueWorkdays == null || dueWorkdays <= 0) return "Subcontratada: produção acabada antes da entrega.";
  const days = dueWorkdays === 1 ? "1 dia útil" : `${dueWorkdays} dias úteis`;
  return `Subcontratada: produção acabada ${days} antes da entrega.`;
}

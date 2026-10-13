import type { StockDayCompact, SubcontractReturn } from "../api/types";
import { fmtDeliveryDate } from "./segmentDeliveries";

type StockCellDay = Pick<
  StockDayCompact,
  "stock" | "demand" | "produced" | "workday" | "subcontract_sent" | "subcontract_returns"
>;

export const NON_WORKDAY_TITLE = "Fim-de-semana / Feriado";

function fmtQty(qty: number): string {
  return qty.toLocaleString();
}

function stampDay(day: number, isoDate: string): string {
  return isoDate ? fmtDeliveryDate(isoDate) : `dia ${day}`;
}

function stampDays(item: SubcontractReturn): string {
  const from = stampDay(item.stamped_from_day, item.stamped_from_date);
  if (item.stamped_from_day === item.stamped_to_day) return `estampadas a ${from}`;
  return `estampadas de ${from} a ${stampDay(item.stamped_to_day, item.stamped_to_date)}`;
}

function machinesText(machines: readonly string[]): string {
  if (!machines.length) return "";
  if (machines.length === 1) return ` na ${machines[0]}`;
  return ` na ${machines.slice(0, -1).join(", ")} e ${machines[machines.length - 1]}`;
}

/** "Volta da subcontratação: 100 (estampadas a 15/09 na PRM043)" */
export function subcontractReturnLine(item: SubcontractReturn): string {
  return `Volta da subcontratação: ${fmtQty(item.qty)} (${stampDays(item)}${machinesText(item.machines)})`;
}

export function subcontractReturnedQty(day: Pick<StockDayCompact, "subcontract_returns">): number {
  return (day.subcontract_returns ?? []).reduce((sum, item) => sum + item.qty, 0);
}

/**
 * Tooltip of a stock cell. A subcontracted piece counts on the day it is
 * back from the subcontractor; the day it is stamped only shows it leaving.
 */
export function stockCellTitle(day: StockCellDay): string {
  const sent = day.subcontract_sent ?? 0;
  const returns = day.subcontract_returns ?? [];
  if (!day.workday && !sent && !returns.length) return NON_WORKDAY_TITLE;
  const lines = [`Stock: ${fmtQty(day.stock)}`, `Procura: ${fmtQty(day.demand)}`];
  const inHouse = day.produced - subcontractReturnedQty(day);
  if (!returns.length || inHouse > 0) lines.push(`Produção: ${fmtQty(Math.max(inHouse, 0))}`);
  lines.push(...returns.map(subcontractReturnLine));
  if (sent > 0) lines.push(`Enviado para subcontratação: ${fmtQty(sent)}`);
  return lines.join("\n");
}

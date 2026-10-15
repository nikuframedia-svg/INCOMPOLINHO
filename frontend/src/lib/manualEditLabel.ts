import type { Lot, ManualEdit } from "../api/types";

/**
 * «Referência 6800016767A.10 · JTE001 (PRM043) → 03/12 08:45»: a lot pinned by hand,
 * as the planner knows it; never the internal lot id (decisão de 15/10/2026).
 */
export function manualEditLabel(edit: ManualEdit, lots: readonly Lot[], workdays: readonly string[]): string {
  const lot = lots.find((item) => item.id === edit.lot_id);
  const twins = lot?.twin_outputs?.map((output) => output[1] || output[0]).filter(Boolean) ?? [];
  const base = twins.length ? [...new Set(twins)].join(" + ") : lot?.sku || lot?.op_id || "lote";
  const reference = lot?.tool_id ? `${base} · ${lot.tool_id}` : base;
  const day = edit.target_day != null ? workdays[edit.target_day] : undefined;
  const date = day ? `${day.slice(8, 10)}/${day.slice(5, 7)}` : edit.target_day != null ? `dia ${edit.target_day}` : "";
  const minute = edit.target_start_min;
  const time = minute != null ? ` ${String(Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}` : "";
  return `Referência ${reference} (${edit.target_machine}) → ${date}${time}`.trim();
}

import type { ConsoleData, GateReport } from "../api/types";

type ConsoleRisk = ConsoleData["top_risks"][number];

/** Server-side risk status; the server already filters the window and sorts. */
export type RiskStatus = "late" | "at_limit" | "short_slack";

const STATUS_LABELS: Record<RiskStatus, string> = {
  late: "Atrasado",
  at_limit: "No limite",
  short_slack: "Folga curta",
};

/**
 * Plain wording for causes the backend has proven (binding-constraint analysis
 * or late-delivery root cause). Anything not listed is not shown: a cause is
 * only displayed when we can explain it in plain words.
 */
const CAUSE_LABELS: Record<string, string> = {
  setup: "mudanças de ferramenta ao mesmo tempo",
  operator: "falta de operadores no turno",
  calendar: "máquina ou ferramenta parada",
  jit_exception: "produção fora dos dias permitidos para o material",
  long_run: "produção longa",
  setup_overhead: "muitas mudanças de ferramenta",
  priority_conflict: "outras encomendas à frente",
  lead_time: "pouco tempo até à entrega",
  tool_contention: "ferramenta ocupada noutra máquina",
};

/** Real pt-PT singular/plural: plural(1, "dia", "dias") -> "1 dia". */
export function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${Math.abs(count) === 1 ? singular : pluralForm}`;
}

export function riskStatus(risk: ConsoleRisk): RiskStatus | null {
  const status = risk.status;
  return status === "late" || status === "at_limit" || status === "short_slack" ? status : null;
}

export function riskStatusLabel(risk: ConsoleRisk): string | null {
  const status = riskStatus(risk);
  return status ? STATUS_LABELS[status] : null;
}

export function riskCauseLabel(risk: ConsoleRisk): string | null {
  const cause = risk.cause;
  if (typeof cause !== "string" || !cause) return null;
  return CAUSE_LABELS[cause] ?? null;
}

export type LateOrderRow = {
  client: string;
  sku: string;
  order_qty: number;
  covered_qty: number;
  shortfall_qty: number;
  due_day: number | null;
  ready_day: number | null;
  late_days: number | null;
  /** Machine where the order is produced, when the report says it. */
  machine_id: string | null;
};

export type LongProductionRow = {
  lot_id: string;
  sku: string;
  machine_id: string;
  workdays: number | null;
  limit_workdays: number | null;
  /** All production days of the lot (may continue after a break). */
  total_days: number | null;
  /** Days in the longest consecutive run. */
  consecutive_days: number | null;
};

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function records(raw: unknown): Record<string, unknown>[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is Record<string, unknown> => !!item && typeof item === "object");
}

/** Late orders from the plan report; older reports without the field give []. */
export function lateOrderRows(gate: GateReport | null | undefined): LateOrderRow[] {
  return records(gate?.late_order_detail).map((item) => ({
    client: String(item.client ?? ""),
    sku: String(item.sku ?? ""),
    order_qty: asNumber(item.order_qty) ?? 0,
    covered_qty: asNumber(item.covered_qty) ?? 0,
    shortfall_qty: asNumber(item.shortfall_qty) ?? 0,
    due_day: asNumber(item.due_day),
    ready_day: asNumber(item.ready_day),
    late_days: asNumber(item.late_days),
    machine_id: typeof item.machine_id === "string" && item.machine_id ? item.machine_id : null,
  }));
}

/** Long productions from the plan report; older reports without the field give []. */
export function longProductionRows(gate: GateReport | null | undefined): LongProductionRow[] {
  return records(gate?.long_production_detail).map((item) => ({
    lot_id: String(item.lot_id ?? ""),
    sku: String(item.sku ?? ""),
    machine_id: String(item.machine_id ?? ""),
    workdays: asNumber(item.workdays),
    limit_workdays: asNumber(item.limit_workdays),
    total_days: Array.isArray(item.days) ? item.days.length : null,
    consecutive_days: Array.isArray(item.consecutive_days) ? item.consecutive_days.length : null,
  }));
}

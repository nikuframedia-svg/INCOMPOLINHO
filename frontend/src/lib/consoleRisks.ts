import type { ConsoleData } from "../api/types";

type ConsoleRisk = ConsoleData["top_risks"][number];

export function riskRelevantDay(risk: ConsoleRisk) {
  const values = [risk.production_day, risk.completion_day, risk.edd]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  return values.length ? Math.min(...values) : null;
}

function riskDateSortKey(risk: ConsoleRisk) {
  const riskDay = Number(risk.edd);
  if (Number.isFinite(riskDay)) return riskDay;
  const completion = Number(risk.completion_day);
  if (Number.isFinite(completion)) return completion;
  const production = Number(risk.production_day);
  return Number.isFinite(production) ? production : Number.POSITIVE_INFINITY;
}

export function sortRisksByNearestDate(risks: ConsoleData["top_risks"]) {
  return [...risks].sort((a, b) => {
    const dateDelta = riskDateSortKey(a) - riskDateSortKey(b);
    if (dateDelta !== 0) return dateDelta;
    const scoreDelta = Number(b.risk_score ?? 0) - Number(a.risk_score ?? 0);
    if (scoreDelta !== 0) return scoreDelta;
    return String(a.sku ?? "").localeCompare(String(b.sku ?? ""));
  });
}

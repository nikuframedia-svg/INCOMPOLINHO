import { ApiError } from "../api/client";
import type { GateReport } from "../api/types";

const APPROVAL_REASON_LABELS: Record<string, string> = {
  delivery_risk: "existem entregas em risco",
  subcontract_dispatch_risk: "existem expedições de subcontratação em risco",
  long_production: "existem produções acima da duração recomendada",
  robustness_not_evaluated: "a robustez ainda não foi avaliada",
  robustness_below_threshold: "a robustez está abaixo do limite definido",
  operational_sequence_review: "a sequência operacional requer revisão",
};

export function approvalReasonLabel(reason: string): string {
  return APPROVAL_REASON_LABELS[reason] ?? reason;
}

export function approvalGateFromError(error: unknown): GateReport | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  if (!error.detail || typeof error.detail !== "object") return null;
  const report = (error.detail as { gate_report?: unknown }).gate_report;
  if (!report || typeof report !== "object") return null;
  const gate = report as GateReport;
  return gate.requires_approval && gate.apply_decision !== "blocked" ? gate : null;
}

export type GateApproval = { reason: string; author: string };

/** Approval fields for a write request; empty when there is no approval. */
export function approvalFields(approval?: GateApproval): Record<string, unknown> {
  return approval
    ? { approve_exceptions: true, approval_reason: approval.reason, approval_author: approval.author }
    : {};
}

/**
 * Send a plan-changing write; when the server answers that the candidate
 * needs explicit approval, ask the planner for a justification and send it
 * again with that approval. The server then applies exactly the candidate it
 * showed (the request identity ignores approval fields). Returns null when the
 * planner cancels: nothing was applied.
 */
export async function sendWithGateApproval<T>(
  send: (approval?: GateApproval) => Promise<T>,
  ask: (gate: GateReport) => Promise<string | null>,
  author = "planeador",
): Promise<T | null> {
  try {
    return await send();
  } catch (error) {
    const gate = approvalGateFromError(error);
    if (!gate) throw error;
    const reason = await ask(gate);
    if (reason === null) return null;
    return await send({ reason, author });
  }
}

export function approvalImpactMessage(gate: GateReport): string {
  const metrics = gate.metrics ?? {};
  const tardy = Number(metrics.tardy_count ?? metrics.tardy_lots ?? 0);
  const robustness = Number(metrics.robustness_success_probability_pct);
  const relativeRobustness = Number(metrics.robustness_model_version ?? 0) >= 4;
  const robustnessNotEvaluated = gate.approval_reasons?.includes("robustness_not_evaluated")
    || Number(metrics.robustness_evaluated_samples ?? 0) === 0;
  const impact = [
    tardy > 0 ? `${tardy} entrega${tardy === 1 ? "" : "s"} com atraso` : "sem atrasos identificados",
    robustnessNotEvaluated
      ? "robustez ainda não avaliada"
      : Number.isFinite(robustness)
      ? relativeRobustness
        ? `probabilidade de não criar novos atrasos de ${robustness.toFixed(1)}%`
        : `robustez de ${robustness.toFixed(1)}% (modelo anterior)`
      : null,
  ].filter(Boolean).join(" e ");
  const reasons = gate.approval_reasons?.map(approvalReasonLabel).join(", ")
    || "exceções operacionais";

  return [
    "O candidato respeita as regras físicas, de capacidade e de matéria-prima.",
    `Requer decisão do planeador por: ${reasons}.`,
    `Impacto previsto: ${impact}.`,
    "Indica uma justificação para aplicar este plano.",
  ].join("\n");
}

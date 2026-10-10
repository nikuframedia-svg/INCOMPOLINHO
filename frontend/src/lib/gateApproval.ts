import { ApiError } from "../api/client";
import type { GateReport } from "../api/types";

/**
 * The single plain-language dictionary for approval reasons (codes from
 * backend/scheduler/gates.py). Every screen that names a reason uses it, so a
 * planner never sees a raw code. Phrases are lowercase fragments; use
 * approvalReasonSentence() for a standalone sentence.
 */
const APPROVAL_REASON_LABELS: Record<string, string> = {
  delivery_risk: "há encomendas que ficam atrasadas",
  subcontract_dispatch_risk: "existem envios para subcontratação em risco",
  jit_window_blocked: "há produções marcadas antes de o material ser libertado",
  material_release_blocked: "há mudanças de ferramenta marcadas antes de o material ser libertado",
  operator_capacity_shortage: "faltam operadores em alguns turnos",
  operational_sequence_review: "a ordem de produção tem pontos a rever",
  operational_sequence_not_evaluated: "a verificação da ordem de produção ficou por avaliar",
  // Revisões antigas ainda trazem estes motivos; a robustez é hoje apenas
  // informativa e já não pede aprovação.
  robustness_not_evaluated: "robustez por avaliar (critério antigo; hoje só informativo)",
  robustness_below_threshold: "robustez abaixo do limite (critério antigo; hoje só informativo)",
  // A fábrica retirou o limite de dias seguidos (09/10/2026); só revisões
  // antigas trazem este motivo.
  long_production: "produção em dias seguidos acima do limite (critério antigo; já não se aplica)",
};

/**
 * Revisões antigas pediam aprovação por lotes acabados depois do prazo de
 * produção, mesmo sem nenhuma encomenda atrasada. Nesse caso o motivo
 * "delivery_risk" mantém o texto antigo, para não contradizer o impacto.
 */
const LEGACY_LOT_DELIVERY_RISK_LABEL = "há lotes que acabam depois do prazo de produção";

/** Reason codes the backend can emit today (gates.py); each one has a plain label. */
export const BACKEND_APPROVAL_REASONS = [
  "delivery_risk",
  "subcontract_dispatch_risk",
  "jit_window_blocked",
  "material_release_blocked",
  "operator_capacity_shortage",
  "operational_sequence_review",
  "operational_sequence_not_evaluated",
] as const;

const UNKNOWN_REASON_LABEL = "existe uma exceção de planeamento a rever";

const LEGACY_ROBUSTNESS_REASONS = new Set(["robustness_not_evaluated", "robustness_below_threshold"]);

/** Old approval reasons from when robustness still gated plans; informative only now. */
export function isLegacyRobustnessReason(reason: string): boolean {
  return LEGACY_ROBUSTNESS_REASONS.has(reason);
}

/** Old reasons the planner no longer decides on (robustness, the removed consecutive-days limit). */
export function isLegacyReason(reason: string): boolean {
  return isLegacyRobustnessReason(reason) || reason === "long_production";
}

const REASON_CODE = /^[a-z0-9_]+$/;

/**
 * Plain phrase for a reason code; never the raw code. A reason that already is
 * written text (not a code) is shown as is.
 */
export function approvalReasonLabel(reason: string): string {
  const label = APPROVAL_REASON_LABELS[reason];
  if (label) return label;
  return REASON_CODE.test(reason) || !reason.trim() ? UNKNOWN_REASON_LABEL : reason;
}

/**
 * Plain phrase for a reason in the context of its report. delivery_risk is
 * order-based; an old report that raised it for late lots only (no late
 * order, or no order metrics at all) keeps the old lot wording so the reason
 * and the impact line agree.
 */
export function gateReasonLabel(reason: string, gate: Pick<GateReport, "metrics">): string {
  if (reason === "delivery_risk") {
    const metrics = gate.metrics ?? {};
    const ordersLate = count(metrics.orders_late);
    if ((ordersLate === null || ordersLate === 0) && (lateLots(metrics) ?? 0) > 0) {
      return LEGACY_LOT_DELIVERY_RISK_LABEL;
    }
  }
  return approvalReasonLabel(reason);
}

function toSentence(label: string): string {
  const trimmed = label.trim();
  const sentence = `${trimmed.charAt(0).toUpperCase()}${trimmed.slice(1)}`;
  return /[.!?]$/.test(sentence) ? sentence : `${sentence}.`;
}

/** The reason as a standalone sentence ("Há encomendas que ficam atrasadas."). */
export function approvalReasonSentence(reason: string): string {
  return toSentence(approvalReasonLabel(reason));
}

const GATE_STATUS_LABELS: Record<string, string> = {
  applicable: "pode ser aplicado",
  auto_applicable: "pode ser aplicado",
  best_effort: "precisa de aprovação",
  approval_required: "precisa de aprovação",
  jit_window_blocked: "bloqueado: produção fora dos dias permitidos",
  invalid_physics: "bloqueado: viola regras físicas",
  blocked: "bloqueado",
};

/** Plain wording for a stored gate status; never shows the raw code. */
export function gateStatusLabel(status: string | null | undefined): string {
  return status ? GATE_STATUS_LABELS[status] ?? "por validar" : "por validar";
}

/** Reasons that still matter for a decision (legacy reasons are informative only). */
export function decisionReasons(gate: Pick<GateReport, "approval_reasons">): string[] {
  return (gate.approval_reasons ?? []).filter((reason) => !isLegacyReason(reason));
}

/** Plain phrases for the reasons that still need a decision, read against the report. */
export function decisionReasonLabels(gate: Pick<GateReport, "approval_reasons" | "metrics">): string[] {
  return decisionReasons(gate).map((reason) => gateReasonLabel(reason, gate));
}

/** Same as decisionReasonLabels, each as a standalone sentence. */
export function decisionReasonSentences(gate: Pick<GateReport, "approval_reasons" | "metrics">): string[] {
  return decisionReasonLabels(gate).map(toSentence);
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Lots that finish after their production due day (tardy_lots on old reports). */
function lateLots(metrics: GateReport["metrics"]): number | null {
  return count(metrics?.tardy_count) ?? count(metrics?.tardy_lots);
}

/** "N lote(s) acaba(m) depois do prazo de produção", with real singular/plural. */
function lotsLateClause(lots: number): string {
  return `${plural(lots, "lote acaba", "lotes acabam")} depois do prazo de produção`;
}

/**
 * Orders when the report has order metrics, otherwise lots (old reports).
 * Old reports could raise delivery_risk for late lots with no late order:
 * then say both, so the reason and the impact never contradict each other.
 */
function deliveryImpact(gate: GateReport): string {
  const metrics = gate.metrics ?? {};
  const ordersLate = count(metrics.orders_late);
  if (ordersLate !== null) {
    if (ordersLate > 0) {
      return `${plural(ordersLate, "encomenda", "encomendas")} ${ordersLate === 1 ? "fica atrasada" : "ficam atrasadas"}`;
    }
    const lotsLate = lateLots(metrics) ?? 0;
    return lotsLate > 0
      ? `nenhuma encomenda fica atrasada; ${lotsLateClause(lotsLate)}`
      : "nenhuma encomenda fica atrasada";
  }
  const lots = lateLots(metrics) ?? 0;
  return lots > 0 ? lotsLateClause(lots) : "sem atrasos identificados";
}

function resourceName(resourceType: string, resourceId: string): string {
  if (resourceType === "machine") return resourceId;
  if (resourceType === "tool") return `ferramenta ${resourceId}`;
  return resourceId;
}

function hoursLabel(minutes: number): string {
  const hours = Math.round(minutes / 60);
  return hours < 1 ? "menos de 1 h" : `cerca de ${hours} h`;
}

export type CapacityShortfall = { resource: string; deficitMin: number };

/**
 * Biggest capacity shortfall per resource. The analysis reports overlapping
 * windows on the same resource (e.g. D23–D33 and D26–D33), so taking the
 * largest is the honest figure; summing would count the same minutes twice.
 */
export function capacityShortfalls(gate: GateReport): CapacityShortfall[] {
  const constraints = gate.feasibility?.binding_constraints;
  if (!Array.isArray(constraints)) return [];
  const byResource = new Map<string, CapacityShortfall>();
  for (const constraint of constraints) {
    const deficit = count(constraint?.deficit_min);
    if (deficit === null || deficit <= 0) continue;
    const resource = resourceName(String(constraint.resource_type), String(constraint.resource_id));
    const current = byResource.get(resource);
    if (!current || deficit > current.deficitMin) byResource.set(resource, { resource, deficitMin: deficit });
  }
  return [...byResource.values()].sort((a, b) => b.deficitMin - a.deficitMin);
}

/** Two to four short, plain sentences for the top of the plan card. */
export function gateSummaryLines(gate: GateReport): string[] {
  const metrics = gate.metrics ?? {};
  const lines: string[] = [];

  const ordersLate = count(metrics.orders_late);
  const ordersTotal = count(metrics.orders_total);
  const lotsLate = lateLots(metrics);
  if (ordersLate !== null) {
    if (ordersLate > 0) {
      lines.push(ordersTotal !== null
        ? `${ordersLate} de ${ordersTotal} encomendas ${ordersLate === 1 ? "fica atrasada" : "ficam atrasadas"}.`
        : `${plural(ordersLate, "encomenda", "encomendas")} ${ordersLate === 1 ? "fica atrasada" : "ficam atrasadas"}.`);
    } else if (lotsLate !== null && lotsLate > 0) {
      // Old reports: delivery_risk fired for late lots; say why without contradicting the orders.
      lines.push(`Nenhuma encomenda fica atrasada; ${lotsLateClause(lotsLate)}.`);
    } else {
      lines.push(ordersTotal !== null
        ? `Todas as ${ordersTotal} encomendas ficam prontas a tempo.`
        : "Todas as encomendas ficam prontas a tempo.");
    }
  } else if (lotsLate !== null) {
    lines.push(lotsLate > 0
      ? `${plural(lotsLate, "lote acaba", "lotes acabam")} depois do prazo de produção.`
      : "Nenhum lote acaba depois do prazo de produção.");
  }

  const shortfalls = capacityShortfalls(gate);
  if (shortfalls.length > 0) {
    const parts = shortfalls.slice(0, 3).map((item) => `${item.resource} ${hoursLabel(item.deficitMin)}`);
    const rest = shortfalls.length - parts.length;
    lines.push(`Falta capacidade para cumprir todos os prazos: ${parts.join(", ")}${rest > 0 ? ` e mais ${rest}` : ""}.`);
  }

  const missingLots = count(metrics.missing_lots);
  if (missingLots && missingLots > 0) {
    lines.push(`${plural(missingLots, "lote fica", "lotes ficam")} sem produção suficiente.`);
  }
  const subcontractMisses = count(metrics.subcontract_dispatch_misses);
  if (subcontractMisses && subcontractMisses > 0) {
    lines.push(`${plural(subcontractMisses, "envio", "envios")} para subcontratação ${subcontractMisses === 1 ? "sai" : "saem"} tarde.`);
  }
  const early = count(metrics.early_window_violations);
  if (early && early > 0) {
    lines.push(`${plural(early, "produção está marcada", "produções estão marcadas")} antes de o material ser libertado.`);
  }
  return lines.slice(0, 4);
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

export type ApprovalDialogKind = "justification" | "confirm";

/**
 * Text for the approval dialog. `dialog` must match the dialog that shows it:
 * "justification" for a prompt with a text field, "confirm" for a plain
 * yes/no dialog (it cannot collect a justification, so it does not ask for one).
 */
export function approvalImpactMessage(gate: GateReport, dialog: ApprovalDialogKind = "justification"): string {
  // Legacy reasons are informative only: they never explain why a decision is needed.
  const reasons = decisionReasonLabels(gate).join(", ") || "exceções operacionais";

  return [
    "O plano proposto pode ser executado: respeita máquinas, ferramentas, equipas, calendário e material.",
    `Requer decisão do planeador por: ${reasons}.`,
    `Impacto previsto: ${deliveryImpact(gate)}.`,
    dialog === "confirm"
      ? "Confirma para aplicar este plano."
      : "Indica uma justificação para aplicar este plano.",
  ].join("\n");
}

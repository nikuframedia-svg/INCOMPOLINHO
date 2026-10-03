import type {
  DeltaReport,
  FeasibilityReport,
  GateReport,
  ManualMoveJob,
  ManualMoveResponse,
} from "../api/types";

const CONTRACT_VERSION = 2;
const DELTA_FIELDS: (keyof DeltaReport)[] = [
  "otd_before",
  "otd_after",
  "otd_d_before",
  "otd_d_after",
  "setups_before",
  "setups_after",
  "earliness_before",
  "earliness_after",
  "tardy_before",
  "tardy_after",
];

interface ManualMoveApplyValidation {
  requiresConfirmation: boolean;
  confirmed: boolean;
  reason: string;
}

export function getManualMoveApplyError({
  requiresConfirmation,
  confirmed,
  reason,
}: ManualMoveApplyValidation): string | null {
  if (!requiresConfirmation) return null;
  if (!confirmed) {
    return "Confirma que aceitas as exceções do plano antes de aplicar.";
  }
  if (!reason.trim()) {
    return "Indica o motivo da alteração para aplicar um movimento com exceções.";
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(isRecord)
    : [];
}

function normalizeFeasibility(value: unknown): FeasibilityReport | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.strict_feasible !== "boolean"
    || !Array.isArray(value.binding_constraints)
    || !Array.isArray(value.interventions)
  ) {
    return null;
  }
  return {
    ...value,
    binding_constraints: recordArray(value.binding_constraints),
    interventions: recordArray(value.interventions),
  } as unknown as FeasibilityReport;
}

function normalizeGateReport(value: unknown): GateReport {
  if (!isRecord(value)) {
    throw new Error("A verificação não devolveu um relatório de riscos válido.");
  }
  if (
    typeof value.apply_decision !== "string"
    || typeof value.requires_approval !== "boolean"
    || typeof value.physical_gate_passed !== "boolean"
    || typeof value.coverage_gate_passed !== "boolean"
  ) {
    throw new Error(
      "O servidor está desatualizado e não consegue verificar este movimento com segurança. Reinicia a aplicação; nenhuma alteração foi guardada.",
    );
  }
  return {
    ...value,
    metrics: isRecord(value.metrics) ? value.metrics : {},
    approval_reasons: Array.isArray(value.approval_reasons)
      ? value.approval_reasons.filter((item): item is string => typeof item === "string")
      : [],
    violations: recordArray(value.violations),
    late_detail: recordArray(value.late_detail),
    jit_window_detail: recordArray(value.jit_window_detail),
    setup_overlap_detail: recordArray(value.setup_overlap_detail),
    long_production_detail: recordArray(value.long_production_detail),
    proposals: recordArray(value.proposals),
    feasibility: normalizeFeasibility(value.feasibility),
  } as unknown as GateReport;
}

export function normalizeManualMoveResponse(value: unknown): ManualMoveResponse {
  if (!isRecord(value) || value.contract_version !== CONTRACT_VERSION) {
    throw new Error(
      "O servidor está desatualizado e não consegue verificar este movimento com segurança. Reinicia a aplicação; nenhuma alteração foi guardada.",
    );
  }
  const delta = isRecord(value.delta) ? value.delta : null;
  if (!delta || DELTA_FIELDS.some((field) => typeof delta[field] !== "number")) {
    throw new Error("A verificação devolveu valores de impacto incompletos.");
  }
  if (
    (value.status !== "preview" && value.status !== "applied")
    || typeof value.lot_id !== "string"
    || typeof value.target_day !== "number"
    || typeof value.target_machine !== "string"
    || typeof value.requires_confirmation !== "boolean"
  ) {
    throw new Error("A verificação devolveu uma resposta incompleta.");
  }
  return {
    ...value,
    contract_version: CONTRACT_VERSION,
    delta: delta as unknown as DeltaReport,
    gate_report: normalizeGateReport(value.gate_report),
    source_days: Array.isArray(value.source_days)
      ? value.source_days.filter((item): item is number => typeof item === "number")
      : [],
    delivery_warnings: Array.isArray(value.delivery_warnings)
      ? value.delivery_warnings.filter((item): item is string => typeof item === "string")
      : [],
  } as ManualMoveResponse;
}

export function normalizeManualMoveJob(value: unknown): ManualMoveJob {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.status !== "string") {
    throw new Error("O servidor devolveu um trabalho de verificação inválido.");
  }
  const validStatuses = new Set([
    "queued",
    "running",
    "ready",
    "applied",
    "failed",
    "cancelled",
  ]);
  if (!validStatuses.has(value.status)) {
    throw new Error("O servidor devolveu um estado de verificação inválido.");
  }
  const phase = typeof value.phase === "string" ? value.phase : value.status;
  const validPhases = new Set([
    "queued",
    "scheduling",
    "validating",
    "finalizing",
    "ready",
    "applied",
    "failed",
    "cancelled",
  ]);
  if (!validPhases.has(phase)) {
    throw new Error("O servidor devolveu uma fase de verificação inválida.");
  }
  const result = value.result == null
    ? null
    : normalizeManualMoveResponse(value.result);
  return {
    ...value,
    progress: typeof value.progress === "number"
      ? Math.min(100, Math.max(0, value.progress))
      : 0,
    phase,
    message: typeof value.message === "string" ? value.message : "",
    error: typeof value.error === "string" ? value.error : null,
    gate_report: value.gate_report == null ? null : normalizeGateReport(value.gate_report),
    result,
  } as unknown as ManualMoveJob;
}

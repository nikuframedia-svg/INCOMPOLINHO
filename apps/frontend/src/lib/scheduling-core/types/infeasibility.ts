// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Infeasibility Types
//  Formal infeasibility reporting per Normative Spec §11
//
//  When a hard constraint cannot be satisfied even after
//  trying all alternatives, the operation is declared
//  INFEASIBLE with a structured report explaining WHY
//  and WHAT was attempted.
// ═══════════════════════════════════════════════════════════

/**
 * Reason why an operation was declared infeasible.
 * Each reason maps to a specific constraint or resource limit.
 */
export type InfeasibilityReason =
  | 'SETUP_CREW_EXHAUSTED' // No slot for setup in any shift/day remaining
  | 'OPERATOR_CAPACITY' // MO insufficient after reallocation attempts
  | 'TOOL_CONFLICT' // Tool occupied in all available windows
  | 'CALCO_CONFLICT' // Calco occupied in all available windows
  | 'DEADLINE_VIOLATION' // Cannot meet Prz.Fabrico deadline
  | 'MACHINE_DOWN' // Machine is down, no alternative available
  | 'CAPACITY_OVERFLOW' // Total machine capacity exhausted in horizon
  | 'DATA_MISSING' // Essential data missing (setup time, pH, MO, etc.)
  | 'MACHINE_PARTIAL_DOWN' // Machine at reduced capacity, insufficient for operation
  | 'TOOL_DOWN_TEMPORAL' // Tool down for specific day range (temporal failure)
  | 'SHIPPING_CUTOFF_VIOLATION'; // Cannot finish production before shipping cutoff deadline

/**
 * Remediation type — proposed actions to resolve infeasibility.
 */
export type RemediationType =
  | 'THIRD_SHIFT' // Activar 3.º turno
  | 'EXTRA_OPERATORS' // Operadores adicionais
  | 'OVERTIME' // Horas extra dentro dos 2 turnos
  | 'SPLIT_OPERATION' // Dividir operação entre máquinas
  | 'ADVANCE_PRODUCTION' // Antecipar produção para dia anterior
  | 'TRANSFER_ALT_MACHINE' // Mover para máquina alternativa
  | 'FORMAL_RISK_ACCEPTANCE'; // Aceitar atraso formalmente

/**
 * A structured remediation proposal for an infeasible operation.
 */
export interface RemediationProposal {
  type: RemediationType;
  opId: string;
  toolId: string;
  machineId: string;
  description: string;
  /** Minutes of capacity this remediation would free */
  capacityGainMin: number;
  /** Can be applied automatically or requires human decision */
  automated: boolean;
  /** Whether this remediation was executed by auto-replan */
  executed?: boolean;
  /** If executed, the decision ID linking to the registry */
  executionDecisionId?: string;
  /** If executed, whether it resolved the issue */
  resolved?: boolean;
}

/**
 * A single infeasibility declaration for one operation.
 * Contains the reason, what was tried, and a suggestion for resolution.
 */
export interface InfeasibilityEntry {
  /** Operation ID */
  opId: string;
  /** Tool ID */
  toolId: string;
  /** Machine ID where scheduling was attempted */
  machineId: string;
  /** Why the operation is infeasible */
  reason: InfeasibilityReason;
  /** Human-readable explanation */
  detail: string;
  /** List of alternatives tried before declaring infeasibility */
  attemptedAlternatives: string[];
  /** Suggested resolution for the user */
  suggestion: string;
  /** Day index where the issue was encountered */
  dayIdx?: number;
  /** Shift where the issue was encountered */
  shift?: 'X' | 'Y' | 'Z';
}

/**
 * FeasibilityReport — Summary of scheduling feasibility.
 *
 * Generated at the end of every scheduling run.
 * Contains the overall feasibility score and detailed
 * entries for every infeasible operation.
 *
 * A feasibilityScore of 1.0 means all operations were scheduled.
 * A score < 1.0 means some operations are infeasible and need attention.
 */
export interface FeasibilityReport {
  /** Total number of operations analysed */
  totalOps: number;
  /** Operations successfully scheduled */
  feasibleOps: number;
  /** Operations declared infeasible */
  infeasibleOps: number;
  /** Detailed infeasibility entries */
  entries: InfeasibilityEntry[];
  /** Count by reason type */
  byReason: Partial<Record<InfeasibilityReason, number>>;
  /** Global feasibility score (0.0 - 1.0) */
  feasibilityScore: number;
  /** Remediation proposals for infeasible operations */
  remediations: RemediationProposal[];
  /** True when all demand is fully covered (zero atraso) */
  deadlineFeasible: boolean;
}

/**
 * Create an empty FeasibilityReport.
 * Used as the starting point for building the report during scheduling.
 */
export function createEmptyFeasibilityReport(): FeasibilityReport {
  return {
    totalOps: 0,
    feasibleOps: 0,
    infeasibleOps: 0,
    entries: [],
    byReason: {},
    feasibilityScore: 1.0,
    remediations: [],
    deadlineFeasible: true,
  };
}

/**
 * Finalize a FeasibilityReport by computing the score and reason counts.
 */
export function finalizeFeasibilityReport(report: FeasibilityReport): FeasibilityReport {
  const byReason: Partial<Record<InfeasibilityReason, number>> = {};
  for (const entry of report.entries) {
    byReason[entry.reason] = (byReason[entry.reason] || 0) + 1;
  }
  return {
    ...report,
    byReason,
    feasibilityScore: report.totalOps > 0 ? report.feasibleOps / report.totalOps : 1.0,
    remediations: report.remediations ?? [],
    deadlineFeasible: report.deadlineFeasible ?? true,
  };
}

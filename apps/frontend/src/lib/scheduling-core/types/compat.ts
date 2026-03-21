// ═══════════════════════════════════════════════════════════
//  Compatibility types — definitions that lived in now-deleted
//  scheduling-core modules (scheduler/, config/, analysis/, etc).
//  Kept as pure type stubs for frontend UI components.
//  Zero runtime code.
// ═══════════════════════════════════════════════════════════

import type { AlternativeAction, DecisionEntry } from './decisions.js';
import type { Block, MoveAction, AdvanceAction, OvertimeAction, SplitAction, ReplanStrategyType } from './blocks.js';

// ── Auto-Replan ─────────────────────────────────────────

export interface AutoReplanAction {
  strategy: ReplanStrategyType;
  opId: string;
  machineId: string;
  decisionId: string;
  description: string;
  detail: string;
  alternatives: AlternativeAction[];
  metadata?: Record<string, unknown>;
}

export interface AutoReplanResult {
  blocks: Block[];
  scheduleResult: ScheduleAllResult;
  actions: AutoReplanAction[];
  autoMoves: MoveAction[];
  autoAdvances: AdvanceAction[];
  overtimeActions: OvertimeAction[];
  splitActions: SplitAction[];
  thirdShiftActivated: boolean;
  unresolved: Array<{ opId: string; deficit: number; reason: string }>;
  registry: unknown;
  decisions: DecisionEntry[];
}

export interface AutoReplanConfig {
  enabled: boolean;
  strategyOrder: ReplanStrategyType[];
  strategyEnabled: Partial<Record<ReplanStrategyType, boolean>>;
  maxMovesPerRun: number;
  maxOvertimeMinPerMachine: number;
  maxOvertimeMinTotal: number;
  thirdShiftEnabled: boolean;
  splitMinDeficit: number;
  splitMinFraction: number;
}

// ── Validation / Coverage / Late Delivery ───────────────

export type ValidationType =
  | 'TOOL_UNIQUENESS'
  | 'SETUP_CREW_OVERLAP'
  | 'MACHINE_OVERCAPACITY'
  | 'EFFICIENCY_WARNING'
  | 'DEADLINE_MISS';

export interface ScheduleViolation {
  id: string;
  type: ValidationType;
  severity: 'critical' | 'high' | 'medium' | 'low';
  title: string;
  detail: string;
  affectedOps: Array<{ opId: string; toolId: string; machineId: string; dayIdx: number }>;
  suggestedFix: string | null;
  action: MoveAction | null;
}

export interface ScheduleValidationReport {
  valid: boolean;
  violations: ScheduleViolation[];
  summary: {
    toolConflicts: number;
    setupOverlaps: number;
    machineOvercapacity: number;
    efficiencyWarnings: number;
    deadlineMisses: number;
    twinBlocks: number;
    twinGroups: number;
  };
  checkedAt: number;
}

export interface QuickValidateResult {
  criticalCount: number;
  highCount: number;
  warnings: string[];
}

export interface CoverageAuditRow {
  opId: string;
  sku: string;
  nm: string;
  machineId: string;
  toolId: string;
  totalDemand: number;
  produced: number;
  coveragePct: number;
  gap: number;
  reason: 'ok' | 'overflow' | 'blocked' | 'partial' | 'rate_zero' | 'no_demand';
  hasAlt: boolean;
  altM: string | null;
  isTwinProduction?: boolean;
  twinPartnerOpId?: string;
}

export interface CoverageAuditResult {
  rows: CoverageAuditRow[];
  totalDemand: number;
  totalProduced: number;
  globalCoveragePct: number;
  fullyCovered: number;
  partiallyCovered: number;
  zeroCovered: number;
  isComplete: boolean;
}

export type SuggestedAction =
  | 'THIRD_SHIFT'
  | 'OVERTIME'
  | 'NEGOTIATE_DATE'
  | 'SPLIT'
  | 'FORMAL_ACCEPT';

export interface LateDeliveryEntry {
  opId: string;
  sku: string;
  nm: string;
  machineId: string;
  toolId: string;
  cl?: string;
  clNm?: string;
  clientTier: number;
  deadline: number;
  deadlineDate?: string;
  shortfall: number;
  delayDays: number;
  suggestedActions: SuggestedAction[];
  isResolved: boolean;
  resolvedVia?: string;
  resolvedBy?: string;
  resolutionCost?: number;
}

export interface LateDeliveryAnalysis {
  entries: LateDeliveryEntry[];
  unresolvedCount: number;
  resolvedWithCostCount: number;
  totalShortfallPcs: number;
  affectedClients: string[];
  worstTierAffected: number;
  otdDelivery: number;
}

// ── Risk ────────────────────────────────────────────────

export type RiskLevel = 'critical' | 'high' | 'medium' | 'ok';

export interface RiskCell {
  rowId: string;
  dayIdx: number;
  level: RiskLevel;
  tooltip: string;
  entityType: 'machine' | 'tool' | 'constraint';
}

export interface RiskRow {
  id: string;
  label: string;
  entityType: 'machine' | 'tool' | 'constraint';
  cells: RiskCell[];
  worstLevel: RiskLevel;
}

export interface RiskGridData {
  rows: RiskRow[];
  dates: string[];
  dnames: string[];
  summary: { criticalCount: number; highCount: number; mediumCount: number };
}

export interface RiskValidationInput {
  violations: Array<{
    severity: 'critical' | 'high' | 'medium' | 'low';
    affectedOps: Array<{ machineId: string; dayIdx: number }>;
  }>;
}

// ── Decisions (gen-decisions) ───────────────────────────

export type DecisionSeverity = 'critical' | 'high' | 'medium' | 'low';
export type DecisionKind = 'replan' | 'blocked';

export interface ReplanProposal {
  id: string;
  opId: string;
  type: DecisionKind;
  severity: DecisionSeverity;
  title: string;
  desc: string;
  reasoning: string[];
  impact: Record<string, unknown> | null;
  action: MoveAction | null;
}

// ── Replan Control ──────────────────────────────────────

export interface ReplanActionDetail {
  decisionId: string;
  strategy: ReplanStrategyType;
  opId: string;
  sku: string;
  machineId: string;
  summary: string;
  detail: string;
  alternatives: AlternativeAction[];
  reversible: boolean;
  sequenceIndex: number;
  affectedBlockCount: number;
}

export interface UserReplanChoice {
  decisionId: string;
  action: 'keep' | 'undo' | 'replace';
  alternative?: AlternativeAction;
}

export interface ReplanSimulation {
  blocks: Block[];
  overflowAfter: number;
  overflowBefore: number;
  overflowDelta: number;
  keptActions: string[];
  modifiedActions: string[];
  unresolved: Array<{ opId: string; deficit: number; reason: string }>;
}

export type ReplanEventType = 'breakdown' | 'rush_order' | 'material_shortage';

// ── Scheduling Config ───────────────────────────────────

export type SchedulingStrategy = 'BalancedStrategy' | 'MaxOTDStrategy' | 'MinSetupsStrategy';

export interface SchedulingConfig {
  version: number;
  weights: { otd: number; setup: number; utilization: number };
  dispatchRule: 'EDD' | 'CR' | 'WSPT' | 'SPT' | 'ATCS';
  direction: 'forward' | 'backward';
  frozenHorizonDays: number;
  lotEconomicoMode: 'strict' | 'relaxed';
  emergencyNightShift: boolean;
  constraints: {
    setupCrew: { mode: 'hard' | 'disabled' };
    toolTimeline: { mode: 'hard' | 'disabled' };
    calcoTimeline: { mode: 'hard' | 'disabled' };
    operatorPool: { mode: 'hard' | 'disabled' };
  };
  atcsParams?: { k1: number; k2: number };
  saIterations: number;
  l2Rules?: { rules: Array<{ field: string; operator: string; value: number; action: string }> };
  l3Formulas?: { formulas: Array<{ name: string; expression: string; variables: string[] }> };
  l4Definitions?: { definitions: Array<{ name: string; formula: string; threshold?: number }> };
  l5Governance?: {
    defaultLevel: string;
    approvalRules: Array<{ action: string; requiredLevel: string; approvers: string[] }>;
  };
  l6Strategy?: {
    steps: Array<{ dispatchRule: string; condition?: string; maxIterations: number }>;
    fallbackRule: string;
  };
}

export interface SchedulingContext {
  config: SchedulingConfig;
  nDays: number;
  machines: Array<{ id: string }>;
  tools: Array<{ id: string }>;
}

// ── Transform Config ────────────────────────────────────

export interface TransformConfig {
  moStrategy: 'cyclic' | 'nominal' | 'custom';
  moNominalPG1: number;
  moNominalPG2: number;
  moCustomPG1: number;
  moCustomPG2: number;
  demandSemantics: 'daily' | 'cumulative_np' | 'raw_np';
  preStartBufferDays?: number;
}

// ── Scheduler Input/Output (stubs) ──────────────────────

export interface ScheduleAllInput {
  ops: unknown[];
  machines: unknown[];
  tools: unknown[];
  nDays: number;
  workdays: number[];
  config: Partial<SchedulingConfig>;
}

export interface ScheduleAllResult {
  blocks: Block[];
  decisions: DecisionEntry[];
  kpis: Record<string, unknown>;
}

// ── Optimization (stubs) ────────────────────────────────

export interface ATCSParams { k1: number; k2: number }

export interface SAConfig {
  initialTemp: number;
  coolingRate: number;
  iterations: number;
}

export interface SAInput {
  blocks: Block[];
  config: SAConfig;
}

export interface SAResult {
  blocks: Block[];
  improvement: number;
  iterations: number;
}

export interface OptimizationInput {
  blocks: Block[];
  config: Partial<SchedulingConfig>;
}

export interface OptimizationSetup {
  method: 'sa' | 'two-opt' | 'hybrid';
  config: SAConfig;
}

export interface GridResult {
  bestK1: number;
  bestK2: number;
  bestScore: number;
}

export interface ScoringJob {
  opId: string;
  priority: number;
  slack: number;
}

// ── Replan Input/Output (stubs) ─────────────────────────

export interface RightShiftInput { machineId: string; delayMin: number; blocks: Block[] }
export interface RightShiftResult { blocks: Block[]; shiftedCount: number }
export interface MatchUpInput { machineId: string; blocks: Block[] }
export interface MatchUpResult { blocks: Block[]; matchedCount: number }
export interface PartialReplanInput { eventType: ReplanEventType; machineId?: string; affectedOpIds: string[] }
export interface PartialReplanResult { blocks: Block[]; replannedCount: number }
export interface FullReplanInput { blocks: Block[] }
export interface FullReplanResult { blocks: Block[] }

// ── Miscellaneous stubs ─────────────────────────────────

export interface MoveableOp { opId: string; currentMachine: string; alternatives: string[] }
export interface TwinValidationInput { ops: unknown[]; tools: unknown[] }
export interface WorkforceDemandResult { demand: unknown[] }
export interface WorkforceForecastInput { blocks: Block[]; config: unknown }

/**
 * api.ts — Typed fetch wrappers for backend scheduling endpoints.
 *
 * Single source of truth for all backend API calls.
 * Each function returns a typed response matching FullScheduleResponse.
 */

import { config } from '../config';
import type {
  ActionMessagesSummary,
  AutoAdvanceEntry,
  AutoMoveEntry,
  CoverageAuditResult,
  CoverageMatrixResult,
  CoverageMatrixSkuResult,
  DayLoad,
  DecisionEntry,
  FeasibilityReport,
  JournalSummary,
  LateDeliveryAnalysis,
  MRPResult,
  MRPSkuViewResult,
  NikufraDataPayload,
  ParseMeta,
  QuickValidateResult,
  ReplanProposal,
  ROPSummary,
  ScheduleBlock,
  ScheduleSettings,
  ScoreResult,
  ValidationResult,
  WhatIfMutation,
  WorkforceForecastResult,
} from '../domain/api-types';
import { fetchWithTimeout } from './fetchWithTimeout';

export type {
  ActionImpact,
  ActionMessage,
  ActionMessagesSummary,
  AffectedOp,
  AutoAdvanceEntry,
  AutoMoveEntry,
  CausingBlock,
  CoverageAuditResult,
  CoverageAuditRow,
  CoverageMatrixCell,
  CoverageMatrixResult,
  CoverageMatrixSkuEntry,
  CoverageMatrixSkuResult,
  CoverageSkuCell,
  DayLoad,
  DecisionEntry,
  FeasibilityReport,
  InfeasibilityEntry,
  JournalDrop,
  JournalSummary,
  LateDeliveryAnalysis,
  LateDeliveryEntry,
  MRPDayBucket,
  MRPRecord,
  MRPResult,
  MRPSkuRecord,
  MRPSkuSummary,
  MRPSkuViewRecord,
  MRPSkuViewResult,
  MRPSummary,
  NikufraDataPayload,
  ParseMeta,
  QuickValidateResult,
  RCCPEntry,
  ReplanProposal,
  ROPRecord,
  ROPSummary,
  ScheduleBlock,
  ScheduleSettings,
  ScheduleViolation,
  ScoreResult,
  StockProjectionPoint,
  TwinOutput,
  ValidationResult,
  ValidationSummary,
  WhatIfMutation,
  WorkforceDemandEntry,
  WorkforceForecastResult,
  WorkforceForecastWarning,
  WorkforceSuggestion,
} from '../domain/api-types';

// ── Response types matching backend FullScheduleResponse ──

export interface PipelineKPIs {
  total_blocks: number;
  production_blocks: number;
  infeasible_blocks: number;
  total_qty: number;
  total_production_min: number;
  otd_pct: number;
  machines_used: number;
  n_ops: number;
}

export interface FullScheduleResponse {
  blocks: ScheduleBlock[];
  kpis: PipelineKPIs;
  decisions: DecisionEntry[];
  feasibility_report: FeasibilityReport | null;
  auto_moves: AutoMoveEntry[];
  auto_advances: AutoAdvanceEntry[];
  solve_time_s: number;
  solver_used: string;
  n_blocks: number;
  n_ops: number;
  parse_meta: ParseMeta | null;
  parse_warnings: string[];
  nikufra_data: Record<string, unknown> | null;
  engine_data: Record<string, unknown> | null;
  score: ScoreResult | null;
  validation: ValidationResult | null;
  coverage: CoverageAuditResult | null;
  cap: Record<string, DayLoad[]> | null;
  mrp: MRPResult | null;
  late_deliveries: LateDeliveryAnalysis | null;
  mrp_sku_view: MRPSkuViewResult | null;
  mrp_rop: ROPSummary | null;
  mrp_rop_sku: ROPSummary | null;
  mrp_actions: ActionMessagesSummary | null;
  mrp_coverage_sku: CoverageMatrixSkuResult | null;
  mrp_coverage_matrix: CoverageMatrixResult | null;
  quick_validate: QuickValidateResult | null;
  gen_decisions: ReplanProposal[] | null;
  workforce_forecast: WorkforceForecastResult | null;
  journal_summary: JournalSummary | null;
}

// ── Schedule Full ────────────────────────────────────────────

export interface ScheduleFullRequest {
  nikufra_data: NikufraDataPayload;
  settings: ScheduleSettings;
}

/**
 * POST /v1/pipeline/schedule/full — full scheduling pipeline.
 * Returns blocks + all analytics in one call.
 */
export async function scheduleFullApi(
  request: ScheduleFullRequest,
  timeoutMs = 30_000,
): Promise<FullScheduleResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/pipeline/schedule/full`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`Schedule full HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── Schedule Run (lighter, no analytics) ─────────────────────

export async function scheduleRunApi(
  nikufraData: NikufraDataPayload,
  settings: ScheduleSettings,
  timeoutMs = 30_000,
): Promise<FullScheduleResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/pipeline/run`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nikufra_data: nikufraData, settings }),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`Schedule run HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── Replan (Sprint 3 — stub) ─────────────────────────────────

export interface ReplanRequest {
  blocks: ScheduleBlock[];
  disruption: {
    type: string;
    resource_id: string;
    start_day: number;
    end_day: number;
    capacity_factor?: number;
  };
  settings?: ScheduleSettings;
}

/** POST /v1/schedule/replan — re-solve with disruption. */
export async function scheduleReplanApi(
  request: ReplanRequest,
  timeoutMs = 60_000,
): Promise<FullScheduleResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/schedule/replan`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`Replan HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── What-If (Sprint 3 — stub) ────────────────────────────────

export interface WhatIfRequest {
  nikufra_data: NikufraDataPayload;
  mutations: WhatIfMutation[];
  settings?: ScheduleSettings;
}

export interface WhatIfDelta {
  otd_change: number;
  score_change: number;
  setup_change: number;
  [key: string]: unknown;
}

export interface WhatIfResponse {
  baseline: FullScheduleResponse | null;
  scenario: FullScheduleResponse | null;
  delta: WhatIfDelta | null;
  solve_time_s: number;
}

/** POST /v1/schedule/what-if — scenario delta analysis. */
export async function scheduleWhatIfApi(
  request: WhatIfRequest,
  timeoutMs = 120_000,
): Promise<WhatIfResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/schedule/what-if`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`What-if HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── Optimize (Sprint 3 — stub) ───────────────────────────────

export interface OptimizeRequest {
  nikufra_data: NikufraDataPayload;
  objective_weights?: Record<string, number>;
  n_alternatives?: number;
  settings?: ScheduleSettings;
}

export interface OptimizeAlternative {
  objective: string;
  blocks: ScheduleBlock[];
  score: ScoreResult | null;
  solve_time_s: number;
  n_blocks: number;
}

export interface OptimizeResponse {
  alternatives: OptimizeAlternative[];
  solve_time_s: number;
}

/** POST /v1/schedule/optimize — top-N alternative schedules. */
export async function scheduleOptimizeApi(
  request: OptimizeRequest,
  timeoutMs = 120_000,
): Promise<OptimizeResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/schedule/optimize`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`Optimize HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── Simulate (unified replan + what-if) ─────────────────────

export interface SimMutation {
  type: string;
  params: Record<string, unknown>;
}

export interface SimDeltaReport {
  otd_before: number;
  otd_after: number;
  otd_d_before: number;
  otd_d_after: number;
  overflow_before: number;
  overflow_after: number;
  tardiness_before: number;
  tardiness_after: number;
  blocks_changed: number;
  blocks_unchanged: number;
  blocks_new: number;
  blocks_removed: number;
  util_before: Record<string, number>;
  util_after: Record<string, number>;
  setups_before: number;
  setups_after: number;
}

export interface SimMutationImpact {
  mutation_idx: number;
  type: string;
  description: string;
  ops_affected: number;
  blocks_affected: number;
  otd_d_impact: number;
  severity: 'none' | 'low' | 'medium' | 'high' | 'critical';
}

export interface SimBlockChange {
  op_id: string;
  sku: string;
  tool_id: string;
  action: 'moved' | 'new' | 'removed' | 'resized' | 'unchanged';
  from_machine: string;
  to_machine: string;
  from_day: number;
  to_day: number;
  qty: number;
  reason: string;
  /** Ghost-block rendering fields (populated for removed blocks) */
  from_start_min?: number;
  from_end_min?: number;
  nm?: string;
}

export interface SimulateRequest {
  nikufra_data: NikufraDataPayload;
  mutations: SimMutation[];
  settings?: ScheduleSettings;
}

export interface SimulateResponse {
  blocks: ScheduleBlock[];
  score: ScoreResult | null;
  time_ms: number;
  delta: SimDeltaReport;
  mutation_impacts: SimMutationImpact[];
  block_changes: SimBlockChange[];
  summary: string[];
}

/** POST /v1/schedule/simulate — unified scenario simulation. */
export async function scheduleSimulateApi(
  request: SimulateRequest,
  timeoutMs = 30_000,
): Promise<SimulateResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/schedule/simulate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`Simulate HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── CTP ──────────────────────────────────────────────────────

export interface CTPApiScenario {
  id: string;
  label: string;
  machine: string;
  feasible: boolean;
  earliest_feasible_day: number | null;
  date_label: string | null;
  required_min: number;
  available_min_on_day: number;
  capacity_slack: number;
  confidence: 'high' | 'medium' | 'low';
  reason: string;
  is_alt: boolean;
  capacity_timeline: Array<{
    day_index: number;
    existing_load: number;
    new_order_load: number;
    capacity: number;
  }>;
}

export interface CTPApiResponse {
  scenarios: CTPApiScenario[];
  solve_time_s: number;
}

/** POST /v1/schedule/ctp — capable-to-promise analysis. */
export async function scheduleCTPApi(
  request: {
    nikufra_data: NikufraDataPayload;
    sku: string;
    quantity: number;
    target_day: number;
    settings?: ScheduleSettings;
  },
  timeoutMs = 30_000,
): Promise<CTPApiResponse> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/schedule/ctp`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`CTP HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

// ── CTP Real (block-based capacity) ─────────────────────────

export interface CTPRealResult {
  feasible: boolean;
  machine: string;
  earliestDay: number | null;
  requiredMin: number;
  freeMinOnTarget: number;
  confidence: 'high' | 'medium' | 'low';
  reason: string;
  altMachine: string | null;
  altEarliestDay: number | null;
}

export async function ctpRealApi(
  sku: string,
  qty: number,
  deadlineDay: number,
  timeoutMs = 10_000,
): Promise<CTPRealResult> {
  const res = await fetchWithTimeout(
    `${config.apiBaseURL}/v1/schedule/stock/${encodeURIComponent(sku)}/ctp`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ qty, deadline_day: deadlineDay }),
    },
    timeoutMs,
  );
  if (!res.ok) {
    const text = await res.text().catch(() => 'unknown');
    throw new Error(`CTP Real HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

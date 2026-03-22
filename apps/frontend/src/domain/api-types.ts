/**
 * api-types.ts — Typed interfaces matching backend FullScheduleResponse.
 *
 * Every field that was Record<string, unknown> is now properly typed
 * to match the Python dataclass shapes from the backend.
 */

// ── Block ─────────────────────────────────────────────────────

export interface TwinOutput {
  sku: string;
  op_id: string;
  qty: number;
}

export interface ScheduleBlock {
  op_id: string;
  tool_id: string;
  sku: string;
  nm: string;
  machine_id: string;
  orig_m: string;
  day_idx: number;
  edd_day: number | null;
  qty: number;
  prod_min: number;
  setup_min: number;
  operators: number;
  blocked: boolean;
  reason: string | null;
  moved: boolean;
  has_alt: boolean;
  alt_m: string | null;
  mp: string | null;
  stk: number;
  lt: number;
  atr: number;
  start_min: number;
  end_min: number;
  setup_s: number | null;
  setup_e: number | null;
  type: 'ok' | 'blocked' | 'overflow' | 'infeasible';
  shift: 'X' | 'Y' | 'Z';
  overflow: boolean;
  overflow_min: number | null;
  below_min_batch: boolean;
  earliest_start: number | null;
  is_leveled: boolean;
  is_advanced: boolean;
  advanced_by_days: number | null;
  infeasibility_reason: string | null;
  infeasibility_detail: string | null;
  has_data_gap: boolean;
  data_gap_detail: string | null;
  operator_warning: boolean;
  failure_event_id: string | null;
  effective_capacity_factor: number | null;
  latest_finish_abs: number | null;
  start_reason: string | null;
  is_system_replanned: boolean;
  replan_strategy: string | null;
  replan_decision_id: string | null;
  is_overtime: boolean;
  overtime_min: number | null;
  is_split_part: boolean;
  split_from_machine: string | null;
  is_twin_production: boolean;
  co_production_group_id: string | null;
  outputs: TwinOutput[] | null;
  freeze_status: string | null;
  pre_start: boolean;
  pre_start_reason: string | null;
}

// ── Decisions ─────────────────────────────────────────────────

export interface DecisionEntry {
  id: string;
  timestamp: number;
  type: string;
  op_id: string | null;
  tool_id: string | null;
  machine_id: string | null;
  day_idx: number | null;
  shift: 'X' | 'Y' | 'Z' | null;
  detail: string;
  metadata: Record<string, unknown>;
  replan_strategy: string | null;
  alternatives: Record<string, unknown>[] | null;
  reversible: boolean;
}

// ── Feasibility ───────────────────────────────────────────────

export interface InfeasibilityEntry {
  op_id: string;
  tool_id: string;
  machine_id: string;
  reason: string;
  detail: string;
  attempted_alternatives: string[];
  suggestion: string;
  day_idx: number | null;
  shift: 'X' | 'Y' | 'Z' | null;
}

export interface FeasibilityReport {
  total_ops: number;
  feasible_ops: number;
  infeasible_ops: number;
  entries: InfeasibilityEntry[];
  by_reason: Record<string, number>;
  feasibility_score: number;
  remediations: Record<string, unknown>[];
  deadline_feasible: boolean;
}

// ── Score ─────────────────────────────────────────────────────

export interface WorkforceDemandEntry {
  machine_id: string;
  day_idx: number;
  shift: string;
  operators: number;
}

export interface ScoreResult {
  score: number;
  otd: number;
  otd_delivery: number;
  produced: number;
  total_demand: number;
  lost_pcs: number;
  setup_count: number;
  setup_min: number;
  peak_ops: number;
  over_ops: number;
  overflows: number;
  cap_util: number;
  cap_var: number;
  tardiness_days: number;
  setup_by_shift: Record<string, number>;
  deadline_feasible: boolean;
  cap_by_machine: Record<string, Record<string, number>[]>;
  workforce_demand: WorkforceDemandEntry[];
  blocks: ScheduleBlock[];
}

// ── Validation ────────────────────────────────────────────────

export interface AffectedOp {
  op_id: string;
  tool_id: string;
  machine_id: string;
  day_idx: number;
}

export interface ScheduleViolation {
  id: string;
  type: string;
  severity: string;
  title: string;
  detail: string;
  affected_ops: AffectedOp[];
  suggested_fix: string | null;
  action: Record<string, unknown> | null;
}

export interface ValidationSummary {
  tool_conflicts: number;
  setup_overlaps: number;
  machine_overcapacity: number;
  efficiency_warnings: number;
  deadline_misses: number;
  twin_blocks: number;
  twin_groups: number;
}

export interface ValidationResult {
  valid: boolean;
  violations: ScheduleViolation[];
  summary: ValidationSummary;
}

// ── Coverage Audit ────────────────────────────────────────────

export interface CoverageAuditRow {
  op_id: string;
  sku: string;
  nm: string;
  machine_id: string;
  tool_id: string;
  total_demand: number;
  produced: number;
  coverage_pct: number;
  gap: number;
  reason: string;
  has_alt: boolean;
  alt_m: string | null;
  is_twin_production: boolean;
  twin_partner_op_id: string | null;
  twin_excess_to_stock: number;
}

export interface CoverageAuditResult {
  rows: CoverageAuditRow[];
  total_demand: number;
  total_produced: number;
  global_coverage_pct: number;
  fully_covered: number;
  partially_covered: number;
  zero_covered: number;
  is_complete: boolean;
}

// ── Cap Analysis ──────────────────────────────────────────────

export interface DayLoad {
  prod: number;
  setup: number;
}

// ── Late Deliveries ───────────────────────────────────────────

export interface LateDeliveryEntry {
  op_id: string;
  sku: string;
  nm: string;
  machine_id: string;
  tool_id: string;
  cl: string | null;
  cl_nm: string | null;
  client_tier: number;
  deadline: number;
  deadline_date: string | null;
  shortfall: number;
  delay_days: number;
  earliest_possible_day: number;
  is_resolved: boolean;
  resolved_by: string | null;
  suggested_actions: string[];
}

export interface LateDeliveryAnalysis {
  entries: LateDeliveryEntry[];
  unresolved_count: number;
  resolved_with_cost_count: number;
  total_shortfall_pcs: number;
  affected_clients: string[];
  worst_tier_affected: number;
  otd_delivery: number;
}

// ── MRP ───────────────────────────────────────────────────────

export interface MRPDayBucket {
  day_index: number;
  date_label: string;
  day_name: string;
  gross_requirement: number;
  scheduled_receipts: number;
  projected_available: number;
  net_requirement: number;
  planned_order_receipt: number;
  planned_order_release: number;
}

export interface MRPSkuRecord {
  sku: string;
  name: string;
  op_id: string;
  tool_code: string;
  machine: string;
  alt_machine: string;
  customer: string;
  twin: string;
  stock: number;
  wip: number;
  backlog: number;
  coverage_days: number;
  stockout_day: number | null;
  buckets: MRPDayBucket[];
}

export interface MRPRecord {
  tool_code: string;
  skus: string[];
  machine: string;
  alt_machine: string;
  stock: number;
  backlog: number;
  lead_days: number;
  stockout_day: number | null;
  coverage_days: number;
  buckets: MRPDayBucket[];
  sku_records: MRPSkuRecord[];
}

export interface RCCPEntry {
  machine: string;
  area: string;
  day_index: number;
  date_label: string;
  available_min: number;
  required_setup_min: number;
  required_prod_min: number;
  required_total_min: number;
  utilization: number;
  overloaded: boolean;
  planned_tools: string[];
}

export interface MRPSummary {
  tools_with_backlog: number;
  tools_with_stockout: number;
  total_planned_qty: number;
  total_gross_req: number;
  bottleneck_machine: string;
  bottleneck_day: number;
  max_utilization: number;
  avg_utilization: number;
}

export interface MRPResult {
  records: MRPRecord[];
  rccp: RCCPEntry[];
  summary: MRPSummary;
}

// ── MRP SKU View ──────────────────────────────────────────────

export interface MRPSkuViewRecord {
  sku: string;
  name: string;
  op_id: string;
  tool_code: string;
  machine: string;
  alt_machine: string;
  customer: string;
  customer_name: string;
  twin: string;
  is_twin: boolean;
  current_stock: number;
  wip: number;
  backlog: number;
  gross_requirement: number;
  projected_end: number;
  stockout_day: number | null;
  coverage_days: number;
  buckets: MRPDayBucket[];
  rate_per_hour: number;
  setup_hours: number;
  lot_economic_qty: number;
}

export interface MRPSkuSummary {
  total_skus: number;
  skus_with_backlog: number;
  skus_with_stockout: number;
  total_gross_req: number;
  total_planned_qty: number;
}

export interface MRPSkuViewResult {
  sku_records: MRPSkuViewRecord[];
  summary: MRPSkuSummary;
}

// ── ROP ───────────────────────────────────────────────────────

export interface StockProjectionPoint {
  day_index: number;
  projected: number;
  rop_line: number;
  ss_line: number;
}

export interface ROPRecord {
  tool_code: string;
  demand_avg: number;
  demand_std_dev: number;
  coefficient_of_variation: number;
  lead_time_days: number;
  safety_stock: number;
  rop: number;
  service_level: number;
  z_score: number;
  current_stock: number;
  abc_class: string;
  xyz_class: string;
  stock_projection: StockProjectionPoint[];
}

export interface ROPSummary {
  records: ROPRecord[];
  abc_distribution: Record<string, number>;
  xyz_distribution: Record<string, number>;
  tools_below_rop: number;
  tools_below_ss: number;
}

// ── Actions ───────────────────────────────────────────────────

export interface ActionImpact {
  qty_affected: number;
  days_affected: number;
  capacity_minutes: number | null;
}

export interface ActionMessage {
  id: string;
  type: string;
  severity: string;
  severity_score: number;
  tool_code: string;
  machine: string;
  day_index: number | null;
  sku: string | null;
  sku_name: string | null;
  title: string;
  description: string;
  suggested_action: string;
  impact: ActionImpact;
}

export interface ActionMessagesSummary {
  messages: ActionMessage[];
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  critical_count: number;
}

// ── Coverage Matrix SKU ───────────────────────────────────────

export interface CoverageSkuCell {
  sku: string;
  tool_code: string;
  day_index: number;
  days_of_supply: number;
  color_band: string;
}

export interface CoverageMatrixSkuEntry {
  sku: string;
  name: string;
  toolCode: string;
  machine: string;
  urgencyScore: number;
}

export interface CoverageMatrixSkuResult {
  skus: CoverageMatrixSkuEntry[];
  days: string[];
  cells: CoverageSkuCell[][];
}

// ── Parse Meta ───────────────────────────────────────────

export interface ParseMeta {
  rows: number;
  skus: number;
  warnings: string[];
  [key: string]: unknown;
}

// ── Journal Summary ──────────────────────────────────────

export interface JournalDrop {
  step: string;
  message: string;
  metadata?: Record<string, unknown>;
}

export interface JournalSummary {
  total_entries: number;
  by_severity: Record<string, number>;
  by_step: Record<string, number>;
  drops: JournalDrop[];
  has_errors: boolean;
  has_warnings: boolean;
}

// ── Auto Move / Auto Advance ─────────────────────────────

export interface AutoMoveEntry {
  op_id: string;
  from_machine: string;
  to_machine: string;
  day_idx: number;
  reason: string;
  [key: string]: unknown;
}

export interface AutoAdvanceEntry {
  op_id: string;
  from_day: number;
  to_day: number;
  reason: string;
  [key: string]: unknown;
}

// ── Coverage Matrix (tool-level) ─────────────────────────

export interface CoverageMatrixCell {
  tool_code: string;
  day_index: number;
  days_of_supply: number;
  color_band: string;
}

export interface CoverageMatrixResult {
  tools: Record<string, unknown>[];
  days: string[];
  cells: CoverageMatrixCell[][];
}

// ── Quick Validate ────────────────────────────────────────────

export interface QuickValidateResult {
  critical_count: number;
  high_count: number;
  warnings: string[];
}

// ── Gen Decisions ─────────────────────────────────────────────

export interface ReplanProposal {
  id: string;
  op_id: string;
  type: string;
  severity: string;
  title: string;
  desc: string;
  reasoning: string[];
  impact: Record<string, unknown> | null;
  action: Record<string, string> | null;
}

// ── Workforce Forecast ────────────────────────────────────────

export interface CausingBlock {
  op_id: string;
  machine_id: string;
  operators: number;
  sku: string;
}

export interface WorkforceSuggestion {
  type: string;
  description: string;
  op_id: string | null;
  machine_id: string | null;
  expected_reduction: number;
}

export interface WorkforceForecastWarning {
  date: string;
  day_idx: number;
  labor_group: string;
  shift: string;
  window_start: number;
  window_end: number;
  capacity: number;
  projected_peak: number;
  excess: number;
  peak_shortage: number;
  overload_people_minutes: number;
  shortage_minutes: number;
  causing_blocks: CausingBlock[];
  machines: string[];
  overload_window: string;
  suggestions: WorkforceSuggestion[];
}

export interface CoverageMissing {
  type: string;
  machine_id: string;
  day_idx: number;
  shift: string;
  detail: string;
}

export interface WorkforceForecastResult {
  next_working_day_idx: number;
  date: string;
  warnings: WorkforceForecastWarning[];
  coverage_missing: CoverageMissing[];
  has_warnings: boolean;
  has_critical: boolean;
}

// ── Request payload types ────────────────────────────────────

/** Serialized NikufraData payload sent to backend. */
export interface NikufraDataPayload {
  operations: Array<{
    id: string;
    sku: string;
    nm: string;
    m: string;
    t: string;
    pH: number;
    d: (number | null)[];
    [key: string]: unknown;
  }>;
  dates?: string[];
  [key: string]: unknown;
}

/** Scheduling engine settings sent to backend. */
export interface ScheduleSettings {
  dispatchRule?: string;
  thirdShift?: boolean;
  maxTier?: number;
  orderBased?: boolean;
  demandSemantics?: string;
  cpsat_time_limit?: number;
  [key: string]: unknown;
}

/** What-If scenario mutation. */
export interface WhatIfMutation {
  type: string;
  target: string;
  [key: string]: unknown;
}

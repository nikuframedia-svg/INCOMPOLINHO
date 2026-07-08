/** TypeScript interfaces matching backend /api/data/* responses exactly. */

// ── Core ─────────────────────────────────────────────────────

export interface Score {
  otd: number;
  otd_d: number;
  tardy_count: number;
  setups: number;
  earliness_avg_days: number;
  utilization_avg: number;
  utilization_balance: number;
  weighted_score: number;
  [key: string]: unknown; // allow extra fields from scorer
}

export interface Segment {
  lot_id: string;
  run_id: string;
  machine_id: string;
  tool_id: string;
  day_idx: number;
  start_min: number;
  end_min: number;
  shift: string;
  qty: number;
  prod_min: number;
  setup_min: number;
  is_continuation: boolean;
  edd: number;
  sku: string;
  twin_outputs: [string, string, number][] | null;
  lot_qty?: number;
  run_qty?: number;
  run_setup_min?: number;
  run_lot_count?: number;
  original_edd?: number | null;
  internal_deadline?: number | null;
  delivery_day?: number | null;
  eco_lot_isop?: number | null;
  eco_lot_effective?: number | null;
  start_buffer_days?: number;
  finish_buffer_days?: number;
  target_start_day?: number | null;
  min_campaign_qty?: number | null;
  min_campaign_prod_min?: number | null;
  max_group_gap_days?: number | null;
  planning_source?: string;
  economic_warning?: string | null;
  subcontract_company_id?: string | null;
  subcontract_lead_time_days?: number;
  subcontract_buffer_days?: number;
}

export interface Lot {
  id: string;
  op_id: string;
  tool_id: string;
  machine_id: string;
  alt_machine_id: string | null;
  qty: number;
  prod_min: number;
  setup_min: number;
  edd: number;
  is_twin: boolean;
  twin_outputs: [string, string, number][] | null;
  original_edd?: number | null;
  internal_deadline?: number | null;
  delivery_day?: number | null;
  eco_lot_isop?: number | null;
  eco_lot_effective?: number | null;
  start_buffer_days?: number;
  finish_buffer_days?: number;
  target_start_day?: number | null;
  min_campaign_qty?: number | null;
  min_campaign_prod_min?: number | null;
  max_group_gap_days?: number | null;
  planning_source?: string;
  economic_warning?: string | null;
  subcontract_company_id?: string | null;
  subcontract_lead_time_days?: number;
  subcontract_buffer_days?: number;
}

export interface TrustIndex {
  score: number;
  gate: string;
  n_ops: number;
  n_issues: number;
  dimensions: { name: string; score: number; details: string[] }[];
}

export interface DatasetInfo {
  id: string;
  filename: string;
  uploaded_at: string;
  n_ops: number;
  n_segments: number;
  trust_score: number;
  trust_gate: string;
  otd: number | null;
  tardy_count: number | null;
}

// ── Analytics ────────────────────────────────────────────────

export interface StockDayCompact {
  day: number;
  date: string;
  stock: number;
  demand: number;
  produced: number;
  workday: boolean;
  is_buffer?: boolean;
}

export interface StockSummary {
  op_id: string;
  sku: string;
  client: string;
  machine: string;
  tool: string;
  initial_stock: number;
  stockout_day: number | null;
  coverage_days: number;
  total_demand: number;
  total_produced: number;
  subcontract_company_id?: string | null;
  internal_deadline_min?: number | null;
  days: StockDayCompact[];
}

export interface StockDay {
  day_idx: number;
  date: string;
  demand: number;
  produced: number;
  cum_demand: number;
  cum_produced: number;
  stock: number;
  machine: string | null;
  is_buffer?: boolean;
}

export interface StockProjection extends Omit<StockSummary, "days"> {
  days: StockDay[];
}

export interface ExpeditionEntry {
  client: string;
  sku: string;
  order_qty: number;
  produced_qty: number;
  shortfall: number;
  status: string;
  coverage_pct: number;
}

export interface ExpeditionDay {
  day_idx: number;
  date: string;
  total: number;
  ready: number;
  partial: number;
  not_planned: number;
  entries: ExpeditionEntry[];
}

export interface ExpeditionKPIs {
  fill_rate: number;
  at_risk_count: number;
  days: ExpeditionDay[];
}

export interface OrderTracking {
  sku: string;
  order_qty: number;
  delivery_day: number;
  delivery_date: string;
  status: string;
  production_machine: string | null;
  days_early: number | null;
  reason: string;
  [key: string]: unknown;
}

export interface ClientOrders {
  client: string;
  total_orders: number;
  total_ready: number;
  orders: OrderTracking[];
}

export interface ClientCoverage {
  client: string;
  total_orders: number;
  covered_orders: number;
  coverage_pct: number;
  at_risk_orders: number;
  worst_sku: string | null;
}

export interface CoverageAudit {
  overall_coverage_pct: number;
  overall_fill_rate: number;
  clients: ClientCoverage[];
  stockout_count: number;
  health_score: number;
  summary: string;
}

export interface LotRisk {
  lot_id: string;
  sku: string;
  machine_id: string;
  edd: number;
  slack: number;
  risk_level: string;
  [key: string]: unknown;
}

export interface HeatmapCell {
  machine_id: string;
  day_idx: number;
  utilization: number;
  risk_level: string;
}

export interface RiskResult {
  health_score: number;
  lot_risks: LotRisk[];
  machine_risks: unknown[];
  heatmap: HeatmapCell[];
  critical_count: number;
  top_risks: LotRisk[];
  bottleneck: string | null;
}

export interface TardyAnalysis {
  lot_id: string;
  op_id: string;
  sku: string;
  machine_id: string;
  edd: number;
  completion_day: number;
  delay_days: number;
  root_cause: string;
  explanation: string;
  capacity_gap_min: number;
  competing_lots: string[];
}

export interface LateDeliveryReport {
  tardy_count: number;
  avg_delay: number;
  by_cause: Record<string, number>;
  analyses: TardyAnalysis[];
  worst_machine: string | null;
  suggestion: string;
}

export interface DayForecast {
  day_idx: number;
  date: string;
  shift: string;
  machine_group: string;
  required: number;
  available: number;
  surplus_or_deficit: number;
}

export interface WorkforceForecast {
  window_days: number;
  daily: DayForecast[];
  peak_day: number;
  peak_required: number;
  avg_required: number;
  deficit_days: number;
  trend: string;
  summary: string;
}

// ── Config / Master Data ─────────────────────────────────────

export interface ShiftConfig {
  id: string;
  start_min: number;
  end_min: number;
  duration_min: number;
  label: string;
}

export interface ToolConfig {
  primary: string;
  alt: string | null;
  setup_hours: number;
}

export interface TwinConfig {
  tool_id: string;
  sku_a: string;
  sku_b: string;
}

export interface FactoryConfig {
  name: string;
  site: string;
  timezone: string;
  shifts: ShiftConfig[];
  day_capacity_min: number;
  machines: Record<string, { group: string; active: boolean }>;
  tools: Record<string, ToolConfig>;
  twins: TwinConfig[];
  operators: Record<string, number>;
  holidays: string[];
  oee_default: number;
  subcontract_skus: string[];
  sku_planning_rules: Record<string, SkuPlanningRule>;
  subcontract_companies: SubcontractCompany[];
  sku_subcontracts: Record<string, SkuSubcontractRule>;
  setup_crews: number;
  jit_enabled: boolean;
  jit_buffer_pct: number;
  jit_threshold: number;
  jit_max_retries: number;
  jit_earliness_target: number;
  max_run_days: number;
  max_edd_gap: number;
  max_edd_span: number;
  edd_swap_tolerance: number;
  edd_assign_threshold: number;
  campaign_window: number;
  urgency_threshold: number;
  interleave_enabled: boolean;
  auto_buffer: boolean;
  vns_enabled: boolean;
  vns_max_iter: number;
  compact_enabled: boolean;
  weight_earliness: number;
  weight_setups: number;
  weight_balance: number;
  eco_lot_mode: string;
}

export interface SkuPlanningRule {
  eco_lot?: number;
  start_buffer_days?: number;
  finish_buffer_days?: number;
  min_campaign_qty?: number;
  min_campaign_prod_min?: number;
  max_group_gap_days?: number;
}

export interface SubcontractCompany {
  id: string;
  name: string;
  lead_time_days: number;
}

export interface SkuSubcontractRule {
  enabled?: boolean;
  company_id?: string;
  lead_time_days?: number;
  buffer_days?: number;
}

export interface EOp {
  id: string;
  sku: string;
  client: string;
  designation: string;
  machine: string;
  tool: string;
  alt_machine: string | null;
  pcs_hour: number;
  setup_hours: number;
  eco_lot: number;
  eco_lot_isop?: number;
  eco_lot_effective?: number;
  start_buffer_days?: number;
  finish_buffer_days?: number;
  min_campaign_qty?: number | null;
  min_campaign_prod_min?: number | null;
  max_group_gap_days?: number | null;
  subcontract_company_id?: string | null;
  subcontract_lead_time_days?: number;
  subcontract_buffer_days?: number;
  stock: number;
  oee: number;
  backlog: number;
  operators: number;
  demand: number[];
}

export interface SkuPlanningImpact {
  lots: number;
  segments: number;
  qty: number;
  prod_min: number;
  setups: number;
  warnings: string[];
}

export interface PlanningDelta {
  otd: number;
  otd_d: number;
  setups: number;
  tardy_count: number;
  earliness_avg_days: number;
  planning_penalty: number;
}

export interface GateProposal {
  id: string;
  type: string;
  description: string;
  expected_impact?: string;
  [key: string]: unknown;
}

export interface SolverTrace {
  version: string;
  mode: string;
  time_ms: number;
  final_source: string;
  baseline: Record<string, unknown>;
  final: Record<string, unknown>;
  delta_vs_baseline: Record<string, number>;
  candidate_search: Record<string, unknown>;
  cp_sat: Record<string, unknown>;
  acceptance_policy: Record<string, unknown>;
}

export interface GateReport {
  status: "applicable" | "invalid_physics" | "infeasible_current_conditions" | string;
  hard_gate_passed: boolean;
  delivery_gate_passed: boolean;
  metrics: Record<string, number>;
  violations: Record<string, unknown>[];
  late_detail: Record<string, unknown>[];
  setup_overlap_detail: Record<string, unknown>[];
  proposals: GateProposal[];
  solver_trace?: SolverTrace;
}

export interface SkuPlanningResponse {
  status: string;
  sku: string;
  rule: SkuPlanningRule;
  score?: Score;
  score_previous?: Score;
  score_before?: Score;
  score_after?: Score;
  delta: PlanningDelta;
  impact?: SkuPlanningImpact;
  impact_before?: SkuPlanningImpact;
  impact_after?: SkuPlanningImpact;
  warnings?: string[];
  gate_report?: GateReport;
}

export interface SubcontractsResponse {
  companies: SubcontractCompany[];
  sku_subcontracts: Record<string, SkuSubcontractRule>;
  legacy_skus?: string[];
  score?: Score;
  score_previous?: Score;
  score_before?: Score;
  score_after?: Score;
  delta?: PlanningDelta;
  warnings?: string[];
  status?: string;
  gate_report?: GateReport;
}

// ── Console ──────────────────────────────────────────────────

export interface ConsoleAction {
  severity: string;
  title: string;
  detail: string;
  suggestion: string | null;
  machine_id: string | null;
  deadline: number | null;
  client: string | null;
  category: string | null;
}

export interface ConsoleMachine {
  machine_id: string;
  group: string;
  utilization_pct: number;
  current_tool: string | null;
  current_sku: string | null;
  runs: { tool_id: string; sku: string; qty: number; prod_min: number }[];
  next_setup_at: number | null;
  eta_current: number | null;
  total_pcs: number;
}

export interface ConsoleExpedition {
  client: string;
  ready: number;
  partial: number;
  not_ready: number;
  total: number;
}

export interface ConsoleSummaryLine {
  text: string;
  color: "red" | "orange" | "green" | "default";
}

export interface TomorrowSetup {
  time: string;
  machine: string;
  from_tool: string | null;
  to_tool: string;
  duration_min: number;
  already_mounted: boolean;
}

export interface TomorrowOperator {
  shift: string;
  group: string;
  required: number;
  available: number;
  deficit: number;
}

export interface TomorrowPrep {
  date: string | null;
  setups: TomorrowSetup[];
  operators: TomorrowOperator[];
  expeditions_summary: string | null;
  problems: string[];
  ok: boolean;
}

export interface ConsoleData {
  state: { color: string; phrase: string };
  actions: ConsoleAction[];
  machines: ConsoleMachine[];
  expedition: ConsoleExpedition[];
  tomorrow: TomorrowPrep | null;
  summary: ConsoleSummaryLine[];
}

// ── Actions ──────────────────────────────────────────────────

export interface MutationInput {
  type: string;
  params: Record<string, unknown>;
}

export interface DeltaReport {
  otd_before: number;
  otd_after: number;
  otd_d_before: number;
  otd_d_after: number;
  setups_before: number;
  setups_after: number;
  earliness_before: number;
  earliness_after: number;
  tardy_before: number;
  tardy_after: number;
}

export interface SimulateResponse {
  score_baseline: Score;
  score_scenario: Score;
  delta: DeltaReport;
  time_ms: number;
  summary: string[];
  segments: Segment[];
  lots: Lot[];
  gate_report?: GateReport;
}

export interface SimulateApplyResponse {
  status: string;
  score: Score;
  score_previous: Score;
  summary: string[];
  n_segments_before: number;
  n_segments_after: number;
  time_ms: number;
  can_revert: boolean;
  mutations?: MutationInput[];
  gate_report?: GateReport;
}

export interface CTPResult {
  sku: string;
  qty_requested: number;
  feasible: boolean;
  latest_day: number | null;
  earliest_end_day: number | null;
  machine: string | null;
  confidence: string;
  slack_min: number;
  reason: string;
  date_start: string | null;
  date_end: string | null;
  required_min: number;
  prod_days: number;
  delivery_deadline?: number;
  effective_deadline?: number;
}

export interface LearningInfo {
  optimized: boolean;
  mode?: string;
  time_ms?: number;
  n_trials?: number;
  confidence?: string;
  improvement?: { reward?: number; earliness_delta?: number; setups_delta?: number };
  total_time_ms?: number;
  best_params?: Record<string, unknown>;
}

export interface LoadResponse {
  status: string;
  n_ops: number;
  n_segments: number;
  score: Score;
  time_ms: number;
  trust_index: { score: number; gate: string };
  journal_summary: { total: number; warnings: number } | null;
  learning: LearningInfo | null;
  dataset: DatasetInfo;
  gate_report?: GateReport;
}

// ── Chat ─────────────────────────────────────────────────────

export interface ChatResponse {
  response: string;
  widgets: unknown[];
  tools_used: number;
}

export interface HealthResponse {
  status: string;
  has_data: boolean;
  n_segments: number;
  dataset: DatasetInfo | null;
}

export interface MasterDataResult {
  status: string;
  score: Score;
  score_anterior: Score;
  [key: string]: unknown;
}

export interface JournalEntry {
  step: string;
  severity: string;
  message: string;
  metadata?: Record<string, unknown>;
  elapsed_ms: number;
}

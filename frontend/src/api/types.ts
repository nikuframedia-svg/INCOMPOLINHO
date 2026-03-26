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
}

export interface TrustIndex {
  score: number;
  gate: string;
  n_ops: number;
  n_issues: number;
  dimensions: { name: string; score: number; details: string[] }[];
}

// ── Analytics ────────────────────────────────────────────────

export interface StockDayCompact {
  day: number;
  date: string;
  stock: number;
  demand: number;
  produced: number;
  workday: boolean;
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
  sku: string;
  machine_id: string;
  edd: number;
  completion_day: number;
  delay_days: number;
  root_cause: string;
  suggestion: string;
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
  jit_enabled: boolean;
  jit_buffer_pct: number;
  jit_threshold: number;
  max_run_days: number;
  max_edd_gap: number;
  edd_swap_tolerance: number;
  campaign_window: number;
  urgency_threshold: number;
  interleave_enabled: boolean;
  weight_earliness: number;
  weight_setups: number;
  weight_balance: number;
  eco_lot_mode: string;
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
  stock: number;
  oee: number;
  backlog: number;
  operators: number;
  demand: number[];
}

// ── Console ──────────────────────────────────────────────────

export interface ConsoleAction {
  severity: string;
  title: string;
  detail: string;
  suggestion: string;
  machine_id: string | null;
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

export interface ConsoleData {
  state: { color: string; phrase: string };
  actions: ConsoleAction[];
  machines: ConsoleMachine[];
  expedition: ConsoleExpedition[];
  tomorrow: unknown;
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
}

export interface CTPResult {
  sku: string;
  qty_requested: number;
  feasible: boolean;
  latest_day: number | null;
  machine: string | null;
  confidence: string;
  slack_min: number;
  reason: string;
}

export interface LearningInfo {
  optimized: boolean;
  n_trials: number;
  confidence: string;
  improvement: { reward: number; earliness_delta: number; setups_delta: number };
  total_time_ms: number;
  best_params: Record<string, unknown>;
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
}

// ── Chat ─────────────────────────────────────────────────────

export interface ChatResponse {
  response: string;
  widgets: unknown[];
  tools_used: number;
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

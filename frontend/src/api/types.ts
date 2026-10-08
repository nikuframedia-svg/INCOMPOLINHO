/** TypeScript interfaces matching backend /api/data/* responses exactly. */

// ── Core ─────────────────────────────────────────────────────

export interface Score {
  otd: number;
  otd_d: number;
  tardy_count: number;
  production_due_misses?: number;
  production_due_late_workdays?: number;
  subcontract_dispatch_total?: number;
  subcontract_dispatch_misses?: number;
  subcontract_dispatch_late_workdays?: number;
  subcontract_dispatch_max_late_workdays?: number;
  subcontract_dispatch_otd?: number;
  duplicate_twin_output_qty?: number;
  duplicate_production_qty?: number;
  setups: number;
  earliness_avg_days: number;
  utilization_avg: number;
  utilization_balance: number;
  weighted_score: number;
  [key: string]: unknown; // allow extra fields from scorer
}

export interface PlanView {
  plan_revision: number;
  dataset_id: string;
  dataset?: DatasetInfo | null;
  active_mutations: MutationInput[];
  manual_edits: ManualEdit[];
  can_revert: boolean;
  learning: LearningInfo | null;
  score: Score;
  gate_report: GateReport;
  improvement_report?: ImprovementReport | null;
  segments: Segment[];
  placement_reasons: Record<string, PlacementReason>;
  lots: Lot[];
  config: FactoryConfig;
  capacity: CapacityResponse;
  workdays: string[];
  blocked_days: BlockedDaysResponse;
}

export interface PlacementReason {
  kind: "manual" | "historical" | "protected";
  machine_id?: string;
  start_at?: string;
  reason?: string;
  historical?: boolean;
}

export interface OutputMilestone {
  op_id: string;
  sku: string;
  qty: number;
  is_subcontracted: boolean;
  subcontract_company_id?: string | null;
  subcontract_lead_time_days?: number;
  subcontract_buffer_days?: number;
  customer_delivery_day: number;
  latest_subcontract_dispatch_day?: number | null;
  subcontract_dispatch_day?: number | null;
  production_due_day: number;
  internal_target_day: number;
  material_reference_day: number;
  material_reference_kind: "customer_delivery" | "subcontract_dispatch" | string;
  material_release_day: number;
  is_coproduced_surplus?: boolean;
}

interface PlanningMilestoneFields {
  customer_delivery_day?: number | null;
  latest_subcontract_dispatch_day?: number | null;
  subcontract_dispatch_day?: number | null;
  production_due_day?: number | null;
  internal_target_day?: number | null;
  material_reference_day?: number | null;
  material_reference_kind?: "customer_delivery" | "subcontract_dispatch" | "mixed" | string;
  material_release_day?: number | null;
  output_milestones?: OutputMilestone[] | null;
  is_subcontracted?: boolean;
}

export interface Segment extends PlanningMilestoneFields {
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
  planning_priority?: number;
  release_delay_workdays?: number;
  planning_source?: string;
  economic_warning?: string | null;
  subcontract_company_id?: string | null;
  subcontract_lead_time_days?: number;
  subcontract_buffer_days?: number;
  left_shift_blockers?: string[];
}

export interface Lot extends PlanningMilestoneFields {
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
  sku: string;
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
  planning_priority?: number;
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
  day_idx: number;
  date: string;
  client: string;
  sku: string;
  order_qty: number;
  produced_qty: number;
  factory_produced_qty: number;
  shortfall: number;
  status: string;
  coverage_pct: number;
}

export interface ExpeditionDay {
  day_idx: number;
  date: string;
  total_orders: number;
  total_ready: number;
  total_partial: number;
  total_at_subcontractor?: number;
  total_in_production?: number;
  total_not_planned: number;
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
  factory_ready_day?: number | null;
  customer_ready_day?: number | null;
  subcontract_dispatch_day?: number | null;
  is_subcontracted?: boolean;
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

/** Plain risk band; "ok" lots never reach top_risks (server filters them out). */
export type LotRiskStatus = "late" | "at_limit" | "short_slack" | "ok";

export interface LotRisk {
  lot_id: string;
  sku: string;
  machine_id: string;
  edd: number;
  slack: number;
  slack_days?: number;
  /** late: slack < 0 · at_limit: slack == 0 · short_slack: 1–2 days. Absent on old servers. */
  status?: LotRiskStatus;
  /** Only a cause proven by the binding-constraint analysis; null when none is proven. */
  cause?: string | null;
  completion_day?: number;
  production_day?: number;
  production_date?: string | null;
  planned_machine_id?: string | null;
  completion_date?: string | null;
  completion_machine_id?: string | null;
  risk_score?: number;
  binding_constraint?: string;
  risk_level: string;
  [key: string]: unknown;
}

export interface HeatmapCell {
  machine_id: string;
  day_idx: number;
  utilization: number | null;
  load_min?: number;
  capacity_min?: number;
  min_slack_min?: number;
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
  customer_ready_day?: number | null;
  production_due_day?: number | null;
  subcontract_dispatch_day?: number | null;
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

export interface CapacityItem {
  machine_id: string;
  bucket: string;
  label: string;
  date_from: string;
  date_to: string;
  day_indices: number[];
  cap_min: number;
  setup_min: number;
  prod_min: number;
  load_min: number;
  util_pct: number | null;
  overload: boolean;
  n_setups: number;
}

export interface CapacityResponse {
  granularity: "day" | "week";
  items: CapacityItem[];
  operators: OperatorCapacityItem[];
}

export interface OperatorCapacityItem {
  bucket: string;
  date_from: string;
  date_to: string;
  group: string;
  shift: string;
  capacity_operator_min: number;
  load_operator_min: number;
  util_pct: number | null;
  peak_required?: number;
  min_available?: number;
  peak_deficit?: number;
  overload: boolean;
}

export interface BlockedDaysResponse {
  workdays: string[];
  holidays: { day_idx: number; date: string | null }[];
  machine_blocks: { machine_id: string; day_idx: number; date: string | null }[];
  tool_blocks: { tool_id: string; day_idx: number; date: string | null }[];
  machine_intervals?: Array<{
    machine_id: string;
    start_day: number;
    start_min: number;
    end_day: number;
    end_min: number;
    category: string;
    reason: string;
    start_at: string;
    end_at: string;
  }>;
  tool_intervals?: Array<{
    tool_id: string;
    start_day: number;
    start_min: number;
    end_day: number;
    end_min: number;
    category: string;
    reason: string;
    start_at: string;
    end_at: string;
  }>;
  operator_intervals?: Array<{
    id: string;
    group: string;
    shift: string;
    count: number;
    start_day: number;
    start_min: number;
    end_day: number;
    end_min: number;
    category: string;
    reason: string;
    start_at: string;
    end_at: string;
  }>;
  inactive_machines: string[];
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

export interface ResourceUnavailability {
  id: string;
  resource: string;
  start_at: string;
  end_at: string;
  category: "Avaria" | "Manutenção" | "Ensaio" | "Outra";
  from?: string;
  to?: string;
  reason: string;
}

export interface OperatorUnavailability {
  id: string;
  group: string;
  shift: string;
  count: number;
  start_at: string;
  end_at: string;
  category: "Avaria" | "Manutenção" | "Ensaio" | "Outra";
  from?: string;
  to?: string;
  reason: string;
}

export interface UnavailabilityConfig {
  machines: ResourceUnavailability[];
  tools: ResourceUnavailability[];
  operators: OperatorUnavailability[];
}

export interface SetupOverride {
  sku: string;
  machine: string;
  hours: number;
}

export interface FactoryConfig {
  plan_revision: number;
  name: string;
  site: string;
  timezone: string;
  shifts: ShiftConfig[];
  day_capacity_min: number;
  machines: Record<string, {
    group: string;
    active: boolean;
    day_capacity_min: number | null;
    oee: number | null;
  }>;
  tools: Record<string, ToolConfig>;
  twins: TwinConfig[];
  operators: Record<string, number>;
  holidays: string[];
  extra_workdays: string[];
  unavailability: UnavailabilityConfig;
  setup_overrides: SetupOverride[];
  setup_families: Record<string, string[][]>;
  earliness_policy: string;
  material_release_days: number;
  early_window_enforcement: string;
  oee_default: number;
  subcontract_skus: string[];
  sku_planning_rules: Record<string, SkuPlanningRule>;
  subcontract_companies: SubcontractCompany[];
  sku_subcontracts: Record<string, SkuSubcontractRule>;
  setup_crews: number;
  setup_crews_by_group: Record<string, number>;
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
  planning_priority?: number;
}

export interface SubcontractCompany {
  id: string;
  name: string;
  lead_time_workdays: number;
  lead_time_days?: number;
}

export interface SkuSubcontractRule {
  enabled?: boolean;
  company_id?: string;
  lead_time_workdays?: number;
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
  planning_priority?: number;
  subcontract_company_id?: string | null;
  subcontract_lead_time_days?: number;
  subcontract_buffer_days?: number;
  stock: number;
  oee: number;
  backlog: number;
  operators: number;
  demand: number[];
  active?: boolean;
}

export type CatalogSource = "isop" | "config" | "both";

export interface MasterCatalog {
  source_policy: {
    active: string;
    persistent: string;
  };
  machines: Array<{
    id: string;
    source: CatalogSource;
    active: boolean;
    group: string;
    oee: number | null;
  }>;
  tools: Array<{
    id: string;
    source: CatalogSource;
    active: boolean;
    primary: string;
    primary_source?: "isop" | "config" | "conflict" | "missing";
    observed_machines?: string[];
    alt: string | null;
    setup_hours: number;
  }>;
  references: Array<{
    id: string;
    source: "isop" | "config";
    active: boolean;
    client: string;
    machine: string;
    tool: string;
    has_override: boolean;
  }>;
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
  subcontract_dispatch_misses: number;
  subcontract_dispatch_late_workdays: number;
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

export interface FeasibilityConstraint {
  resource_type: "machine" | "tool" | string;
  resource_id: string;
  from_day: number;
  to_day: number;
  demand_min: number;
  capacity_min: number;
  deficit_min: number;
  affected_lots: string[];
  affected_ops: string[];
  affected_qty: number;
}

export interface FeasibilityIntervention {
  type: "overtime" | "subcontract" | "alternate_machine" | string;
  resource_type: string;
  resource_id: string;
  from_day: number;
  to_day: number;
  required_minutes?: number;
  required_qty_upper_bound?: number;
  automatic: boolean;
}

export interface FeasibilityReport {
  solver_status: "feasible" | "proven_infeasible" | "timeout_with_candidate" | "timeout_no_solution" | string;
  strict_solver_status: string;
  strict_feasible: boolean;
  jit_window_workdays: number;
  minimum_required_window_workdays_lower_bound: number | null;
  binding_constraints: FeasibilityConstraint[];
  interventions: FeasibilityIntervention[];
}

export interface JitWindowViolation {
  lot_id: string;
  run_id: string;
  op_id: string;
  sku: string;
  tool_id: string;
  machine_id: string;
  qty: number;
  is_twin: boolean;
  delivery_day: number;
  delivery_date?: string | null;
  customer_delivery_day?: number;
  customer_delivery_date?: string | null;
  material_reference_day?: number;
  material_reference_date?: string | null;
  material_reference_kind?: "customer_delivery" | "subcontract_dispatch" | "mixed" | string;
  production_due_day?: number;
  production_due_date?: string | null;
  subcontract_dispatch_day?: number | null;
  subcontract_dispatch_date?: string | null;
  start_day: number;
  start_date?: string | null;
  earliest_allowed_start_day: number;
  earliest_allowed_start_date?: string | null;
  anticipation_workdays: number;
  allowed_anticipation_workdays: number;
  excess_workdays: number;
  increment_workdays: number;
  reason_code: string;
  reason: string;
  campaign_lot_count: number;
  campaign_span_workdays: number;
}

/** Order-level delivery metrics (same criterion as the no-loss improvement). Old reports lack them. */
export interface GateOrderMetrics {
  orders_total?: number;
  orders_on_time?: number;
  orders_late?: number;
  /** Percent of orders on time, 1 decimal. */
  order_otd?: number;
}

export type GateMetrics = Record<string, number> & GateOrderMetrics;

/** One late customer order; ready_day/late_days are null when it is never fully covered. */
export interface LateOrderDetail {
  client: string;
  sku: string;
  /** Machine that produces the SKU; absent on reports made before it was sent. */
  machine_id?: string | null;
  order_qty: number;
  covered_qty: number;
  shortfall_qty: number;
  due_day: number;
  ready_day: number | null;
  late_days: number | null;
}

/** A lot produced on more consecutive days than max_run_days (a weekend breaks the count). */
export interface LongProductionDetail {
  lot_id: string;
  sku: string;
  machine_id: string;
  workdays: number;
  limit_workdays: number;
  excess_workdays: number;
  consecutive?: boolean;
  days: number[];
  consecutive_days: number[];
}

export interface GateReport {
  status: "applicable" | "best_effort" | "invalid_physics" | string;
  apply_decision: "auto_applicable" | "approval_required" | "blocked";
  requires_approval: boolean;
  approval_reasons: string[];
  plan_revision?: number;
  hard_gate_passed: boolean;
  physical_gate_passed: boolean;
  coverage_gate_passed: boolean;
  delivery_gate_passed: boolean;
  subcontract_dispatch_gate_passed: boolean;
  jit_window_gate_passed: boolean;
  /** Legacy: robustness no longer gates plans; old revisions may still carry it. */
  robustness_gate_passed?: boolean | null;
  material_gate_passed: boolean;
  metrics: GateMetrics;
  violations: Record<string, unknown>[];
  late_detail: Record<string, unknown>[];
  /** Late orders, max 50, most late first. Old reports lack it. */
  late_order_detail?: LateOrderDetail[];
  jit_window_detail: JitWindowViolation[];
  subcontract_dispatch_detail?: Array<{
    lot_id: string;
    op_id: string;
    sku: string;
    qty: number;
    subcontract_company_id?: string | null;
    customer_delivery_day: number;
    customer_delivery_date?: string | null;
    latest_subcontract_dispatch_day?: number | null;
    latest_subcontract_dispatch_date?: string | null;
    subcontract_dispatch_day: number;
    subcontract_dispatch_date?: string | null;
    production_due_day: number;
    production_due_date?: string | null;
    completion_day: number;
    completion_date?: string | null;
    late_workdays: number;
  }>;
  setup_overlap_detail: Record<string, unknown>[];
  long_production_detail?: LongProductionDetail[];
  proposals: GateProposal[];
  solver_trace?: SolverTrace;
  solver_status?: string;
  feasibility?: FeasibilityReport | null;
  /** Informational summary of the no-loss improvement phase (never gates). */
  improvement?: ImprovementSummary;
}

export interface ToolTransferExplanation {
  key: string;
  tool_id: string;
  kind: "ping_pong" | "split" | string;
  from_machine: string;
  to_machine: string;
  day_idx: number;
  lot_ids: string[];
  duration_ratio: number;
  reason: string;
  details: string[];
  summary: string;
}

export interface ImprovementSummary {
  contract_version: number;
  status: "completed" | "partial" | "not_evaluated" | string;
  stop_reason?: string | null;
  moves_accepted: number;
  accepted_by_scope: Record<string, number>;
  rolled_back_moves?: number;
  tool_transfers?: {
    remaining: number;
    items: ToolTransferExplanation[];
    omitted: number;
  };
}

export interface ImprovementReport {
  contract_version?: number;
  status: "completed" | "partial" | "not_evaluated";
  stop_reason?: string | null;
  scopes?: string[];
  candidates_evaluated?: number;
  moves_accepted?: number;
  accepted_by_scope?: Record<string, number>;
  duration_ms?: number;
  [key: string]: unknown;
}

export interface RobustnessResult {
  model_version: number;
  profile: string;
  seed: number;
  sample_seeds: number[];
  requested_samples: number;
  completed_samples: number;
  success_definition?: "no_additional_tardy_lots";
  /** Model v5 only looks this many working days ahead of the planning anchor. */
  horizon_workdays?: number | null;
  /** First and last working day of the v5 window (ISO yyyy-mm-dd). */
  horizon_start_date?: string | null;
  horizon_end_date?: string | null;
  /** Lots with a real delivery inside the window; 0 means nothing was measured. */
  horizon_lot_count?: number | null;
  /** True when the window has no deliveries; the percentage is then null. */
  no_deliveries_in_window?: boolean;
  informational_only?: boolean;
  baseline_tardy_count?: number;
  /** Null when there was nothing to measure (no deliveries in the window). */
  success_probability_pct: number | null;
  additional_tardy_mean?: number;
  additional_tardy_p95?: number;
  otd_p50: number;
  otd_p90: number;
  otd_p95: number;
  tardy_mean: number;
  tardy_p90: number;
  tardy_p95: number;
  total_tardiness_cvar95: number;
  worst_scenarios: Array<{
    index: number;
    seed: number;
    otd: number;
    tardy_count: number;
    total_tardiness: number;
    max_tardiness: number;
    affected_lots: string[];
    manifest: Record<string, unknown>;
  }>;
}

export interface RobustnessJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: "queued" | "running" | "cancelling" | "cancelled" | "completed" | "failed" | "interrupted";
  profile: "quick" | "standard" | "intensive";
  samples: number;
  seed: number;
  progress: number;
  dataset_fingerprint: string;
  result: RobustnessResult | null;
  error: string | null;
  stale?: boolean;
  /** "auto" runs after every plan commit; "manual" is the planner's button. */
  trigger?: "auto" | "manual";
  plan_revision?: number | null;
  horizon_workdays?: number | null;
  model_version?: number;
}

export interface ReplanJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: "queued" | "running" | "ready" | "completed" | "failed" | "cancelled";
  progress: number;
  phase: string;
  message: string;
  reason: string;
  dataset_id: string;
  base_revision: number;
  result: {
    score: Score;
    gate_report: GateReport;
    improvement_report?: ImprovementReport | null;
    n_segments: number;
    plan_revision?: number;
  } | null;
  warnings: string[];
  error: string | null;
  request_fingerprint?: string | null;
  deduplicated?: boolean;
  stale?: boolean;
  interrupted?: boolean;
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
  runs: {
    run_id: string;
    lot_id: string;
    tool_id: string;
    sku: string;
    qty: number;
    prod_min: number;
    setup_min: number;
    start_min: number;
    end_min: number;
    start: string;
    end: string;
    shift: string;
    is_continuation: boolean;
  }[];
  next_setup_at: string | null;
  current_state?: "idle" | "producing" | "setup" | "trial" | "down" | null;
  eta_current: number | string | null;
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
  start_min: number;
  shift: string;
  machine: string;
  from_tool: string | null;
  to_tool: string;
  sku: string;
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

export interface ConsoleDayOverview {
  today: {
    date?: string | null;
    production_by_group?: Array<{ group: string; machines: string[]; count: number }>;
    setups_by_group_shift?: Array<{ group: string; shift: string; count: number }>;
    average_utilization_pct?: number;
    unavailable_count?: number;
    trial_count?: number;
    expedition?: { ready: number; partial: number; not_ready: number };
  };
  tomorrow: {
    date?: string | null;
    setups_count?: number;
    operator_deficit?: number;
    problems_count?: number;
    expeditions_summary?: string;
  };
}

export interface ConsoleData {
  date: string | null;
  state: { color: string; phrase: string };
  actions: ConsoleAction[];
  machines: ConsoleMachine[];
  setups_today: TomorrowSetup[];
  top_risks: LotRisk[];
  expedition: ConsoleExpedition[];
  tomorrow: TomorrowPrep | null;
  summary: ConsoleSummaryLine[];
  day_overview?: ConsoleDayOverview;
  operational_summary?: {
    production_by_group: Array<{
      group: string;
      machines: string[];
      count: number;
    }>;
    setups_by_group_shift: Array<{
      group: string;
      shift: string;
      count: number;
    }>;
    average_utilization_pct: number;
    unavailable: {
      machines: Array<{ resource: string; category: string; reason: string; start_at?: string; end_at?: string }>;
      tools: Array<{ resource: string; category: string; reason: string; start_at?: string; end_at?: string }>;
      operators: Array<{ group: string; shift: string; count: number; reason: string; start_at?: string; end_at?: string }>;
    };
    trials: Array<{
      machine_id: string;
      tool_id?: string;
      expected_end?: string;
      note?: string;
    }>;
    expedition: { ready: number; partial: number; not_ready: number };
  };
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
  early_window_before?: number;
  early_window_after?: number;
  utilization_before?: number;
  utilization_after?: number;
  subcontract_dispatch_before?: number;
  subcontract_dispatch_after?: number;
  subcontract_dispatch_late_workdays_before?: number;
  subcontract_dispatch_late_workdays_after?: number;
}

export interface CandidateIdentity {
  candidate_id: string;
  dataset_id: string;
  base_revision: number;
  input_fingerprint: string;
  candidate_fingerprint: string;
}

export interface CTPRequest {
  sku: string;
  qty: number;
  deadline: number;
}

export interface SimulateResponse extends CandidateIdentity {
  score_baseline: Score;
  score_scenario: Score;
  delta: DeltaReport;
  time_ms: number;
  summary: string[];
  segments: Segment[];
  lots: Lot[];
  gate_report?: GateReport;
  improvement_report?: ImprovementReport | null;
}

export interface SimulateApplyResponse {
  plan_revision: number;
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
  improvement_report?: ImprovementReport | null;
}

export interface CTPResult extends CandidateIdentity {
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
  customer_delivery_day?: number | null;
  latest_subcontract_dispatch_day?: number | null;
  production_due_day?: number | null;
  subcontract_dispatch_day?: number | null;
  internal_target_day?: number | null;
  material_reference_day?: number | null;
  material_release_day?: number | null;
  material_reference_kind?: "customer_delivery" | "subcontract_dispatch" | string;
  customer_delivery_date?: string | null;
  latest_subcontract_dispatch_date?: string | null;
  production_due_date?: string | null;
  subcontract_dispatch_date?: string | null;
  internal_target_date?: string | null;
  material_reference_date?: string | null;
  material_release_date?: string | null;
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
  improvement_report?: ImprovementReport | null;
  plan_revision?: number;
  state_warnings?: string[];
}

export interface PreparedLoad {
  status: "prepared";
  token: string;
  expected_revision: number;
  filename: string;
  n_ops: number;
  trust_index: { score: number; gate: string };
  machines: { id: string; group: string }[];
  references: string[];
  tools: string[];
  warnings?: string[];
  next_step: string;
}

export type LoadJobStatus = "preparing" | "prepared" | "queued" | "running"
  | "awaiting_approval" | "applied" | "blocked" | "failed" | "cancelled" | "stale";

export interface LoadJob {
  id: string;
  filename: string;
  status: LoadJobStatus;
  phase: string;
  message: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  elapsed_ms: number;
  timings_ms: Record<string, number>;
  base_revision: number;
  prepared: PreparedLoad | null;
  gate_report: GateReport | null;
  result: LoadResponse | null;
  error: { code: string; message: string; violations?: unknown[] } | null;
  plan_id?: string;
}

export interface LoadJobResponse { job: LoadJob }

export interface CurrentMachineState {
  machine_id: string;
  status: "idle" | "producing" | "setup" | "trial" | "down";
  sku?: string;
  tool_id?: string;
  remaining_qty?: number;
  expected_end?: string;
  note?: string;
}

// ── Chat ─────────────────────────────────────────────────────

export interface ChatResponse {
  response: string;
  widgets: unknown[];
  tools_used: number;
}

export interface HealthResponse {
  status: string;
  plan_revision: number;
  has_data: boolean;
  n_segments: number;
  dataset: DatasetInfo | null;
  copilot?: {
    available: boolean;
    backend: string;
    reason: string;
  };
}

export interface MasterDataResult {
  status: string;
  score: Score;
  score_anterior?: Score;
  score_previous?: Score;
  [key: string]: unknown;
}

export interface PlanSummary {
  id: string;
  created_at: string;
  name: string;
  source: string;
  origin: string;
  note: string;
  is_auto: boolean;
  otd: number | null;
  otd_d: number | null;
  tardy_count: number | null;
  setups: number | null;
  gate_status: string | null;
}

export interface RestorePlanResponse {
  status: string;
  plan: PlanSummary;
  dataset: DatasetInfo;
  score: Score;
  gate_report: GateReport;
  improvement_report?: ImprovementReport | null;
  plan_revision: number;
}

export interface ManualEdit {
  id: string;
  created_at: string;
  lot_id: string;
  source_days: number[];
  target_day: number;
  target_start_min?: number;
  target_machine: string;
  delivery_risk_confirmed: boolean;
}

export interface ManualMoveResponse {
  contract_version: 2;
  status: "preview" | "applied";
  lot_id: string;
  source_days: number[];
  target_day: number;
  target_start_min: number;
  target_machine: string;
  score: Score;
  score_previous: Score;
  delta: DeltaReport;
  gate_report: GateReport;
  improvement_report?: ImprovementReport | null;
  requires_confirmation: boolean;
  delivery_warnings: string[];
  time_ms: number;
  edit?: ManualEdit;
  can_revert?: boolean;
  plan_revision?: number;
}

export interface ManualMoveJob {
  id: string;
  created_at: string;
  updated_at: string;
  status: "queued" | "running" | "ready" | "applied" | "failed" | "cancelled";
  progress: number;
  phase: "queued" | "scheduling" | "validating" | "finalizing" | "ready" | "applied" | "failed" | "cancelled";
  message: string;
  dataset_id: string;
  base_revision: number;
  error: string | null;
  gate_report?: GateReport | null;
  result: ManualMoveResponse | null;
}

export interface JournalEntry {
  step: string;
  severity: string;
  message: string;
  metadata?: Record<string, unknown>;
  elapsed_ms: number;
}

// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — PlanState Types
//  Backend API contract / adapter output format
// ═══════════════════════════════════════════════════════════

import type { FailureEvent } from './failure.js';
import type { ShippingCutoffConfig } from './shipping.js';
import type { WorkforceConfig } from './workforce.js';

export interface PlanningMachine {
  id: string;
  area: 'PG1' | 'PG2';
  man_minutes: number[];
  operator_pool?: number;
}

export interface PlanningTool {
  id: string;
  machine: string;
  alt_machine: string;
  setup_hours: number;
  pcs_per_hour: number;
  operators: number;
  skus: string[];
  names: string[];
  lot_economic_qty: number;
  stock: number;
  calco_code?: string;
  wip?: number;
}

export interface PlanningOperation {
  id: string;
  machine: string;
  tool: string;
  sku: string;
  name: string;
  pcs_per_hour: number;
  atraso: number;
  daily_qty: (number | null)[];
  setup_hours: number;
  operators: number;
  stock: number;
  status: 'PLANNED' | 'RUNNING' | 'LATE' | 'BLOCKED';
  customer_code?: string;
  customer_name?: string;
  parent_sku?: string;
  wip?: number;
  qtd_exp?: number;
  lead_time_days?: number;
  /** Per-operation shipping buffer (hours). Set by user in UI per order/expedition. */
  buffer_hours?: number;
  /** Peça Gémea SKU reference */
  twin?: string;
}

export interface ScheduleSlot {
  operation_id: string;
  machine: string;
  tool: string;
  sku: string;
  day_index: number;
  shift: 'X' | 'Y';
  start_minute: number;
  duration_minutes: number;
  quantity: number;
  is_setup: boolean;
}

export interface MachineLoadEntry {
  machine: string;
  day_index: number;
  total_minutes: number;
  production_minutes: number;
  setup_minutes: number;
  utilization: number;
  ops_count: number;
}

export interface PlanningKPIs {
  otd_rate: number;
  tardiness_total_days: number;
  setup_count: number;
  setup_total_minutes: number;
  balance_score: number;
  total_production_minutes: number;
  machine_utilization: Record<string, number>;
}

export interface PlanState {
  dates: string[];
  days_label: string[];
  machines: PlanningMachine[];
  tools: PlanningTool[];
  operations: PlanningOperation[];
  schedule: ScheduleSlot[];
  machine_loads: MachineLoadEntry[];
  kpis: PlanningKPIs | null;
  parsed_at: string | null;
  data_hash: string | null;
  workday_flags?: boolean[];
  mo?: { PG1: number[]; PG2: number[]; poolPG1?: number[]; poolPG2?: number[] };
  machineStatus?: Record<string, 'running' | 'down'>;
  toolStatus?: Record<string, 'running' | 'down'>;
  /** Temporal failure events. When present, these OVERRIDE machineStatus/toolStatus
   *  for the affected day ranges. Binary status is still used for resources without
   *  any FailureEvent entries. */
  failureEvents?: FailureEvent[];
  thirdShift?: boolean;
  /** Shipping cutoff configuration. When present, activates shipping-as-law pipeline. */
  shippingCutoff?: ShippingCutoffConfig;
  /** Workforce zone configuration (overrides default machine-to-zone mapping) */
  workforceConfig?: WorkforceConfig;
}

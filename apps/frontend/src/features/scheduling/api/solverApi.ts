/**
 * Solver API client — POST /v1/solver/schedule
 * Falls back to error if backend unavailable (caller handles fallback).
 */

import { config } from '../../../config';

// ── Request types (mirror backend schemas.py) ──

export interface OperationInput {
  id: string;
  machine_id: string;
  tool_id: string;
  duration_min: number;
  setup_min: number;
  operators: number;
  calco_code: string | null;
}

export interface JobInput {
  id: string;
  sku: string;
  due_date_min: number;
  weight: number;
  operations: OperationInput[];
}

export interface MachineInput {
  id: string;
  capacity_min: number;
}

export interface TwinPairInput {
  op_id_a: string;
  op_id_b: string;
  machine_id: string;
  tool_id: string;
}

export interface ConstraintConfigInput {
  setup_crew: boolean;
  tool_timeline: boolean;
  calco_timeline: boolean;
  operator_pool: boolean;
}

export interface SolverConfig {
  time_limit_s: number;
  objective: 'makespan' | 'tardiness' | 'weighted_tardiness';
  num_workers: number;
}

export interface SolverRequest {
  jobs: JobInput[];
  machines: MachineInput[];
  config: SolverConfig;
  twin_pairs: TwinPairInput[];
  constraints: ConstraintConfigInput;
  workdays?: number[];
}

// ── Response types ──

export interface ScheduledOp {
  op_id: string;
  job_id: string;
  machine_id: string;
  tool_id: string;
  start_min: number;
  end_min: number;
  setup_min: number;
  is_tardy: boolean;
  tardiness_min: number;
  is_twin_production: boolean;
  twin_partner_op_id: string | null;
}

export interface SolverResult {
  schedule: ScheduledOp[];
  makespan_min: number;
  total_tardiness_min: number;
  weighted_tardiness: number;
  solver_used: 'cpsat' | 'heuristic';
  solve_time_s: number;
  status: 'optimal' | 'feasible' | 'infeasible' | 'timeout';
  objective_value: number;
  n_ops: number;
  operator_warnings: Record<string, unknown>[];
}

// ── Optimal Pipeline types ──

export interface OptimalRequest {
  solver_request: SolverRequest;
  frozen_ops: string[];
  alt_machines: Record<string, string[]> | null;
  run_monte_carlo: boolean;
  n_scenarios: number;
}

export interface OptimalResult {
  solver_result: SolverResult;
  recovery_used: boolean;
  recovery_level: number;
  robustness: {
    p_otd_100: number;
    p_otd_95: number;
    mean_tardiness: number;
    vulnerable_jobs: Array<{ job_id: string; late_pct: number; avg_tardiness_min: number }>;
    suggested_buffers: Array<{ job_id: string; buffer_min: number; reason: string }>;
    n_scenarios: number;
    elapsed_s: number;
  } | null;
}

// ── API calls ──

/** SAT-08: Fetch with AbortController timeout (default 5s for connection, solver has its own time_limit_s) */
function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal }).finally(() => clearTimeout(timer));
}

export async function callServerSolver(request: SolverRequest): Promise<SolverResult> {
  const base = config.apiBaseURL;
  // Solver timeout = time_limit_s + 5s buffer for network
  const timeoutMs = (request.config.time_limit_s + 5) * 1000;
  const res = await fetchWithTimeout(
    `${base}/v1/solver/schedule`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    throw new Error(`Solver HTTP ${res.status}: ${await res.text().catch(() => 'unknown')}`);
  }
  return await res.json();
}

export async function callOptimalPipeline(request: OptimalRequest): Promise<OptimalResult> {
  const base = config.apiBaseURL;
  // Optimal pipeline: solver + recovery + monte carlo — give generous timeout
  // but cap at 90s to avoid infinite waits when backend is down
  const solverLimit = request.solver_request.config.time_limit_s;
  const timeoutMs = Math.min((solverLimit + 30) * 1000, 90_000);
  const res = await fetchWithTimeout(
    `${base}/v1/optimal/solve`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': crypto.randomUUID(),
      },
      body: JSON.stringify(request),
    },
    timeoutMs,
  );
  if (!res.ok) {
    throw new Error(`Optimal HTTP ${res.status}: ${await res.text().catch(() => 'unknown')}`);
  }
  return await res.json();
}

/**
 * api.ts — Typed fetch wrappers for backend scheduling endpoints.
 *
 * Single source of truth for all backend API calls.
 * Each function returns a typed response matching FullScheduleResponse.
 */

import { config } from '../config';
import { fetchWithTimeout } from './fetchWithTimeout';

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
  blocks: Record<string, unknown>[];
  kpis: PipelineKPIs;
  decisions: Record<string, unknown>[];
  feasibility_report: Record<string, unknown> | null;
  auto_moves: Record<string, unknown>[];
  auto_advances: Record<string, unknown>[];
  solve_time_s: number;
  solver_used: string;
  n_blocks: number;
  n_ops: number;
  parse_meta: Record<string, unknown> | null;
  parse_warnings: string[];
  nikufra_data: Record<string, unknown> | null;
  // Engine data (camelCase, matches EngineData interface)
  engine_data: Record<string, unknown> | null;
  // Analytics
  score: Record<string, unknown> | null;
  validation: Record<string, unknown> | null;
  coverage: Record<string, unknown> | null;
  cap: Record<string, unknown[]> | null;
  mrp: Record<string, unknown> | null;
  late_deliveries: Record<string, unknown> | null;
  mrp_sku_view: Record<string, unknown> | null;
  mrp_rop: Record<string, unknown> | null;
  mrp_rop_sku: Record<string, unknown> | null;
  mrp_actions: Record<string, unknown> | null;
  mrp_coverage_sku: Record<string, unknown> | null;
  mrp_coverage_matrix: Record<string, unknown> | null;
  quick_validate: Record<string, unknown> | null;
  gen_decisions: Record<string, unknown>[] | null;
  workforce_forecast: Record<string, unknown> | null;
}

// ── Schedule Full ────────────────────────────────────────────

export interface ScheduleFullRequest {
  nikufra_data: Record<string, unknown>;
  settings: {
    dispatchRule?: string;
    thirdShift?: boolean;
    maxTier?: number;
    orderBased?: boolean;
    demandSemantics?: string;
  };
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
  nikufraData: Record<string, unknown>,
  settings: Record<string, unknown>,
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
  blocks: Record<string, unknown>[];
  disruption: {
    type: string;
    resource_id: string;
    start_day: number;
    end_day: number;
    capacity_factor?: number;
  };
  settings?: Record<string, unknown>;
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
  nikufra_data: Record<string, unknown>;
  mutations: Record<string, unknown>[];
  settings?: Record<string, unknown>;
}

export interface WhatIfResponse {
  baseline: Record<string, unknown> | null;
  scenario: Record<string, unknown> | null;
  delta: Record<string, unknown> | null;
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
  nikufra_data: Record<string, unknown>;
  objective_weights?: Record<string, number>;
  n_alternatives?: number;
  settings?: Record<string, unknown>;
}

export interface OptimizeAlternative {
  objective: string;
  blocks: Record<string, unknown>[];
  score: Record<string, unknown> | null;
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

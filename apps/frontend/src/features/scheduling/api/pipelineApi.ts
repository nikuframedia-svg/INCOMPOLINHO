/**
 * Pipeline API client — POST /v1/pipeline/schedule
 *
 * Sends pre-parsed NikufraData + settings to backend.
 * Backend does: transform → schedule → return blocks + KPIs.
 * Falls back to error if backend unavailable (caller handles fallback).
 */

import { config } from '../../../config';
import type {
  AdvanceAction,
  Block,
  DecisionEntry,
  FeasibilityReport,
  MoveAction,
} from '../../../lib/engine';

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

export interface PipelineResponse {
  blocks: Block[];
  kpis: PipelineKPIs;
  decisions: DecisionEntry[];
  feasibility_report: FeasibilityReport | null;
  auto_moves: MoveAction[];
  auto_advances: AdvanceAction[];
  solve_time_s: number;
  solver_used: string;
  n_blocks: number;
  n_ops: number;
  parse_meta: Record<string, unknown> | null;
  parse_warnings: string[];
  nikufra_data: Record<string, unknown> | null;
}

export async function callBackendPipeline(
  nikufraData: Record<string, unknown>,
  settings: Record<string, unknown>,
): Promise<PipelineResponse> {
  const base = config.apiBaseURL;
  const res = await fetch(`${base}/v1/pipeline/schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      nikufra_data: nikufraData,
      settings,
    }),
  });
  if (!res.ok) {
    throw new Error(`Pipeline HTTP ${res.status}: ${await res.text().catch(() => 'unknown')}`);
  }
  return await res.json();
}

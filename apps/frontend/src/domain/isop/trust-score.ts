/**
 * isop/trust-score.ts — Simplified client-side trust score computation.
 */

import type { NikufraOperation, NikufraTool } from '../nikufra-types';
import type { ParsedRow } from './helpers';

export interface TrustScoreResult {
  score: number;
  dimensions: {
    completeness: number;
    quality: number;
    demandCoverage: number;
    consistency: number;
  };
}

export function computeTrustScore(
  rows: ParsedRow[],
  tools: NikufraTool[],
  operations: NikufraOperation[],
  _nDays: number,
): TrustScoreResult {
  if (rows.length === 0)
    return {
      score: 0,
      dimensions: { completeness: 0, quality: 0, demandCoverage: 0, consistency: 0 },
    };

  // 1. Completeness (40%): % of rows with all key fields
  let complete = 0;
  for (const r of rows) {
    const hasAll = r.item_sku && r.resource_code && r.tool_code && r.rate > 0 && r.setup_time >= 0;
    if (hasAll) complete++;
  }
  const completeness = complete / rows.length;

  // 2. Quality (30%): rates > 0, setup >= 0, operators >= 1
  let valid = 0;
  for (const r of rows) {
    const ok = r.rate > 0 && r.setup_time >= 0 && r.operators_required >= 1;
    if (ok) valid++;
  }
  const quality = valid / rows.length;

  // 3. Demand coverage (20%): % of operations with at least one non-zero demand day
  let withDemand = 0;
  for (const op of operations) {
    if (op.d.some((v) => v !== null && v !== 0)) withDemand++;
  }
  const demandCoverage = operations.length > 0 ? withDemand / operations.length : 0;

  // 4. Consistency (10%): % of tools with valid machine assignment
  let validTools = 0;
  const machineSet = new Set(rows.map((r) => r.resource_code));
  for (const t of tools) {
    if (machineSet.has(t.m)) validTools++;
  }
  const consistency = tools.length > 0 ? validTools / tools.length : 1;

  const score =
    Math.round(
      (completeness * 0.4 + quality * 0.3 + demandCoverage * 0.2 + consistency * 0.1) * 100,
    ) / 100;

  return {
    score,
    dimensions: {
      completeness: Math.round(completeness * 100) / 100,
      quality: Math.round(quality * 100) / 100,
      demandCoverage: Math.round(demandCoverage * 100) / 100,
      consistency: Math.round(consistency * 100) / 100,
    },
  };
}

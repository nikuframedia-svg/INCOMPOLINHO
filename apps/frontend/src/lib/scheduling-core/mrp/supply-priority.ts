// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Supply Priority
//  MRP risk -> scheduler priority boost
//  Closes the feedback loop: MRP detects stockouts -> scheduler prioritises those ops
//  Extracted from supplyPriority.ts (Incompol)
// ═══════════════════════════════════════════════════════════

import type { EngineData } from '../types/engine.js';
import type { MRPResult } from '../types/mrp.js';

export interface SupplyPriority {
  opId: string;
  toolCode: string;
  boost: 0 | 1 | 2 | 3; // 0=normal, 1=medium, 2=high, 3=critical
  reason: string;
}

export interface SupplyPriorityConfig {
  /** Coverage threshold in days -- below this triggers medium boost */
  coverageDays: number;
}

export const DEFAULT_SUPPLY_PRIORITY_CONFIG: SupplyPriorityConfig = {
  coverageDays: 3,
};

/**
 * Compute supply-based priority boosts per operation.
 * Maps MRP risk (stockout days, coverage) to scheduler priority levels.
 *
 * Boost levels:
 *  3 (critical) -- stockout within 1 day
 *  2 (high)     -- stockout beyond 1 day
 *  1 (medium)   -- coverage < threshold days with active demand
 *  0 (normal)   -- no supply risk
 */
export function computeSupplyPriority(
  engine: EngineData,
  mrp: MRPResult,
  config?: Partial<SupplyPriorityConfig>,
): Map<string, SupplyPriority> {
  const cfg = { ...DEFAULT_SUPPLY_PRIORITY_CONFIG, ...config };
  const map = new Map<string, SupplyPriority>();

  // Build toolCode -> MRPRecord lookup
  const mrpByTool = new Map(mrp.records.map((r) => [r.toolCode, r]));

  for (const op of engine.ops) {
    const rec = mrpByTool.get(op.t);
    if (!rec) continue;

    // Per-SKU data when available, fallback to tool-level
    const skuRec = rec.skuRecords?.find((sr) => sr.opId === op.id);
    const effectiveStockout = skuRec?.stockoutDay ?? rec.stockoutDay;
    const effectiveCoverage = skuRec?.coverageDays ?? rec.coverageDays;
    const effectiveGrossReq = skuRec?.grossRequirement ?? rec.totalGrossReq;

    let boost: 0 | 1 | 2 | 3 = 0;
    let reason = '';

    if (effectiveStockout !== null && effectiveStockout <= 1) {
      boost = 3;
      reason = `Rutura iminente (dia ${effectiveStockout})`;
    } else if (effectiveStockout !== null) {
      boost = 2;
      reason = `Rutura prevista dia ${effectiveStockout}`;
    } else if (effectiveCoverage < cfg.coverageDays && effectiveGrossReq > 0) {
      boost = 1;
      reason = `Cobertura baixa (${effectiveCoverage.toFixed(1)}d)`;
    }

    if (boost > 0) {
      map.set(op.id, { opId: op.id, toolCode: op.t, boost, reason });
    }
  }

  return map;
}

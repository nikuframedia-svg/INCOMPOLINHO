// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Per-SKU CTP (Capable-to-Promise)
//  Resolves SKU → tool, delegates to computeCTP()
// ═══════════════════════════════════════════════════════════

import type { EngineData } from '../types/engine.js';
import type { CTPResult, CTPSkuInput, MRPResult } from '../types/mrp.js';
import { computeCTP } from './mrp-ctp.js';

/**
 * Compute Capable-to-Promise for a given SKU.
 *
 * Resolves the SKU to its tool via engine.ops, then delegates
 * to the existing tool-level computeCTP(). Returns the result
 * annotated with SKU information.
 */
export function computeCTPSku(
  input: CTPSkuInput,
  mrp: MRPResult,
  engine: EngineData,
): CTPResult & { sku: string; skuName: string } {
  // Resolve SKU → tool
  const op = engine.ops.find((o) => o.sku === input.sku);

  if (!op) {
    return {
      feasible: false,
      toolCode: '?',
      machine: '?',
      requiredMin: 0,
      availableMinOnDay: 0,
      capacitySlack: 0,
      projectedStockOnDay: 0,
      stockAfterOrder: 0,
      earliestFeasibleDay: null,
      confidence: 'low',
      reason: `SKU ${input.sku} not found.`,
      capacityTimeline: [],
      sku: input.sku,
      skuName: '',
    };
  }

  const toolCode = op.t;
  const ctpResult = computeCTP(
    { toolCode, quantity: input.quantity, targetDay: input.targetDay },
    mrp,
    engine,
  );

  // Annotate with per-SKU projected stock (if available)
  const rec = mrp.records.find((r) => r.toolCode === toolCode);
  const skuRec = rec?.skuRecords.find((sr) => sr.opId === op.id);
  const skuProjectedStock =
    skuRec?.buckets[input.targetDay]?.projectedAvailable ?? ctpResult.projectedStockOnDay;

  return {
    ...ctpResult,
    projectedStockOnDay: skuProjectedStock,
    stockAfterOrder: skuProjectedStock - input.quantity,
    sku: input.sku,
    skuName: op.nm,
  };
}

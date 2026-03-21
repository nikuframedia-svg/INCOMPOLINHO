// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Per-SKU Coverage Matrix
//  computeCoverageMatrixSku(): rows = SKUs (not tools)
// ═══════════════════════════════════════════════════════════

import type { EngineData } from '../types/engine.js';
import type { CoverageMatrixSkuResult, CoverageSkuCell, MRPResult } from '../types/mrp.js';

/**
 * Compute coverage matrix with SKU rows (instead of tool rows).
 *
 * Each row = one SKU operation. Uses per-SKU buckets from
 * MRPRecord.skuRecords for days-of-supply calculation.
 */
export function computeCoverageMatrixSku(
  mrp: MRPResult,
  engine: EngineData,
): CoverageMatrixSkuResult {
  const numDays = engine.dates.length;

  // Flatten all SKU records from all tool records
  const allSkuRecords: Array<{
    sku: string;
    name: string;
    toolCode: string;
    machine: string;
    coverageDays: number;
    totalGrossReq: number;
    buckets: (typeof mrp.records)[0]['buckets'];
  }> = [];

  for (const rec of mrp.records) {
    for (const sr of rec.skuRecords) {
      allSkuRecords.push({
        sku: sr.sku,
        name: sr.name,
        toolCode: sr.toolCode,
        machine: sr.machine,
        coverageDays: sr.coverageDays,
        totalGrossReq: sr.grossRequirement,
        buckets: sr.buckets,
      });
    }
  }

  // Sort by urgency (lowest coverage first)
  allSkuRecords.sort((a, b) => a.coverageDays - b.coverageDays);

  const skus = allSkuRecords.map((r) => ({
    sku: r.sku,
    name: r.name,
    toolCode: r.toolCode,
    machine: r.machine,
    urgencyScore: r.coverageDays,
  }));

  const cells: CoverageSkuCell[][] = [];
  for (const sr of allSkuRecords) {
    const avgDailyDemand = sr.totalGrossReq / numDays;
    const row: CoverageSkuCell[] = [];
    for (const bucket of sr.buckets) {
      const dos = avgDailyDemand > 0 ? bucket.projectedAvailable / avgDailyDemand : numDays;
      const band: CoverageSkuCell['colorBand'] =
        dos < 1 ? 'red' : dos < 3 ? 'amber' : dos < 7 ? 'green' : 'blue';
      row.push({
        sku: sr.sku,
        toolCode: sr.toolCode,
        dayIndex: bucket.dayIndex,
        daysOfSupply: Math.round(dos * 10) / 10,
        colorBand: band,
      });
    }
    cells.push(row);
  }

  return { skus, days: engine.dates, cells };
}

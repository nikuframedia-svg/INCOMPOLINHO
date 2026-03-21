// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — MRP SKU View Transform
//  Flattens tool-centric MRPResult into SKU-primary view
// ═══════════════════════════════════════════════════════════

import type { MRPResult, MRPSkuSummary, MRPSkuViewRecord, MRPSkuViewResult } from '../types/mrp.js';

/**
 * Transform tool-centric MRPResult into a flat SKU-primary view.
 *
 * Each MRPRecord (tool-level) contains `skuRecords[]` (per-SKU netting).
 * This function flattens all skuRecords into a single list with
 * tool/machine metadata attached, ready for SKU-first UI rendering.
 */
export function computeMRPSkuView(mrp: MRPResult): MRPSkuViewResult {
  const skuRecords: MRPSkuViewRecord[] = [];

  for (const rec of mrp.records) {
    for (const sr of rec.skuRecords) {
      skuRecords.push({
        sku: sr.sku,
        name: sr.name,
        opId: sr.opId,
        toolCode: sr.toolCode,
        machine: sr.machine,
        altMachine: sr.altMachine,
        customer: sr.customer,
        customerName: sr.customerName,
        twin: sr.twin,
        isTwin: sr.twin !== undefined && sr.twin !== '',
        currentStock: sr.currentStock,
        wip: sr.wip,
        backlog: sr.backlog,
        grossRequirement: sr.grossRequirement,
        projectedEnd: sr.projectedEnd,
        stockoutDay: sr.stockoutDay,
        coverageDays: sr.coverageDays,
        buckets: sr.buckets,
        ratePerHour: sr.ratePerHour,
        setupHours: sr.setupHours,
        lotEconomicQty: sr.lotEconomicQty,
      });
    }
  }

  const summary: MRPSkuSummary = {
    totalSkus: skuRecords.length,
    skusWithBacklog: skuRecords.filter((r) => r.backlog > 0).length,
    skusWithStockout: skuRecords.filter((r) => r.stockoutDay !== null).length,
    totalGrossReq: skuRecords.reduce((s, r) => s + r.grossRequirement, 0),
    totalPlannedQty: skuRecords.reduce((s, r) => {
      return s + r.buckets.reduce((bs, b) => bs + b.plannedOrderReceipt, 0);
    }, 0),
  };

  return { skuRecords, summary };
}

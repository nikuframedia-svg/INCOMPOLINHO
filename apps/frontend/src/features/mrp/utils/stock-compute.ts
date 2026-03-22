/**
 * stock-compute.ts — Pure computation for stock dashboard.
 */

import type {
  Block,
  EngineData,
  MRPResult,
  MRPSkuViewRecord,
  MRPSkuViewResult,
} from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';

export type StockRisk = 'stockout' | 'critical' | 'warning' | 'ok';

export interface StockRow {
  sku: string;
  name: string;
  toolCode: string;
  machine: string;
  customer: string;
  currentStock: number;
  productionToday: number;
  shipmentsToday: number;
  stockFinalToday: number;
  nextOrderQty: number;
  nextOrderDeadline: string | null;
  coverageDays: number;
  stockoutDay: number | null;
  riskLevel: StockRisk;
  ratePerHour: number;
}

export interface StockKPIs {
  stockoutCount: number;
  riskCount: number;
  totalStock: number;
  avgCoverage: number;
}

function classifyStockRisk(stockoutDay: number | null, coverageDays: number): StockRisk {
  if (stockoutDay !== null && stockoutDay <= 1) return 'stockout';
  if (stockoutDay !== null && stockoutDay <= 5) return 'critical';
  if (coverageDays < 15) return 'warning';
  return 'ok';
}

export function coverageColor(days: number, stockoutDay: number | null): string {
  if (stockoutDay !== null && stockoutDay <= 1) return '#111';
  if (days <= 0) return '#111';
  if (days < 15) return C.rd;
  if (days <= 30) return C.yl;
  return C.ac;
}

/** Coverage including planned production from schedule blocks. */
function augmentedCoverage(
  rec: MRPSkuViewRecord,
  skuProd: Map<number, number> | undefined,
): { coverageDays: number; stockoutDay: number | null } {
  const netStock = Math.max(0, rec.currentStock - rec.backlog);
  let available = netStock;
  const numDays = rec.buckets.length;

  for (let d = 0; d < numDays; d++) {
    const demand = rec.buckets[d]?.grossRequirement ?? 0;
    const prod = skuProd?.get(rec.buckets[d]?.dayIndex ?? d) ?? 0;
    available += prod - demand;
    if (available < 0) {
      const prevAvail = available + demand - prod;
      const deficit = demand - prod;
      const frac = deficit > 0 ? prevAvail / deficit : 0;
      const covDays = Math.round((d + frac) * 10) / 10;
      return { coverageDays: Math.max(0, covDays), stockoutDay: d };
    }
  }
  return { coverageDays: numDays, stockoutDay: null };
}

export function computeStockRows(
  engine: EngineData,
  _mrp: MRPResult,
  skuView: MRPSkuViewResult,
  blocks: Block[],
): StockRow[] {
  // Production by SKU for today (day 0) — used for stockFinalToday
  const todayBlocks = blocks.filter((b) => b.dayIdx === 0 && b.type !== 'blocked');
  const prodBySku = new Map<string, number>();
  for (const b of todayBlocks) {
    prodBySku.set(b.sku, (prodBySku.get(b.sku) ?? 0) + b.qty);
  }

  // Full production map by SKU × dayIndex — used for augmented coverage
  const fullProdBySku = new Map<string, Map<number, number>>();
  for (const b of blocks) {
    if (b.type === 'blocked') continue;
    let skuMap = fullProdBySku.get(b.sku);
    if (!skuMap) {
      skuMap = new Map();
      fullProdBySku.set(b.sku, skuMap);
    }
    skuMap.set(b.dayIdx, (skuMap.get(b.dayIdx) ?? 0) + b.qty);
  }

  const rows: StockRow[] = [];
  for (const rec of skuView.skuRecords) {
    const productionToday = prodBySku.get(rec.sku) ?? 0;
    const shipmentsToday = rec.buckets[0]?.grossRequirement ?? 0;
    const stockFinalToday = rec.currentStock + productionToday - shipmentsToday;

    let nextOrderQty = 0;
    let nextOrderDeadline: string | null = null;
    for (let i = 1; i < rec.buckets.length; i++) {
      if (rec.buckets[i].grossRequirement > 0) {
        nextOrderQty = rec.buckets[i].grossRequirement;
        nextOrderDeadline = engine.dates[rec.buckets[i].dayIndex] ?? null;
        break;
      }
    }

    const cov = augmentedCoverage(rec, fullProdBySku.get(rec.sku));

    rows.push({
      sku: rec.sku,
      name: rec.name,
      toolCode: rec.toolCode,
      machine: rec.machine,
      customer: rec.customer ?? '',
      currentStock: rec.currentStock,
      productionToday,
      shipmentsToday,
      stockFinalToday,
      nextOrderQty,
      nextOrderDeadline,
      coverageDays: cov.coverageDays,
      stockoutDay: cov.stockoutDay,
      riskLevel: classifyStockRisk(cov.stockoutDay, cov.coverageDays),
      ratePerHour: rec.ratePerHour,
    });
  }

  rows.sort((a, b) => a.coverageDays - b.coverageDays);
  return rows;
}

export function computeStockKPIs(rows: StockRow[]): StockKPIs {
  let stockoutCount = 0;
  let riskCount = 0;
  let totalStock = 0;
  let totalCoverage = 0;

  for (const r of rows) {
    if (r.riskLevel === 'stockout') stockoutCount++;
    if (r.riskLevel === 'warning' || r.riskLevel === 'critical') riskCount++;
    totalStock += r.currentStock;
    totalCoverage += r.coverageDays;
  }

  return {
    stockoutCount,
    riskCount,
    totalStock,
    avgCoverage: rows.length > 0 ? totalCoverage / rows.length : 0,
  };
}

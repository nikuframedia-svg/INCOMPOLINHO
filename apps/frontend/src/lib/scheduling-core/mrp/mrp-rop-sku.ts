// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Per-SKU Safety Stock & ROP
//  computeROPSku(): same algorithm as computeROP() but per-SKU
// ═══════════════════════════════════════════════════════════

import type { EngineData } from '../types/engine.js';
import type { MRPResult, ROPSkuResult, ROPSkuSummary, ServiceLevel } from '../types/mrp.js';
import type { ROPConfig } from './mrp-rop.js';
import { DEFAULT_ROP_CONFIG } from './mrp-rop.js';

// ── Z-score mapping ─────────────────────────────────────────

const Z_MAP: Record<ServiceLevel, number> = { 90: 1.28, 95: 1.645, 99: 2.33 };

// ── Main Per-SKU ROP Computation ────────────────────────────

export function computeROPSku(
  mrp: MRPResult,
  _engine: EngineData,
  serviceLevel: ServiceLevel,
  config?: Partial<ROPConfig>,
): ROPSkuSummary {
  const cfg = { ...DEFAULT_ROP_CONFIG, ...config };
  const z = Z_MAP[serviceLevel];

  const records: ROPSkuResult[] = [];

  for (const rec of mrp.records) {
    for (const sr of rec.skuRecords) {
      // Per-SKU daily demands from buckets
      const demands = sr.buckets.map((b) => b.grossRequirement);
      const dAvg = mean(demands);
      const sigma = stddev(demands);
      const cv = dAvg > 0 ? sigma / dAvg : 0;
      const lt = rec.productionLeadDays;
      const ss = z * sigma * Math.sqrt(lt);
      const rop = dAvg * lt + ss;

      const stockProjection = sr.buckets.map((b) => ({
        dayIndex: b.dayIndex,
        projected: b.projectedAvailable,
        ropLine: Math.round(rop),
        ssLine: Math.round(ss),
      }));

      records.push({
        sku: sr.sku,
        name: sr.name,
        opId: sr.opId,
        toolCode: rec.toolCode,
        machine: rec.machine,
        demandAvg: Math.round(dAvg * 10) / 10,
        demandStdDev: Math.round(sigma * 10) / 10,
        coefficientOfVariation: Math.round(cv * 100) / 100,
        leadTimeDays: lt,
        safetyStock: Math.round(ss),
        rop: Math.round(rop),
        serviceLevel,
        zScore: z,
        currentStock: sr.currentStock,
        abcClass: 'C', // assigned below
        xyzClass: cv < cfg.xyzX ? 'X' : cv < cfg.xyzY ? 'Y' : 'Z',
        stockProjection,
      });
    }
  }

  // ABC classification by total volume
  const sorted = [...records].sort((a, b) => b.demandAvg - a.demandAvg);
  const totalVolume = sorted.reduce((s, r) => s + r.demandAvg, 0);
  let cumulative = 0;
  for (const r of sorted) {
    cumulative += r.demandAvg;
    const pct = totalVolume > 0 ? cumulative / totalVolume : 1;
    r.abcClass = pct <= cfg.abcA ? 'A' : pct <= cfg.abcB ? 'B' : 'C';
  }

  const abcDistribution = { A: 0, B: 0, C: 0 };
  const xyzDistribution = { X: 0, Y: 0, Z: 0 };
  for (const r of records) {
    abcDistribution[r.abcClass]++;
    xyzDistribution[r.xyzClass]++;
  }

  return {
    records,
    abcDistribution,
    xyzDistribution,
    skusBelowROP: records.filter((r) => r.currentStock < r.rop).length,
    skusBelowSS: records.filter((r) => r.currentStock < r.safetyStock).length,
  };
}

// ── Statistical helpers ──────────────────────────────────────

function mean(arr: number[]): number {
  if (arr.length === 0) return 0;
  return arr.reduce((s, v) => s + v, 0) / arr.length;
}

function stddev(arr: number[]): number {
  if (arr.length < 2) return 0;
  const m = mean(arr);
  const variance = arr.reduce((s, v) => s + (v - m) ** 2, 0) / (arr.length - 1);
  return Math.sqrt(variance);
}

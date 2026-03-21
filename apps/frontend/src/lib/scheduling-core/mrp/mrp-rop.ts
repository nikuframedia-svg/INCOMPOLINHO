// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Safety Stock & ROP (Reorder Point)
//  computeROP() and computeCoverageMatrix()
//  Extracted from mrp-engine.ts (Incompol)
// ═══════════════════════════════════════════════════════════

import type { EngineData } from '../types/engine.js';
import type {
  CoverageCell,
  CoverageMatrixResult,
  MRPResult,
  ROPResult,
  ROPSummary,
  ServiceLevel,
} from '../types/mrp.js';

// ── Configuration ─────────────────────────────────────────

export interface ROPConfig {
  /** ABC classification thresholds (cumulative % volume) */
  abcA: number; // e.g. 0.80 (top 80% volume = A)
  abcB: number; // e.g. 0.95 (next 15% = B, rest = C)
  /** XYZ classification thresholds (coefficient of variation) */
  xyzX: number; // e.g. 0.50 (CV < 0.5 = X = stable)
  xyzY: number; // e.g. 1.00 (CV < 1.0 = Y = variable)
}

export const DEFAULT_ROP_CONFIG: ROPConfig = {
  abcA: 0.8,
  abcB: 0.95,
  xyzX: 0.5,
  xyzY: 1.0,
};

// ── Z-score mapping ─────────────────────────────────────────

const Z_MAP: Record<ServiceLevel, number> = { 90: 1.28, 95: 1.645, 99: 2.33 };

// ── Main ROP Computation ────────────────────────────────────

export function computeROP(
  mrp: MRPResult,
  engine: EngineData,
  serviceLevel: ServiceLevel,
  config?: Partial<ROPConfig>,
): ROPSummary {
  const cfg = { ...DEFAULT_ROP_CONFIG, ...config };
  const z = Z_MAP[serviceLevel];
  const numDays = engine.dates.length;

  // Aggregate daily demand per tool
  const demandByTool: Record<string, number[]> = {};
  for (const op of engine.ops) {
    if (!demandByTool[op.t]) demandByTool[op.t] = new Array(numDays).fill(0);
    for (let d = 0; d < numDays && d < op.d.length; d++) {
      demandByTool[op.t][d] += op.d[d];
    }
  }

  const records: ROPResult[] = [];
  for (const rec of mrp.records) {
    const demands = demandByTool[rec.toolCode] || new Array(numDays).fill(0);
    const dAvg = mean(demands);
    const sigma = stddev(demands);
    const cv = dAvg > 0 ? sigma / dAvg : 0;
    const lt = rec.productionLeadDays;
    const ss = z * sigma * Math.sqrt(lt);
    const rop = dAvg * lt + ss;

    const stockProjection = rec.buckets.map((b) => ({
      dayIndex: b.dayIndex,
      projected: b.projectedAvailable,
      ropLine: Math.round(rop),
      ssLine: Math.round(ss),
    }));

    records.push({
      toolCode: rec.toolCode,
      demandAvg: Math.round(dAvg * 10) / 10,
      demandStdDev: Math.round(sigma * 10) / 10,
      coefficientOfVariation: Math.round(cv * 100) / 100,
      leadTimeDays: lt,
      safetyStock: Math.round(ss),
      rop: Math.round(rop),
      serviceLevel,
      zScore: z,
      currentStock: rec.currentStock,
      abcClass: 'C', // will be set below
      xyzClass: cv < cfg.xyzX ? 'X' : cv < cfg.xyzY ? 'Y' : 'Z',
      stockProjection,
    });
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
    toolsBelowROP: records.filter((r) => r.currentStock < r.rop).length,
    toolsBelowSS: records.filter((r) => r.currentStock < r.safetyStock).length,
  };
}

// ── Coverage Matrix ─────────────────────────────────────────

export function computeCoverageMatrix(mrp: MRPResult, engine: EngineData): CoverageMatrixResult {
  const numDays = engine.dates.length;
  const sortedRecords = [...mrp.records].sort((a, b) => a.coverageDays - b.coverageDays);

  const tools = sortedRecords.map((r) => ({
    toolCode: r.toolCode,
    machine: r.machine,
    urgencyScore: r.coverageDays,
  }));

  const cells: CoverageCell[][] = [];
  for (const rec of sortedRecords) {
    const avgDailyDemand = rec.totalGrossReq / numDays;
    const row: CoverageCell[] = [];
    for (const bucket of rec.buckets) {
      const dos = avgDailyDemand > 0 ? bucket.projectedAvailable / avgDailyDemand : numDays;
      const band: CoverageCell['colorBand'] =
        dos < 1 ? 'red' : dos < 3 ? 'amber' : dos < 7 ? 'green' : 'blue';
      row.push({
        toolCode: rec.toolCode,
        dayIndex: bucket.dayIndex,
        daysOfSupply: Math.round(dos * 10) / 10,
        colorBand: band,
      });
    }
    cells.push(row);
  }

  return { tools, days: engine.dates, cells };
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

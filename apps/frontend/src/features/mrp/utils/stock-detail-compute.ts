/**
 * stock-detail-compute.ts — Pure computation for StockDetailPage.
 * Builds event list + ECharts data from MRPSkuViewRecord + blocks.
 */

import type { Block, MRPSkuViewRecord } from '@/domain/types/scheduling';

export type StockEventType = 'production' | 'shipment' | 'receipt';

export interface StockEvent {
  dayIndex: number;
  dateLabel: string;
  type: StockEventType;
  qty: number;
  stockAfter: number;
  opId?: string;
  machineId?: string;
}

export interface StockChartData {
  dates: string[];
  projected: number[];
  safetyStock: number | null;
  productions: Array<{ dayIdx: number; qty: number }>;
  shipments: Array<{ dayIdx: number; qty: number }>;
}

export function computeStockEvents(skuRec: MRPSkuViewRecord, blocks: Block[]): StockEvent[] {
  const skuBlocks = blocks.filter((b) => b.sku === skuRec.sku && b.type !== 'blocked');
  const prodByDay = new Map<string, { qty: number; machineId: string }>();
  for (const b of skuBlocks) {
    const key = String(b.dayIdx);
    const prev = prodByDay.get(key);
    prodByDay.set(key, {
      qty: (prev?.qty ?? 0) + b.qty,
      machineId: b.machineId,
    });
  }

  const events: StockEvent[] = [];

  for (const bucket of skuRec.buckets) {
    const prod = prodByDay.get(String(bucket.dayIndex));
    if (prod && prod.qty > 0) {
      events.push({
        dayIndex: bucket.dayIndex,
        dateLabel: bucket.dateLabel,
        type: 'production',
        qty: prod.qty,
        stockAfter: bucket.projectedAvailable,
        machineId: prod.machineId,
      });
    }

    if (bucket.grossRequirement > 0) {
      events.push({
        dayIndex: bucket.dayIndex,
        dateLabel: bucket.dateLabel,
        type: 'shipment',
        qty: bucket.grossRequirement,
        stockAfter: bucket.projectedAvailable,
      });
    }

    if (bucket.scheduledReceipts > 0 && !prod) {
      events.push({
        dayIndex: bucket.dayIndex,
        dateLabel: bucket.dateLabel,
        type: 'receipt',
        qty: bucket.scheduledReceipts,
        stockAfter: bucket.projectedAvailable,
      });
    }
  }

  events.sort((a, b) => a.dayIndex - b.dayIndex || a.type.localeCompare(b.type));
  return events;
}

export function computeStockChartData(
  skuRec: MRPSkuViewRecord,
  blocks: Block[],
  ropSafetyStock?: number,
): StockChartData {
  const dates: string[] = [];
  const projected: number[] = [];
  const productions: StockChartData['productions'] = [];
  const shipments: StockChartData['shipments'] = [];

  const skuBlocks = blocks.filter((b) => b.sku === skuRec.sku && b.type !== 'blocked');
  const prodByDay = new Map<number, number>();
  for (const b of skuBlocks) {
    prodByDay.set(b.dayIdx, (prodByDay.get(b.dayIdx) ?? 0) + b.qty);
  }

  for (const bucket of skuRec.buckets) {
    dates.push(bucket.dateLabel);
    projected.push(bucket.projectedAvailable);

    const dayProd = prodByDay.get(bucket.dayIndex) ?? 0;
    if (dayProd > 0) productions.push({ dayIdx: bucket.dayIndex, qty: dayProd });
    if (bucket.grossRequirement > 0)
      shipments.push({ dayIdx: bucket.dayIndex, qty: bucket.grossRequirement });
  }

  return {
    dates,
    projected,
    safetyStock: ropSafetyStock ?? null,
    productions,
    shipments,
  };
}

export function computeUncertaintyBands(
  projected: number[],
  trustScore: number,
  nDays: number,
): { upper: number[]; lower: number[] } {
  const upper: number[] = [];
  const lower: number[] = [];
  const basePct = 0.1 * (2 - trustScore);

  for (let i = 0; i < projected.length; i++) {
    const horizonFactor = 1 + (i / Math.max(nDays, 1)) * 0.5;
    const pct = Math.min(basePct * horizonFactor, 0.3);
    upper.push(projected[i] * (1 + pct));
    lower.push(Math.max(0, projected[i] * (1 - pct)));
  }

  return { upper, lower };
}

export function computeProjectionConfidence(trustScore: number, coverageDays: number): number {
  let conf = trustScore * 100;
  if (coverageDays < 5) conf -= 20;
  else if (coverageDays < 15) conf -= 10;
  return Math.max(0, Math.min(100, Math.round(conf)));
}

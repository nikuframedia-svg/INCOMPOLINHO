/**
 * orders-compute.ts — Pure computation for OrdersPage.
 * Enriches OrderRiskEntry with deadline, gap, status, and OTD per client.
 */

import type { MRPResult, MRPSkuViewResult } from '@/domain/mrp/mrp-types';
import type { Block, EngineData } from '@/domain/types/scheduling';
import { computeOrderRisk } from './encomendas-compute';

export type OrderStatus = 'on-time' | 'at-risk' | 'late' | 'done';

export interface OrderEntry {
  opId: string;
  sku: string;
  skuName: string;
  toolCode: string;
  machineId: string;
  customerCode: string | null;
  customerName: string | null;
  orderQty: number;
  totalScheduledQty: number;
  shortfallQty: number;
  deadline: string | null;
  deadlineDayIdx: number | null;
  scheduledEndDay: number | null;
  scheduledEndDate: string | null;
  status: OrderStatus;
  gapDays: number;
  isTwin: boolean;
  twinSku: string | null;
  productionDays: Array<{ dayIdx: number; qty: number; machineId: string }>;
}

export interface ClientOrderGroup {
  customerCode: string;
  customerName: string;
  totalOrders: number;
  otdPercent: number;
  lateCount: number;
  atRiskCount: number;
  onTimeCount: number;
  entries: OrderEntry[];
}

function deriveStatus(
  totalScheduledQty: number,
  orderQty: number,
  scheduledEndDay: number | null,
  deadlineDayIdx: number | null,
): OrderStatus {
  if (deadlineDayIdx == null) return 'on-time';
  if (totalScheduledQty >= orderQty && scheduledEndDay != null && scheduledEndDay <= deadlineDayIdx)
    return 'done';
  if (scheduledEndDay == null) return 'late';
  const gap = scheduledEndDay - deadlineDayIdx;
  if (gap <= 0) return 'on-time';
  if (gap <= 2) return 'at-risk';
  return 'late';
}

export function computeOrderEntries(
  engine: EngineData,
  mrp: MRPResult,
  skuView: MRPSkuViewResult,
  blocks: Block[],
): OrderEntry[] {
  const riskEntries = computeOrderRisk(engine, mrp, skuView, blocks);

  return riskEntries.map((e) => {
    const skuRec = skuView.skuRecords.find((r) => r.opId === e.opId);
    let deadlineDayIdx: number | null = null;
    let deadline: string | null = null;

    if (skuRec) {
      for (const bucket of skuRec.buckets) {
        if (bucket.grossRequirement > 0) {
          deadlineDayIdx = bucket.dayIndex;
          deadline = engine.dates[bucket.dayIndex] ?? null;
          break;
        }
      }
    }

    const scheduledEndDay =
      e.productionDays.length > 0 ? Math.max(...e.productionDays.map((p) => p.dayIdx)) : null;
    const scheduledEndDate =
      scheduledEndDay != null ? (engine.dates[scheduledEndDay] ?? null) : null;

    const gapDays =
      scheduledEndDay != null && deadlineDayIdx != null ? scheduledEndDay - deadlineDayIdx : 0;

    const status = deriveStatus(e.totalScheduledQty, e.orderQty, scheduledEndDay, deadlineDayIdx);

    return {
      opId: e.opId,
      sku: e.sku,
      skuName: e.skuName,
      toolCode: e.toolCode,
      machineId: e.machineId,
      customerCode: e.customerCode,
      customerName: e.customerName,
      orderQty: e.orderQty,
      totalScheduledQty: e.totalScheduledQty,
      shortfallQty: e.shortfallQty,
      deadline,
      deadlineDayIdx,
      scheduledEndDay,
      scheduledEndDate,
      status,
      gapDays,
      isTwin: e.isTwin,
      twinSku: e.twinSku,
      productionDays: e.productionDays,
    };
  });
}

export function groupOrdersByClient(entries: OrderEntry[]): ClientOrderGroup[] {
  const map = new Map<string, OrderEntry[]>();
  for (const e of entries) {
    const key = e.customerCode || '__sem_cliente__';
    const list = map.get(key) || [];
    list.push(e);
    map.set(key, list);
  }

  const groups: ClientOrderGroup[] = [];
  for (const [code, groupEntries] of map) {
    const onTime = groupEntries.filter((e) => e.status === 'on-time' || e.status === 'done').length;
    groups.push({
      customerCode: code === '__sem_cliente__' ? '-' : code,
      customerName: groupEntries[0].customerName || 'Sem cliente',
      totalOrders: groupEntries.length,
      otdPercent: groupEntries.length > 0 ? Math.round((onTime / groupEntries.length) * 100) : 100,
      lateCount: groupEntries.filter((e) => e.status === 'late').length,
      atRiskCount: groupEntries.filter((e) => e.status === 'at-risk').length,
      onTimeCount: onTime,
      entries: groupEntries,
    });
  }

  return groups.sort((a, b) => {
    if (a.lateCount !== b.lateCount) return b.lateCount - a.lateCount;
    return a.otdPercent - b.otdPercent;
  });
}

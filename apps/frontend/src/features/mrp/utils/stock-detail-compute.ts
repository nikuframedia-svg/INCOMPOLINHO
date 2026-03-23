/**
 * stock-detail-compute.ts — Pure computation for StockDetailPage.
 * Builds stock projection from REAL scheduler blocks (not MRP infinite capacity).
 */

import type { Block, ClientDemandEntry, EngineData } from '@/domain/types/scheduling';

// ── Types ──

export type StockEventType = 'production' | 'shipment' | 'receipt';

export interface StockEvent {
  dayIndex: number;
  dateLabel: string;
  type: StockEventType;
  qty: number;
  stockAfter: number;
  opId?: string;
  machineId?: string;
  client?: string;
}

export interface StockChartData {
  dates: string[];
  projected: number[];
  safetyStock: number | null;
  productions: Array<{ dayIdx: number; qty: number }>;
  shipments: Array<{ dayIdx: number; qty: number }>;
}

export interface ProductionEntry {
  machine: string;
  qty: number;
  isTwin: boolean;
}

export interface ClientShipment {
  client: string;
  qty: number;
}

export interface StockDayRow {
  dayIdx: number;
  date: string;
  dayName: string;
  isWorkday: boolean;
  opening: number;
  production: ProductionEntry[];
  shipments: ClientShipment[];
  closing: number;
  cumDemand: number;
  cumProd: number;
}

export type SkuStatus = 'stockout' | 'low' | 'ok' | 'high';

export interface SkuSummary {
  opId: string;
  sku: string;
  name: string;
  tool: string;
  machine: string;
  altMachine: string;
  clients: string[];
  totalDemand: number;
  totalProduced: number;
  surplus: number;
  stockoutDay: number | null;
  coverageDays: number;
  status: SkuStatus;
  ecoLot: number;
  pH: number;
}

// ── Core: Real stock projection from blocks ──

export function computeRealStockProjection(
  sku: string,
  blocks: Block[],
  engineData: EngineData,
): StockDayRow[] {
  const op = engineData.ops.find((o) => o.sku === sku);
  if (!op) return [];

  const nDays = engineData.nDays;
  const clientDemands = engineData.clientDemands?.[sku];

  // Build production by day (twin-aware)
  const prodByDay = new Map<number, ProductionEntry[]>();
  for (const b of blocks) {
    if (b.type !== 'ok' || b.qty <= 0) continue;
    // Twin outputs
    if (b.outputs) {
      for (const out of b.outputs) {
        if (out.sku === sku) {
          const arr = prodByDay.get(b.dayIdx) ?? [];
          arr.push({ machine: b.machineId, qty: out.qty, isTwin: true });
          prodByDay.set(b.dayIdx, arr);
        }
      }
    } else if (b.sku === sku) {
      const arr = prodByDay.get(b.dayIdx) ?? [];
      arr.push({ machine: b.machineId, qty: b.qty, isTwin: false });
      prodByDay.set(b.dayIdx, arr);
    }
  }

  const rows: StockDayRow[] = [];
  let running = 0;
  let cumD = 0;
  let cumP = 0;

  for (let d = 0; d < nDays; d++) {
    const date = d < engineData.dates.length ? engineData.dates[d] : `d${d}`;
    const dayName = d < engineData.dnames.length ? engineData.dnames[d] : '';
    const isWorkday = d < engineData.workdays.length ? engineData.workdays[d] : true;

    const opening = running;
    const production = prodByDay.get(d) ?? [];
    const dayProduced = production.reduce((s, p) => s + p.qty, 0);

    // Per-client shipments
    const shipments: ClientShipment[] = [];
    if (clientDemands && clientDemands.length > 0) {
      for (const cd of clientDemands) {
        const qty = d < cd.d.length ? cd.d[d] : 0;
        if (qty > 0) shipments.push({ client: cd.clientName || cd.clientCode, qty });
      }
    } else {
      // Fallback: use merged op.d (single "client")
      const qty = d < op.d.length ? op.d[d] : 0;
      if (qty > 0) shipments.push({ client: op.cl ?? 'Expedição', qty });
    }
    const dayShipped = shipments.reduce((s, sh) => s + sh.qty, 0);

    running = opening + dayProduced - dayShipped;
    cumD += dayShipped;
    cumP += dayProduced;

    rows.push({
      dayIdx: d,
      date,
      dayName,
      isWorkday,
      opening,
      production,
      shipments,
      closing: running,
      cumDemand: cumD,
      cumProd: cumP,
    });
  }
  return rows;
}

// ── SKU summaries for sidebar ──

export function computeSkuSummaries(blocks: Block[], engineData: EngineData): SkuSummary[] {
  // Production per op
  const prodByOp = new Map<string, number>();
  for (const b of blocks) {
    if (b.type !== 'ok' || b.qty <= 0) continue;
    if (b.outputs) {
      for (const out of b.outputs) {
        prodByOp.set(out.opId, (prodByOp.get(out.opId) ?? 0) + out.qty);
      }
    } else {
      prodByOp.set(b.opId, (prodByOp.get(b.opId) ?? 0) + b.qty);
    }
  }

  // Production per day per op (for stockout check)
  const prodDayMap = new Map<string, Map<number, number>>();
  for (const b of blocks) {
    if (b.type !== 'ok' || b.qty <= 0) continue;
    if (b.outputs) {
      for (const out of b.outputs) {
        if (!prodDayMap.has(out.opId)) prodDayMap.set(out.opId, new Map());
        const m = prodDayMap.get(out.opId)!;
        m.set(b.dayIdx, (m.get(b.dayIdx) ?? 0) + out.qty);
      }
    } else {
      if (!prodDayMap.has(b.opId)) prodDayMap.set(b.opId, new Map());
      const m = prodDayMap.get(b.opId)!;
      m.set(b.dayIdx, (m.get(b.dayIdx) ?? 0) + b.qty);
    }
  }

  const summaries: SkuSummary[] = [];

  for (const op of engineData.ops) {
    const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
    const produced = prodByOp.get(op.id) ?? 0;
    const tool = engineData.toolMap[op.t];

    // Stockout check
    let cumD = 0;
    let cumP = 0;
    let stockoutDay: number | null = null;
    let coverageDays = 0;
    const pMap = prodDayMap.get(op.id);

    for (let d = 0; d < engineData.nDays; d++) {
      const demand = d < op.d.length ? Math.max(op.d[d], 0) : 0;
      cumD += demand;
      cumP += pMap?.get(d) ?? 0;
      if (cumP < cumD && stockoutDay === null) stockoutDay = d;
      if (cumP >= cumD && demand > 0) coverageDays = d + 1;
    }

    const ecoLot = tool?.lt ?? 0;
    const clients =
      engineData.clientDemands?.[op.sku]
        ?.map((c) => c.clientName || c.clientCode)
        .filter((v, i, a) => a.indexOf(v) === i) ?? [];
    if (clients.length === 0 && op.cl) clients.push(op.cl);

    let status: SkuStatus = 'ok';
    if (stockoutDay !== null) status = 'stockout';
    else if (produced - totalDemand < ecoLot && totalDemand > 0) status = 'low';
    else if (produced - totalDemand > ecoLot * 3) status = 'high';

    summaries.push({
      opId: op.id,
      sku: op.sku,
      name: op.nm,
      tool: op.t,
      machine: op.m,
      altMachine: tool?.alt && tool.alt !== '-' ? tool.alt : '',
      clients,
      totalDemand,
      totalProduced: produced,
      surplus: produced - totalDemand,
      stockoutDay,
      coverageDays,
      status,
      ecoLot,
      pH: tool?.pH ?? 0,
    });
  }

  summaries.sort((a, b) => {
    const aS = a.stockoutDay ?? 999;
    const bS = b.stockoutDay ?? 999;
    return aS - bS || b.totalDemand - a.totalDemand;
  });
  return summaries;
}

// ── Adapters: projection → chart/events (same shapes as before) ──

export function computeStockChartDataReal(
  rows: StockDayRow[],
  safetyStock?: number,
): StockChartData {
  return {
    dates: rows.map((r) => r.date),
    projected: rows.map((r) => r.closing),
    safetyStock: safetyStock ?? null,
    productions: rows
      .filter((r) => r.production.length > 0)
      .map((r) => ({ dayIdx: r.dayIdx, qty: r.production.reduce((s, p) => s + p.qty, 0) })),
    shipments: rows
      .filter((r) => r.shipments.length > 0)
      .map((r) => ({ dayIdx: r.dayIdx, qty: r.shipments.reduce((s, sh) => s + sh.qty, 0) })),
  };
}

export function computeStockEventsReal(rows: StockDayRow[]): StockEvent[] {
  const events: StockEvent[] = [];
  for (const row of rows) {
    for (const p of row.production) {
      events.push({
        dayIndex: row.dayIdx,
        dateLabel: row.date,
        type: 'production',
        qty: p.qty,
        stockAfter: row.closing,
        machineId: p.machine,
      });
    }
    for (const sh of row.shipments) {
      events.push({
        dayIndex: row.dayIdx,
        dateLabel: row.date,
        type: 'shipment',
        qty: sh.qty,
        stockAfter: row.closing,
        client: sh.client,
      });
    }
  }
  return events;
}

// ── Kept from original ──

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

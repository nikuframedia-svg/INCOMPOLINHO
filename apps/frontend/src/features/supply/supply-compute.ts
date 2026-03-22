/**
 * supply-compute.ts — Supply risk computation logic.
 */

import type {
  ActionMessage,
  EngineData,
  MRPRecord,
  MRPResult,
  RCCPEntry,
  ROPResult,
  ROPSummary,
} from '@/domain/types/scheduling';

export type Risk = 'critical' | 'high' | 'medium' | 'ok';

export interface SupplyRow {
  toolCode: string;
  skus: Array<{ sku: string; name: string }>;
  machine: string;
  altMachine: string | null;
  currentStock: number;
  backlog: number;
  ratePerHour: number;
  coverageDays: number;
  stockoutDay: number | null;
  stockoutDate: string | null;
  totalDemand: number;
  totalPlannedQty: number;
  canMeetDelivery: boolean;
  safetyStock: number;
  rop: number;
  abcClass: 'A' | 'B' | 'C';
  belowROP: boolean;
  belowSS: boolean;
  risk: Risk;
  actions: ActionMessage[];
  dailyProjection: Array<{ day: number; projected: number; ropLine: number; ssLine: number }>;
}

function classifyRisk(rec: MRPRecord, ropRec: ROPResult | null, isOverloaded: boolean): Risk {
  if (rec.stockoutDay !== null && rec.stockoutDay <= 1) return 'critical';
  if (rec.stockoutDay !== null && isOverloaded) return 'critical';
  if (rec.stockoutDay !== null) return 'high';
  if (ropRec && ropRec.currentStock < ropRec.rop) return 'medium';
  if (rec.coverageDays < 3 && rec.totalGrossReq > 0) return 'medium';
  return 'ok';
}

function checkMachineOverloaded(rec: MRPRecord, rccp: RCCPEntry[]): boolean {
  for (const bucket of rec.buckets) {
    if (bucket.plannedOrderRelease > 0) {
      const entry = rccp.find((e) => e.machine === rec.machine && e.dayIndex === bucket.dayIndex);
      if (entry?.overloaded) return true;
    }
  }
  return false;
}

const RISK_ORDER: Record<Risk, number> = { critical: 0, high: 1, medium: 2, ok: 3 };

export function computeSupplyRows(
  mrp: MRPResult,
  rop: ROPSummary,
  actions: ActionMessage[],
  engine: EngineData,
): SupplyRow[] {
  const ropMap: Record<string, ROPResult> = {};
  for (const r of rop.records) ropMap[r.toolCode] = r;

  const actionMap: Record<string, ActionMessage[]> = {};
  for (const a of actions) {
    if (!actionMap[a.toolCode]) actionMap[a.toolCode] = [];
    actionMap[a.toolCode].push(a);
  }

  const rows: SupplyRow[] = [];
  for (const rec of mrp.records) {
    const ropRec = ropMap[rec.toolCode] ?? null;
    const isOverloaded = checkMachineOverloaded(rec, mrp.rccp);
    const risk = classifyRisk(rec, ropRec, isOverloaded);
    const canMeet = rec.stockoutDay === null || !isOverloaded;

    const stockoutDate =
      rec.stockoutDay !== null && engine.dates[rec.stockoutDay]
        ? engine.dates[rec.stockoutDay]
        : null;

    const dailyProjection = rec.buckets.map((b) => ({
      day: b.dayIndex,
      projected: b.projectedAvailable,
      ropLine: ropRec?.rop ?? 0,
      ssLine: ropRec?.safetyStock ?? 0,
    }));

    rows.push({
      toolCode: rec.toolCode,
      skus: rec.skus,
      machine: rec.machine,
      altMachine: rec.altMachine,
      currentStock: rec.currentStock,
      backlog: rec.backlog,
      ratePerHour: rec.ratePerHour,
      coverageDays: rec.coverageDays,
      stockoutDay: rec.stockoutDay,
      stockoutDate,
      totalDemand: rec.totalGrossReq,
      totalPlannedQty: rec.totalPlannedQty,
      canMeetDelivery: canMeet,
      safetyStock: ropRec?.safetyStock ?? 0,
      rop: ropRec?.rop ?? 0,
      abcClass: ropRec?.abcClass ?? 'C',
      belowROP: ropRec ? rec.currentStock < ropRec.rop : false,
      belowSS: ropRec ? rec.currentStock < ropRec.safetyStock : false,
      risk,
      actions: actionMap[rec.toolCode] ?? [],
      dailyProjection,
    });
  }

  rows.sort((a, b) => {
    const rd = RISK_ORDER[a.risk] - RISK_ORDER[b.risk];
    if (rd !== 0) return rd;
    return a.coverageDays - b.coverageDays;
  });

  return rows;
}

export function fmtQty(n: number): string {
  if (n === 0) return '-';
  if (Math.abs(n) >= 10000) return `${(n / 1000).toFixed(0)}K`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(Math.round(n));
}

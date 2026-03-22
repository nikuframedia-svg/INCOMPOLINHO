// ═══════════════════════════════════════════════════════════
//  Plan Diff — Compare two plan versions (PlanVersion → PlanDiff)
//  Pure utility function, no React dependencies.
// ═══════════════════════════════════════════════════════════

import type { Block } from '@/domain/types/scheduling';
import type { PlanVersion } from '../stores/usePlanVersionStore';

export interface PlanDiffKPIs {
  otd: number;
  otdDelivery: number;
  setupCount: number;
  setupMin: number;
  tardinessDays: number;
  balanceScore: number;
  totalProdMin: number;
  setupTotalMin: number;
  capUtil: number;
}

export interface MovedOp {
  opId: string;
  fromM: string;
  toM: string;
  fromDay: number;
  toDay: number;
}

export interface PlanDiff {
  added: number;
  removed: number;
  changed: number;
  moves: string[];
  moved: MovedOp[];
  churn: number;
  summary: string;
  kpiDelta: PlanDiffKPIs;
}

interface OpSummary {
  machineId: string;
  dayIdx: number;
  totalProdMin: number;
  totalSetupMin: number;
  totalQty: number;
}

/** Aggregate blocks per opId: earliest day, total prod/setup minutes */
function summarizeBlocks(blocks: Block[]): Map<string, OpSummary> {
  const map = new Map<string, OpSummary>();
  for (const b of blocks) {
    if (b.type !== 'ok') continue;
    const existing = map.get(b.opId);
    if (existing) {
      existing.totalProdMin += b.prodMin;
      existing.totalSetupMin += b.setupMin;
      existing.totalQty += b.qty;
      if (b.dayIdx < existing.dayIdx) {
        existing.dayIdx = b.dayIdx;
        existing.machineId = b.machineId;
      }
    } else {
      map.set(b.opId, {
        machineId: b.machineId,
        dayIdx: b.dayIdx,
        totalProdMin: b.prodMin,
        totalSetupMin: b.setupMin,
        totalQty: b.qty,
      });
    }
  }
  return map;
}

/** Load balance score: 1 - coefficient of variation of per-machine load (0=unbalanced, 1=perfect) */
function computeBalance(blocks: Block[]): number {
  const loadByMachine: Record<string, number> = {};
  for (const b of blocks) {
    if (b.type !== 'ok') continue;
    loadByMachine[b.machineId] = (loadByMachine[b.machineId] ?? 0) + b.prodMin + b.setupMin;
  }
  const loads = Object.values(loadByMachine);
  if (loads.length === 0) return 0;
  const mean = loads.reduce((a, v) => a + v, 0) / loads.length;
  if (mean === 0) return 1;
  const variance = loads.reduce((s, l) => s + (l - mean) ** 2, 0) / loads.length;
  return Math.max(0, 1 - Math.sqrt(variance) / mean);
}

/** Compute a full diff between two PlanVersion objects */
export function computePlanDiff(vA: PlanVersion, vB: PlanVersion): PlanDiff {
  const mapA = summarizeBlocks(vA.blocks);
  const mapB = summarizeBlocks(vB.blocks);

  let added = 0;
  let removed = 0;
  let changed = 0;
  const moved: MovedOp[] = [];
  let churn = 0;

  // Operations only in B (added)
  for (const [opId] of mapB) {
    if (!mapA.has(opId)) added++;
  }

  // Operations only in A (removed)
  for (const [opId] of mapA) {
    if (!mapB.has(opId)) removed++;
  }

  // Operations in both — check for changes
  for (const [opId, sA] of mapA) {
    const sB = mapB.get(opId);
    if (!sB) continue;
    if (sA.machineId !== sB.machineId || sA.dayIdx !== sB.dayIdx) {
      changed++;
      moved.push({
        opId,
        fromM: sA.machineId,
        toM: sB.machineId,
        fromDay: sA.dayIdx,
        toDay: sB.dayIdx,
      });
      churn += sB.totalProdMin; // displaced production minutes
    }
  }

  // KPI deltas
  const okA = vA.blocks.filter((b) => b.type === 'ok');
  const okB = vB.blocks.filter((b) => b.type === 'ok');
  const totalProdA = okA.reduce((s, b) => s + b.prodMin, 0);
  const totalProdB = okB.reduce((s, b) => s + b.prodMin, 0);
  const totalSetupA = okA.reduce((s, b) => s + b.setupMin, 0);
  const totalSetupB = okB.reduce((s, b) => s + b.setupMin, 0);

  const kpiDelta: PlanDiffKPIs = {
    otd: vB.kpis.otd - vA.kpis.otd,
    otdDelivery: vB.kpis.otdDelivery - vA.kpis.otdDelivery,
    setupCount: vB.kpis.setupCount - vA.kpis.setupCount,
    setupMin: vB.kpis.setupMin - vA.kpis.setupMin,
    tardinessDays: vB.kpis.tardinessDays - vA.kpis.tardinessDays,
    balanceScore: computeBalance(vB.blocks) - computeBalance(vA.blocks),
    totalProdMin: totalProdB - totalProdA,
    setupTotalMin: totalSetupB - totalSetupA,
    capUtil: vB.kpis.capUtil - vA.kpis.capUtil,
  };

  // Summary in Portuguese
  const parts: string[] = [];
  if (moved.length > 0)
    parts.push(
      `${moved.length} op${moved.length > 1 ? 's' : ''} movida${moved.length > 1 ? 's' : ''}`,
    );
  if (added > 0) parts.push(`${added} adicionada${added > 1 ? 's' : ''}`);
  if (removed > 0) parts.push(`${removed} removida${removed > 1 ? 's' : ''}`);
  if (kpiDelta.otd !== 0)
    parts.push(`OTD-D ${kpiDelta.otd > 0 ? '+' : ''}${kpiDelta.otd.toFixed(1)}pp`);
  if (kpiDelta.tardinessDays !== 0) {
    const sign = kpiDelta.tardinessDays < 0 ? '-' : '+';
    parts.push(`tardiness ${sign}${Math.abs(kpiDelta.tardinessDays).toFixed(1)}d`);
  }
  const summary = parts.length > 0 ? parts.join(' · ') : 'Planos idênticos';

  return {
    added,
    removed,
    changed,
    moves: moved.map((m) => m.opId),
    moved,
    churn,
    summary,
    kpiDelta,
  };
}

import type { MRPResult, MRPSkuViewResult } from '@/domain/mrp/mrp-types';
import type { ActionMessage, Block, EngineData } from '@/lib/engine';
import { computeActionMessages, getBlockQtyForOp, getBlocksForOp } from '@/lib/engine';

// ── Types ──────────────────────────────────────────────────

export interface OrderRiskEntry {
  opId: string;
  sku: string;
  skuName: string;
  toolCode: string;
  machineId: string;
  customerCode: string | null;
  customerName: string | null;
  orderQty: number;
  shortfallQty: number;
  coverageDays: number;
  stockoutDay: number | null;
  riskLevel: 'ok' | 'warning' | 'critical';
  isTwin: boolean;
  twinSku: string | null;
  altMachine: string | null;
  productionDays: Array<{ dayIdx: number; qty: number; machineId: string }>;
  totalScheduledQty: number;
  suggestions: ActionMessage[];
}

export interface ClientRiskGroup {
  customerCode: string;
  customerName: string;
  totalOrders: number;
  criticalCount: number;
  warningCount: number;
  totalShortfall: number;
  entries: OrderRiskEntry[];
}

// ── Computation ────────────────────────────────────────────

function computeRiskLevel(
  shortfallQty: number,
  stockoutDay: number | null,
  coverageDays: number,
): 'ok' | 'warning' | 'critical' {
  // Critical: actual unmet demand — production plan doesn't cover
  if (shortfallQty > 0) return 'critical';
  // Warning: production covers it but stock alone doesn't last 3 days
  if (stockoutDay !== null && coverageDays < 3) return 'warning';
  return 'ok';
}

export function computeOrderRisk(
  engine: EngineData,
  mrp: MRPResult,
  skuView: MRPSkuViewResult,
  blocks: Block[],
): OrderRiskEntry[] {
  const actionData = computeActionMessages(mrp, engine);

  return skuView.skuRecords
    .map((record) => {
      // Get scheduled production blocks for this operation
      const opBlocks = getBlocksForOp(blocks, record.opId);
      // Use getBlockQtyForOp to correctly attribute per-SKU qty (twin-aware)
      const productionDays = opBlocks.map((b) => ({
        dayIdx: b.dayIdx,
        qty: getBlockQtyForOp(b, record.opId),
        machineId: b.machineId,
      }));
      const totalScheduledQty = productionDays.reduce((s, p) => s + p.qty, 0);

      // Compute actual deficit: MRP production required minus what's scheduled
      const productionRequired = record.buckets.reduce(
        (s, b) => s + Math.max(0, b.netRequirement),
        0,
      );
      const shortfallQty = Math.max(0, productionRequired - totalScheduledQty);

      // Find matching action messages
      const suggestions = actionData.messages.filter(
        (m) => m.toolCode === record.toolCode && (!m.sku || m.sku === record.sku),
      );

      return {
        opId: record.opId,
        sku: record.sku,
        skuName: record.name,
        toolCode: record.toolCode,
        machineId: record.machine,
        customerCode: record.customer ?? null,
        customerName: record.customerName ?? null,
        orderQty: record.grossRequirement,
        shortfallQty,
        coverageDays: record.coverageDays,
        stockoutDay: record.stockoutDay,
        riskLevel: computeRiskLevel(shortfallQty, record.stockoutDay, record.coverageDays),
        isTwin: record.isTwin,
        twinSku: record.twin ?? null,
        altMachine: record.altMachine,
        productionDays,
        totalScheduledQty,
        suggestions,
      };
    })
    .sort((a, b) => {
      const riskOrder = { critical: 0, warning: 1, ok: 2 };
      const riskDiff = riskOrder[a.riskLevel] - riskOrder[b.riskLevel];
      if (riskDiff !== 0) return riskDiff;
      return a.coverageDays - b.coverageDays;
    });
}

export function groupByClient(entries: OrderRiskEntry[]): ClientRiskGroup[] {
  const map = new Map<string, OrderRiskEntry[]>();

  for (const entry of entries) {
    const key = entry.customerCode || '__sem_cliente__';
    const list = map.get(key) || [];
    list.push(entry);
    map.set(key, list);
  }

  const groups: ClientRiskGroup[] = [];
  for (const [code, groupEntries] of map) {
    groups.push({
      customerCode: code === '__sem_cliente__' ? '-' : code,
      customerName: groupEntries[0].customerName || 'Sem cliente',
      totalOrders: groupEntries.length,
      criticalCount: groupEntries.filter((e) => e.riskLevel === 'critical').length,
      warningCount: groupEntries.filter((e) => e.riskLevel === 'warning').length,
      totalShortfall: groupEntries.reduce((s, e) => s + e.shortfallQty, 0),
      entries: groupEntries,
    });
  }

  // Sort: clients with critical orders first, then by total shortfall
  return groups.sort((a, b) => {
    if (a.criticalCount !== b.criticalCount) return b.criticalCount - a.criticalCount;
    return b.totalShortfall - a.totalShortfall;
  });
}

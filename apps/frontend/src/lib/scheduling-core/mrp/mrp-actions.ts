// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Action Messages & Summary
//  computeActionMessages() and computeSummary() helpers
//  Extracted from mrp-engine.ts (Incompol)
// ═══════════════════════════════════════════════════════════

import type { EngineData } from '../types/engine.js';
import type { ImpactReport } from '../types/failure.js';
import type {
  ActionMessage,
  ActionMessagesSummary,
  ActionSeverity,
  MRPResult,
} from '../types/mrp.js';

// ── Configuration ─────────────────────────────────────────

export interface ActionConfig {
  /** Coverage threshold in days -- below this triggers warnings */
  coverageDays: number;
}

export const DEFAULT_ACTION_CONFIG: ActionConfig = {
  coverageDays: 3,
};

// ── Main Action Messages ────────────────────────────────────

export function computeActionMessages(
  mrp: MRPResult,
  engine: EngineData,
  config?: Partial<ActionConfig>,
): ActionMessagesSummary {
  const cfg = { ...DEFAULT_ACTION_CONFIG, ...config };
  const numDays = engine.dates.length;
  const messages: ActionMessage[] = [];
  let idCounter = 0;

  for (const rec of mrp.records) {
    const hasAlt = rec.altMachine !== null;

    // Type 1: Stockout -> launch POR (per-SKU granularity)
    for (const sr of rec.skuRecords) {
      if (sr.stockoutDay !== null) {
        const skuPlannedQty = sr.buckets.reduce((s, b) => s + b.plannedOrderReceipt, 0);
        const porDay = Math.max(0, sr.stockoutDay - rec.productionLeadDays);
        const score = severityScore('stockout', sr.coverageDays, skuPlannedQty, hasAlt);
        messages.push({
          id: `ACT-${++idCounter}`,
          type: 'launch_por',
          severity: scoreToSeverity(score),
          severityScore: score,
          toolCode: rec.toolCode,
          machine: rec.machine,
          dayIndex: sr.stockoutDay,
          sku: sr.sku,
          skuName: sr.name,
          title: `Lancar POR de ${fmtQ(skuPlannedQty)} pcs (${sr.sku})`,
          description: `${sr.sku} ${sr.name} (${rec.toolCode}/${rec.machine}): stockout dia ${sr.stockoutDay}. Stock ${fmtQ(sr.currentStock)}, backlog ${fmtQ(sr.backlog)}.`,
          suggestedAction: `Lancar POR de ${fmtQ(skuPlannedQty)} pcs para ${sr.sku} (lote ${fmtQ(rec.lotEconomicQty)}) -- release dia ${porDay}`,
          impact: {
            qtyAffected: skuPlannedQty,
            daysAffected: numDays - sr.stockoutDay,
            capacityMinutes: Math.round(
              (skuPlannedQty / rec.ratePerHour) * 60 + rec.setupHours * 60,
            ),
          },
        });
      }
    }

    // Type 2: Low coverage (but no stockout yet) — per-SKU
    for (const sr of rec.skuRecords) {
      if (
        sr.coverageDays < cfg.coverageDays &&
        sr.grossRequirement > 0 &&
        sr.stockoutDay === null
      ) {
        const score = severityScore('low_coverage', sr.coverageDays, sr.grossRequirement, hasAlt);
        messages.push({
          id: `ACT-${++idCounter}`,
          type: 'advance_prod',
          severity: scoreToSeverity(score),
          severityScore: score,
          toolCode: rec.toolCode,
          machine: rec.machine,
          dayIndex: null,
          sku: sr.sku,
          skuName: sr.name,
          title: `Cobertura apenas ${sr.coverageDays.toFixed(1)} dias (${sr.sku})`,
          description: `${sr.sku} ${sr.name} (${rec.toolCode}/${rec.machine}): stock ${fmtQ(sr.currentStock)} cobre apenas ${sr.coverageDays.toFixed(1)} dias.`,
          suggestedAction: `Antecipar producao de ${sr.sku} -- stock actual cobre ${sr.coverageDays.toFixed(1)} dias vs necessidade de ${numDays} dias`,
          impact: {
            qtyAffected: sr.grossRequirement,
            daysAffected: Math.ceil(sr.coverageDays),
            capacityMinutes: null,
          },
        });
      }
    }

    // Type 3: No alternative machine risk
    if (!hasAlt && rec.totalGrossReq > 0) {
      const score = severityScore('no_alt', rec.coverageDays, rec.totalGrossReq, false);
      messages.push({
        id: `ACT-${++idCounter}`,
        type: 'no_alt_risk',
        severity: scoreToSeverity(score),
        severityScore: score,
        toolCode: rec.toolCode,
        machine: rec.machine,
        dayIndex: null,
        title: `Sem maquina alternativa`,
        description: `${rec.toolCode} (${rec.machine}): sem alternativa. Se ${rec.machine} avariar, producao de ${fmtQ(rec.totalGrossReq)} pcs para.`,
        suggestedAction: `Avaliar routing alternativo para ${rec.toolCode} ou criar buffer de stock`,
        impact: {
          qtyAffected: rec.totalGrossReq,
          daysAffected: numDays,
          capacityMinutes: null,
        },
      });
    }
  }

  // Type 4: Overload -> transfer tool to alt machine
  for (const entry of mrp.rccp) {
    if (!entry.overloaded) continue;
    for (const toolCode of entry.plannedTools) {
      const rec = mrp.records.find((r) => r.toolCode === toolCode);
      if (rec?.altMachine) {
        const toolProdMin = Math.round((rec.totalPlannedQty / rec.ratePerHour) * 60);
        const score = severityScore('overload', rec.coverageDays, rec.totalPlannedQty, true);
        messages.push({
          id: `ACT-${++idCounter}`,
          type: 'transfer_tool',
          severity: scoreToSeverity(score),
          severityScore: score,
          toolCode,
          machine: entry.machine,
          dayIndex: entry.dayIndex,
          title: `Transferir ${toolCode} para ${rec.altMachine}`,
          description: `${entry.machine} dia ${entry.dayIndex}: sobrecarga ${(entry.utilization * 100).toFixed(0)}%. Transferir ${toolCode} para ${rec.altMachine} liberta ~${toolProdMin}min.`,
          suggestedAction: `Mover ${toolCode} de ${entry.machine} para ${rec.altMachine} no dia ${entry.dayIndex}`,
          impact: {
            qtyAffected: rec.totalPlannedQty,
            daysAffected: 1,
            capacityMinutes: toolProdMin,
          },
        });
      } else if (rec) {
        const score = severityScore('no_alt', rec.coverageDays, rec.totalPlannedQty, false);
        messages.push({
          id: `ACT-${++idCounter}`,
          type: 'no_alt_risk',
          severity: scoreToSeverity(score),
          severityScore: score,
          toolCode,
          machine: entry.machine,
          dayIndex: entry.dayIndex,
          title: `${toolCode} sobrecarregado sem alternativa`,
          description: `${entry.machine} dia ${entry.dayIndex}: sobrecarga ${(entry.utilization * 100).toFixed(0)}%. Ferramenta ${toolCode} sem maquina alternativa.`,
          suggestedAction: `Avaliar overtime ou redistribuicao de carga para ${entry.machine} no dia ${entry.dayIndex}`,
          impact: {
            qtyAffected: rec.totalPlannedQty,
            daysAffected: 1,
            capacityMinutes: null,
          },
        });
      }
    }
  }

  messages.sort((a, b) => b.severityScore - a.severityScore);

  const bySeverity: Record<ActionSeverity, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  const byType: Record<string, number> = {};
  for (const m of messages) {
    bySeverity[m.severity]++;
    byType[m.type] = (byType[m.type] || 0) + 1;
  }

  return {
    messages,
    bySeverity,
    byType: byType as ActionMessagesSummary['byType'],
    criticalCount: bySeverity.critical,
  };
}

// ── Severity scoring ────────────────────────────────────────

/**
 * Severity scoring heuristic for action message prioritization.
 * Weights (30/25/25/20) are tuning parameters for alert ranking, not from factory data.
 * qtyFactor divisor of 10000 may underweight high-volume Nikufra tools (lot sizes up to 32K).
 */
function severityScore(
  type: 'stockout' | 'overload' | 'low_coverage' | 'no_alt',
  coverageDays: number,
  qty: number,
  hasAlt: boolean,
): number {
  const typeWeight =
    type === 'stockout' ? 1.0 : type === 'overload' ? 0.8 : type === 'low_coverage' ? 0.5 : 0.3;
  const coverageFactor = Math.min(1, Math.max(0, (3 - coverageDays) / 3));
  const qtyFactor = Math.min(1, qty / 40000);
  const altFactor = hasAlt ? 0 : 1;
  return Math.round(typeWeight * 30 + coverageFactor * 25 + qtyFactor * 25 + altFactor * 20);
}

function scoreToSeverity(score: number): ActionSeverity {
  if (score >= 70) return 'critical';
  if (score >= 50) return 'high';
  if (score >= 30) return 'medium';
  return 'low';
}

// ── Helpers ─────────────────────────────────────────────────

function fmtQ(n: number): string {
  if (n === 0) return '0';
  if (n >= 10000) return `${Math.round(n / 1000)}K`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

// ── Failure-specific action messages ────────────────────────

/**
 * Generate action messages from failure impact reports.
 *
 * Produces two types of messages:
 * - `failure_impact`: overall warning per failure event
 * - `failure_reroute`: per-block reroute suggestion for blocks with alternatives
 */
export function computeFailureActionMessages(impacts: ImpactReport[]): ActionMessage[] {
  const messages: ActionMessage[] = [];
  let idCounter = 0;

  for (const impact of impacts) {
    const fe = impact.failureEvent;
    if (impact.summary.totalBlocksAffected === 0) continue;

    // Overall failure impact message
    const sev: ActionSeverity =
      fe.severity === 'total' ? 'critical' : fe.severity === 'partial' ? 'high' : 'medium';
    const score = fe.severity === 'total' ? 90 : fe.severity === 'partial' ? 60 : 40;

    messages.push({
      id: `FAIL-${++idCounter}`,
      type: 'failure_impact',
      severity: sev,
      severityScore: score,
      toolCode: '',
      machine: fe.resourceId,
      dayIndex: fe.startDay,
      title: `Avaria ${fe.severity} em ${fe.resourceId} (dias ${fe.startDay}-${fe.endDay})`,
      description: `${impact.summary.totalBlocksAffected} blocos afectados, ${fmtQ(impact.summary.totalQtyAtRisk)} pcs em risco.`,
      suggestedAction:
        impact.summary.blocksWithAlternative > 0
          ? `Rerotar ${impact.summary.blocksWithAlternative} operacoes para maquinas alternativas`
          : `Sem alternativas disponiveis — ${fmtQ(impact.summary.totalQtyAtRisk)} pcs em perda`,
      impact: {
        qtyAffected: impact.summary.totalQtyAtRisk,
        daysAffected: fe.endDay - fe.startDay + 1,
        capacityMinutes: impact.summary.totalMinutesAtRisk,
      },
    });

    // Per-block reroute suggestions
    for (const ib of impact.impactedBlocks) {
      if (!ib.hasAlternative || !ib.altMachine) continue;
      messages.push({
        id: `FAIL-${++idCounter}`,
        type: 'failure_reroute',
        severity: 'high',
        severityScore: 65,
        toolCode: ib.toolId,
        machine: ib.machineId,
        dayIndex: ib.dayIdx,
        title: `Transferir ${ib.toolId} para ${ib.altMachine}`,
        description: `${ib.sku} (${fmtQ(ib.scheduledQty)} pcs) afectado por avaria em ${fe.resourceId}. Alternativa: ${ib.altMachine}.`,
        suggestedAction: `Mover ${ib.toolId} de ${ib.machineId} para ${ib.altMachine} no dia ${ib.dayIdx}`,
        impact: {
          qtyAffected: ib.qtyAtRisk,
          daysAffected: 1,
          capacityMinutes: ib.minutesAtRisk,
        },
      });
    }
  }

  return messages;
}

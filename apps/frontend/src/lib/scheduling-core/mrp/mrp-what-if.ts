// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — What-If Simulator
//  Scenario mutations: rush orders, machine down, demand factor
//  Extracted from mrp-engine.ts (Incompol)
// ═══════════════════════════════════════════════════════════

import { DAY_CAP } from '../constants.js';
import type { EngineData } from '../types/engine.js';
import type { MRPResult, WhatIfDelta, WhatIfMutation, WhatIfResult } from '../types/mrp.js';
import { computeMRP } from './mrp-engine.js';

/**
 * Compute What-If scenario by applying mutations to engine data
 * and comparing modified MRP against baseline.
 */
export function computeWhatIf(
  engine: EngineData,
  mutations: WhatIfMutation[],
  baseline: MRPResult,
): WhatIfResult {
  let _widCounter = 0;
  const clone: EngineData = JSON.parse(JSON.stringify(engine));
  const numDays = engine.dates.length;
  const capacityOverrides: Record<string, number[]> = {};

  for (const mut of mutations) {
    if (mut.type === 'rush_order' && mut.toolCode && mut.rushQty && mut.rushDay != null) {
      const existingOps = clone.ops.filter((o) => o.t === mut.toolCode);
      if (existingOps.length > 0) {
        const dArr = existingOps[0].d;
        if (mut.rushDay < dArr.length) dArr[mut.rushDay] += mut.rushQty;
      } else {
        const tool = clone.toolMap[mut.toolCode];
        if (tool) {
          const newD = new Array(numDays).fill(0) as number[];
          newD[mut.rushDay] = mut.rushQty;
          clone.ops.push({
            id: `RUSH_${++_widCounter}`,
            t: mut.toolCode,
            m: tool.m,
            sku: 'RUSH',
            nm: 'Rush Order',
            atr: 0,
            d: newD,
          });
        }
      }
    }

    if (mut.type === 'demand_factor' && mut.factor != null) {
      for (const op of clone.ops) {
        if (mut.factorToolCode === '__all__' || op.t === mut.factorToolCode) {
          op.d = op.d.map((v) => Math.round(v * mut.factor!));
        }
      }
    }

    if (
      mut.type === 'machine_down' &&
      mut.machine &&
      mut.downStartDay != null &&
      mut.downEndDay != null
    ) {
      if (!capacityOverrides[mut.machine]) {
        capacityOverrides[mut.machine] = new Array(numDays).fill(DAY_CAP) as number[];
      }
      for (let d = mut.downStartDay; d <= mut.downEndDay && d < numDays; d++) {
        capacityOverrides[mut.machine][d] = 0;
      }
    }

    // Full failure event with severity and capacity factor
    if (mut.type === 'failure_event' && mut.failureEvent) {
      const fe = mut.failureEvent;
      if (fe.resourceType === 'machine') {
        if (!capacityOverrides[fe.resourceId]) {
          capacityOverrides[fe.resourceId] = new Array(numDays).fill(DAY_CAP) as number[];
        }
        const dStart = Math.max(fe.startDay, 0);
        const dEnd = Math.min(fe.endDay, numDays - 1);
        for (let d = dStart; d <= dEnd; d++) {
          capacityOverrides[fe.resourceId][d] = Math.round(DAY_CAP * fe.capacityFactor);
        }
      }
    }
  }

  const hasCO = Object.keys(capacityOverrides).length > 0;
  const modified = computeMRP(clone, hasCO ? capacityOverrides : undefined);

  // Build deltas per tool
  const deltas: WhatIfDelta[] = [];
  for (const br of baseline.records) {
    const mr = modified.records.find((r) => r.toolCode === br.toolCode);
    deltas.push({
      toolCode: br.toolCode,
      baselineStockout: br.stockoutDay,
      modifiedStockout: mr?.stockoutDay ?? null,
      baselineCoverage: br.coverageDays,
      modifiedCoverage: mr?.coverageDays ?? br.coverageDays,
      baselinePlannedQty: br.totalPlannedQty,
      modifiedPlannedQty: mr?.totalPlannedQty ?? 0,
    });
  }
  // Include new tools in modified that don't exist in baseline
  for (const mr of modified.records) {
    if (!baseline.records.find((br) => br.toolCode === mr.toolCode)) {
      deltas.push({
        toolCode: mr.toolCode,
        baselineStockout: null,
        modifiedStockout: mr.stockoutDay,
        baselineCoverage: 0,
        modifiedCoverage: mr.coverageDays,
        baselinePlannedQty: 0,
        modifiedPlannedQty: mr.totalPlannedQty,
      });
    }
  }

  // RCCP deltas
  const rccpDeltas: WhatIfResult['rccpDeltas'] = [];
  for (const be of baseline.rccp) {
    const me = modified.rccp.find((e) => e.machine === be.machine && e.dayIndex === be.dayIndex);
    rccpDeltas.push({
      machine: be.machine,
      dayIndex: be.dayIndex,
      baselineUtil: be.utilization,
      modifiedUtil: me?.utilization ?? 0,
    });
  }

  return {
    baseline,
    modified,
    deltas,
    rccpDeltas,
    summaryDelta: {
      stockoutsChange: modified.summary.toolsWithStockout - baseline.summary.toolsWithStockout,
      avgUtilChange: modified.summary.avgUtilization - baseline.summary.avgUtilization,
    },
  };
}

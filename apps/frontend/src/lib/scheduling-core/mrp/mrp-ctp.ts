// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — CTP Calculator (Capable-to-Promise)
//  Determines if a new order can be fulfilled by a target day
//  Extracted from mrp-engine.ts (Incompol)
// ═══════════════════════════════════════════════════════════

import { DEFAULT_OEE } from '../constants.js';
import type { EngineData } from '../types/engine.js';
import type { CTPInput, CTPResult, MRPResult } from '../types/mrp.js';

/**
 * Compute Capable-to-Promise for a given order.
 *
 * Checks capacity on the primary machine across the planning horizon,
 * finds the earliest day with sufficient capacity, and compares
 * against the requested target day.
 */
export function computeCTP(input: CTPInput, mrp: MRPResult, engine: EngineData): CTPResult {
  const tool = engine.toolMap[input.toolCode];
  const numDays = engine.dates.length;

  if (!tool) {
    return {
      feasible: false,
      toolCode: input.toolCode,
      machine: '?',
      requiredMin: 0,
      availableMinOnDay: 0,
      capacitySlack: 0,
      projectedStockOnDay: 0,
      stockAfterOrder: 0,
      earliestFeasibleDay: null,
      confidence: 'low',
      reason: `Tool ${input.toolCode} not found.`,
      capacityTimeline: [],
    };
  }

  const machineId = tool.m;
  const record = mrp.records.find((r) => r.toolCode === input.toolCode);
  const toolOee = tool.oee ?? DEFAULT_OEE;
  const requiredProdMin = tool.pH > 0 ? ((input.quantity / tool.pH) * 60) / toolOee : 0;
  const requiredSetupMin = tool.sH * 60;
  const totalRequired = requiredProdMin + requiredSetupMin;

  // Build capacity timeline
  const rccpForMachine = mrp.rccp.filter((e) => e.machine === machineId);
  const capacityTimeline: CTPResult['capacityTimeline'] = rccpForMachine.map((e) => ({
    dayIndex: e.dayIndex,
    existingLoad: e.requiredTotalMin,
    newOrderLoad: 0,
    capacity: e.availableMin,
  }));

  // Find earliest feasible day (accumulate capacity across CONSECUTIVE days only)
  let earliestFeasibleDay: number | null = null;
  let accumulated = 0;
  let startDay: number | null = null;
  let prevDay = -2;
  for (let d = 0; d < numDays; d++) {
    const entry = rccpForMachine[d];
    if (!entry) continue;
    const available = entry.availableMin - entry.requiredTotalMin;
    if (available > 0) {
      if (d !== prevDay + 1) {
        // Non-consecutive: reset accumulation (new production run needs new setup)
        accumulated = 0;
        startDay = d;
      }
      if (startDay === null) startDay = d;
      accumulated += available;
      prevDay = d;
      if (accumulated >= totalRequired) {
        earliestFeasibleDay = startDay;
        break;
      }
    } else {
      // Day with no capacity breaks continuity
      accumulated = 0;
      startDay = null;
      prevDay = -2;
    }
  }

  // P10: If primary machine has no capacity, check alternative machine
  let usedAltMachine = false;
  if (earliestFeasibleDay === null && tool.alt && tool.alt !== '-') {
    const altRccp = mrp.rccp.filter((e) => e.machine === tool.alt);
    accumulated = 0;
    startDay = null;
    prevDay = -2;
    for (let d = 0; d < numDays; d++) {
      const entry = altRccp[d];
      if (!entry) continue;
      const available = entry.availableMin - entry.requiredTotalMin;
      if (available > 0) {
        if (d !== prevDay + 1) {
          accumulated = 0;
          startDay = d;
        }
        if (startDay === null) startDay = d;
        accumulated += available;
        prevDay = d;
        if (accumulated >= totalRequired) {
          earliestFeasibleDay = startDay;
          usedAltMachine = true;
          break;
        }
      } else {
        accumulated = 0;
        startDay = null;
        prevDay = -2;
      }
    }
  }

  // Mark the new order load on the feasible day
  if (earliestFeasibleDay !== null && capacityTimeline[earliestFeasibleDay]) {
    capacityTimeline[earliestFeasibleDay].newOrderLoad = Math.round(totalRequired);
  }

  const feasible = earliestFeasibleDay !== null && earliestFeasibleDay <= input.targetDay;
  const targetEntry = rccpForMachine[input.targetDay];
  const availableOnTarget = targetEntry
    ? targetEntry.availableMin - targetEntry.requiredTotalMin
    : 0;
  const slack = targetEntry ? availableOnTarget / targetEntry.availableMin : 0;

  const projStock = record?.buckets[input.targetDay]?.projectedAvailable ?? 0;

  let confidence: CTPResult['confidence'] = 'low';
  if (feasible) {
    const feasSlack = rccpForMachine[earliestFeasibleDay!]
      ? (rccpForMachine[earliestFeasibleDay!].availableMin -
          rccpForMachine[earliestFeasibleDay!].requiredTotalMin -
          totalRequired) /
        rccpForMachine[earliestFeasibleDay!].availableMin
      : 0;
    confidence = feasSlack > 0.3 ? 'high' : feasSlack > 0.1 ? 'medium' : 'low';
  }

  const effectiveMachine = usedAltMachine ? tool.alt! : machineId;
  let reason: string;
  if (feasible) {
    const altNote = usedAltMachine ? ` (maquina alternativa ${tool.alt})` : '';
    reason = `Capacidade disponivel na ${effectiveMachine} dia ${earliestFeasibleDay}${altNote}. Necessario ${Math.round(totalRequired)}min, folga ${(slack * 100).toFixed(0)}%.`;
  } else if (earliestFeasibleDay !== null) {
    reason = `Sem capacidade ate dia ${input.targetDay}. Primeiro dia viavel: ${earliestFeasibleDay} (${engine.dates[earliestFeasibleDay]}).`;
  } else {
    const altNote = tool.alt && tool.alt !== '-' ? ` nem na alternativa ${tool.alt}` : '';
    reason = `Sem capacidade em nenhum dia do horizonte na ${machineId}${altNote}. Necessario ${Math.round(totalRequired)}min.`;
  }

  return {
    feasible,
    toolCode: input.toolCode,
    machine: effectiveMachine,
    requiredMin: Math.round(totalRequired),
    availableMinOnDay: Math.round(Math.max(0, availableOnTarget)),
    capacitySlack: slack,
    projectedStockOnDay: projStock,
    stockAfterOrder: projStock - input.quantity,
    earliestFeasibleDay,
    confidence,
    reason,
    capacityTimeline,
  };
}

/**
 * ctp-compute.ts — Pure computation for CTPPage.
 * 3-scenario CTP simulation + confidence intervals + commitment types.
 */

import type { CTPResult, MRPResult } from '@/domain/mrp/mrp-types';
import type { EngineData } from '@/domain/types/scheduling';
import { computeCTP, computeCTPSku } from '@/utils/mrp-compute-stubs';

export interface CTPScenario {
  id: 'best' | 'tradeoff' | 'infeasible';
  label: string;
  result: CTPResult;
  machine: string;
  dateLabel: string | null;
  isAlt: boolean;
}

export interface CTPConfidenceInterval {
  earliestDate: string;
  latestDate: string;
  confidencePercent: number;
}

export interface CTPCommitment {
  id: string;
  timestamp: number;
  sku: string;
  skuName: string;
  customer: string | null;
  quantity: number;
  promisedDay: number;
  promisedDate: string;
  machine: string;
  confidence: 'high' | 'medium' | 'low';
  confidencePercent: number;
}

export function computeCTPScenarios(
  sku: string,
  qty: number,
  targetDay: number,
  mrp: MRPResult,
  engine: EngineData,
): CTPScenario[] {
  const scenarios: CTPScenario[] = [];

  // Cenário 1: Best case — primary machine, target day
  const best = computeCTPSku({ sku, quantity: qty, targetDay }, mrp, engine);
  if (!best) return scenarios;

  const bestDateLabel =
    best.earliestFeasibleDay != null ? (engine.dates[best.earliestFeasibleDay] ?? null) : null;

  const op = engine.ops.find((o) => o.sku === sku);
  const tool = op ? engine.tools.find((t) => t.id === op.t) : null;
  const primaryMachine = tool?.m ?? best.machine;

  if (best.feasible && best.earliestFeasibleDay != null && best.earliestFeasibleDay <= targetDay) {
    scenarios.push({
      id: 'best',
      label: 'Melhor caso',
      result: best,
      machine: best.machine,
      dateLabel: bestDateLabel,
      isAlt: best.machine !== primaryMachine,
    });
    return scenarios;
  }

  // Best is not ideal — show it and try trade-offs
  scenarios.push({
    id: best.feasible ? 'best' : 'infeasible',
    label: best.feasible ? 'Melhor caso' : 'Inviável — máquina principal',
    result: best,
    machine: best.machine,
    dateLabel: bestDateLabel,
    isAlt: best.machine !== primaryMachine,
  });

  // Cenário 2: Trade-off — try alt machine or extended horizon
  if (tool?.alt && tool.alt !== '-') {
    const altResult = computeCTP({ toolCode: tool.id, quantity: qty, targetDay }, mrp, engine);
    if (altResult && altResult.machine !== primaryMachine && altResult.feasible) {
      const altDate =
        altResult.earliestFeasibleDay != null
          ? (engine.dates[altResult.earliestFeasibleDay] ?? null)
          : null;
      scenarios.push({
        id: 'tradeoff',
        label: 'Com trade-off — máquina alternativa',
        result: altResult,
        machine: altResult.machine,
        dateLabel: altDate,
        isAlt: true,
      });
    }
  }

  // Try extended horizon (+7 days)
  if (
    !best.feasible ||
    (best.earliestFeasibleDay != null && best.earliestFeasibleDay > targetDay)
  ) {
    const extDay = Math.min(targetDay + 7, engine.dates.length - 1);
    if (extDay > targetDay) {
      const extResult = computeCTPSku({ sku, quantity: qty, targetDay: extDay }, mrp, engine);
      if (extResult?.feasible && extResult.earliestFeasibleDay != null) {
        const alreadyHasBetter = scenarios.some(
          (s) =>
            s.id !== 'infeasible' &&
            s.result.earliestFeasibleDay != null &&
            extResult.earliestFeasibleDay != null &&
            s.result.earliestFeasibleDay <= extResult.earliestFeasibleDay,
        );
        if (!alreadyHasBetter) {
          const extDate = engine.dates[extResult.earliestFeasibleDay] ?? null;
          scenarios.push({
            id: 'tradeoff',
            label: 'Com trade-off — horizonte estendido',
            result: extResult,
            machine: extResult.machine,
            dateLabel: extDate,
            isAlt: extResult.machine !== primaryMachine,
          });
        }
      }
    }
  }

  return scenarios;
}

export function computeConfidenceInterval(
  result: CTPResult,
  trustScore: number,
  engine: EngineData,
): CTPConfidenceInterval | null {
  if (!result.feasible || result.earliestFeasibleDay == null) return null;

  const ts = Math.max(trustScore, 0.3);
  const slack = Math.max(result.capacitySlack, 0);
  const buffer = Math.ceil(((1 - slack) * 3) / ts);
  const latestDay = Math.min(result.earliestFeasibleDay + buffer, engine.dates.length - 1);
  const confidencePercent = Math.min(95, Math.round(slack * 60 + ts * 40));

  return {
    earliestDate: engine.dates[result.earliestFeasibleDay] ?? `D${result.earliestFeasibleDay}`,
    latestDate: engine.dates[latestDay] ?? `D${latestDay}`,
    confidencePercent,
  };
}

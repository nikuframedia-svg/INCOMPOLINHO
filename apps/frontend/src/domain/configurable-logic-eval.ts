/**
 * configurable-logic-eval.ts — Pure evaluation functions for L2/L3/L4 configurable logic.
 *
 * No React dependency. Used by useClassifications hook and settings page previews.
 * All functions are deterministic and safe (expr-eval, no eval()).
 */

import { Parser } from 'expr-eval';
import type { RuleGroupType } from 'react-querybuilder';
import type { Block, EngineData, EOp } from '@/domain/types/scheduling';
import type { ConceptDefinition, FormulaConfig } from '../stores/settings-types';

// Singleton parser — avoid re-instantiation per evaluation
const parser = new Parser();

/** Variables available for definition/formula evaluation per operation */
export interface EvalVars {
  completionDay: number;
  deadline: number;
  toleranceHours: number;
  clientTier: number;
  slackHours: number;
  demandTotal: number;
  stock: number;
  load2Shifts: number;
  capacity2Shifts: number;
  pendingOrders: number;
  stressTestOTD: number;
  stressTestCascade: number;
  bufferHours: number;
  violations: number;
  // formula-specific
  slack: number;
  setup: number;
  piecesPerHour: number;
  wip: number;
  deviationHours: number;
  multiplier: number;
  originalPriority: number;
  avgSlack: number;
  otdScore: number;
  cascadeRisk: number;
}

export function defaultTierFromName(name: string): number {
  const n = name.toLowerCase();
  if (n.includes('faurecia') || n.includes('forvia')) return 1;
  if (n.includes('continental') || n.includes('bosch')) return 2;
  if (!name || name === 'Sem cliente') return 5;
  return 3;
}

/** Build evaluation variables from an EOp + EngineData context */
export function buildOpVars(
  op: EOp,
  data: EngineData,
  clientTiers: Record<string, number>,
): EvalVars {
  const tool = data.toolMap[op.t];
  const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
  const ph = tool?.pH ?? 100;
  const nDays = data.nDays;
  const slackHours = Math.max(0, nDays * 17 - totalDemand / (ph * 0.66));
  const tier = (op.cl && clientTiers[op.cl]) || defaultTierFromName(op.clNm || '');

  return {
    completionDay: Math.ceil(totalDemand / (ph * 0.66 * 17)),
    deadline: nDays,
    toleranceHours: 8,
    clientTier: tier,
    slackHours,
    demandTotal: totalDemand,
    stock: op.stk ?? 0,
    load2Shifts: totalDemand / (ph * 0.66),
    capacity2Shifts: nDays * 17,
    pendingOrders: 1,
    stressTestOTD: 0.92,
    stressTestCascade: 2,
    bufferHours: slackHours,
    violations: 0,
    // formula-specific
    slack: slackHours,
    setup: tool?.sH ?? 1,
    piecesPerHour: ph,
    wip: op.wip ?? 0,
    deviationHours: 0,
    multiplier: 3,
    originalPriority: 50,
    avgSlack: nDays * 8,
    otdScore: 0.95,
    cascadeRisk: 2,
  };
}

/** Evaluate a definition expression, return boolean */
export function evaluateDefinition(def: ConceptDefinition, vars: EvalVars): boolean {
  try {
    const expr = parser.parse(def.expression);
    return !!expr.evaluate(vars as unknown as Record<string, number>);
  } catch {
    return false;
  }
}

/** Evaluate a formula expression, return number */
export function evaluateFormula(formula: FormulaConfig, vars: EvalVars): number {
  try {
    const expr = parser.parse(formula.expression);
    return expr.evaluate(vars as unknown as Record<string, number>) ?? 0;
  } catch {
    return 0;
  }
}

/** Evaluate a rule query (react-querybuilder RuleGroupType), return boolean */
export function evaluateRule(group: RuleGroupType, ctx: Record<string, unknown>): boolean {
  const results = (group.rules || []).map((rule) => {
    if ('rules' in rule) return evaluateRule(rule as RuleGroupType, ctx);
    const val = ctx[rule.field];
    const rv = rule.value;
    switch (rule.operator) {
      case '=':
        return String(val) === String(rv);
      case '!=':
        return String(val) !== String(rv);
      case '>':
        return Number(val) > Number(rv);
      case '>=':
        return Number(val) >= Number(rv);
      case '<':
        return Number(val) < Number(rv);
      case '<=':
        return Number(val) <= Number(rv);
      case 'contains':
        return String(val).includes(String(rv));
      case 'beginsWith':
        return String(val).startsWith(String(rv));
      case 'endsWith':
        return String(val).endsWith(String(rv));
      default:
        return false;
    }
  });
  return group.combinator === 'and' ? results.every(Boolean) : results.some(Boolean);
}

/** Build rule context from an EOp (maps to RULE_FIELDS) */
export function buildRuleContext(
  op: EOp,
  data: EngineData,
  clientTiers: Record<string, number>,
): Record<string, unknown> {
  const tool = data.toolMap[op.t];
  const totalDemand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
  const ph = tool?.pH ?? 100;
  const nDays = data.nDays;
  const slackHours = Math.max(0, nDays * 17 - totalDemand / (ph * 0.66));
  const tier = (op.cl && clientTiers[op.cl]) || defaultTierFromName(op.clNm || '');

  return {
    'cliente.tier': tier,
    slack_hours: slackHours,
    'maquina.utilizacao': 0,
    'operacao.ferramenta_familia': op.t.substring(0, 3),
    dia_semana: 'seg',
    turno: 'A',
    stock_final: op.stk ?? 0,
    zona: slackHours < 120 ? 'frozen' : slackHours < 336 ? 'slushy' : 'liquid',
  };
}

/** Block key for classification maps */
export function blockKey(b: Block): string {
  return `${b.opId}-${b.dayIdx}`;
}

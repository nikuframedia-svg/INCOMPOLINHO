import { useMemo } from 'react';

import type {
  Block,
  CoverageAuditResult,
  EngineData,
  EOp,
  ScheduleValidationReport,
} from '../../../lib/engine';
import { auditCoverage, validateSchedule } from '../../../lib/engine';

export interface FeasibilitySummary {
  totalOps: number;
  feasibleOps: number;
  infeasibleOps: number;
  score: number;
  deadlineFeasible: boolean;
}

export interface ScheduleValidationResult {
  validation: ScheduleValidationReport | null;
  audit: CoverageAuditResult | null;
  feasibility: FeasibilitySummary | null;
}

export function useScheduleValidation(
  blocks: Block[],
  allOps: EOp[],
  engineData: EngineData | null,
): ScheduleValidationResult {
  const validation = useMemo(() => {
    if (!engineData) return null;
    return validateSchedule(
      blocks,
      engineData.machines,
      engineData.toolMap,
      allOps,
      engineData.thirdShift,
    );
  }, [blocks, engineData, allOps]);

  const audit = useMemo(() => {
    if (!engineData) return null;
    return auditCoverage(blocks, allOps, engineData.toolMap, engineData.twinGroups);
  }, [blocks, allOps, engineData]);

  const feasibility = useMemo(() => {
    if (!blocks.length || !engineData) return null;
    const okOps = new Set<string>();
    const infOps = new Set<string>();
    for (const b of blocks) {
      if (b.type === 'ok' && b.qty > 0) okOps.add(b.opId);
      if (b.type === 'infeasible' || b.type === 'blocked') infOps.add(b.opId);
    }
    for (const id of okOps) infOps.delete(id);
    const total = okOps.size + infOps.size;
    return {
      totalOps: total,
      feasibleOps: okOps.size,
      infeasibleOps: infOps.size,
      score: total > 0 ? okOps.size / total : 1,
      deadlineFeasible: infOps.size === 0,
    };
  }, [blocks, engineData]);

  return { validation, audit, feasibility };
}

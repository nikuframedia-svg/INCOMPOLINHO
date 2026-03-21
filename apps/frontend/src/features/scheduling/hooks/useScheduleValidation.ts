/**
 * useScheduleValidation — Schedule validation from backend analytics.
 *
 * Uses backendAnalytics.validation and backendAnalytics.coverage
 * instead of calling validateSchedule()/auditCoverage() locally.
 */

import { useMemo } from 'react';
import type {
  Block,
  CoverageAuditResult,
  EngineData,
  EOp,
  ScheduleValidationReport,
} from '../../../lib/engine';
import { useScheduleData } from '../../../hooks/useScheduleData';

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
  _allOps: EOp[],
  engineData: EngineData | null,
): ScheduleValidationResult {
  // Use backend-computed validation and coverage (no local computation)
  const scheduleData = useScheduleData();

  const validation = useMemo(
    () => (scheduleData.validation as ScheduleValidationReport | null) ?? null,
    [scheduleData.validation],
  );

  const audit = useMemo(
    () => (scheduleData.coverageAudit as CoverageAuditResult | null) ?? null,
    [scheduleData.coverageAudit],
  );

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

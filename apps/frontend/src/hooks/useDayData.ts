/**
 * useDayData — Derives day-specific data from useScheduleData().
 *
 * Pure derivation via useMemo — no new engine calls.
 * Consumes selectedDayIdx from useUIStore (persisted).
 */

import { useMemo } from 'react';
import type {
  Block,
  DayLoad,
  DecisionEntry,
  EngineData,
  FailureJustification,
  InfeasibilityEntry,
  OrderJustification,
  ScheduleViolation,
  WorkforceForecast,
  ZoneShiftDemand,
} from '../lib/engine';
import {
  computeWorkforceForecast,
  DAY_CAP,
  DEFAULT_WORKFORCE_CONFIG,
  opsByDayFromWorkforce,
} from '../lib/engine';
import { useUIStore } from '../stores/useUIStore';
import { useScheduleData } from './useScheduleData';

// Re-export OpDay type from lib/engine for consumers
export type { OpDay } from '../lib/engine';

export interface MachineLoad {
  machineId: string;
  area: string;
  load: DayLoad;
  utilization: number;
  blocks: Block[];
}

export interface DayData {
  dayIdx: number;
  date: string;
  dayName: string;
  isWorkday: boolean;

  blocks: Block[];
  okBlocks: Block[];
  overflowBlocks: Block[];
  infeasibleBlocks: Block[];

  machineLoads: MachineLoad[];
  factoryUtil: number;

  totalPcs: number;
  totalOps: number;
  totalSetupMin: number;
  totalProdMin: number;

  workforce: ZoneShiftDemand[];
  operatorsByArea: { pg1: number; pg2: number; total: number };
  operatorCapacity: { pg1: number; pg2: number };

  violations: ScheduleViolation[];
  infeasibilities: InfeasibilityEntry[];

  decisions: DecisionEntry[];
  systemDecisions: DecisionEntry[];

  orderJustifications: OrderJustification[];
  failureJustifications: FailureJustification[];

  d1Forecast: WorkforceForecast | null;

  engine: EngineData;
  nDays: number;
  allDates: string[];
  workdays: boolean[];
}

export interface UseDayDataResult {
  dayData: DayData | null;
  loading: boolean;
  error: string | null;
}

const EMPTY_DAYLOAD: DayLoad = { prod: 0, setup: 0, ops: 0, pcs: 0, blk: 0 };

export function useDayData(): UseDayDataResult {
  const {
    engine,
    blocks: allBlocks,
    cap,
    metrics,
    validation,
    feasibilityReport,
    transparencyReport,
    decisions: allDecisions,
    loading,
    error,
  } = useScheduleData();
  const selectedDayIdx = useUIStore((s) => s.selectedDayIdx);

  const dayData = useMemo((): DayData | null => {
    if (!engine || loading || error) return null;

    const dayIdx = selectedDayIdx;
    const nDays = engine.nDays;

    // Clamp dayIdx to valid range
    const idx = Math.max(0, Math.min(dayIdx, nDays - 1));

    // Identity
    const date = engine.dates[idx] ?? '';
    const dayName = engine.dnames[idx] ?? '';
    const isWorkday = engine.workdays[idx] ?? true;

    // Blocks for this day, split by type
    const blocks = allBlocks.filter((b) => b.dayIdx === idx);
    const okBlocks = blocks.filter((b) => b.type === 'ok');
    const overflowBlocks = blocks.filter((b) => b.type === 'overflow');
    const infeasibleBlocks = blocks.filter((b) => b.type === 'infeasible');

    // Machine loads
    const machineLoads: MachineLoad[] = engine.machines.map((m) => {
      const load = cap[m.id]?.[idx] ?? EMPTY_DAYLOAD;
      const utilization = DAY_CAP > 0 ? (load.prod + load.setup) / DAY_CAP : 0;
      const mBlocks = blocks.filter((b) => b.machineId === m.id);
      return { machineId: m.id, area: m.area, load, utilization, blocks: mBlocks };
    });

    // Factory-wide utilization (average)
    const factoryUtil =
      machineLoads.length > 0
        ? machineLoads.reduce((s, ml) => s + ml.utilization, 0) / machineLoads.length
        : 0;

    // Aggregated KPIs
    let totalPcs = 0,
      totalOps = 0,
      totalSetupMin = 0,
      totalProdMin = 0;
    for (const ml of machineLoads) {
      totalPcs += ml.load.pcs;
      totalOps += ml.load.ops;
      totalSetupMin += ml.load.setup;
      totalProdMin += ml.load.prod;
    }

    // Workforce for this day
    const workforce = metrics?.workforceDemand?.filter((w) => w.dayIdx === idx) ?? [];

    // Operators aggregated via opsByDayFromWorkforce
    const opsByDay = metrics?.workforceDemand
      ? opsByDayFromWorkforce(metrics.workforceDemand, nDays)
      : [];
    const operatorsByArea = opsByDay[idx] ?? { pg1: 0, pg2: 0, total: 0 };

    // Operator capacity from engine.mo
    const operatorCapacity = {
      pg1: engine.mo?.PG1[idx] ?? 3,
      pg2: engine.mo?.PG2[idx] ?? 4,
    };

    // Violations affecting this day
    const violations =
      validation?.violations.filter((v) => v.affectedOps.some((a) => a.dayIdx === idx)) ?? [];

    // Infeasibilities on this day
    const infeasibilities = feasibilityReport?.entries.filter((e) => e.dayIdx === idx) ?? [];

    // Decisions on this day
    const decisions = allDecisions.filter((d) => d.dayIdx === idx);
    const systemDecisions = decisions.filter((d) => d.replanStrategy !== undefined);

    // Transparency — match by opIds of this day's blocks
    const dayOpIds = new Set(blocks.map((b) => b.opId));
    const orderJustifications =
      transparencyReport?.orderJustifications.filter((j) => dayOpIds.has(j.opId)) ?? [];
    const failureJustifications =
      transparencyReport?.failureJustifications.filter((j) => dayOpIds.has(j.opId)) ?? [];

    // D+1 forecast — relative to selected day (idx)
    // Use transparency report cache only for day 0 (it was computed with fromDayIdx=0)
    let d1Forecast: WorkforceForecast | null = null;
    if (transparencyReport?.workforceForecast && idx === 0) {
      d1Forecast = transparencyReport.workforceForecast;
    } else if (allBlocks.length > 0) {
      try {
        d1Forecast = computeWorkforceForecast({
          blocks: allBlocks,
          workforceConfig: engine.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
          workdays: engine.workdays,
          dates: engine.dates,
          toolMap: engine.toolMap,
          fromDayIdx: idx,
        });
      } catch {
        d1Forecast = null;
      }
    }

    return {
      dayIdx: idx,
      date,
      dayName,
      isWorkday,
      blocks,
      okBlocks,
      overflowBlocks,
      infeasibleBlocks,
      machineLoads,
      factoryUtil,
      totalPcs,
      totalOps,
      totalSetupMin,
      totalProdMin,
      workforce,
      operatorsByArea,
      operatorCapacity,
      violations,
      infeasibilities,
      decisions,
      systemDecisions,
      orderJustifications,
      failureJustifications,
      d1Forecast,
      engine,
      nDays,
      allDates: engine.dates,
      workdays: engine.workdays,
    };
  }, [
    engine,
    allBlocks,
    cap,
    metrics,
    validation,
    feasibilityReport,
    transparencyReport,
    allDecisions,
    selectedDayIdx,
    loading,
    error,
  ]);

  return { dayData, loading, error };
}

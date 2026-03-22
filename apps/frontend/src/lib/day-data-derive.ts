/**
 * day-data-derive.ts — Pure day-data derivation logic.
 *
 * Extracted from useDayData to keep the hook thin.
 * Given schedule data + a day index, derives all day-specific views.
 */

import type {
  Block,
  DayLoad,
  DecisionEntry,
  EngineData,
  FailureJustification,
  FeasibilityReport,
  InfeasibilityEntry,
  OptResult,
  OrderJustification,
  ScheduleValidationReport,
  ScheduleViolation,
  TransparencyReport,
  WorkforceForecast,
  ZoneShiftDemand,
} from '@/domain/types/scheduling';
import { DAY_CAP } from '@/domain/types/scheduling/constants';
import { opsByDayFromWorkforce } from '@/utils/workforce';

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

const EMPTY_DAYLOAD: DayLoad = { prod: 0, setup: 0, ops: 0, pcs: 0, blk: 0 };

export interface DeriveDayDataInput {
  engine: EngineData;
  allBlocks: Block[];
  cap: Record<string, DayLoad[]>;
  metrics: (OptResult & { blocks: Block[] }) | null;
  validation: ScheduleValidationReport | null;
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  allDecisions: DecisionEntry[];
  selectedDayIdx: number;
}

export function deriveDayData(input: DeriveDayDataInput): DayData {
  const {
    engine,
    allBlocks,
    cap,
    metrics,
    validation,
    feasibilityReport,
    transparencyReport,
    allDecisions,
    selectedDayIdx,
  } = input;

  const nDays = engine.nDays;
  const idx = Math.max(0, Math.min(selectedDayIdx, nDays - 1));

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

  // D+1 forecast — from backend analytics (no local computation)
  const d1Forecast: WorkforceForecast | null = transparencyReport?.workforceForecast ?? null;

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
}

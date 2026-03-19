/**
 * solver-bridge.ts — Transform between EngineData and SolverRequest/Result.
 *
 * engineDataToSolverRequest: EngineData → SolverRequest (for backend CP-SAT)
 * solverResultToBlocks: SolverResult → Block[] (for Gantt display)
 */

import type { Block, EMachine, EngineData, EOp, ETool } from '../../../lib/engine';
import { DAY_CAP, DEFAULT_OEE, S0, T1 } from '../../../lib/engine';
import type {
  ConstraintConfigInput,
  JobInput,
  MachineInput,
  ScheduledOp,
  SolverConfig,
  SolverRequest,
  SolverResult,
  TwinPairInput,
} from './solverApi';

// ── EngineData → SolverRequest ──

interface SolverBridgeConfig {
  oee: number;
  timeLimit: number;
  objective: 'makespan' | 'tardiness' | 'weighted_tardiness';
}

/**
 * Build workday mapping from boolean array.
 * Returns: workdayIndices (calendar days that are workdays),
 *          calToWork (calendar day → workday index, -1 if weekend).
 */
function buildWorkdayMap(
  workdays: boolean[] | undefined,
  nDays: number,
  preStartDays: number,
): { workdayIndices: number[]; calToWork: number[] } {
  // Build full calendar including pre-start days before ISOP
  const totalDays = preStartDays + nDays;
  const workdayIndices: number[] = [];
  const calToWork: number[] = new Array(totalDays).fill(-1);

  for (let cal = 0; cal < totalDays; cal++) {
    // Pre-start days (cal < preStartDays): treat as workdays
    // ISOP days (cal >= preStartDays): use workdays[] if available
    const isopDay = cal - preStartDays;
    const isWorkday =
      cal < preStartDays
        ? true // pre-start = always workday (Mon-Fri assumed)
        : workdays && isopDay < workdays.length
          ? workdays[isopDay]
          : true;

    if (isWorkday) {
      calToWork[cal] = workdayIndices.length;
      workdayIndices.push(cal);
    }
  }

  return { workdayIndices, calToWork };
}

export function engineDataToSolverRequest(
  data: EngineData,
  cfg: SolverBridgeConfig,
): SolverRequest {
  const oee = cfg.oee || DEFAULT_OEE;
  const PRE_START_DAYS = data._preStartDays ?? 5;

  // Build workday mapping (calendar → workday index)
  const { workdayIndices, calToWork } = buildWorkdayMap(data.workdays, data.nDays, PRE_START_DAYS);

  const jobs: JobInput[] = [];
  const machineSet = new Set<string>();

  // ── FINAL-02: Twin pre-merge ──
  // Merge twin pairs BEFORE creating jobs. One merged job per twin pair per day.
  // qty = max(A, B), duration = max(durA, durB), setup = 1× (shared).
  const twinMergedKeys = new Set<string>(); // "opId:dayIdx" keys already merged
  const twinGroups = data.twinGroups ?? [];

  // Build op lookup for twin merge
  const opById = new Map<string, EOp>();
  for (const op of data.ops) opById.set(op.id, op);

  for (const tg of twinGroups) {
    const opA = opById.get(tg.opId1);
    const opB = opById.get(tg.opId2);
    if (!opA || !opB) continue;

    const tool = data.toolMap[opA.t];
    if (!tool) continue;

    const toolOee = tool.oee ?? oee;
    const pH = tool.pH;
    if (pH <= 0) continue;

    machineSet.add(tg.machine);

    // Collect demand days for both twins (cross-EDD pairing: pair 1st-1st, 2nd-2nd)
    const daysA: Array<{ day: number; qty: number }> = [];
    const daysB: Array<{ day: number; qty: number }> = [];
    for (let d = 0; d < Math.max(opA.d.length, opB.d.length); d++) {
      if (d < opA.d.length && opA.d[d] > 0) daysA.push({ day: d, qty: opA.d[d] });
      if (d < opB.d.length && opB.d[d] > 0) daysB.push({ day: d, qty: opB.d[d] });
    }
    // Sort by day (already sorted since we iterate ascending)

    // Pair sequentially: 1st A with 1st B, 2nd A with 2nd B
    const nPairs = Math.min(daysA.length, daysB.length);
    for (let i = 0; i < nPairs; i++) {
      const a = daysA[i];
      const b = daysB[i];
      const mergedQty = Math.max(a.qty, b.qty);
      const mergedDur = Math.ceil((mergedQty / (pH * toolOee)) * 60);
      const setupMin = Math.round(tool.sH * 60);
      const mergedEdd = Math.min(a.day, b.day); // earliest deadline

      const calDay = mergedEdd + PRE_START_DAYS;
      const workdayIdx =
        calToWork[calDay] ??
        calToWork
          .slice()
          .reverse()
          .find((w: number) => w >= 0) ??
        0;
      const dueDateMin = (workdayIdx + 1) * DAY_CAP;

      const jobId = `twin_${tg.opId1}_${tg.opId2}_d${mergedEdd}`;
      jobs.push({
        id: jobId,
        sku: `${opA.sku}+${opB.sku}`,
        due_date_min: dueDateMin,
        weight: 10.0, // twin pairs are important
        operations: [
          {
            id: jobId,
            machine_id: tg.machine,
            tool_id: tg.tool,
            duration_min: mergedDur,
            setup_min: setupMin,
            operators: tool.op,
            calco_code: tool.calco ?? null,
          },
        ],
      });

      // Mark both ops+days as merged (skip in main loop)
      twinMergedKeys.add(`${tg.opId1}:${a.day}`);
      twinMergedKeys.add(`${tg.opId2}:${b.day}`);
    }

    // Unpaired remainder: handled by main loop (not merged)
  }

  // ── Main job creation loop (skip twin-merged demand) ──
  for (const op of data.ops) {
    const tool = data.toolMap[op.t];
    if (!tool) continue;

    const toolOee = tool.oee ?? oee;
    const pH = tool.pH;
    if (pH <= 0) continue;

    machineSet.add(op.m);

    for (let dayIdx = 0; dayIdx < op.d.length; dayIdx++) {
      const qty = op.d[dayIdx];
      if (qty <= 0) continue;

      // Skip if this demand was already merged as a twin pair
      if (twinMergedKeys.has(`${op.id}:${dayIdx}`)) continue;

      const setupMin = Math.round(tool.sH * 60);

      // Map ISOP calendar day to solver workday-indexed time
      const calDay = dayIdx + PRE_START_DAYS;
      const workdayIdx =
        calToWork[calDay] ??
        calToWork
          .slice()
          .reverse()
          .find((w: number) => w >= 0) ??
        0;
      const dueDateMin = (workdayIdx + 1) * DAY_CAP;
      const ecoLot = tool.lt ?? 0;

      // SAT-02: Economic lot — 2-job approach
      if (ecoLot > 0 && qty < ecoLot) {
        const reqId = `${op.id}_d${dayIdx}_req`;
        const reqDur = Math.ceil((qty / (pH * toolOee)) * 60);
        jobs.push({
          id: reqId,
          sku: op.sku,
          due_date_min: dueDateMin,
          weight: 100.0,
          operations: [
            {
              id: reqId,
              machine_id: op.m,
              tool_id: op.t,
              duration_min: reqDur,
              setup_min: setupMin,
              operators: tool.op,
              calco_code: tool.calco ?? null,
            },
          ],
        });

        const lotExtra = ecoLot - qty;
        const lotId = `${op.id}_d${dayIdx}_lot`;
        const lotDur = Math.ceil((lotExtra / (pH * toolOee)) * 60);
        jobs.push({
          id: lotId,
          sku: op.sku,
          due_date_min: dueDateMin,
          weight: 1.0,
          operations: [
            {
              id: lotId,
              machine_id: op.m,
              tool_id: op.t,
              duration_min: lotDur,
              setup_min: 0,
              operators: tool.op,
              calco_code: tool.calco ?? null,
            },
          ],
        });
      } else {
        const jobId = `${op.id}_d${dayIdx}`;
        const durationMin = Math.ceil((qty / (pH * toolOee)) * 60);

        jobs.push({
          id: jobId,
          sku: op.sku,
          due_date_min: dueDateMin,
          weight: 1.0,
          operations: [
            {
              id: jobId,
              machine_id: op.m,
              tool_id: op.t,
              duration_min: durationMin,
              setup_min: setupMin,
              operators: tool.op,
              calco_code: tool.calco ?? null,
            },
          ],
        });
      }
    }
  }

  // Machines
  const machines: MachineInput[] = data.machines
    .filter((m: EMachine) => machineSet.has(m.id))
    .map((m: EMachine) => ({ id: m.id, capacity_min: DAY_CAP }));

  // Twin pairs — empty since we pre-merged (no solver constraint needed)
  const twinPairs: TwinPairInput[] = [];

  // Constraints (all enabled except operator pool)
  const constraints: ConstraintConfigInput = {
    setup_crew: true,
    tool_timeline: true,
    calco_timeline: true,
    operator_pool: false,
  };

  const solverConfig: SolverConfig = {
    time_limit_s: cfg.timeLimit,
    objective: cfg.objective,
    num_workers: 4,
  };

  return {
    jobs,
    machines,
    config: solverConfig,
    twin_pairs: twinPairs,
    constraints,
    workdays: workdayIndices,
  };
}

// ── SolverResult → Block[] ──

export function solverResultToBlocks(result: SolverResult, data: EngineData): Block[] {
  const PRE_START_DAYS = data._preStartDays ?? 5;

  // Build workday mapping for reverse translation (solver day → calendar day)
  const { workdayIndices } = buildWorkdayMap(data.workdays, data.nDays, PRE_START_DAYS);

  // Build lookup maps
  const opMap = new Map<string, EOp>();
  for (const op of data.ops) {
    opMap.set(op.id, op);
  }

  const blocks: Block[] = [];

  for (const sop of result.schedule) {
    // Handle merged twin jobs: "twin_{opId1}_{opId2}_d{day}"
    const twinMatch = sop.op_id.match(/^twin_(.+?)_(.+?)_d(\d+)$/);
    if (twinMatch) {
      const [, opId1, opId2, dayStr] = twinMatch;
      const eddDay = parseInt(dayStr, 10);
      // Create 2 blocks — one for each twin member
      for (const twinOpId of [opId1, opId2]) {
        const op = opMap.get(twinOpId);
        if (!op) continue;
        const tool = data.toolMap[op.t];
        if (!tool) continue;

        const block = sopToBlock(sop, op, tool, eddDay, PRE_START_DAYS, workdayIndices);
        block.isTwinProduction = true;
        block.coProductionGroupId = `twin_${[opId1, opId2].sort().join('_')}`;
        blocks.push(block);
      }
      continue;
    }

    // Normal/eco-lot jobs: "OP01_d3" or "OP01_d3_req"/"OP01_d3_lot"
    const match = sop.op_id.match(/^(.+)_d(\d+)(?:_(?:req|lot))?$/);
    if (!match) continue;

    const [, origOpId, dayIdxStr] = match;
    const eddDay = parseInt(dayIdxStr, 10);
    const op = opMap.get(origOpId);
    if (!op) continue;

    const tool = data.toolMap[op.t];
    if (!tool) continue;

    const block = sopToBlock(sop, op, tool, eddDay, PRE_START_DAYS, workdayIndices);
    blocks.push(block);
  }

  // Sort by machine + start
  blocks.sort((a, b) => a.machineId.localeCompare(b.machineId) || a.startMin - b.startMin);
  return blocks;
}

function sopToBlock(
  sop: ScheduledOp,
  op: EOp,
  tool: ETool,
  eddDay: number,
  preStartDays: number,
  workdayIndices?: number[],
): Block {
  // Map solver workday index back to ISOP calendar day
  const solverDay = Math.floor(sop.start_min / DAY_CAP);
  let dayIdx: number;
  if (workdayIndices && workdayIndices.length > 0) {
    // workdayIndices[solverDay] = calendar day (including pre-start offset)
    const calDay = solverDay < workdayIndices.length ? workdayIndices[solverDay] : solverDay;
    dayIdx = calDay - preStartDays; // convert to ISOP day (can be < 0 for pre-start)
  } else {
    dayIdx = solverDay - preStartDays;
  }
  const startInDay = (sop.start_min % DAY_CAP) + S0;
  const shift: 'X' | 'Y' | 'Z' = startInDay < T1 ? 'X' : 'Y';

  // Calculate qty from duration
  const oee = tool.oee ?? DEFAULT_OEE;
  const prodMin = sop.end_min - sop.start_min - sop.setup_min;
  const qty = Math.round((prodMin / 60) * tool.pH * oee);

  const isPreStart = dayIdx < 0;

  return {
    opId: op.id,
    toolId: op.t,
    sku: op.sku,
    nm: op.nm,
    machineId: sop.machine_id,
    origM: op.m,
    dayIdx,
    eddDay,
    qty,
    prodMin: Math.max(prodMin, 0),
    setupMin: sop.setup_min,
    operators: tool.op,
    blocked: false,
    reason: null,
    moved: sop.machine_id !== op.m,
    hasAlt: tool.alt !== '-',
    altM: tool.alt !== '-' ? tool.alt : null,
    stk: tool.stk,
    lt: tool.lt,
    atr: op.atr,
    startMin: sop.start_min,
    endMin: sop.end_min,
    setupS: sop.setup_min > 0 ? sop.start_min : null,
    setupE: sop.setup_min > 0 ? sop.start_min + sop.setup_min : null,
    type: sop.is_tardy ? 'overflow' : 'ok',
    shift,
    isTwinProduction: sop.is_twin_production,
    coProductionGroupId: sop.twin_partner_op_id
      ? `twin_${[op.id, sop.twin_partner_op_id].sort().join('_')}`
      : undefined,
    ...(isPreStart
      ? {
          preStart: true,
          preStartReason: `Producao antecipada ${Math.abs(dayIdx)} dia(s) antes do ISOP`,
        }
      : {}),
  };
}

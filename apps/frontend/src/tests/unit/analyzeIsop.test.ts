/**
 * analyze-isop.ts — Programmatic ISOP data analysis
 *
 * Runs the FULL pipeline outside the browser:
 *   Parse ISOP → Merge bdmestre → Transform → Schedule → KPIs → MRP → Supply
 *
 * Usage: cd frontend && npx vitest run scripts/analyze-isop.ts
 * Uses vitest to handle CSS imports from NikufraEngine.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it } from 'vitest';

import { parseISOPFile } from '../../domain/isop';
import type { NikufraData } from '../../domain/nikufra-types';
import type { DayLoad } from '../../lib/engine';
import {
  autoRouteOverflow,
  capAnalysis,
  computeActionMessages,
  computeMRP,
  computeROP,
  computeSupplyPriority,
  DAY_CAP,
  DEFAULT_WORKFORCE_CONFIG,
  scoreSchedule,
  transformPlanState,
  validateSchedule,
} from '../../lib/engine';

// ── Paths ──

const cwd = process.cwd();
const base = cwd.endsWith('frontend') ? cwd : join(cwd, 'frontend');
const isopPath = join(base, 'src', 'tests', 'fixtures', 'ISOP_Nikufra_27_2.xlsx');
const fixturePath = join(base, 'public', 'fixtures', 'nikufra', 'nikufra_data.json');

// ── Helpers ──

function line(ch = '─', len = 60): string {
  return ch.repeat(len);
}
function header(title: string): void {
  console.log(`\n${line('═')}\n  ${title}\n${line('═')}`);
}
function section(title: string): void {
  console.log(`\n${line()}\n  ${title}\n${line()}`);
}

function mergeWithMasterData(data: NikufraData, fixture: NikufraData): NikufraData {
  const fixToolMap = new Map(fixture.tools.map((t) => [t.id, t]));

  const mergedTools = data.tools.map((tool) => {
    const fix = fixToolMap.get(tool.id);
    if (!fix) return tool;
    const newS = tool.s > 0 ? tool.s : fix.s;
    const newAlt = tool.alt !== '-' ? tool.alt : fix.alt;
    return { ...tool, s: newS, alt: newAlt };
  });

  const toolLookup = new Map(mergedTools.map((t) => [t.id, t]));
  const mergedOps = data.operations.map((op) => {
    const tool = toolLookup.get(op.t);
    if (!tool) return op;
    return { ...op, s: op.s > 0 ? op.s : tool.s };
  });

  const parsedMoEmpty = !data.mo || data.mo.PG1.length === 0 || data.mo.PG1.every((v) => v === 0);
  const mergedMo = parsedMoEmpty && fixture.mo ? fixture.mo : data.mo;

  return { ...data, tools: mergedTools, operations: mergedOps, mo: mergedMo };
}

// ── Analysis (runs as a vitest test so CSS imports work) ──

describe('ISOP Full Pipeline Analysis', () => {
  it('runs complete analysis', () => {
    header('ISOP DATA ANALYSIS REPORT');
    console.log(`  File: ${isopPath}`);
    console.log(`  Date: ${new Date().toISOString()}`);

    // 1. Parse ISOP
    section('1. PARSING');

    const buf = readFileSync(isopPath);
    const ab = new ArrayBuffer(buf.length);
    const view = new Uint8Array(ab);
    for (let i = 0; i < buf.length; i++) view[i] = buf[i];

    const parseResult = parseISOPFile(ab);
    if (!parseResult.success) {
      console.error('  PARSE FAILED:', parseResult.errors.join('\n  '));
      return;
    }

    const { data, meta } = parseResult;
    console.log(`  Operations:    ${meta.rows}`);
    console.log(`  Machines:      ${meta.machines} (${data.machines.map((m) => m.id).join(', ')})`);
    console.log(`  Tools:         ${meta.tools}`);
    console.log(`  SKUs:          ${meta.skus}`);
    console.log(`  Customers:     ${data.customers?.length ?? 0}`);
    console.log(
      `  Dates:         ${meta.dates} (${data.dates[0]} — ${data.dates[data.dates.length - 1]})`,
    );
    console.log(`  Workdays:      ${meta.workdays}`);
    console.log(`  Trust Score:   ${(meta.trustScore * 100).toFixed(1)}%`);

    if (meta.warnings.length > 0) {
      console.log(`\n  Warnings (${meta.warnings.length}):`);
      for (const w of meta.warnings.slice(0, 10)) {
        console.log(`    - ${w}`);
      }
      if (meta.warnings.length > 10) console.log(`    ... +${meta.warnings.length - 10} more`);
    }

    // 2. Merge with master data
    section('2. MASTER DATA MERGE');

    const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8')) as NikufraData;
    const fixtureToolIds = new Set(fixture.tools.map((t) => t.id));
    const merged = mergeWithMasterData(data, fixture);

    const toolsWithSetup = merged.tools.filter((t) => fixtureToolIds.has(t.id) && t.s > 0);
    const toolsWithAlt = merged.tools.filter((t) => t.alt !== '-');
    const unknownTools = merged.tools.filter((t) => !fixtureToolIds.has(t.id));

    console.log(`  Setup times enriched:   ${toolsWithSetup.length} tools`);
    console.log(`  Alt machines enriched:   ${toolsWithAlt.length} tools`);
    console.log(
      `  Tools NOT in fixture:    ${unknownTools.length}${unknownTools.length > 0 ? ` (${unknownTools.map((t) => t.id).join(', ')})` : ''}`,
    );
    console.log(
      `  MO enriched:            ${merged.mo.PG1.length > 0 ? 'Yes' : 'No'} (PG1: ${merged.mo.PG1.length} days, PG2: ${merged.mo.PG2.length} days)`,
    );

    // 3. Demand distribution
    section('3. DEMAND DISTRIBUTION');

    let totalDemand = 0;
    let totalBacklog = 0;
    const demandByMachine: Record<string, { demand: number; ops: number; backlog: number }> = {};

    for (const op of merged.operations) {
      const dSum = op.d.reduce<number>((a, b) => a + (b ?? 0), 0);
      totalDemand += dSum;
      totalBacklog += Math.max(0, op.atr);

      if (!demandByMachine[op.m]) demandByMachine[op.m] = { demand: 0, ops: 0, backlog: 0 };
      demandByMachine[op.m].demand += dSum;
      demandByMachine[op.m].ops++;
      demandByMachine[op.m].backlog += Math.max(0, op.atr);
    }

    const opsWithDemand = merged.operations.filter((op) =>
      op.d.some((v) => v !== null && v < 0),
    ).length;
    const opsWithBacklog = merged.operations.filter((op) => op.atr > 0).length;

    console.log(`  Total demand (all ops):   ${totalDemand.toLocaleString()} pcs`);
    console.log(`  Total backlog:            ${totalBacklog.toLocaleString()} pcs`);
    console.log(`  Ops with demand > 0:      ${opsWithDemand} / ${merged.operations.length}`);
    console.log(`  Ops with backlog > 0:     ${opsWithBacklog} / ${merged.operations.length}`);
    console.log(`\n  Demand by machine:`);
    for (const [mId, info] of Object.entries(demandByMachine).sort(
      (a, b) => b[1].demand - a[1].demand,
    )) {
      console.log(
        `    ${mId}: ${info.demand.toLocaleString()} pcs (${info.ops} ops, backlog: ${info.backlog.toLocaleString()})`,
      );
    }

    // 4. Transform and Schedule
    section('4. SCHEDULING');

    const planState = {
      dates: merged.dates,
      days_label: merged.days_label,
      machines: merged.machines.map((m) => ({
        id: m.id,
        area: m.area as 'PG1' | 'PG2',
        man_minutes: m.man,
      })),
      tools: merged.tools.map((t) => ({
        id: t.id,
        machine: t.m,
        alt_machine: t.alt,
        setup_hours: t.s,
        pcs_per_hour: t.pH,
        operators: t.op,
        skus: t.skus,
        names: t.nm,
        lot_economic_qty: t.lt,
        stock: t.stk,
        wip: t.wip,
      })),
      operations: merged.operations.map((op) => ({
        id: op.id,
        machine: op.m,
        tool: op.t,
        sku: op.sku,
        name: op.nm,
        pcs_per_hour: op.pH,
        atraso: op.atr,
        daily_qty: op.d,
        setup_hours: op.s,
        operators: op.op,
        stock: 0,
        status: 'PLANNED' as const,
        customer_code: op.cl,
        customer_name: op.clNm,
        parent_sku: op.pa,
        wip: op.wip,
        qtd_exp: op.qe,
        lead_time_days: op.ltDays,
        twin: op.twin,
      })),
      schedule: [],
      machine_loads: [],
      kpis: null,
      parsed_at: new Date().toISOString(),
      data_hash: null,
      mo: merged.mo ? { PG1: merged.mo.PG1, PG2: merged.mo.PG2 } : undefined,
      workday_flags: merged.workday_flags,
    };

    const engineData = transformPlanState(planState);

    // Compute MRP for supply priority
    const mrp = computeMRP(engineData);
    const supplyBoosts = computeSupplyPriority(engineData, mrp);

    const mSt: Record<string, string> = Object.fromEntries(
      engineData.machines.map((m) => [m.id, 'running']),
    );
    const nDays = engineData.ops[0]?.d.length ?? 80;
    const schedResult = autoRouteOverflow({
      ops: engineData.ops,
      mSt,
      tSt: {},
      userMoves: [],
      machines: engineData.machines,
      toolMap: engineData.toolMap,
      workdays: engineData.workdays,
      nDays,
      rule: 'EDD',
      supplyBoosts: supplyBoosts.size > 0 ? supplyBoosts : undefined,
    });
    const blocks = schedResult.blocks;
    const autoMoves = schedResult.autoMoves;

    const okBlocks = blocks.filter((b) => b.type === 'ok');
    const setupBlocks = blocks.filter((b) => b.setupMin > 0 && b.type === 'ok');
    const blocksByMachine: Record<string, number> = {};
    for (const b of blocks) {
      blocksByMachine[b.machineId] = (blocksByMachine[b.machineId] || 0) + 1;
    }

    console.log(
      `  Engine: ${engineData.ops.length} ops, ${engineData.machines.length} machines, ${engineData.dates.length} days`,
    );
    console.log(`  DAY_CAP (capacity/day): ${DAY_CAP} min`);
    console.log(`  Total blocks:   ${blocks.length}`);
    console.log(`  OK blocks:      ${okBlocks.length}`);
    console.log(`  Setup blocks:   ${setupBlocks.length}`);
    console.log(`  Auto-moves:     ${autoMoves.length}`);
    console.log(`\n  Blocks per machine:`);
    for (const [mId, count] of Object.entries(blocksByMachine).sort()) {
      console.log(`    ${mId}: ${count} blocks`);
    }

    // 5. KPIs
    section('5. KPIs (scoreSchedule)');

    const metrics = scoreSchedule(
      blocks,
      engineData.ops,
      mSt,
      DEFAULT_WORKFORCE_CONFIG,
      engineData.machines,
      engineData.toolMap,
    );

    console.log(`  OTD:              ${metrics.otd.toFixed(1)}%`);
    console.log(`  OTD-Delivery:     ${metrics.otdDelivery.toFixed(1)}%`);
    console.log(`  Produced:         ${metrics.produced?.toLocaleString() ?? 'N/A'} pcs`);
    console.log(`  Setup count:      ${metrics.setupCount}`);
    console.log(`  Tardiness (days): ${metrics.tardinessDays?.toFixed(1) ?? 'N/A'}`);
    console.log(`  Cap utilization:  ${(metrics.capUtil * 100).toFixed(1)}%`);
    console.log(`  Overflows:        ${metrics.overflows}`);

    // 6. Validation
    section('6. CONSTRAINT VALIDATION');

    const validation = validateSchedule(
      blocks,
      engineData.machines,
      engineData.toolMap,
      engineData.ops,
    );

    console.log(`  Tool conflicts:     ${validation.summary.toolConflicts}`);
    console.log(`  Setup overlaps:     ${validation.summary.setupOverlaps}`);
    console.log(`  Machine overcap:    ${validation.summary.machineOvercapacity}`);
    console.log(`  Total violations:   ${validation.violations.length}`);

    if (validation.violations.length > 0) {
      console.log(`\n  Violations:`);
      for (const v of validation.violations.slice(0, 10)) {
        console.log(`    - [${v.type}] ${v.title}`);
      }
      if (validation.violations.length > 10)
        console.log(`    ... +${validation.violations.length - 10} more`);
    } else {
      console.log(`  >> ALL CONSTRAINTS PASS`);
    }

    // 7. Capacity analysis
    section('7. CAPACITY ANALYSIS');

    const cap = capAnalysis(blocks, engineData.machines);

    console.log(`  Machine utilization (avg / peak):`);
    for (const m of engineData.machines) {
      const loads = cap[m.id] || [];
      if (loads.length === 0) {
        console.log(`    ${m.id}: no data`);
        continue;
      }
      const utils = loads.map((dl: DayLoad) => {
        const total = dl.prod + dl.setup;
        return DAY_CAP > 0 ? (total / DAY_CAP) * 100 : 0;
      });
      const avg = utils.reduce((a, b) => a + b, 0) / utils.length;
      const peak = Math.max(...utils);
      const daysOver80 = utils.filter((u) => u > 80).length;
      console.log(
        `    ${m.id} (${m.area}): avg ${avg.toFixed(1)}%, peak ${peak.toFixed(1)}%, days>80%: ${daysOver80}`,
      );
    }

    // 8. MRP Summary
    section('8. MRP SUMMARY');

    console.log(`  Total MRP records:   ${mrp.records.length}`);
    console.log(`  Tools with stockout: ${mrp.summary.toolsWithStockout}`);
    console.log(`  Tools with backlog:  ${mrp.summary.toolsWithBacklog}`);
    console.log(`  Total planned qty:   ${mrp.summary.totalPlannedQty.toLocaleString()}`);
    console.log(`  Total gross req:     ${mrp.summary.totalGrossReq.toLocaleString()}`);
    console.log(`  Avg utilization:     ${mrp.summary.avgUtilization.toFixed(1)}%`);
    console.log(
      `  Bottleneck machine:  ${mrp.summary.bottleneckMachine ?? 'none'} (day ${mrp.summary.bottleneckDay ?? '-'})`,
    );

    // RCCP overloaded days
    const overloaded = mrp.rccp.filter((r) => r.overloaded);
    console.log(`  RCCP overloaded entries: ${overloaded.length}`);
    if (overloaded.length > 0) {
      const byMachine: Record<string, number> = {};
      for (const r of overloaded) byMachine[r.machine] = (byMachine[r.machine] || 0) + 1;
      console.log(`  Overloaded days by machine:`);
      for (const [m, count] of Object.entries(byMachine).sort((a, b) => b[1] - a[1])) {
        console.log(`    ${m}: ${count} days overloaded`);
      }
    }

    // 9. Supply Risk
    section('9. SUPPLY RISK');

    const rop = computeROP(mrp, engineData, 95);
    const actions = computeActionMessages(mrp, engineData);

    console.log(`  Supply priority boosts: ${supplyBoosts.size}`);
    const boostCounts = { critical: 0, high: 0, medium: 0 };
    for (const [, sp] of supplyBoosts) {
      if (sp.boost === 3) boostCounts.critical++;
      else if (sp.boost === 2) boostCounts.high++;
      else if (sp.boost === 1) boostCounts.medium++;
    }
    console.log(`    Critical (3): ${boostCounts.critical}`);
    console.log(`    High (2):     ${boostCounts.high}`);
    console.log(`    Medium (1):   ${boostCounts.medium}`);

    console.log(`\n  ROP records: ${rop.records.length}`);
    console.log(`  Action messages: ${actions.messages.length}`);
    if (actions.messages.length > 0) {
      const byType: Record<string, number> = {};
      for (const msg of actions.messages) byType[msg.type] = (byType[msg.type] || 0) + 1;
      console.log(`  Actions by type:`);
      for (const [type, count] of Object.entries(byType).sort((a, b) => b[1] - a[1])) {
        console.log(`    ${type}: ${count}`);
      }
    }

    // 10. Top operations
    section('10. TOP 10 OPERATIONS BY DEMAND');

    const opDemands = merged.operations
      .map((op) => ({
        id: op.id,
        sku: op.sku,
        machine: op.m,
        tool: op.t,
        totalDemand: op.d.reduce((a: number, b: number | null) => a + (b ?? 0), 0),
        backlog: op.atr,
        customer: op.cl || '-',
      }))
      .sort((a, b) => (b.totalDemand ?? 0) - (a.totalDemand ?? 0));

    console.log(
      `  ${'Op'.padEnd(6)} ${'SKU'.padEnd(18)} ${'Maq'.padEnd(8)} ${'Tool'.padEnd(10)} ${'Demand'.padStart(8)} ${'Backlog'.padStart(8)} ${'Client'.padEnd(8)}`,
    );
    console.log(`  ${'-'.repeat(68)}`);
    for (const op of opDemands.slice(0, 10)) {
      console.log(
        `  ${op.id.padEnd(6)} ${op.sku.padEnd(18)} ${op.machine.padEnd(8)} ${op.tool.padEnd(10)} ${(op.totalDemand ?? 0).toString().padStart(8)} ${op.backlog.toString().padStart(8)} ${op.customer.padEnd(8)}`,
      );
    }

    // Top tools by stockout risk
    section('11. TOP 10 TOOLS BY STOCKOUT RISK');

    const toolRisk = mrp.records
      .filter((r) => r.stockoutDay !== null)
      .sort((a, b) => (a.stockoutDay ?? 999) - (b.stockoutDay ?? 999));

    if (toolRisk.length === 0) {
      console.log('  No tools with stockout risk.');
    } else {
      console.log(
        `  ${'Tool'.padEnd(10)} ${'Maq'.padEnd(8)} ${'Stockout'.padStart(8)} ${'Coverage'.padStart(10)} ${'Stock'.padStart(8)} ${'GrossReq'.padStart(10)}`,
      );
      console.log(`  ${'-'.repeat(56)}`);
      for (const t of toolRisk.slice(0, 10)) {
        console.log(
          `  ${t.toolCode.padEnd(10)} ${t.machine.padEnd(8)} ${`dia ${t.stockoutDay}`.padStart(8)} ${`${t.coverageDays.toFixed(1)}d`.padStart(10)} ${t.currentStock.toString().padStart(8)} ${t.totalGrossReq.toString().padStart(10)}`,
        );
      }
    }

    // Final summary
    header('SUMMARY');
    const allOk = validation.violations.length === 0;
    console.log(`  Parse:        OK (${meta.rows} ops, ${meta.tools} tools, ${meta.dates} days)`);
    console.log(`  Trust:        ${(meta.trustScore * 100).toFixed(1)}%`);
    console.log(
      `  Merge:        OK (${toolsWithSetup.length} setups, ${toolsWithAlt.length} alts enriched)`,
    );
    console.log(`  Schedule:     OK (${blocks.length} blocks, ${autoMoves.length} auto-moves)`);
    console.log(`  KPIs:         OTD ${metrics.otd.toFixed(1)}%, ${metrics.setupCount} setups`);
    console.log(
      `  Constraints:  ${allOk ? 'ALL PASS' : `${validation.violations.length} VIOLATIONS`}`,
    );
    console.log(
      `  MRP:          ${mrp.records.length} records, ${mrp.summary.toolsWithStockout} stockouts`,
    );
    console.log(
      `  Supply:       ${supplyBoosts.size} boosted ops (${boostCounts.critical} critical)`,
    );
    console.log(`\n${line('═')}`);
  });
});

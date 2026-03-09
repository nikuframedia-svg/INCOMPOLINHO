/**
 * ISOP Verification: Raw NP vs Engine Demand + Full Planning Pipeline
 *
 * Part 1: Compares raw negative NP cells with rawNPtoOrderDemand() output.
 * Part 2: Runs the FULL scheduling pipeline (same as useScheduleData.ts)
 *         and outputs KPIs, heatmap, coverage — for comparison with Planning page.
 *
 * The factory planner counted 699 negative cells summing to 3,185,769 pcs.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

import { parseISOPFile } from '../../domain/isop';
import type { MRPSkuViewResult } from '../../domain/mrp/mrp-types';
import type { NikufraData } from '../../domain/nikufra-types';
import { computeOrderRisk, groupByClient } from '../../features/mrp/utils/encomendas-compute';
import type { Block, CoverageAuditResult, DayLoad, EngineData, MRPResult } from '../../lib/engine';
import {
  auditCoverage,
  autoRouteOverflow,
  capAnalysis,
  computeMRP,
  computeMRPSkuView,
  computeSupplyPriority,
  DAY_CAP,
  rawNPtoOrderDemand,
  T1,
  transformPlanState,
  validateSchedule,
} from '../../lib/engine';

// ── Paths ──

const cwd = process.cwd();
const base = cwd.endsWith('frontend') ? cwd : join(cwd, 'frontend');

const userIsopPath = '/Users/martimnicolau/Downloads/ISOP_ Nikufra_27_2-2.xlsx';
const fixtureIsopPath = join(base, 'src', 'tests', 'fixtures', 'ISOP_Nikufra_27_2.xlsx');
const fixturePath = join(base, 'public', 'fixtures', 'nikufra', 'nikufra_data.json');

// ── Helpers ──

function mergeWithMasterData(data: NikufraData, fixture: NikufraData): NikufraData {
  const fixToolMap = new Map(fixture.tools.map((t) => [t.id, t]));
  const mergedTools = data.tools.map((tool) => {
    const fix = fixToolMap.get(tool.id);
    if (!fix) return tool;
    return { ...tool, s: tool.s > 0 ? tool.s : fix.s, alt: tool.alt !== '-' ? tool.alt : fix.alt };
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

// ── Shared state (file-level, reused across Part 1/2/3) ──

let nikufraData: NikufraData;
let isopSource: string;
let engineData: EngineData;
let blocks: Block[];
let cap: Record<string, DayLoad[]>;
let audit: CoverageAuditResult;
let mrpResult: MRPResult;
let skuView: MRPSkuViewResult;

beforeAll(() => {
  // 0. Load ISOP
  let path: string;
  try {
    readFileSync(userIsopPath);
    path = userIsopPath;
    isopSource = 'user ISOP (Nikufra_27_2-2.xlsx)';
  } catch {
    path = fixtureIsopPath;
    isopSource = 'test fixture (ISOP_Nikufra_27_2.xlsx)';
  }

  const buf = readFileSync(path);
  const ab = new ArrayBuffer(buf.length);
  const view = new Uint8Array(ab);
  for (let i = 0; i < buf.length; i++) view[i] = buf[i];

  const result = parseISOPFile(ab);
  if (!result.success) throw new Error(`Parse failed: ${result.errors.join(', ')}`);
  nikufraData = result.data;

  // 1. Merge with master data
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf-8')) as NikufraData;
  const merged = mergeWithMasterData(nikufraData, fixture);

  // 2. Build PlanState
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

  // 3. Transform → EngineData (raw_np mode)
  engineData = transformPlanState(planState, { demandSemantics: 'raw_np' });

  // 4. MRP + supply priority
  mrpResult = computeMRP(engineData);
  skuView = computeMRPSkuView(mrpResult);
  const supplyBoosts = computeSupplyPriority(engineData, mrpResult);

  // 5. Schedule
  const mSt: Record<string, string> = Object.fromEntries(
    engineData.machines.map((m) => [m.id, 'running']),
  );
  const schedResult = autoRouteOverflow({
    ops: engineData.ops,
    mSt,
    tSt: {},
    userMoves: [],
    machines: engineData.machines,
    toolMap: engineData.toolMap,
    workdays: engineData.workdays,
    nDays: engineData.nDays,
    rule: 'EDD',
    supplyBoosts: supplyBoosts.size > 0 ? supplyBoosts : undefined,
    twinValidationReport: engineData.twinValidationReport,
    dates: engineData.dates,
    orderBased: engineData.orderBased,
  });
  blocks = schedResult.blocks;

  // 6. Analysis
  cap = capAnalysis(blocks, engineData.machines, engineData.nDays);
  audit = auditCoverage(blocks, engineData.ops, engineData.toolMap, engineData.twinGroups);
});

// ══════════════════════════════════════════════════════════════
// Part 1: Raw NP vs Engine Demand
// ══════════════════════════════════════════════════════════════

describe('Part 1: Raw NP vs Engine Demand', () => {
  it('reports source file', () => {
    console.log(`\n  Source: ${isopSource}`);
    console.log(`   Operations: ${nikufraData.operations.length}`);
    console.log(`   Date columns: ${nikufraData.dates.length}`);
    expect(nikufraData.operations.length).toBeGreaterThan(0);
  });

  it('every negative NP cell = demand (no deduplication)', () => {
    let rawNegCount = 0;
    let rawNegSum = 0;
    let engineOrderCount = 0;
    let engineOrderSum = 0;

    for (const op of nikufraData.operations) {
      const rawNP = op.d as (number | null)[];

      for (const v of rawNP) {
        if (v !== null && v !== undefined && v < 0) {
          rawNegCount++;
          rawNegSum += Math.abs(v);
        }
      }

      const demand = rawNPtoOrderDemand(rawNP, op.atr);
      for (const v of demand) {
        if (v > 0) {
          engineOrderCount++;
          engineOrderSum += v;
        }
      }
    }

    console.log('\n════════════════════════════════════════════════');
    console.log('  RAW NP vs ENGINE DEMAND');
    console.log('════════════════════════════════════════════════');
    console.log(`  Raw negative cells:  ${rawNegCount.toLocaleString()} cells`);
    console.log(`  Raw absolute sum:    ${rawNegSum.toLocaleString()} pcs`);
    console.log(`  Engine orders:       ${engineOrderCount.toLocaleString()} orders`);
    console.log(`  Engine demand sum:   ${engineOrderSum.toLocaleString()} pcs`);
    console.log('════════════════════════════════════════════════\n');

    // After removing deduplication, engine should match raw NP count exactly
    // (minus atr subtraction from first orders)
    expect(rawNegCount).toBe(699);
    expect(rawNegSum).toBe(3_185_769);
    expect(engineOrderCount).toBe(rawNegCount);
  });
});

// ══════════════════════════════════════════════════════════════
// Part 2: Full Planning Pipeline (mirrors useScheduleData.ts)
// ══════════════════════════════════════════════════════════════

describe('Part 2: Planning Page Verification', () => {
  it('outputs KPIs (same formulas as NikufraEngine.tsx)', () => {
    const ok = blocks.filter((b) => b.type !== 'blocked');

    // Twin-aware qty (same bQty helper as NikufraEngine line 626)
    const bQty = (b: Block) =>
      b.isTwinProduction && b.outputs ? b.outputs.reduce((s, o) => s + o.qty, 0) : b.qty;

    const tPcs = ok.reduce((a, b) => a + bQty(b), 0);
    const tProd = ok.reduce((a, b) => a + (b.endMin - b.startMin), 0);
    const tSetup = ok
      .filter((b) => b.setupS != null)
      .reduce((a, b) => a + ((b.setupE ?? 0) - (b.setupS ?? 0)), 0);
    const sX = ok.filter((b) => b.setupS != null && (b.setupS ?? 0) < T1).length;
    const sY = ok.filter((b) => b.setupS != null && (b.setupS ?? 0) >= T1).length;
    const blockedOps = new Set(blocks.filter((b) => b.type === 'blocked').map((b) => b.opId)).size;

    console.log('\n════════════════════════════════════════════════');
    console.log('  PLANNING PAGE — KPIs');
    console.log('════════════════════════════════════════════════');
    console.log(`  Cobertura:   ${audit.globalCoveragePct.toFixed(1)}%`);
    console.log(`  Peças:       ${(tPcs / 1000).toFixed(0)}K (${tPcs.toLocaleString()} pcs)`);
    console.log(`  Produção:    ${(tProd / 60).toFixed(0)}h (${Math.round(tProd)} min)`);
    console.log(`  Setup:       ${(tSetup / 60).toFixed(1)}h`);
    console.log(`  Balance:     ${sX}/${sY} (shiftX/shiftY)`);
    console.log(`  Bloqueadas:  ${blockedOps} ops`);
    console.log('════════════════════════════════════════════════');

    // Demand pipeline verification
    console.log('\n  Demand Pipeline:');
    console.log(`    audit.totalDemand:    ${audit.totalDemand.toLocaleString()} pcs`);
    console.log(`    audit.totalProduced:  ${audit.totalProduced.toLocaleString()} pcs`);
    console.log(
      `    Total blocks:         ${blocks.length} (${ok.length} ok, ${blocks.length - ok.length} blocked)`,
    );

    expect(tPcs).toBeGreaterThan(0);
    expect(audit.totalDemand).toBeGreaterThan(0);
  });

  it('outputs heatmap: Capacidade Máquina × Dia', () => {
    // Working day indices (same as NikufraEngine)
    const wdi: number[] = [];
    for (let i = 0; i < engineData.nDays; i++) {
      if (engineData.workdays[i]) wdi.push(i);
    }

    console.log('\n════════════════════════════════════════════════');
    console.log('  HEATMAP: Capacidade Máquina × Dia');
    console.log('════════════════════════════════════════════════');

    for (const m of engineData.machines) {
      const loads = cap[m.id] || [];
      const hasProd = loads.some((dl) => dl.prod > 0);
      if (!hasProd) continue;

      const cells: string[] = [];
      for (const i of wdi) {
        const dl = loads[i];
        if (!dl) {
          cells.push('---');
          continue;
        }
        const tot = Math.round(dl.prod + dl.setup);
        const u = DAY_CAP > 0 ? ((dl.prod + dl.setup) / DAY_CAP) * 100 : 0;
        cells.push(`${tot}(${u.toFixed(0)}%)`);
      }

      console.log(`\n  ${m.id} (${m.area}):`);
      // Print in rows of 10 days
      for (let row = 0; row < cells.length; row += 10) {
        const slice = cells.slice(row, row + 10);
        const dayLabels = wdi.slice(row, row + 10).map((i) => {
          const d = engineData.dates[i];
          return d ? d.slice(0, 5) : `d${i}`;
        });
        console.log(`    ${dayLabels.map((l) => l.padStart(12)).join('')}`);
        console.log(`    ${slice.map((c) => c.padStart(12)).join('')}`);
      }
    }
    console.log('\n════════════════════════════════════════════════');

    expect(Object.keys(cap).length).toBeGreaterThan(0);
  });

  it('outputs Volume / Dia (daily production)', () => {
    const wdi: number[] = [];
    for (let i = 0; i < engineData.nDays; i++) {
      if (engineData.workdays[i]) wdi.push(i);
    }

    const bQty = (b: Block) =>
      b.isTwinProduction && b.outputs ? b.outputs.reduce((s, o) => s + o.qty, 0) : b.qty;

    const prodByDay = wdi.map((i) =>
      blocks.filter((b) => b.dayIdx === i && b.type !== 'blocked').reduce((a, b) => a + bQty(b), 0),
    );

    console.log('\n════════════════════════════════════════════════');
    console.log('  VOLUME / DIA (peças por dia)');
    console.log('════════════════════════════════════════════════');
    for (let j = 0; j < wdi.length; j++) {
      const d = engineData.dates[wdi[j]]?.slice(0, 5) ?? `d${wdi[j]}`;
      const pcs = prodByDay[j];
      const bar = '█'.repeat(Math.min(50, Math.round(pcs / 5000)));
      console.log(`  ${d}: ${(pcs / 1000).toFixed(0).padStart(5)}K  ${bar}`);
    }
    console.log('════════════════════════════════════════════════');

    expect(prodByDay.length).toBeGreaterThan(0);
  });

  it('outputs constraint validation', () => {
    const validation = validateSchedule(
      blocks,
      engineData.machines,
      engineData.toolMap,
      engineData.ops,
    );

    console.log('\n════════════════════════════════════════════════');
    console.log('  CONSTRAINT VALIDATION');
    console.log('════════════════════════════════════════════════');
    console.log(`  Tool conflicts:     ${validation.summary.toolConflicts}`);
    console.log(`  Setup overlaps:     ${validation.summary.setupOverlaps}`);
    console.log(`  Machine overcap:    ${validation.summary.machineOvercapacity}`);
    console.log(`  Total violations:   ${validation.violations.length}`);

    if (validation.violations.length > 0) {
      console.log('\n  Violations:');
      for (const v of validation.violations.slice(0, 10)) {
        console.log(`    [${v.type}] ${v.title}`);
      }
      if (validation.violations.length > 10) {
        console.log(`    ... +${validation.violations.length - 10} more`);
      }
    }
    console.log('════════════════════════════════════════════════');
  });

  it('outputs coverage per machine', () => {
    console.log('\n════════════════════════════════════════════════');
    console.log('  COVERAGE PER MACHINE');
    console.log('════════════════════════════════════════════════');

    const byMachine = new Map<string, { demand: number; produced: number; ops: number }>();

    for (const row of audit.rows) {
      const m = row.machineId;
      const entry = byMachine.get(m) || { demand: 0, produced: 0, ops: 0 };
      entry.demand += row.totalDemand;
      entry.produced += row.produced;
      entry.ops++;
      byMachine.set(m, entry);
    }

    for (const [mId, info] of [...byMachine].sort((a, b) => a[0].localeCompare(b[0]))) {
      const cov = info.demand > 0 ? (info.produced / info.demand) * 100 : 100;
      const gap = Math.max(0, info.demand - info.produced);
      console.log(
        `  ${mId}: ${info.ops} ops, demand ${info.demand.toLocaleString()}, ` +
          `produced ${info.produced.toLocaleString()}, coverage ${cov.toFixed(1)}%` +
          (gap > 0 ? ` [GAP: ${gap.toLocaleString()} pcs]` : ''),
      );
    }

    console.log(
      `\n  GLOBAL: ${audit.globalCoveragePct.toFixed(1)}% ` +
        `(${audit.fullyCovered} full, ${audit.partiallyCovered} partial, ${audit.zeroCovered} zero)`,
    );
    console.log('════════════════════════════════════════════════');
  });
});

// ══════════════════════════════════════════════════════════════
// Part 3: Encomendas Tab Verification
// ══════════════════════════════════════════════════════════════

describe('Part 3: Encomendas Tab Verification', () => {
  it('outputs KPIs (same formulas as EncomendasTab lines 77-80)', () => {
    const allEntries = computeOrderRisk(engineData, mrpResult, skuView, blocks);

    const totalDemand = allEntries.reduce((s, e) => s + e.orderQty, 0);
    const totalScheduled = allEntries.reduce((s, e) => s + e.totalScheduledQty, 0);
    const totalShortfall = allEntries.reduce((s, e) => s + e.shortfallQty, 0);
    const criticalCount = allEntries.filter((e) => e.riskLevel === 'critical').length;
    const warningCount = allEntries.filter((e) => e.riskLevel === 'warning').length;
    const okCount = allEntries.filter((e) => e.riskLevel === 'ok').length;

    console.log('\n════════════════════════════════════════════════');
    console.log('  ENCOMENDAS TAB — KPIs');
    console.log('════════════════════════════════════════════════');
    console.log(`  Total encomendas:  ${allEntries.length}`);
    console.log(`  Procura:           ${totalDemand.toLocaleString()} pcs`);
    console.log(`  Produção:          ${totalScheduled.toLocaleString()} pcs`);
    console.log(`  Deficit:           ${totalShortfall.toLocaleString()} pcs`);
    console.log(`  Criticas:          ${criticalCount}`);
    console.log(`  Warning:           ${warningCount}`);
    console.log(`  OK:                ${okCount}`);
    console.log('════════════════════════════════════════════════');

    expect(allEntries.length).toBeGreaterThan(0);
    expect(totalDemand).toBeGreaterThan(0);
  });

  it('outputs top 20 critical entries', () => {
    const allEntries = computeOrderRisk(engineData, mrpResult, skuView, blocks);
    const critical = allEntries.filter((e) => e.riskLevel === 'critical');

    console.log('\n════════════════════════════════════════════════');
    console.log('  TOP 20 CRITICAL ENTRIES');
    console.log('════════════════════════════════════════════════');
    console.log(
      '  SKU                  Tool     Machine  OrderQty   Scheduled  Shortfall  Coverage  Twin',
    );

    for (const e of critical.slice(0, 20)) {
      const twin = e.isTwin ? `← ${e.twinSku?.slice(0, 10)}` : '';
      console.log(
        `  ${e.sku.padEnd(22)} ${e.toolCode.padEnd(8)} ${e.machineId.padEnd(8)} ` +
          `${e.orderQty.toLocaleString().padStart(9)}  ${e.totalScheduledQty.toLocaleString().padStart(9)}  ` +
          `${e.shortfallQty.toLocaleString().padStart(9)}  ${(e.coverageDays.toFixed(1) + 'd').padStart(8)}  ${twin}`,
      );
    }

    if (critical.length > 20) {
      console.log(`  ... +${critical.length - 20} more critical entries`);
    }
    console.log('════════════════════════════════════════════════');
  });

  it('outputs client groups summary', () => {
    const allEntries = computeOrderRisk(engineData, mrpResult, skuView, blocks);
    const groups = groupByClient(allEntries);

    console.log('\n════════════════════════════════════════════════');
    console.log('  CLIENT GROUPS');
    console.log('════════════════════════════════════════════════');
    console.log('  Cliente                     Code       Orders  Crit  Warn  Shortfall');

    for (const g of groups) {
      console.log(
        `  ${(g.customerName || 'Sem cliente').padEnd(28)} ${g.customerCode.padEnd(10)} ` +
          `${String(g.totalOrders).padStart(6)}  ${String(g.criticalCount).padStart(4)}  ` +
          `${String(g.warningCount).padStart(4)}  ${g.totalShortfall.toLocaleString().padStart(9)}`,
      );
    }

    console.log(`\n  Total clients: ${groups.length}`);
    console.log(`  Total orders:  ${groups.reduce((s, g) => s + g.totalOrders, 0)}`);
    console.log('════════════════════════════════════════════════');
  });

  it('outputs twin entries', () => {
    const allEntries = computeOrderRisk(engineData, mrpResult, skuView, blocks);
    const twins = allEntries.filter((e) => e.isTwin);

    console.log('\n════════════════════════════════════════════════');
    console.log('  TWIN ENTRIES');
    console.log('════════════════════════════════════════════════');

    for (const e of twins) {
      console.log(
        `  ${e.sku.padEnd(22)} ↔ ${(e.twinSku || '?').padEnd(22)} ` +
          `Tool: ${e.toolCode.padEnd(8)} Máq: ${e.machineId}  ` +
          `Order: ${e.orderQty.toLocaleString().padStart(8)}  Sched: ${e.totalScheduledQty.toLocaleString().padStart(8)}  ` +
          `Risk: ${e.riskLevel}`,
      );
    }

    console.log(`\n  Total twin entries: ${twins.length}`);
    console.log('════════════════════════════════════════════════');
  });

  it('validates invariants', () => {
    const allEntries = computeOrderRisk(engineData, mrpResult, skuView, blocks);
    const groups = groupByClient(allEntries);

    // 1. orderQty matches MRP grossRequirement (flattened)
    const mrpGrossTotal = mrpResult.records.reduce(
      (s, r) => s + r.skuRecords.reduce((ss, sr) => ss + sr.grossRequirement, 0),
      0,
    );
    const encomendasGrossTotal = allEntries.reduce((s, e) => s + e.orderQty, 0);

    console.log('\n════════════════════════════════════════════════');
    console.log('  INVARIANT CHECKS');
    console.log('════════════════════════════════════════════════');
    console.log(`  MRP grossRequirement total:     ${mrpGrossTotal.toLocaleString()}`);
    console.log(`  Encomendas orderQty total:       ${encomendasGrossTotal.toLocaleString()}`);
    console.log(`  Match: ${mrpGrossTotal === encomendasGrossTotal ? '✓' : '✗'}`);

    expect(encomendasGrossTotal).toBe(mrpGrossTotal);

    // 2. No negative shortfallQty or coverageDays
    const negShortfall = allEntries.filter((e) => e.shortfallQty < 0);
    const negCoverage = allEntries.filter((e) => e.coverageDays < 0);
    console.log(`  Negative shortfallQty entries:   ${negShortfall.length} (expect 0)`);
    console.log(`  Negative coverageDays entries:   ${negCoverage.length} (expect 0)`);
    expect(negShortfall.length).toBe(0);
    expect(negCoverage.length).toBe(0);

    // 3. shortfallQty > 0 → riskLevel === 'critical'
    const shortfallNotCritical = allEntries.filter(
      (e) => e.shortfallQty > 0 && e.riskLevel !== 'critical',
    );
    console.log(`  Shortfall>0 but not critical:    ${shortfallNotCritical.length} (expect 0)`);
    expect(shortfallNotCritical.length).toBe(0);

    // 4. coverageDays < 3 && stockoutDay !== null → riskLevel !== 'ok'
    const lowCoverageOk = allEntries.filter(
      (e) => e.coverageDays < 3 && e.stockoutDay !== null && e.riskLevel === 'ok',
    );
    console.log(`  Low coverage but OK:             ${lowCoverageOk.length} (expect 0)`);
    expect(lowCoverageOk.length).toBe(0);

    // 5. Twins have isTwin=true and twinSku non-null
    const twins = allEntries.filter((e) => e.isTwin);
    const twinsMissingPair = twins.filter((e) => !e.twinSku);
    console.log(`  Twin entries:                    ${twins.length}`);
    console.log(`  Twins missing twinSku:           ${twinsMissingPair.length} (expect 0)`);
    expect(twins.length).toBeGreaterThan(0);
    expect(twinsMissingPair.length).toBe(0);

    // 6. Client groups sum = total entries
    const groupOrdersSum = groups.reduce((s, g) => s + g.totalOrders, 0);
    console.log(
      `  Client groups totalOrders sum:   ${groupOrdersSum} (expect ${allEntries.length})`,
    );
    expect(groupOrdersSum).toBe(allEntries.length);

    // 7. Client groups shortfall sum = entries shortfall sum
    const groupShortfallSum = groups.reduce((s, g) => s + g.totalShortfall, 0);
    const entriesShortfallSum = allEntries.reduce((s, e) => s + e.shortfallQty, 0);
    console.log(`  Client groups shortfall sum:     ${groupShortfallSum.toLocaleString()}`);
    console.log(`  Entries shortfall sum:           ${entriesShortfallSum.toLocaleString()}`);
    console.log(`  Match: ${groupShortfallSum === entriesShortfallSum ? '✓' : '✗'}`);
    expect(groupShortfallSum).toBe(entriesShortfallSum);

    // 8. Entry count matches skuView records
    console.log(`  skuView.skuRecords count:        ${skuView.skuRecords.length}`);
    console.log(`  Encomendas entries count:         ${allEntries.length}`);
    console.log(`  Match: ${skuView.skuRecords.length === allEntries.length ? '✓' : '✗'}`);
    expect(allEntries.length).toBe(skuView.skuRecords.length);

    console.log('════════════════════════════════════════════════');
  });
});

/**
 * Integration test: ISOP Nikufra_27_2.xlsx → Parser → Merge → Engine → Validation
 *
 * Tests the FULL pipeline with real production data:
 *   1. Parse real ISOP Excel file
 *   2. Merge with master data (fixture) for setup times + alt machines
 *   3. Run scheduling engine (scheduleAll + autoRouteOverflow)
 *   4. Validate constraints (no tool conflicts, no setup overlaps)
 *   5. Score schedule (KPIs)
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

import { parseISOPFile } from '../../domain/isop';
import type { NikufraData } from '../../domain/nikufra-types';
import type { Block, DayLoad, EngineData } from '../../lib/engine';
import {
  autoRouteOverflow,
  capAnalysis,
  DEFAULT_WORKFORCE_CONFIG,
  S0,
  S1,
  scoreSchedule,
  T1,
  transformPlanState,
  validateSchedule,
} from '../../lib/engine';

// ── Load real ISOP file ──

const cwd = process.cwd();
const base = cwd.endsWith('frontend') ? cwd : join(cwd, 'frontend');
const isopPath = join(base, 'src', 'tests', 'fixtures', 'ISOP_Nikufra_27_2.xlsx');

let isopBuffer: ArrayBuffer;

beforeAll(() => {
  const buf = readFileSync(isopPath);
  // Create a proper ArrayBuffer copy (jsdom may have different ArrayBuffer global)
  const ab = new ArrayBuffer(buf.length);
  const view = new Uint8Array(ab);
  for (let i = 0; i < buf.length; i++) view[i] = buf[i];
  isopBuffer = ab;
});

// ── Load fixture for merge ──

function loadFixture(): NikufraData {
  const fixturePath = join(base, 'public', 'fixtures', 'nikufra', 'nikufra_data.json');
  const raw = readFileSync(fixturePath, 'utf-8');
  return JSON.parse(raw) as NikufraData;
}

/** Simulate mergeWithMasterData (same logic as useDataStore) */
function mergeWithMasterData(data: NikufraData, fixture: NikufraData): NikufraData {
  const fixToolMap = new Map(fixture.tools.map((t) => [t.id, t]));

  const mergedTools = data.tools.map((tool) => {
    const fix = fixToolMap.get(tool.id);
    if (!fix) return tool;
    return {
      ...tool,
      s: tool.s > 0 ? tool.s : fix.s,
      alt: tool.alt !== '-' ? tool.alt : fix.alt,
    };
  });

  const toolLookup = new Map(mergedTools.map((t) => [t.id, t]));
  const mergedOps = data.operations.map((op) => {
    const tool = toolLookup.get(op.t);
    if (!tool) return op;
    return { ...op, s: op.s > 0 ? op.s : tool.s };
  });

  return { ...data, tools: mergedTools, operations: mergedOps };
}

// ═══════════════════════════════════════════════════════════
//  FASE 1: Parser
// ═══════════════════════════════════════════════════════════

describe('ISOP Integration: Nikufra_27_2.xlsx', () => {
  describe('1. Parser', () => {
    it('parseia o ficheiro com sucesso', () => {
      const result = parseISOPFile(isopBuffer);
      expect(result.success).toBe(true);
    });

    it('detecta 94 operações', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      expect(result.data.operations.length).toBe(94);
    });

    it('detecta 80 datas', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      expect(result.data.dates.length).toBe(80);
      expect(result.data.operations[0].d.length).toBe(80);
    });

    it('detecta 5 máquinas', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      expect(result.data.machines.length).toBe(5);
      const ids = result.data.machines.map((m) => m.id).sort();
      // ISOP Nikufra_27_2 has: PRM019, PRM031, PRM039, PRM042, PRM043 (no PRM020)
      expect(ids).toContain('PRM019');
      expect(ids).toContain('PRM031');
      expect(ids).toContain('PRM039');
      expect(ids).toContain('PRM042');
      expect(ids).toContain('PRM043');
    });

    it('detecta 54 ferramentas', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      expect(result.data.tools.length).toBe(54);
    });

    it('preserva raw NP values (positivo=stock, negativo=déficit, null=vazio)', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      // Raw NP: positive = stock covers demand, negative = shortfall, null = empty cell
      // Engine converts via rawNPtoDailyDemand() pipeline (forward-fill → max(0,-NP) → deltaize)
      for (const op of result.data.operations) {
        for (const v of op.d) {
          expect(v === null || typeof v === 'number').toBe(true);
        }
      }
    });

    it('todas as operações têm pH > 0', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      for (const op of result.data.operations) {
        expect(op.pH).toBeGreaterThan(0);
      }
    });

    it('operadores são 1 ou 2', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      for (const op of result.data.operations) {
        expect(op.op).toBeGreaterThanOrEqual(1);
        expect(op.op).toBeLessThanOrEqual(2);
      }
    });

    it('detecta clientes (16 clientes)', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      expect(result.data.customers?.length).toBe(16);
    });

    it('mapeia coluna Prz.Fabrico (ltDays)', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      // At least some operations should have ltDays > 0
      const withLtDays = result.data.operations.filter((op) => op.ltDays && op.ltDays > 0);
      expect(withLtDays.length).toBeGreaterThan(0);
      // All ltDays should be in valid range (0-15 days)
      for (const op of result.data.operations) {
        if (op.ltDays != null) {
          expect(op.ltDays).toBeGreaterThanOrEqual(0);
          expect(op.ltDays).toBeLessThanOrEqual(15);
        }
      }
    });

    it('ISOP não tem setup times (tudo 0)', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      // Before merge, all setups should be 0 (ISOP has no Tp.Setup column)
      for (const tool of result.data.tools) {
        expect(tool.s).toBe(0);
      }
    });

    it('ISOP não tem alt machines (tudo "-")', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));
      // Before merge, all alt should be '-' (ISOP has no Máq. Alt. column)
      for (const tool of result.data.tools) {
        expect(tool.alt).toBe('-');
      }
    });
  });

  // ═══════════════════════════════════════════════════════════
  //  FASE 2: Merge com dados mestres
  // ═══════════════════════════════════════════════════════════

  describe('2. Merge com dados mestres', () => {
    it('enriquece setup times a partir do fixture', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      const merged = mergeWithMasterData(result.data, fixture);

      // After merge, tools that exist in fixture should have setup > 0
      const fixtureToolIds = new Set(fixture.tools.map((t) => t.id));
      const enrichedTools = merged.tools.filter((t) => fixtureToolIds.has(t.id) && t.s > 0);
      expect(enrichedTools.length).toBeGreaterThan(0);
    });

    it('enriquece alt machines a partir do fixture', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      const merged = mergeWithMasterData(result.data, fixture);

      // After merge, tools that have alt in fixture should have alt != '-'
      const withAlt = merged.tools.filter((t) => t.alt !== '-');
      expect(withAlt.length).toBeGreaterThan(0);
    });

    it('propaga setup time para operations', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      const merged = mergeWithMasterData(result.data, fixture);

      // Operations should get setup from their enriched tool
      const opsWithSetup = merged.operations.filter((op) => op.s > 0);
      expect(opsWithSetup.length).toBeGreaterThan(0);
    });

    it('mantém dados do ISOP quando existem (não sobrescreve)', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      const merged = mergeWithMasterData(result.data, fixture);

      // All operations should keep their original demand
      for (let i = 0; i < merged.operations.length; i++) {
        expect(merged.operations[i].d).toEqual(result.data.operations[i].d);
        expect(merged.operations[i].pH).toBe(result.data.operations[i].pH);
        expect(merged.operations[i].op).toBe(result.data.operations[i].op);
      }
    });

    it('ferramentas novas (não no fixture) mantêm s=0', () => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      const fixtureToolIds = new Set(fixture.tools.map((t) => t.id));
      const merged = mergeWithMasterData(result.data, fixture);

      // Tools NOT in fixture should still have s=0
      const newTools = merged.tools.filter((t) => !fixtureToolIds.has(t.id));
      for (const t of newTools) {
        expect(t.s).toBe(0);
      }
    });
  });

  // ═══════════════════════════════════════════════════════════
  //  FASE 3: Engine scheduling
  // ═══════════════════════════════════════════════════════════

  describe('3. Engine scheduling', () => {
    let mergedData: NikufraData;
    let engineData: EngineData;
    let blocks: Block[];

    beforeAll(() => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      mergedData = mergeWithMasterData(result.data, fixture);

      // Build PlanState (same as MockDataSource)
      const planState = {
        dates: mergedData.dates,
        days_label: mergedData.days_label,
        machines: mergedData.machines.map((m) => ({
          id: m.id,
          area: m.area as 'PG1' | 'PG2',
          man_minutes: m.man,
        })),
        tools: mergedData.tools.map((t) => ({
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
        operations: mergedData.operations.map((op) => ({
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
        mo: mergedData.mo ? { PG1: mergedData.mo.PG1, PG2: mergedData.mo.PG2 } : undefined,
      };

      engineData = transformPlanState(planState);

      // Schedule with autoRouteOverflow (like useScheduleData)
      const mSt: Record<string, string> = Object.fromEntries(
        engineData.machines.map((m) => [m.id, 'running']),
      );
      const nDays = engineData.ops[0]?.d.length ?? 80;
      const result2 = autoRouteOverflow({
        ops: engineData.ops,
        mSt,
        tSt: {},
        userMoves: [],
        machines: engineData.machines,
        toolMap: engineData.toolMap,
        workdays: engineData.workdays,
        nDays,
      });
      blocks = result2.blocks;
    });

    it('constantes de turno correctas', () => {
      expect(S0).toBe(420); // 07:00
      expect(T1).toBe(930); // 15:30
      expect(S1).toBe(1440); // 24:00
    });

    it('transforma 94 ops em engine ops', () => {
      expect(engineData.ops.length).toBe(94);
    });

    it('transforma 5 máquinas', () => {
      expect(engineData.machines.length).toBe(5);
    });

    it('horizon = 80 dias (não truncado)', () => {
      expect(engineData.ops[0].d.length).toBe(80);
    });

    it('produz blocos de scheduling', () => {
      expect(blocks.length).toBeGreaterThan(0);
    });

    it('blocos têm setup time > 0 (merge funcionou)', () => {
      const withSetup = blocks.filter((b) => b.setupMin > 0 && b.type === 'ok');
      // At least some blocks should have setup time after merge
      expect(withSetup.length).toBeGreaterThan(0);
    });

    it('nenhum bloco cruza fronteira de turno T1=930', () => {
      const okBlocks = blocks.filter((b) => b.type === 'ok');
      for (const b of okBlocks) {
        const start = b.setupS ?? b.startMin;
        const end = b.endMin;
        // Block must be entirely in shift X (<=930) or entirely in shift Y (>=930)
        const crossesBoundary = start < T1 && end > T1;
        if (crossesBoundary) {
          // If it crosses, it's a violation
          expect(crossesBoundary).toBe(false);
        }
      }
    });

    it('nenhuma sobreposição de tool em máquinas diferentes', () => {
      const okBlocks = blocks.filter((b) => b.type === 'ok');
      // Group by toolId
      const byTool = new Map<string, Block[]>();
      for (const b of okBlocks) {
        const arr = byTool.get(b.toolId) || [];
        arr.push(b);
        byTool.set(b.toolId, arr);
      }

      let violations = 0;
      for (const [, toolBlocks] of byTool) {
        for (let i = 0; i < toolBlocks.length; i++) {
          for (let j = i + 1; j < toolBlocks.length; j++) {
            const a = toolBlocks[i],
              b = toolBlocks[j];
            if (a.machineId === b.machineId) continue;
            const aStart = a.dayIdx * 1440 + (a.setupS ?? a.startMin);
            const aEnd = a.dayIdx * 1440 + a.endMin;
            const bStart = b.dayIdx * 1440 + (b.setupS ?? b.startMin);
            const bEnd = b.dayIdx * 1440 + b.endMin;
            if (aStart < bEnd && bStart < aEnd) violations++;
          }
        }
      }
      expect(violations).toBe(0);
    });

    it('nenhuma sobreposição de setup (SetupCrew)', () => {
      const setupBlocks = blocks.filter((b) => b.setupS != null && b.setupE != null);
      let overlaps = 0;
      for (let i = 0; i < setupBlocks.length; i++) {
        for (let j = i + 1; j < setupBlocks.length; j++) {
          const a = setupBlocks[i],
            b = setupBlocks[j];
          if (a.machineId === b.machineId) continue;
          const aStart = a.dayIdx * 1440 + a.setupS!;
          const aEnd = a.dayIdx * 1440 + a.setupE!;
          const bStart = b.dayIdx * 1440 + b.setupS!;
          const bEnd = b.dayIdx * 1440 + b.setupE!;
          if (aStart < bEnd && bStart < aEnd) overlaps++;
        }
      }
      expect(overlaps).toBe(0);
    });
  });

  // ═══════════════════════════════════════════════════════════
  //  FASE 4: Validation & KPIs
  // ═══════════════════════════════════════════════════════════

  describe('4. Validation & KPIs', () => {
    let mergedData: NikufraData;
    let engineData: EngineData;
    let blocks: Block[];

    beforeAll(() => {
      const result = parseISOPFile(isopBuffer);
      if (!result.success) throw new Error(result.errors.join(', '));

      const fixture = loadFixture();
      mergedData = mergeWithMasterData(result.data, fixture);

      const planState = {
        dates: mergedData.dates,
        days_label: mergedData.days_label,
        machines: mergedData.machines.map((m) => ({
          id: m.id,
          area: m.area as 'PG1' | 'PG2',
          man_minutes: m.man,
        })),
        tools: mergedData.tools.map((t) => ({
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
        operations: mergedData.operations.map((op) => ({
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
          twin: op.twin,
        })),
        schedule: [],
        machine_loads: [],
        kpis: null,
        parsed_at: new Date().toISOString(),
        data_hash: null,
        mo: mergedData.mo ? { PG1: mergedData.mo.PG1, PG2: mergedData.mo.PG2 } : undefined,
      };

      engineData = transformPlanState(planState);

      const mSt: Record<string, string> = Object.fromEntries(
        engineData.machines.map((m) => [m.id, 'running']),
      );
      const nDays = engineData.ops[0]?.d.length ?? 80;
      const result2 = autoRouteOverflow({
        ops: engineData.ops,
        mSt,
        tSt: {},
        userMoves: [],
        machines: engineData.machines,
        toolMap: engineData.toolMap,
        workdays: engineData.workdays,
        nDays,
      });
      blocks = result2.blocks;
    });

    it('validateSchedule não tem tool conflicts', () => {
      const report = validateSchedule(
        blocks,
        engineData.machines,
        engineData.toolMap,
        engineData.ops,
      );
      expect(report.summary.toolConflicts).toBe(0);
    });

    it('validateSchedule não tem setup overlaps', () => {
      const report = validateSchedule(
        blocks,
        engineData.machines,
        engineData.toolMap,
        engineData.ops,
      );
      expect(report.summary.setupOverlaps).toBe(0);
    });

    it('scoreSchedule produz KPIs válidos', () => {
      const mSt: Record<string, string> = Object.fromEntries(
        engineData.machines.map((m) => [m.id, 'running']),
      );
      const metrics = scoreSchedule(
        blocks,
        engineData.ops,
        mSt,
        DEFAULT_WORKFORCE_CONFIG,
        engineData.machines,
        engineData.toolMap,
      );
      expect(metrics).toBeDefined();
      // OTD can exceed 100% when lot economic rounding produces more than demand
      expect(metrics.otd).toBeGreaterThanOrEqual(0);
      // OTD-D (delivery-based) checks cumulative production vs cumulative demand per due date
      expect(metrics.otdDelivery).toBeGreaterThanOrEqual(0);
      expect(metrics.otdDelivery).toBeLessThanOrEqual(100);
      expect(metrics.setupCount).toBeGreaterThanOrEqual(0);
    });

    it('capAnalysis cobre todas as máquinas', () => {
      const cap = capAnalysis(blocks, engineData.machines);
      const machineIds = engineData.machines.map((m) => m.id);
      for (const mId of machineIds) {
        expect(cap[mId]).toBeDefined();
        expect(Array.isArray(cap[mId])).toBe(true);
      }
    });

    it('capAnalysis: produção e setup >= 0', () => {
      const cap = capAnalysis(blocks, engineData.machines);
      for (const [, dayLoads] of Object.entries(cap)) {
        for (const dl of dayLoads as DayLoad[]) {
          expect(dl.prod).toBeGreaterThanOrEqual(0);
          expect(dl.setup).toBeGreaterThanOrEqual(0);
        }
      }
    });
  });
});

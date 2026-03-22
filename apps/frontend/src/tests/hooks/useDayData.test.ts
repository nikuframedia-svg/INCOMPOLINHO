/**
 * useDayData.test.ts — Tests for the pure deriveDayData function.
 * Avoids hook complexity by testing the extracted pure logic directly.
 */

import { describe, expect, it } from 'vitest';
import type { Block, EngineData } from '@/domain/types/scheduling';
import type { DeriveDayDataInput } from '@/lib/day-data-derive';
import { deriveDayData } from '@/lib/day-data-derive';

function makeMinimalEngine(overrides: Partial<EngineData> = {}): EngineData {
  return {
    machines: [{ id: 'PRM019', area: 'Grandes', focus: true }],
    tools: [],
    ops: [],
    dates: ['2026-03-22'],
    dnames: ['Seg'],
    toolMap: {},
    focusIds: ['PRM019'],
    workdays: [true],
    nDays: 1,
    mSt: { PRM019: 'running' },
    tSt: {},
    ...overrides,
  } as EngineData;
}

function makeInput(overrides: Partial<DeriveDayDataInput> = {}): DeriveDayDataInput {
  return {
    engine: makeMinimalEngine(),
    allBlocks: [],
    cap: {},
    metrics: null,
    validation: null,
    feasibilityReport: null,
    transparencyReport: null,
    allDecisions: [],
    selectedDayIdx: 0,
    ...overrides,
  };
}

describe('deriveDayData', () => {
  it('returns zero-filled DayData for empty blocks + minimal engine', () => {
    const result = deriveDayData(makeInput());

    expect(result.dayIdx).toBe(0);
    expect(result.date).toBe('2026-03-22');
    expect(result.dayName).toBe('Seg');
    expect(result.isWorkday).toBe(true);
    expect(result.blocks).toEqual([]);
    expect(result.okBlocks).toEqual([]);
    expect(result.overflowBlocks).toEqual([]);
    expect(result.infeasibleBlocks).toEqual([]);
    expect(result.totalPcs).toBe(0);
    expect(result.totalOps).toBe(0);
    expect(result.totalSetupMin).toBe(0);
    expect(result.totalProdMin).toBe(0);
    expect(result.factoryUtil).toBe(0);
    expect(result.violations).toEqual([]);
    expect(result.decisions).toEqual([]);
    expect(result.nDays).toBe(1);
  });

  it('returns correct counts given blocks for day 0', () => {
    const blocks: Block[] = [
      {
        opId: 'op1',
        machineId: 'PRM019',
        toolId: 'T001',
        dayIdx: 0,
        type: 'ok',
        startMin: 420,
        endMin: 600,
        prodMin: 150,
        setupMin: 30,
        pcs: 500,
        sku: 'SKU001',
        name: 'Part A',
      } as Block,
      {
        opId: 'op2',
        machineId: 'PRM019',
        toolId: 'T002',
        dayIdx: 0,
        type: 'overflow',
        startMin: 600,
        endMin: 800,
        prodMin: 170,
        setupMin: 30,
        pcs: 300,
        sku: 'SKU002',
        name: 'Part B',
      } as Block,
      {
        opId: 'op3',
        machineId: 'PRM019',
        toolId: 'T003',
        dayIdx: 1,
        type: 'ok',
        startMin: 420,
        endMin: 600,
        prodMin: 150,
        setupMin: 30,
        pcs: 200,
        sku: 'SKU003',
        name: 'Part C',
      } as Block,
    ];

    const cap = {
      PRM019: [{ prod: 320, setup: 60, ops: 2, pcs: 800, blk: 2 }],
    };

    const result = deriveDayData(makeInput({ allBlocks: blocks, cap }));

    // Only day 0 blocks
    expect(result.blocks).toHaveLength(2);
    expect(result.okBlocks).toHaveLength(1);
    expect(result.overflowBlocks).toHaveLength(1);
    expect(result.infeasibleBlocks).toHaveLength(0);

    // Aggregated from cap
    expect(result.totalPcs).toBe(800);
    expect(result.totalOps).toBe(2);
    expect(result.totalSetupMin).toBe(60);
    expect(result.totalProdMin).toBe(320);

    // Utilization: (320 + 60) / 1020 = ~0.3725
    expect(result.factoryUtil).toBeCloseTo(0.3725, 3);
  });

  it('clamps selectedDayIdx to valid range', () => {
    const result = deriveDayData(makeInput({ selectedDayIdx: 999 }));
    // nDays=1, so clamped to 0
    expect(result.dayIdx).toBe(0);
  });
});

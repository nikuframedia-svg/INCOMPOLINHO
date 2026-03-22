/**
 * useStressTest — Runs 6 predefined stress tests via backend /v1/schedule/replan.
 *
 * Each test: build disruption → POST replan → compare with baseline.
 * Fragility score = mean of individual test scores (0-10).
 */

import { useCallback, useMemo, useState } from 'react';
import type { Block, EngineData, EOp, OptResult } from '@/domain/types/scheduling';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import { scheduleReplanApi } from '../../../lib/api';

export interface StressTestResult {
  id: string;
  name: string;
  description: string;
  baseline: { otd: number; setupMin: number; tardiness: number; overflows: number };
  stressed: { otd: number; setupMin: number; tardiness: number; overflows: number };
  score: number;
  passed: boolean;
}

interface StressTestDef {
  id: string;
  name: string;
  description: string;
  disruption: {
    type: string;
    resource_id: string;
    start_day: number;
    end_day: number;
    capacity_factor?: number;
  };
}

const STRESS_TESTS: StressTestDef[] = [
  {
    id: 'ST-001',
    name: 'Avaria PRM039 (8h)',
    description: 'Máquina PRM039 fica indisponível durante 1 dia',
    disruption: { type: 'machine_down', resource_id: 'PRM039', start_day: 0, end_day: 0 },
  },
  {
    id: 'ST-002',
    name: 'Fornecedor atrasa 3 dias',
    description: 'Todas as deadlines deslocadas +3 dias (simula atraso de material)',
    disruption: {
      type: 'demand_change',
      resource_id: 'all',
      start_day: 0,
      end_day: 3,
      capacity_factor: 0,
    },
  },
  {
    id: 'ST-003',
    name: 'Procura +20%',
    description: 'Toda a procura aumenta 20%',
    disruption: {
      type: 'demand_change',
      resource_id: 'all',
      start_day: 0,
      end_day: 80,
      capacity_factor: 1.2,
    },
  },
  {
    id: 'ST-004',
    name: '2 operadores faltam',
    description: 'PG1 perde 2 operadores no turno X',
    disruption: {
      type: 'machine_down',
      resource_id: 'PRM019',
      start_day: 0,
      end_day: 0,
      capacity_factor: 0.5,
    },
  },
  {
    id: 'ST-005',
    name: 'Rejeição sobe 5%',
    description: 'Taxa de rejeição aumenta — necessário produzir 5% mais peças',
    disruption: {
      type: 'demand_change',
      resource_id: 'all',
      start_day: 0,
      end_day: 80,
      capacity_factor: 1.05,
    },
  },
  {
    id: 'ST-006',
    name: 'Falha energia 2h',
    description: 'Todas as máquinas perdem 120min de capacidade no dia 0',
    disruption: {
      type: 'machine_down',
      resource_id: 'all',
      start_day: 0,
      end_day: 0,
      capacity_factor: 0.85,
    },
  },
];

async function runSingleTest(
  def: StressTestDef,
  blocks: Block[],
  baselineMetrics: OptResult,
): Promise<StressTestResult> {
  const response = await scheduleReplanApi(
    {
      blocks: blocks as unknown as Record<string, unknown>[],
      disruption: def.disruption,
    },
    60_000,
  );

  const scoreData = (response.score ?? {}) as Record<string, number>;
  const stressedOtd = scoreData.otdDelivery ?? scoreData.otd_delivery ?? 0;
  const stressedSetup = scoreData.setupMin ?? scoreData.setup_min ?? 0;
  const stressedTardiness = scoreData.tardinessDays ?? scoreData.tardiness_days ?? 0;
  const stressedOverflows = scoreData.overflows ?? 0;

  const baseOTD = baselineMetrics.otdDelivery || 1;
  const rawScore = Math.min(10, Math.max(0, (stressedOtd / baseOTD) * 10));

  return {
    id: def.id,
    name: def.name,
    description: def.description,
    baseline: {
      otd: baselineMetrics.otdDelivery,
      setupMin: baselineMetrics.setupMin,
      tardiness: baselineMetrics.tardinessDays,
      overflows: baselineMetrics.overflows,
    },
    stressed: {
      otd: stressedOtd,
      setupMin: stressedSetup,
      tardiness: stressedTardiness,
      overflows: stressedOverflows,
    },
    score: Math.round(rawScore * 10) / 10,
    passed: stressedOtd > 85,
  };
}

export function useStressTest(
  _data: EngineData | null,
  blocks: Block[],
  _allOps: EOp[],
  baselineMetrics: OptResult | null,
) {
  const [results, setResults] = useState<StressTestResult[]>([]);
  const [running, setRunning] = useState(false);

  const fragilityScore = useMemo(() => {
    if (results.length === 0) return 0;
    return Math.round((results.reduce((a, r) => a + r.score, 0) / results.length) * 10) / 10;
  }, [results]);

  const runAll = useCallback(async () => {
    if (!baselineMetrics || blocks.length === 0) return;
    const nikufraData = getCachedNikufraData();
    if (!nikufraData) return;

    setRunning(true);
    const allResults: StressTestResult[] = [];

    for (const def of STRESS_TESTS) {
      try {
        const result = await runSingleTest(def, blocks, baselineMetrics);
        allResults.push(result);
        setResults([...allResults]);
      } catch {
        allResults.push({
          id: def.id,
          name: def.name,
          description: def.description,
          baseline: { otd: 0, setupMin: 0, tardiness: 0, overflows: 0 },
          stressed: { otd: 0, setupMin: 0, tardiness: 0, overflows: 0 },
          score: 0,
          passed: false,
        });
        setResults([...allResults]);
      }
    }
    setRunning(false);
  }, [blocks, baselineMetrics]);

  const runSingle = useCallback(
    async (id: string) => {
      if (!baselineMetrics || blocks.length === 0) return;
      const def = STRESS_TESTS.find((t) => t.id === id);
      if (!def) return;

      setRunning(true);
      try {
        const result = await runSingleTest(def, blocks, baselineMetrics);
        setResults((prev) => {
          const idx = prev.findIndex((r) => r.id === id);
          if (idx >= 0) {
            const next = [...prev];
            next[idx] = result;
            return next;
          }
          return [...prev, result];
        });
      } catch {
        // Keep previous result
      }
      setRunning(false);
    },
    [blocks, baselineMetrics],
  );

  return { results, fragilityScore, running, runAll, runSingle };
}

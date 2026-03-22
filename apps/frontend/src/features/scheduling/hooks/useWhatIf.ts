/**
 * useWhatIf — What-if scenario analysis via backend /v1/schedule/what-if.
 */

import { useCallback, useMemo, useState } from 'react';
import type {
  AreaCaps,
  DispatchRule,
  EngineData,
  ETool,
  MoveableOp,
  ObjectiveProfile,
  OptResult,
  QuickValidateResult,
} from '@/domain/types/scheduling';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import type { WhatIfMutation } from '../../../lib/api';
import { scheduleWhatIfApi } from '../../../lib/api';

export interface WhatIfScenario {
  t1: number;
  p1: number;
  t2: number;
  p2: number;
  seed: number;
}

export interface WhatIfState {
  sc: WhatIfScenario;
  N: number;
  dispatchRule: DispatchRule;
  objProfile: string;
  res: { top3: OptResult[]; moveable: MoveableOp[] } | null;
  run: boolean;
  prog: number;
  editingDown: { type: 'machine' | 'tool'; id: string } | null;
  wdi: number[];
  wiDownStartDay: number;
  wiDownEndDay: number;
  sel: number;
  showHistory: boolean;
  showCompare: boolean;
  diffPair: [string, string] | null;
  focusT: ETool[];
  areaCaps: AreaCaps;
  avOps: number;
  selBlocks: OptResult['blocks'];
  qv: QuickValidateResult;
}

export interface WhatIfActions {
  setSc: React.Dispatch<React.SetStateAction<WhatIfScenario>>;
  setN: React.Dispatch<React.SetStateAction<number>>;
  setDispatchRule: React.Dispatch<React.SetStateAction<DispatchRule>>;
  setObjProfile: React.Dispatch<React.SetStateAction<string>>;
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
  setWiDownStartDay: React.Dispatch<React.SetStateAction<number>>;
  setWiDownEndDay: React.Dispatch<React.SetStateAction<number>>;
  setSel: React.Dispatch<React.SetStateAction<number>>;
  setShowHistory: React.Dispatch<React.SetStateAction<boolean>>;
  setShowCompare: React.Dispatch<React.SetStateAction<boolean>>;
  setDiffPair: React.Dispatch<React.SetStateAction<[string, string] | null>>;
  setRes: React.Dispatch<React.SetStateAction<WhatIfState['res']>>;
  optimize: () => void;
}

export function useWhatIf(
  data: EngineData,
  _profiles: ObjectiveProfile[],
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>,
  _replanTimelines: unknown,
): { state: WhatIfState; actions: WhatIfActions } {
  const { machines, tools, focusIds } = data;

  const [sc, setSc] = useState<WhatIfScenario>({ t1: 6, p1: 2, t2: 8, p2: 3, seed: 42 });
  const [N, setN] = useState(300);
  const [dispatchRule, setDispatchRule] = useState<DispatchRule>('EDD');
  const [objProfile, setObjProfile] = useState<string>('balanced');
  const [res, setRes] = useState<{
    top3: OptResult[];
    moveable: MoveableOp[];
  } | null>(null);
  const [run, setRun] = useState(false);
  const [prog, setProg] = useState(0);
  const [editingDown, setEditingDown] = useState<{ type: 'machine' | 'tool'; id: string } | null>(
    null,
  );
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );
  const [wiDownStartDay, setWiDownStartDay] = useState(() => wdi[0] ?? 0);
  const [wiDownEndDay, setWiDownEndDay] = useState(() => wdi[0] ?? 0);
  const [sel, setSel] = useState(0);
  const [showHistory, setShowHistory] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [diffPair, setDiffPair] = useState<[string, string] | null>(null);

  const focusT = tools.filter(
    (t) => focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
  );
  const areaCaps: AreaCaps = { PG1: sc.t1 + sc.p1, PG2: sc.t2 + sc.p2 };
  const avOps = areaCaps.PG1 + areaCaps.PG2;

  const optimize = useCallback(async () => {
    const nikufraData = getCachedNikufraData();
    if (!nikufraData) return;

    setRun(true);
    setProg(10);
    setRes(null);
    setSel(0);

    try {
      // Build mutations from resource down-days
      const mutations: Record<string, unknown>[] = [];
      for (const m of machines) {
        const downDays = getResourceDownDays('machine', m.id);
        if (downDays.size > 0) {
          const days = Array.from(downDays).sort((a, b) => a - b);
          mutations.push({
            type: 'machine_down',
            resource_id: m.id,
            start_day: days[0],
            end_day: days[days.length - 1],
          });
        }
      }
      for (const t of focusT) {
        const downDays = getResourceDownDays('tool', t.id);
        if (downDays.size > 0) {
          const days = Array.from(downDays).sort((a, b) => a - b);
          mutations.push({
            type: 'tool_down',
            resource_id: t.id,
            start_day: days[0],
            end_day: days[days.length - 1],
          });
        }
      }

      setProg(30);
      const response = await scheduleWhatIfApi(
        { nikufra_data: nikufraData, mutations: mutations as WhatIfMutation[] },
        120_000,
      );
      setProg(90);

      // Map response to OptResult shape
      const scenario = response.scenario as Record<string, unknown> | null;
      const scenarioBlocks = (scenario?.blocks ?? []) as unknown as OptResult['blocks'];
      const scenarioScore = (scenario?.score ?? {}) as Record<string, number>;

      const top3: OptResult[] = [
        {
          blocks: scenarioBlocks,
          moves: [],
          score: scenarioScore.score ?? 0,
          otd: scenarioScore.otd ?? 0,
          otdDelivery: scenarioScore.otdDelivery ?? scenarioScore.otd_delivery ?? 0,
          produced: scenarioScore.produced ?? 0,
          totalDemand: scenarioScore.totalDemand ?? scenarioScore.total_demand ?? 0,
          lostPcs: scenarioScore.lostPcs ?? scenarioScore.lost_pcs ?? 0,
          setupCount: scenarioScore.setupCount ?? scenarioScore.setup_count ?? 0,
          setupMin: scenarioScore.setupMin ?? scenarioScore.setup_min ?? 0,
          peakOps: scenarioScore.peakOps ?? scenarioScore.peak_ops ?? 0,
          overOps: scenarioScore.overOps ?? scenarioScore.over_ops ?? 0,
          overflows: scenarioScore.overflows ?? 0,
          capUtil: scenarioScore.capUtil ?? scenarioScore.cap_util ?? 0,
          capVar: scenarioScore.capVar ?? scenarioScore.cap_var ?? 0,
          tardinessDays: scenarioScore.tardinessDays ?? scenarioScore.tardiness_days ?? 0,
          setupByShift: { X: 0, Y: 0, Z: 0 },
          capByMachine: {},
          workforceDemand: [],
          label: 'What-If',
          deadlineFeasible: true,
        },
      ];

      setRes({ top3, moveable: [] });
      setProg(100);
    } catch {
      // Silently fail — user sees empty results
    }
    setRun(false);
  }, [machines, focusT, getResourceDownDays]);

  const selBlocks = res?.top3[sel]?.blocks ?? [];
  // Inline quick validate — count blocked/infeasible blocks (no engine dependency)
  const qv = useMemo((): QuickValidateResult => {
    let criticalCount = 0;
    let highCount = 0;
    const warnings: string[] = [];
    for (const b of selBlocks) {
      if (b.type === 'infeasible') criticalCount++;
      if (b.type === 'blocked') highCount++;
    }
    if (criticalCount > 0) warnings.push(`${criticalCount} operações infeasíveis`);
    if (highCount > 0) warnings.push(`${highCount} operações bloqueadas`);
    return { criticalCount, highCount, warnings };
  }, [selBlocks]);

  return {
    state: {
      sc,
      N,
      dispatchRule,
      objProfile,
      res,
      run,
      prog,
      editingDown,
      wdi,
      wiDownStartDay,
      wiDownEndDay,
      sel,
      showHistory,
      showCompare,
      diffPair,
      focusT,
      areaCaps,
      avOps,
      selBlocks,
      qv,
    },
    actions: {
      setSc,
      setN,
      setDispatchRule,
      setObjProfile,
      setEditingDown,
      setWiDownStartDay,
      setWiDownEndDay,
      setSel,
      setShowHistory,
      setShowCompare,
      setDiffPair,
      setRes,
      optimize,
    },
  };
}

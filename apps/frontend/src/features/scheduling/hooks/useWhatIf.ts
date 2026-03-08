import { useCallback, useMemo, useState } from 'react';

import type {
  AreaCaps,
  DispatchRule,
  EngineData,
  ETool,
  ObjectiveProfile,
  OptResult,
  ScoreWeights,
} from '../../../lib/engine';
import {
  DEFAULT_WORKFORCE_CONFIG,
  type moveableOps,
  quickValidate,
  runOptimization,
} from '../../../lib/engine';
import { useSettingsStore } from '../../../stores/useSettingsStore';

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
  res: { top3: OptResult[]; moveable: ReturnType<typeof moveableOps> } | null;
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
  qv: ReturnType<typeof quickValidate>;
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
  profiles: ObjectiveProfile[],
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>,
  replanTimelines: ReturnType<typeof import('../../../lib/engine').buildResourceTimelines> | null,
): { state: WhatIfState; actions: WhatIfActions } {
  const { machines, tools, ops, toolMap: TM, focusIds } = data;

  const [sc, setSc] = useState<WhatIfScenario>({ t1: 6, p1: 2, t2: 8, p2: 3, seed: 42 });
  const [N, setN] = useState(300);
  const [dispatchRule, setDispatchRule] = useState<DispatchRule>('EDD');
  const [objProfile, setObjProfile] = useState<string>('balanced');
  const [res, setRes] = useState<{
    top3: OptResult[];
    moveable: ReturnType<typeof moveableOps>;
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

  const optimize = useCallback(() => {
    setRun(true);
    setProg(0);
    setRes(null);
    setSel(0);
    const bM = Object.fromEntries(
      machines.map((m) => [
        m.id,
        getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
      ]),
    );
    const bT = Object.fromEntries(
      focusT.filter((t) => getResourceDownDays('tool', t.id).size > 0).map((t) => [t.id, 'down']),
    );
    const profile = profiles.find((p) => p.id === objProfile);
    const wts = profile ? { ...profile.weights } : null;
    const opt = runOptimization({
      ops,
      mSt: bM,
      tSt: bT,
      machines,
      TM,
      focusIds,
      tools,
      workforceConfig: data.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
      weights: wts ? (wts as Partial<ScoreWeights>) : undefined,
      seed: sc.seed,
      workdays: data.workdays,
      nDays: data.nDays,
      rule: dispatchRule,
      N,
      K: 3,
      thirdShift: data.thirdShift ?? useSettingsStore.getState().thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      twinValidationReport: data.twinValidationReport,
      dates: data.dates,
      orderBased: data.orderBased,
    });
    opt.run(
      (top3) => {
        setRes({ top3, moveable: opt.moveable });
        setRun(false);
      },
      (p) => setProg(p),
    );
  }, [
    sc,
    N,
    machines,
    ops,
    TM,
    focusIds,
    tools,
    dispatchRule,
    objProfile,
    data,
    replanTimelines,
    getResourceDownDays,
    focusT,
    profiles,
  ]);

  const selBlocks = res?.top3[sel]?.blocks ?? [];
  const qv = useMemo(() => quickValidate(selBlocks, machines, TM), [selBlocks, machines, TM]);

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

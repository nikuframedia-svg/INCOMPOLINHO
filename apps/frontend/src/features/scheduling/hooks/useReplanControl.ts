import { useCallback, useMemo, useRef, useState } from 'react';
import { useSchedulingWorker } from '../../../hooks/useSchedulingWorker';
import type {
  AlternativeAction,
  AutoReplanConfig,
  AutoReplanResult,
  Block,
  DispatchRule,
  EngineData,
  EOp,
  FailureEvent,
  ImpactReport,
  MoveAction,
  ObjectiveProfile,
  OptimizationInput,
  OptResult,
  ReplanActionDetail,
  ReplanSimulation,
  SAInput,
  ScoreWeights,
} from '../../../lib/engine';
import {
  analyzeAllFailures,
  applyAlternative,
  autoReplan,
  cascadingReplan,
  DEFAULT_AUTO_REPLAN_CONFIG,
  DEFAULT_WORKFORCE_CONFIG,
  genDecisions,
  getReplanActions,
  moveableOps,
  quickValidate,
  runOptimization,
  simulateWithout,
  undoReplanActions,
} from '../../../lib/engine';
import { useSettingsStore } from '../../../stores/useSettingsStore';
import { useToastStore } from '../../../stores/useToastStore';

export interface ReplanControlState {
  xai: string | null;
  editingDown: { type: 'machine' | 'tool'; id: string } | null;
  // Auto-Replan
  arResult: AutoReplanResult | null;
  arActions: ReplanActionDetail[];
  arRunning: boolean;
  arSim: ReplanSimulation | null;
  arSimId: string | null;
  arExclude: Set<string>;
  wdi: number[];
  downStartDay: number;
  downEndDay: number;
  arDayFrom: number;
  arDayTo: number;
  arExpanded: string | null;
  arShowExclude: boolean;
  // Failures
  failures: FailureEvent[];
  failureImpacts: ImpactReport[];
  showFailureForm: boolean;
  ffResType: 'machine' | 'tool';
  ffResId: string;
  ffSev: 'total' | 'partial' | 'degraded';
  ffCap: number;
  ffStartDay: number;
  ffEndDay: number;
  ffDesc: string;
  cascRunning: boolean;
  // Optimization
  optRunning: boolean;
  optResults: OptResult[];
  optProgress: number;
  optN: number;
  optProfile: string;
  optMoveable: ReturnType<typeof moveableOps>;
  // Simulated Annealing
  saRunning: boolean;
  saProgress: number | null;
  saError: string | null;
  // Rush Orders
  roTool: string;
  roQty: number;
  roDeadline: number;
  // Derived
  blockCountByMachine: Record<string, number>;
  decs: ReturnType<typeof genDecisions>;
  qv: ReturnType<typeof quickValidate>;
}

export interface ReplanControlActions {
  setXai: React.Dispatch<React.SetStateAction<string | null>>;
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
  setArExclude: React.Dispatch<React.SetStateAction<Set<string>>>;
  setDownStartDay: React.Dispatch<React.SetStateAction<number>>;
  setDownEndDay: React.Dispatch<React.SetStateAction<number>>;
  setArDayFrom: React.Dispatch<React.SetStateAction<number>>;
  setArDayTo: React.Dispatch<React.SetStateAction<number>>;
  setArExpanded: React.Dispatch<React.SetStateAction<string | null>>;
  setArShowExclude: React.Dispatch<React.SetStateAction<boolean>>;
  setShowFailureForm: React.Dispatch<React.SetStateAction<boolean>>;
  setFfResType: React.Dispatch<React.SetStateAction<'machine' | 'tool'>>;
  setFfResId: React.Dispatch<React.SetStateAction<string>>;
  setFfSev: React.Dispatch<React.SetStateAction<'total' | 'partial' | 'degraded'>>;
  setFfCap: React.Dispatch<React.SetStateAction<number>>;
  setFfStartDay: React.Dispatch<React.SetStateAction<number>>;
  setFfEndDay: React.Dispatch<React.SetStateAction<number>>;
  setFfDesc: React.Dispatch<React.SetStateAction<string>>;
  setOptN: React.Dispatch<React.SetStateAction<number>>;
  setOptProfile: React.Dispatch<React.SetStateAction<string>>;
  setRoTool: React.Dispatch<React.SetStateAction<string>>;
  setRoQty: React.Dispatch<React.SetStateAction<number>>;
  setRoDeadline: React.Dispatch<React.SetStateAction<number>>;
  setArResult: React.Dispatch<React.SetStateAction<AutoReplanResult | null>>;
  setOptResults: React.Dispatch<React.SetStateAction<OptResult[]>>;
  // Callbacks
  runAutoReplan: () => void;
  handleArUndo: (decisionId: string) => void;
  handleArAlt: (decisionId: string, alt: AlternativeAction) => void;
  handleArSimulate: (decisionId: string) => void;
  handleArUndoAll: () => void;
  handleArApplyAll: () => void;
  addFailure: () => void;
  removeFailure: (id: string) => void;
  runCascadingReplan: () => void;
  runOpt: () => void;
  runSA: () => void;
  cancelSA: () => void;
  applyOptResult: (r: OptResult) => void;
  addRushOrder: () => void;
  removeRushOrder: (idx: number) => void;
}

export function useReplanControl(
  data: EngineData,
  blocks: Block[],
  allOps: EOp[],
  mSt: Record<string, string>,
  tSt: Record<string, string>,
  moves: MoveAction[],
  applyMove: (opId: string, toM: string) => void,
  replanTimelines: ReturnType<typeof import('../../../lib/engine').buildResourceTimelines> | null,
  profiles: ObjectiveProfile[],
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >,
): { state: ReplanControlState; actions: ReplanControlActions } {
  const { machines, tools, ops, toolMap: TM, focusIds } = data;

  // Block count per machine
  const blockCountByMachine = useMemo(() => {
    const map: Record<string, number> = {};
    for (const b of blocks) {
      if (b.type !== 'blocked') map[b.machineId] = (map[b.machineId] ?? 0) + 1;
    }
    return map;
  }, [blocks]);

  const [xai, setXai] = useState<string | null>(null);
  const [editingDown, setEditingDown] = useState<{ type: 'machine' | 'tool'; id: string } | null>(
    null,
  );

  // Auto-Replan state
  const [arResult, setArResult] = useState<AutoReplanResult | null>(null);
  const [arActions, setArActions] = useState<ReplanActionDetail[]>([]);
  const [arRunning, setArRunning] = useState(false);
  const [arSim, setArSim] = useState<ReplanSimulation | null>(null);
  const [arSimId, setArSimId] = useState<string | null>(null);
  const [arExclude, setArExclude] = useState<Set<string>>(new Set());
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );
  const [downStartDay, setDownStartDay] = useState(() => wdi[0] ?? 0);
  const [downEndDay, setDownEndDay] = useState(() => wdi[0] ?? 0);
  const [arDayFrom, setArDayFrom] = useState(() => wdi[0] ?? 0);
  const [arDayTo, setArDayTo] = useState(() => wdi[wdi.length - 1] ?? data.nDays - 1);
  const [arExpanded, setArExpanded] = useState<string | null>(null);
  const [arShowExclude, setArShowExclude] = useState(false);
  const arInputRef = useRef<unknown>(null);

  const buildArInput = useCallback(() => {
    const settings = useSettingsStore.getState();
    const rule = (settings.dispatchRule || 'EDD') as DispatchRule;
    return {
      ops: allOps,
      mSt,
      tSt,
      moves: [] as MoveAction[],
      machines: data.machines,
      toolMap: data.toolMap,
      workdays: data.workdays,
      nDays: data.nDays,
      workforceConfig: data.workforceConfig,
      rule,
      thirdShift: data.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      dates: data.dates,
      twinValidationReport: data.twinValidationReport,
      orderBased: data.orderBased,
    };
  }, [data, allOps, mSt, tSt, replanTimelines]);

  const runAutoReplan = useCallback(() => {
    setArRunning(true);
    setArSim(null);
    setArSimId(null);
    setTimeout(() => {
      const input = buildArInput();
      const excludeOpIds = allOps.filter((o) => arExclude.has(o.t)).map((o) => o.id);
      const config: Partial<AutoReplanConfig> = {
        ...DEFAULT_AUTO_REPLAN_CONFIG,
        excludeOps: excludeOpIds,
      };
      try {
        const result = autoReplan(input, config as AutoReplanConfig);
        const actions = getReplanActions(result);
        arInputRef.current = input;
        setArResult(result);
        setArActions(actions);
      } catch (e) {
        useToastStore
          .getState()
          .actions.addToast(
            `Erro no auto-replan: ${e instanceof Error ? e.message : String(e)}`,
            'error',
            5000,
          );
      }
      setArRunning(false);
    }, 0);
  }, [buildArInput, allOps, arExclude]);

  const handleArUndo = useCallback(
    (decisionId: string) => {
      if (!arInputRef.current || !arResult) return;
      try {
        const inp = arInputRef.current as Parameters<typeof undoReplanActions>[0];
        const newResult = undoReplanActions(inp, arResult, [decisionId]);
        setArResult(newResult);
        setArActions(getReplanActions(newResult));
        setArSim(null);
        setArSimId(null);
        useToastStore.getState().actions.addToast('Acção desfeita', 'success', 3000);
      } catch (e) {
        useToastStore
          .getState()
          .actions.addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 4000);
      }
    },
    [arResult],
  );

  const handleArAlt = useCallback(
    (decisionId: string, alt: AlternativeAction) => {
      if (!arInputRef.current || !arResult) return;
      try {
        const inp = arInputRef.current as Parameters<typeof applyAlternative>[0];
        const newResult = applyAlternative(inp, arResult, decisionId, alt);
        setArResult(newResult);
        setArActions(getReplanActions(newResult));
        setArSim(null);
        setArSimId(null);
        useToastStore.getState().actions.addToast('Alternativa aplicada', 'success', 3000);
      } catch (e) {
        useToastStore
          .getState()
          .actions.addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 4000);
      }
    },
    [arResult],
  );

  const handleArSimulate = useCallback(
    (decisionId: string) => {
      if (!arInputRef.current || !arResult) return;
      try {
        const inp = arInputRef.current as Parameters<typeof simulateWithout>[0];
        const sim = simulateWithout(inp, arResult, [decisionId]);
        setArSim(sim);
        setArSimId(decisionId);
      } catch (e) {
        useToastStore
          .getState()
          .actions.addToast(
            `Erro na simulação: ${e instanceof Error ? e.message : String(e)}`,
            'error',
            4000,
          );
      }
    },
    [arResult],
  );

  const handleArUndoAll = useCallback(() => {
    if (!arInputRef.current || !arResult || arActions.length === 0) return;
    try {
      const inp = arInputRef.current as Parameters<typeof undoReplanActions>[0];
      const allIds = arActions.map((a) => a.decisionId);
      const newResult = undoReplanActions(inp, arResult, allIds);
      setArResult(newResult);
      setArActions(getReplanActions(newResult));
      setArSim(null);
      setArSimId(null);
    } catch (e) {
      useToastStore
        .getState()
        .actions.addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 4000);
    }
  }, [arResult, arActions]);

  const handleArApplyAll = useCallback(() => {
    if (!arResult) return;
    for (const mv of arResult.autoMoves) applyMove(mv.opId, mv.toM);
    useToastStore
      .getState()
      .actions.addToast(
        `Auto-replan aplicado: ${arResult.autoMoves.length} movimentos`,
        'success',
        5000,
      );
  }, [arResult, applyMove]);

  // Failure/Breakdown state
  const [failures, setFailures] = useState<FailureEvent[]>([]);
  const [failureImpacts, setFailureImpacts] = useState<ImpactReport[]>([]);
  const [showFailureForm, setShowFailureForm] = useState(false);
  const [ffResType, setFfResType] = useState<'machine' | 'tool'>('machine');
  const [ffResId, setFfResId] = useState('');
  const [ffSev, setFfSev] = useState<'total' | 'partial' | 'degraded'>('total');
  const [ffCap, setFfCap] = useState(50);
  const [ffStartDay, setFfStartDay] = useState(() => wdi[0] ?? 0);
  const [ffEndDay, setFfEndDay] = useState(() => wdi[0] ?? 0);
  const [ffDesc, setFfDesc] = useState('');

  const addFailure = useCallback(() => {
    if (!ffResId) return;
    const f: FailureEvent = {
      id: `f-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      resourceType: ffResType,
      resourceId: ffResId,
      startDay: ffStartDay,
      endDay: ffEndDay,
      startShift: null,
      endShift: null,
      severity: ffSev,
      capacityFactor: ffSev === 'total' ? 0 : ffCap / 100,
      description: ffDesc || undefined,
    };
    const newF = [...failures, f];
    setFailures(newF);
    setFailureImpacts(analyzeAllFailures(newF, blocks, data.nDays));
    setShowFailureForm(false);
    setFfDesc('');
  }, [
    ffResType,
    ffResId,
    ffSev,
    ffCap,
    ffStartDay,
    ffEndDay,
    ffDesc,
    failures,
    blocks,
    data.nDays,
  ]);

  const removeFailure = useCallback(
    (id: string) => {
      const newF = failures.filter((f) => f.id !== id);
      setFailures(newF);
      setFailureImpacts(newF.length > 0 ? analyzeAllFailures(newF, blocks, data.nDays) : []);
    },
    [failures, blocks, data.nDays],
  );

  const [cascRunning, setCascRunning] = useState(false);
  const runCascadingReplan = useCallback(() => {
    if (failures.length === 0) return;
    setCascRunning(true);
    setTimeout(() => {
      const input = buildArInput();
      try {
        const result = cascadingReplan(
          input as Parameters<typeof cascadingReplan>[0],
          failures,
          blocks,
        );
        for (const mv of result.mitigationMoves) applyMove(mv.opId, mv.toM);
        useToastStore
          .getState()
          .actions.addToast(
            `Replan cascata: ${result.mitigationMoves.length} movimentos, ${result.unrecoverableBlocks.length} irrecuperáveis`,
            result.unrecoverableBlocks.length > 0 ? 'warning' : 'success',
            5000,
          );
      } catch (e) {
        useToastStore
          .getState()
          .actions.addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 5000);
      }
      setCascRunning(false);
    }, 0);
  }, [failures, blocks, buildArInput, applyMove]);

  // Optimization state
  const [optRunning, setOptRunning] = useState(false);
  const [optResults, setOptResults] = useState<OptResult[]>([]);
  const [optProgress, setOptProgress] = useState(0);
  const [optN, setOptN] = useState(200);
  const [optProfile, setOptProfile] = useState('balanced');
  const optMoveable = useMemo(() => moveableOps(allOps, mSt, tSt, TM), [allOps, mSt, tSt, TM]);

  const runOpt = useCallback(() => {
    setOptRunning(true);
    setOptProgress(0);
    setOptResults([]);
    const settings = useSettingsStore.getState();
    const rule = (settings.dispatchRule || 'EDD') as DispatchRule;
    const prof = profiles.find((p) => p.id === optProfile);
    const weights = prof ? (prof.weights as unknown as ScoreWeights) : undefined;
    const input: OptimizationInput = {
      ops: allOps,
      mSt,
      tSt,
      machines,
      TM,
      focusIds,
      tools,
      workforceConfig: data.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
      weights,
      seed: 42,
      workdays: data.workdays,
      nDays: data.nDays,
      rule,
      baselineBlocks: blocks,
      N: optN,
      K: 5,
      thirdShift: data.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      twinValidationReport: data.twinValidationReport,
      dates: data.dates,
      orderBased: data.orderBased,
    };
    try {
      const setup = runOptimization(input);
      setup.run(
        (batch) => {
          setOptResults(batch);
        },
        (pct) => {
          setOptProgress(pct);
        },
      );
      setOptResults(setup.top);
    } catch (e) {
      useToastStore
        .getState()
        .actions.addToast(
          `Erro na optimização: ${e instanceof Error ? e.message : String(e)}`,
          'error',
          5000,
        );
    }
    setOptRunning(false);
  }, [
    allOps,
    mSt,
    tSt,
    machines,
    TM,
    focusIds,
    tools,
    data,
    blocks,
    optN,
    optProfile,
    replanTimelines,
    profiles,
  ]);

  const applyOptResult = useCallback(
    (r: OptResult) => {
      for (const mv of r.moves) applyMove(mv.opId, mv.toM);
      useToastStore
        .getState()
        .actions.addToast(`Optimização aplicada: ${r.moves.length} movimentos`, 'success', 5000);
    },
    [applyMove],
  );

  // Simulated Annealing via Web Worker
  const {
    runSA: workerRunSA,
    progress: saProgress,
    isRunning: saRunning,
    error: saError,
    cancel: cancelSA,
  } = useSchedulingWorker();

  const runSA = useCallback(() => {
    const settings = useSettingsStore.getState();
    const rule = (settings.dispatchRule || 'ATCS') as DispatchRule;

    const saInput: SAInput = {
      ops: allOps,
      mSt,
      tSt,
      machines,
      TM,
      workdays: data.workdays,
      nDays: data.nDays,
      workforceConfig: data.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
      rule,
      thirdShift: data.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      twinValidationReport: data.twinValidationReport,
      dates: data.dates,
      orderBased: data.orderBased,
      initialBlocks: blocks,
      initialMoves: moves,
    };

    workerRunSA(saInput, { maxIter: 10_000 })
      .then((result) => {
        if (result.improved) {
          // Apply SA moves
          for (const mv of result.moves) applyMove(mv.opId, mv.toM);
          useToastStore
            .getState()
            .actions.addToast(
              `SA concluido: score ${result.metrics.score.toFixed(0)} (${result.accepted} aceites em ${result.iterations} iteracoes)`,
              'success',
              5000,
            );
        } else {
          useToastStore
            .getState()
            .actions.addToast('SA concluido: sem melhoria sobre solucao actual', 'info', 4000);
        }
      })
      .catch((err) => {
        useToastStore
          .getState()
          .actions.addToast(
            `Erro SA: ${err instanceof Error ? err.message : String(err)}`,
            'error',
            5000,
          );
      });
  }, [
    allOps,
    mSt,
    tSt,
    machines,
    TM,
    data,
    blocks,
    moves,
    replanTimelines,
    workerRunSA,
    applyMove,
  ]);

  // Rush Order form state
  const [roTool, setRoTool] = useState('');
  const [roQty, setRoQty] = useState(500);
  const [roDeadline, setRoDeadline] = useState(() => wdi[2] ?? 2);

  const addRushOrder = useCallback(() => {
    if (!roTool) return;
    const matchOp = ops.find((o) => o.t === roTool);
    const sku = matchOp?.sku ?? roTool;
    setRushOrders((prev) => [...prev, { toolId: roTool, sku, qty: roQty, deadline: roDeadline }]);
    setRoTool('');
    useToastStore
      .getState()
      .actions.addToast(`Rush order adicionada: ${roTool} · ${roQty} pcs`, 'success', 3000);
  }, [roTool, roQty, roDeadline, ops, setRushOrders]);

  const removeRushOrder = useCallback(
    (idx: number) => {
      setRushOrders((prev) => prev.filter((_, i) => i !== idx));
    },
    [setRushOrders],
  );

  const decs = useMemo(
    () => genDecisions(allOps, mSt, tSt, moves, blocks, machines, TM, focusIds, tools),
    [allOps, mSt, tSt, moves, blocks, machines, TM, focusIds, tools],
  );
  const qv = useMemo(() => quickValidate(blocks, machines, TM), [blocks, machines, TM]);

  return {
    state: {
      xai,
      editingDown,
      arResult,
      arActions,
      arRunning,
      arSim,
      arSimId,
      arExclude,
      wdi,
      downStartDay,
      downEndDay,
      arDayFrom,
      arDayTo,
      arExpanded,
      arShowExclude,
      failures,
      failureImpacts,
      showFailureForm,
      ffResType,
      ffResId,
      ffSev,
      ffCap,
      ffStartDay,
      ffEndDay,
      ffDesc,
      cascRunning,
      optRunning,
      optResults,
      optProgress,
      optN,
      optProfile,
      optMoveable,
      saRunning,
      saProgress,
      saError,
      roTool,
      roQty,
      roDeadline,
      blockCountByMachine,
      decs,
      qv,
    },
    actions: {
      setXai,
      setEditingDown,
      setArExclude,
      setDownStartDay,
      setDownEndDay,
      setArDayFrom,
      setArDayTo,
      setArExpanded,
      setArShowExclude,
      setShowFailureForm,
      setFfResType,
      setFfResId,
      setFfSev,
      setFfCap,
      setFfStartDay,
      setFfEndDay,
      setFfDesc,
      setOptN,
      setOptProfile,
      setRoTool,
      setRoQty,
      setRoDeadline,
      setArResult,
      setOptResults,
      runAutoReplan,
      handleArUndo,
      handleArAlt,
      handleArSimulate,
      handleArUndoAll,
      handleArApplyAll,
      addFailure,
      removeFailure,
      runCascadingReplan,
      runOpt,
      runSA,
      cancelSA,
      applyOptResult,
      addRushOrder,
      removeRushOrder,
    },
  };
}

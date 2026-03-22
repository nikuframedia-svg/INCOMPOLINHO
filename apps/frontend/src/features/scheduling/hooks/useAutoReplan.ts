/**
 * useAutoReplan — Auto-replan state and actions.
 *
 * Manages AR strategies via backend /v1/schedule/replan API.
 * All scheduling logic is backend-only (CP-SAT).
 */

import { useCallback, useMemo, useState } from 'react';
import type {
  AlternativeAction,
  AutoReplanResult,
  EngineData,
  EOp,
  MoveAction,
  ReplanActionDetail,
  ReplanSimulation,
} from '@/domain/types/scheduling';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import type { ScheduleBlock } from '../../../lib/api';
import { scheduleReplanApi } from '../../../lib/api';
import { useSettingsStore } from '../../../stores/useSettingsStore';
import { useToastStore } from '../../../stores/useToastStore';

export interface AutoReplanState {
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
}

export interface AutoReplanActions {
  setArExclude: React.Dispatch<React.SetStateAction<Set<string>>>;
  setDownStartDay: React.Dispatch<React.SetStateAction<number>>;
  setDownEndDay: React.Dispatch<React.SetStateAction<number>>;
  setArDayFrom: React.Dispatch<React.SetStateAction<number>>;
  setArDayTo: React.Dispatch<React.SetStateAction<number>>;
  setArExpanded: React.Dispatch<React.SetStateAction<string | null>>;
  setArShowExclude: React.Dispatch<React.SetStateAction<boolean>>;
  setArResult: React.Dispatch<React.SetStateAction<AutoReplanResult | null>>;
  runAutoReplan: () => void;
  handleArUndo: (decisionId: string) => void;
  handleArAlt: (decisionId: string, alt: AlternativeAction) => void;
  handleArSimulate: (decisionId: string) => void;
  handleArUndoAll: () => void;
  handleArApplyAll: () => void;
}

export function useAutoReplan(
  data: EngineData,
  _allOps: EOp[],
  mSt: Record<string, string>,
  _tSt: Record<string, string>,
  applyMove: (opId: string, toM: string) => void,
  _replanTimelines: unknown,
  setAppliedReplan: (result: AutoReplanResult | null) => void,
  onReplanComplete?: (info: {
    trigger: string;
    triggerType: string;
    strategy: string;
    strategyLabel: string;
    movesCount: number;
    moves: MoveAction[];
  }) => void,
): { state: AutoReplanState; actions: AutoReplanActions; buildArInput: () => unknown } {
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );

  const [arResult, setArResult] = useState<AutoReplanResult | null>(null);
  const [arActions, setArActions] = useState<ReplanActionDetail[]>([]);
  const [arRunning, setArRunning] = useState(false);
  const [arSim, setArSim] = useState<ReplanSimulation | null>(null);
  const [arSimId, setArSimId] = useState<string | null>(null);
  const [arExclude, setArExclude] = useState<Set<string>>(new Set());
  const [downStartDay, setDownStartDay] = useState(() => wdi[0] ?? 0);
  const [downEndDay, setDownEndDay] = useState(() => wdi[0] ?? 0);
  const [arDayFrom, setArDayFrom] = useState(() => wdi[0] ?? 0);
  const [arDayTo, setArDayTo] = useState(() => wdi[wdi.length - 1] ?? data.nDays - 1);
  const [arExpanded, setArExpanded] = useState<string | null>(null);
  const [arShowExclude, setArShowExclude] = useState(false);

  const buildArInput = useCallback(() => {
    const settings = useSettingsStore.getState();
    return {
      mSt,
      machines: data.machines,
      workdays: data.workdays,
      nDays: data.nDays,
      thirdShift: data.thirdShift ?? settings.thirdShiftDefault,
    };
  }, [data, mSt]);

  const runAutoReplan = useCallback(async () => {
    setArRunning(true);
    setArSim(null);
    setArSimId(null);
    try {
      const nikufraData = getCachedNikufraData();
      if (!nikufraData) throw new Error('No schedule data cached');

      // Find first down machine for disruption
      const downMachine =
        Object.entries(mSt).find(([, st]) => st === 'down')?.[0] ?? data.machines[0]?.id ?? '';

      const response = await scheduleReplanApi({
        blocks: [] as ScheduleBlock[],
        disruption: {
          type: 'breakdown',
          resource_id: downMachine,
          start_day: downStartDay,
          end_day: downEndDay,
        },
        settings: { nikufra_data: nikufraData },
      });

      const r = response as unknown as Record<string, unknown>;
      const resMoves = ((r.auto_moves ?? []) as unknown as MoveAction[]).map((mv) => ({
        opId: mv.opId,
        toM: mv.toM,
      }));

      const result: AutoReplanResult = {
        blocks: (response.blocks ?? []) as unknown as AutoReplanResult['blocks'],
        scheduleResult: { blocks: [], decisions: [], kpis: {} },
        actions: [],
        autoMoves: resMoves as MoveAction[],
        autoAdvances: [],
        overtimeActions: [],
        splitActions: [],
        thirdShiftActivated: false,
        unresolved: [],
        registry: null,
        decisions: (r.decisions ?? []) as AutoReplanResult['decisions'],
      };

      setArResult(result);
      setArActions([]);
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
  }, [mSt, data.machines, downStartDay, downEndDay]);

  const handleArUndo = useCallback((_decisionId: string) => {
    useToastStore
      .getState()
      .actions.addToast('Undo via backend — em desenvolvimento', 'info', 3000);
  }, []);

  const handleArAlt = useCallback((_decisionId: string, _alt: AlternativeAction) => {
    useToastStore
      .getState()
      .actions.addToast('Alternativa via backend — em desenvolvimento', 'info', 3000);
  }, []);

  const handleArSimulate = useCallback((_decisionId: string) => {
    useToastStore
      .getState()
      .actions.addToast('Simulação via backend — em desenvolvimento', 'info', 3000);
  }, []);

  const handleArUndoAll = useCallback(() => {
    setArResult(null);
    setArActions([]);
    setArSim(null);
    setArSimId(null);
  }, []);

  const handleArApplyAll = useCallback(() => {
    if (!arResult) return;
    setAppliedReplan(arResult);
    for (const mv of arResult.autoMoves) applyMove(mv.opId, mv.toM);
    const summary = [
      arResult.autoMoves.length > 0 && `${arResult.autoMoves.length} movimentos`,
      arResult.autoAdvances.length > 0 && `${arResult.autoAdvances.length} avanços`,
      arResult.overtimeActions.length > 0 && `${arResult.overtimeActions.length} horas extra`,
      arResult.splitActions.length > 0 && `${arResult.splitActions.length} splits`,
      arResult.thirdShiftActivated && '3º turno activado',
    ]
      .filter(Boolean)
      .join(', ');
    useToastStore
      .getState()
      .actions.addToast(`Auto-replan aplicado: ${summary || 'sem alterações'}`, 'success', 5000);
    onReplanComplete?.({
      trigger: 'Auto-Replan',
      triggerType: 'manual',
      strategy: 'auto_replan',
      strategyLabel: 'AUTO',
      movesCount: arResult.autoMoves.length,
      moves: arResult.autoMoves.map((mv) => ({ opId: mv.opId, toM: mv.toM })),
    });
  }, [arResult, applyMove, setAppliedReplan, onReplanComplete]);

  return {
    state: {
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
    },
    actions: {
      setArExclude,
      setDownStartDay,
      setDownEndDay,
      setArDayFrom,
      setArDayTo,
      setArExpanded,
      setArShowExclude,
      setArResult,
      runAutoReplan,
      handleArUndo,
      handleArAlt,
      handleArSimulate,
      handleArUndoAll,
      handleArApplyAll,
    },
    buildArInput,
  };
}

import { useCallback, useEffect, useRef, useState } from 'react';
import type { AutoReplanResult, EngineData, EOp, MoveAction } from '@/domain/types/scheduling';
import { useDataSource } from '../../../hooks/useDataSource';
import { invalidateScheduleCache, useScheduleData } from '../../../hooks/useScheduleData';
import { useReplanStore } from '../../../stores/useReplanStore';
import { useToastStore } from '../../../stores/useToastStore';
import { useScheduleFilters } from './useScheduleFilters';

export function useScheduleCore(initialView = 'plan') {
  const ds = useDataSource();
  // Use backend-computed schedule data (no client-side transformPlanState)
  const scheduleData = useScheduleData();
  const engineData = scheduleData.engine;
  const loading = scheduleData.loading;
  const error = scheduleData.error;

  const { state: filters, actions: filterActions } = useScheduleFilters(engineData);
  const { mSt, tSt, failureEvents, isScheduling, replanTimelines } = filters;
  const {
    setMSt,
    setTSt,
    toggleM,
    toggleT,
    setResourceDown,
    clearResourceDown,
    getResourceDownDays,
  } = filterActions;
  const [moves, setMoves] = useState<MoveAction[]>([]);
  const [view, setView] = useState(initialView);
  const [isSaving, setIsSaving] = useState(false);
  const [rushOrders, setRushOrders] = useState<
    Array<{ toolId: string; sku: string; qty: number; deadline: number }>
  >([]);
  const [isopBanner, setIsopBanner] = useState<string | null>(null);
  const prevOpsRef = useRef<EOp[] | null>(null);
  const [appliedReplan, setAppliedReplan] = useState<AutoReplanResult | null>(null);

  // Reset filters when engineData changes (replaces old loadData logic)
  const prevEngineRef = useRef<EngineData | null>(null);
  useEffect(() => {
    if (engineData && engineData !== prevEngineRef.current) {
      prevEngineRef.current = engineData;
      filterActions.resetFilters(engineData.machines);
      setMoves([]);
      setAppliedReplan(null);
      setIsopBanner(null);
      prevOpsRef.current = engineData.ops;
    }
  }, [engineData, filterActions.resetFilters]);

  const loadData = useCallback(() => {
    invalidateScheduleCache();
  }, []);

  const applyMove = useCallback(
    (opId: string, toM: string) =>
      setMoves((p) => (p.find((m) => m.opId === opId) ? p : [...p, { opId, toM }])),
    [],
  );
  const undoMove = useCallback(
    (opId: string) => setMoves((p) => p.filter((m) => m.opId !== opId)),
    [],
  );

  const handleApplyAndSave = useCallback(
    async (
      movesToApply?: MoveAction[],
      scenarioState?: { mSt: Record<string, string>; tSt: Record<string, string> },
    ) => {
      const applyMoves = movesToApply || moves;
      const appliedMSt = scenarioState?.mSt || mSt;
      const appliedTSt = scenarioState?.tSt || tSt;
      if (applyMoves.length === 0 && Object.values(appliedMSt).every((s) => s !== 'down')) return;
      if (ds.applyReplan) {
        setIsSaving(true);
        try {
          const backendMoves = applyMoves.map((mv) => {
            const origM = engineData?.ops.find((o) => o.id === mv.opId)?.m || '';
            return { op_id: mv.opId, from_machine: origM, to_machine: mv.toM };
          });
          const machineStatus: Record<string, string> = {};
          for (const [id, st] of Object.entries(appliedMSt)) {
            if (st === 'down') machineStatus[id] = 'down';
          }
          const toolStatus: Record<string, string> = {};
          for (const [id, st] of Object.entries(appliedTSt)) {
            if (st === 'down') toolStatus[id] = 'down';
          }
          await ds.applyReplan({
            moves: backendMoves,
            machine_status: machineStatus,
            tool_status: toolStatus,
            author: 'planner-001',
            description: `Replan: ${applyMoves.length} movimentos`,
          });
          await loadData();
          useToastStore
            .getState()
            .actions.addToast(
              `Replan aplicado: ${applyMoves.length} movimentos guardados`,
              'success',
              5000,
            );
          setView('plan');
        } catch (e) {
          useToastStore
            .getState()
            .actions.addToast(
              `Erro ao aplicar replan: ${e instanceof Error ? e.message : String(e)}`,
              'error',
              6000,
            );
        } finally {
          setIsSaving(false);
        }
      } else {
        if (scenarioState) {
          setMSt(scenarioState.mSt);
          setTSt(scenarioState.tSt);
        }
        setMoves(applyMoves);
        useToastStore
          .getState()
          .actions.addToast(`Plano aplicado: ${applyMoves.length} movimentos`, 'success', 5000);
        setView('plan');
      }
    },
    [ds, moves, mSt, tSt, engineData, loadData, setMSt, setTSt],
  );

  useEffect(() => {
    useReplanStore.getState().actions.setOnApplyCallback(loadData);
    return () => {
      useReplanStore.getState().actions.setOnApplyCallback(null);
    };
  }, [loadData]);

  return {
    engineData,
    loading,
    error,
    loadData,
    view,
    setView,
    mSt,
    tSt,
    toggleM,
    toggleT,
    setMSt,
    setTSt,
    moves,
    applyMove,
    undoMove,
    handleApplyAndSave,
    isSaving,
    rushOrders,
    setRushOrders,
    isopBanner,
    setIsopBanner,
    isScheduling,
    failureEvents,
    replanTimelines,
    setResourceDown,
    clearResourceDown,
    getResourceDownDays,
    appliedReplan,
    setAppliedReplan,
  };
}

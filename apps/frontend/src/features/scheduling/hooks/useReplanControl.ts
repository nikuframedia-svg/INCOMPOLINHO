/**
 * useReplanControl — Orchestrator hook that composes sub-hooks.
 *
 * Exports the same public interface as before for backward compatibility.
 */

import { useMemo, useState } from 'react';
import type { AutoReplanResult, Block, EngineData, EOp, MoveAction, ObjectiveProfile, QuickValidateResult, ReplanProposal } from '../../../lib/engine';
import { useScheduleData } from '../../../hooks/useScheduleData';
import type { AutoReplanActions, AutoReplanState } from './useAutoReplan';
import { useAutoReplan } from './useAutoReplan';
import type { FailureActions, FailureState } from './useFailureManagement';
import { useFailureManagement } from './useFailureManagement';
import type { OptimizationActions, OptimizationState } from './useOptimizationControl';
import { useOptimizationControl } from './useOptimizationControl';
import type { RushOrderActions, RushOrderState } from './useRushOrders';
import { useRushOrders } from './useRushOrders';

export interface ReplanControlState
  extends AutoReplanState,
    FailureState,
    OptimizationState,
    RushOrderState {
  xai: string | null;
  editingDown: { type: 'machine' | 'tool'; id: string } | null;
  blockCountByMachine: Record<string, number>;
  decs: ReplanProposal[];
  qv: QuickValidateResult | null;
}

export interface ReplanControlActions
  extends AutoReplanActions,
    FailureActions,
    OptimizationActions,
    RushOrderActions {
  setXai: React.Dispatch<React.SetStateAction<string | null>>;
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
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
  setAppliedReplan: (result: AutoReplanResult | null) => void,
  onReplanComplete?: (info: {
    trigger: string;
    triggerType: string;
    strategy: string;
    strategyLabel: string;
    movesCount: number;
    moves: MoveAction[];
  }) => void,
): { state: ReplanControlState; actions: ReplanControlActions } {
  // Shared state
  const [xai, setXai] = useState<string | null>(null);
  const [editingDown, setEditingDown] = useState<{ type: 'machine' | 'tool'; id: string } | null>(
    null,
  );

  const blockCountByMachine = useMemo(() => {
    const map: Record<string, number> = {};
    for (const b of blocks) {
      if (b.type !== 'blocked') map[b.machineId] = (map[b.machineId] ?? 0) + 1;
    }
    return map;
  }, [blocks]);

  // Sub-hooks
  const ar = useAutoReplan(data, allOps, mSt, tSt, applyMove, replanTimelines, setAppliedReplan, onReplanComplete);
  const fm = useFailureManagement(
    data,
    blocks,
    ar.state.wdi,
    ar.buildArInput,
    applyMove,
    onReplanComplete,
  );
  const opt = useOptimizationControl(
    data,
    blocks,
    allOps,
    mSt,
    tSt,
    moves,
    applyMove,
    replanTimelines,
    profiles,
  );
  const ro = useRushOrders(data.ops, ar.state.wdi, setRushOrders);

  // Use backend-computed analytics (no local genDecisions/quickValidate)
  const backendData = useScheduleData();
  const decs = useMemo(
    () => (backendData.genDecisions as unknown as ReplanProposal[]) ?? [],
    [backendData.genDecisions],
  );
  const qv = useMemo(
    () => (backendData.quickValidate as unknown as QuickValidateResult) ?? null,
    [backendData.quickValidate],
  );

  return {
    state: {
      xai,
      editingDown,
      blockCountByMachine,
      decs,
      qv,
      ...ar.state,
      ...fm.state,
      ...opt.state,
      ...ro.state,
    },
    actions: {
      setXai,
      setEditingDown,
      ...ar.actions,
      ...fm.actions,
      ...opt.actions,
      ...ro.actions,
    },
  };
}

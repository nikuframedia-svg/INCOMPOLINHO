/**
 * useReplanOrchestrator — Wires up replan history tracking and replan control state.
 */
import React from 'react';
import type {
  Block,
  buildResourceTimelines,
  EngineData,
  EOp,
  MoveAction,
  ObjectiveProfile,
  OptResult,
} from '../../../lib/engine';
import { useReplanControl } from './useReplanControl';
import type { ReplanKPISnapshot } from './useReplanHistory';
import { useReplanHistory } from './useReplanHistory';

export function useReplanOrchestrator(
  data: EngineData,
  blocks: Block[],
  allOps: EOp[],
  mSt: Record<string, string>,
  tSt: Record<string, string>,
  moves: MoveAction[],
  applyMove: (opId: string, toM: string) => void,
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null,
  profiles: ObjectiveProfile[],
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >,
  neMetrics: (OptResult & { blocks: Block[] }) | null,
) {
  const {
    entries: replanEntries,
    addEntry: addReplanEntry,
    undoEntry,
    clear: clearHistory,
  } = useReplanHistory();

  const [replanPreview, setReplanPreview] = React.useState<{
    before: ReplanKPISnapshot;
    after: ReplanKPISnapshot;
    movesCount: number;
    pendingApply: (() => void) | null;
  } | null>(null);

  const onReplanComplete = React.useCallback(
    (info: {
      trigger: string;
      triggerType: string;
      strategy: string;
      strategyLabel: string;
      movesCount: number;
      moves: MoveAction[];
    }) => {
      const kpiBefore: ReplanKPISnapshot = neMetrics
        ? {
            otd: neMetrics.otdDelivery,
            setupMin: neMetrics.setupMin,
            tardiness: neMetrics.tardinessDays,
            overflows: neMetrics.overflows,
          }
        : { otd: 0, setupMin: 0, tardiness: 0, overflows: 0 };
      addReplanEntry({
        trigger: info.trigger,
        triggerType: info.triggerType as
          | 'machine_down'
          | 'tool_down'
          | 'rush_order'
          | 'material_delay'
          | 'operator_absent'
          | 'manual',
        strategy: info.strategy as
          | 'right_shift'
          | 'match_up'
          | 'partial'
          | 'full_regen'
          | 'auto_replan',
        strategyLabel: info.strategyLabel,
        movesCount: info.movesCount,
        moves: info.moves,
        kpiBefore,
        kpiAfter: kpiBefore,
      });
    },
    [neMetrics, addReplanEntry],
  );

  const { state: rpc, actions: rpcActions } = useReplanControl(
    data,
    blocks,
    allOps,
    mSt,
    tSt,
    moves,
    applyMove,
    replanTimelines,
    profiles,
    setRushOrders,
    onReplanComplete,
  );

  return {
    rpc,
    rpcActions,
    replanEntries,
    undoEntry,
    clearHistory,
    replanPreview,
    setReplanPreview,
  };
}

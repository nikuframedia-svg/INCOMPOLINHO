/**
 * ReplanPanel — Orchestrator for all replan sub-components.
 * Delegates rendering to focused sub-components in ./replan/.
 * Includes simplified mode (default) for operators and advanced mode for planners.
 */
import type React from 'react';
import { useCallback, useState } from 'react';
import type {
  AutoReplanResult,
  Block,
  DayLoad,
  EngineData,
  EOp,
  MoveAction,
  OptResult,
  ReplanDispatchResult,
} from '@/domain/types/scheduling';
import type { buildResourceTimelines } from '@/utils/failure-timeline';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import { scheduleReplanApi } from '../../../lib/api';
import { useReplanOrchestrator } from '../hooks/useReplanOrchestrator';
import { OBJECTIVE_PROFILES } from './constants';
import { ReplanAdvancedView, SimpleReplanView } from './replan';

export function ReplanView({
  mSt,
  tSt,
  moves,
  applyMove,
  undoMove,
  blocks,
  cap,
  data,
  onApplyAndSave,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
  rushOrders,
  setRushOrders,
  allOps,
  neMetrics,
  setAppliedReplan,
}: {
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  toggleM?: (id: string) => void;
  toggleT?: (id: string) => void;
  moves: MoveAction[];
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  onApplyAndSave?: () => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >;
  allOps: EOp[];
  neMetrics: (OptResult & { blocks: Block[] }) | null;
  setAppliedReplan: (result: AutoReplanResult | null) => void;
}) {
  const [advancedMode, setAdvancedMode] = useState(false);
  const [replanRunning, setReplanRunning] = useState(false);
  const [replanResult, setReplanResult] = useState<ReplanDispatchResult | null>(null);

  const {
    rpc,
    rpcActions,
    replanEntries,
    undoEntry,
    clearHistory,
    replanPreview,
    setReplanPreview,
  } = useReplanOrchestrator(
    data,
    blocks,
    allOps,
    mSt,
    tSt,
    moves,
    applyMove,
    replanTimelines,
    OBJECTIVE_PROFILES,
    setRushOrders,
    neMetrics,
    setAppliedReplan,
  );

  const handleDispatchReplan = useCallback(
    async (machineId: string, delayMin: number) => {
      setReplanRunning(true);
      setReplanResult(null);
      try {
        const nikufraData = getCachedNikufraData();
        if (!nikufraData) throw new Error('No schedule data cached');

        const response = await scheduleReplanApi({
          blocks: blocks as unknown as Record<string, unknown>[],
          disruption: {
            type: delayMin >= 510 ? 'catastrophe' : 'breakdown',
            resource_id: machineId,
            start_day: 0,
            end_day: Math.ceil(delayMin / 510),
          },
          settings: { nikufra_data: nikufraData },
        });
        const r = response as unknown as Record<string, unknown>;
        const resMoves = ((r.auto_moves ?? []) as unknown as MoveAction[]).map((mv) => ({
          opId: mv.opId,
          toM: mv.toM,
        }));
        setReplanResult({
          layer: (r.strategy as string) ?? 'partial',
          blocks: (response.blocks ?? blocks) as unknown as Block[],
          emergencyNightShift: false,
          layerResult: { moves: resMoves },
        } as unknown as ReplanDispatchResult);
      } catch {
        // Silently fail — user sees no result
      } finally {
        setReplanRunning(false);
      }
    },
    [blocks],
  );

  if (!advancedMode) {
    return (
      <SimpleReplanView
        machines={data.machines}
        mSt={mSt}
        getResourceDownDays={getResourceDownDays}
        setEditingDown={rpcActions.setEditingDown}
        onRunAutoReplan={rpcActions.runAutoReplan}
        arRunning={rpc.arRunning}
        arResult={rpc.arResult}
        arActionsCount={rpc.arActions.length}
        moves={moves}
        onSwitchAdvanced={() => setAdvancedMode(true)}
        onDispatchReplan={handleDispatchReplan}
        replanRunning={replanRunning}
        replanResult={replanResult}
      />
    );
  }

  return (
    <ReplanAdvancedView
      data={data}
      blocks={blocks}
      cap={cap}
      mSt={mSt}
      tSt={tSt}
      moves={moves}
      applyMove={applyMove}
      undoMove={undoMove}
      onApplyAndSave={onApplyAndSave}
      isSaving={isSaving}
      setResourceDown={setResourceDown}
      clearResourceDown={clearResourceDown}
      getResourceDownDays={getResourceDownDays}
      rushOrders={rushOrders}
      neMetrics={neMetrics}
      rpc={rpc}
      rpcActions={rpcActions}
      replanEntries={replanEntries}
      undoEntry={undoEntry}
      clearHistory={clearHistory}
      replanPreview={replanPreview}
      setReplanPreview={setReplanPreview}
      onSwitchSimple={() => setAdvancedMode(false)}
      profiles={OBJECTIVE_PROFILES}
    />
  );
}

/**
 * useScheduleComputed — Schedule blocks + metrics from backend.
 *
 * Initial load: uses backend blocks from useScheduleData (zero local computation).
 * Applied replan: uses appliedReplan blocks.
 * Auto-replan: calls POST /v1/schedule/replan asynchronously.
 */

import { useCallback, useMemo } from 'react';
import type {
  AutoReplanResult,
  Block,
  DecisionEntry,
  EngineData,
  EOp,
  MoveAction,
} from '@/domain/types/scheduling';
import { getCachedNikufraData, useScheduleData } from '../../../hooks/useScheduleData';
import type { ScheduleBlock } from '../../../lib/api';
import { scheduleReplanApi } from '../../../lib/api';
import { useToastStore } from '../../../stores/useToastStore';
import { useScheduleValidation } from './useScheduleValidation';

export function useScheduleComputed({
  engineData,
  rushOrders,
  mSt,
  appliedReplan,
}: {
  engineData: EngineData | null;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  mSt: Record<string, string>;
  appliedReplan: AutoReplanResult | null;
}) {
  // Backend-computed schedule data (blocks, metrics, cap, analytics)
  const scheduleData = useScheduleData();

  const rushOps = useMemo((): EOp[] => {
    if (!engineData || rushOrders.length === 0) return [];
    return rushOrders
      .map((ro, idx): EOp | null => {
        const tool = engineData.toolMap[ro.toolId];
        if (!tool) return null;
        const d = Array(engineData.nDays).fill(0) as number[];
        d[ro.deadline] = -ro.qty;
        return {
          id: `rush-${ro.toolId}-${ro.deadline}-${ro.qty}-${idx}`,
          t: ro.toolId,
          m: tool.m,
          sku: ro.sku,
          nm: `RUSH: ${tool.nm || ro.sku}`,
          atr: 0,
          d,
        };
      })
      .filter((op): op is EOp => op !== null);
  }, [engineData, rushOrders]);

  const allOps = useMemo(
    () =>
      !engineData
        ? ([] as EOp[])
        : rushOps.length > 0
          ? [...engineData.ops, ...rushOps]
          : engineData.ops,
    [engineData, rushOps],
  );

  // Use backend blocks — no local autoRouteOverflow computation
  const {
    blocks,
    autoMoves,
    decisions: schedDecisions,
  } = useMemo(() => {
    if (!engineData)
      return {
        blocks: [] as Block[],
        autoMoves: [] as MoveAction[],
        decisions: [] as DecisionEntry[],
      };
    if (appliedReplan) {
      return {
        blocks: appliedReplan.blocks,
        autoMoves: appliedReplan.autoMoves,
        decisions: appliedReplan.decisions,
      };
    }
    // Backend-computed blocks (no local scheduling)
    return {
      blocks: (scheduleData.blocks ?? []) as Block[],
      autoMoves: (scheduleData.autoMoves ?? []) as MoveAction[],
      decisions: (scheduleData.decisions ?? []) as DecisionEntry[],
    };
  }, [
    engineData,
    appliedReplan,
    scheduleData.blocks,
    scheduleData.autoMoves,
    scheduleData.decisions,
  ]);

  // Backend-computed analytics (no local scoreSchedule/capAnalysis)
  const cap = useMemo(() => scheduleData.cap ?? {}, [scheduleData.cap]);

  const neMetrics = useMemo(() => scheduleData.metrics ?? null, [scheduleData.metrics]);

  const { validation, audit, feasibility } = useScheduleValidation(blocks, allOps, engineData);

  // Auto-replan via backend (replaces local autoReplan call)
  const handlePlanAutoReplan = useCallback(async () => {
    if (!engineData) return null;
    const nikufraData = getCachedNikufraData();
    if (!nikufraData) return null;
    try {
      const response = await scheduleReplanApi({
        blocks: blocks as unknown as ScheduleBlock[],
        disruption: {
          type: 'auto_replan',
          resource_id: '',
          start_day: 0,
          end_day: engineData.nDays,
        },
        settings: { nikufra_data: nikufraData },
      });
      const newMoves = (response.auto_moves ?? []) as unknown as MoveAction[];
      return {
        actions: [],
        moveCount: newMoves.length,
        unresolvedCount: 0,
      };
    } catch (e) {
      useToastStore
        .getState()
        .actions.addToast(
          `Erro no auto-replan: ${e instanceof Error ? e.message : String(e)}`,
          'error',
          5000,
        );
      return null;
    }
  }, [engineData, blocks]);

  const downC = Object.values(mSt).filter((s) => s === 'down').length;
  const blkOps = new Set(blocks.filter((b) => b.type === 'blocked').map((b) => b.opId)).size;

  return {
    allOps,
    blocks,
    autoMoves,
    schedDecisions,
    cap,
    neMetrics,
    validation,
    audit,
    feasibility,
    handlePlanAutoReplan,
    downC,
    blkOps,
  };
}

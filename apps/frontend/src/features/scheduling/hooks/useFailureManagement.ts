/**
 * useFailureManagement — Failure/breakdown management and cascading replan.
 */

import { useCallback, useState } from 'react';
import type {
  Block,
  EngineData,
  FailureEvent,
  ImpactReport,
  MoveAction,
} from '../../../lib/engine';
import { scheduleReplanApi } from '../../../lib/api';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import { useToastStore } from '../../../stores/useToastStore';

export interface FailureState {
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
  selectedStrategy: string | null;
}

export interface FailureActions {
  setShowFailureForm: React.Dispatch<React.SetStateAction<boolean>>;
  setFfResType: React.Dispatch<React.SetStateAction<'machine' | 'tool'>>;
  setFfResId: React.Dispatch<React.SetStateAction<string>>;
  setFfSev: React.Dispatch<React.SetStateAction<'total' | 'partial' | 'degraded'>>;
  setFfCap: React.Dispatch<React.SetStateAction<number>>;
  setFfStartDay: React.Dispatch<React.SetStateAction<number>>;
  setFfEndDay: React.Dispatch<React.SetStateAction<number>>;
  setFfDesc: React.Dispatch<React.SetStateAction<string>>;
  setSelectedStrategy: React.Dispatch<React.SetStateAction<string | null>>;
  addFailure: () => void;
  removeFailure: (id: string) => void;
  runCascadingReplan: () => void;
}

export function useFailureManagement(
  data: EngineData,
  blocks: Block[],
  wdi: number[],
  _buildArInput: () => unknown,
  applyMove: (opId: string, toM: string) => void,
  onReplanComplete?: (info: {
    trigger: string;
    triggerType: string;
    strategy: string;
    strategyLabel: string;
    movesCount: number;
    moves: MoveAction[];
  }) => void,
): { state: FailureState; actions: FailureActions } {
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
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [cascRunning, setCascRunning] = useState(false);

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
    // Simple local impact estimation: count blocks affected by each failure
    const impacts: ImpactReport[] = newF.map((fe) => {
      const affected = blocks.filter(
        (b) =>
          b.dayIdx >= fe.startDay &&
          b.dayIdx <= fe.endDay &&
          ((fe.resourceType === 'machine' && b.machineId === fe.resourceId) ||
            (fe.resourceType === 'tool' && b.toolId === fe.resourceId)),
      );
      const totalQty = affected.reduce((s, b) => s + (b.qty ?? 0), 0);
      const totalMin = affected.reduce((s, b) => s + (b.endMin - b.startMin), 0);
      return {
        failureEvent: fe,
        impactedBlocks: affected.map((b) => ({
          opId: b.opId,
          toolId: b.toolId,
          sku: b.sku,
          machineId: b.machineId,
          dayIdx: b.dayIdx,
          shift: (b.startMin < 510 ? 'X' : 'Y') as 'X' | 'Y',
          scheduledQty: b.qty ?? 0,
          qtyAtRisk: b.qty ?? 0,
          minutesAtRisk: b.endMin - b.startMin,
          hasAlternative: false,
          altMachine: null,
        })),
        summary: {
          totalBlocksAffected: affected.length,
          totalQtyAtRisk: totalQty,
          totalMinutesAtRisk: totalMin,
          blocksWithAlternative: 0,
          blocksWithoutAlternative: affected.length,
          opsAffected: new Set(affected.map((b) => b.opId)).size,
          skusAffected: new Set(affected.map((b) => b.sku)).size,
        },
        dailyImpact: [],
      } satisfies ImpactReport;
    });
    setFailureImpacts(impacts);
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
      setFailureImpacts(newF.length > 0 ? failureImpacts.filter((i) => i.failureEvent.id !== id) : []);
    },
    [failures, failureImpacts],
  );

  const runCascadingReplan = useCallback(async () => {
    if (failures.length === 0) return;
    setCascRunning(true);
    try {
      const nikufraData = getCachedNikufraData();
      if (!nikufraData) throw new Error('No schedule data cached');

      const disruption = {
        type: 'cascading_failure' as const,
        resource_id: failures[0].resourceId,
        start_day: Math.min(...failures.map((f) => f.startDay)),
        end_day: Math.max(...failures.map((f) => f.endDay)),
        failures: failures.map((f) => ({
          resource_type: f.resourceType,
          resource_id: f.resourceId,
          start_day: f.startDay,
          end_day: f.endDay,
          severity: f.severity,
        })),
      };

      const response = await scheduleReplanApi({
        blocks: blocks as unknown as Record<string, unknown>[],
        disruption,
        settings: { nikufra_data: nikufraData },
      });

      const mvs = ((response.auto_moves ?? []) as unknown as MoveAction[]);
      for (const mv of mvs) applyMove(mv.opId, mv.toM);
      useToastStore
        .getState()
        .actions.addToast(
          `Replan cascata: ${mvs.length} movimentos`,
          mvs.length > 0 ? 'success' : 'warning',
          5000,
        );
      const triggerDesc = failures.map((f) => f.resourceId).join(', ');
      const stratLabel =
        selectedStrategy === 'right_shift'
          ? 'RIGHT-SHIFT'
          : selectedStrategy === 'match_up'
            ? 'MATCH-UP'
            : selectedStrategy === 'full_regen'
              ? 'REGEN'
              : 'PARCIAL';
      onReplanComplete?.({
        trigger: `Avaria ${triggerDesc}`,
        triggerType: failures[0]?.resourceType === 'machine' ? 'machine_down' : 'tool_down',
        strategy: selectedStrategy || 'partial',
        strategyLabel: stratLabel,
        movesCount: mvs.length,
        moves: mvs.map((mv) => ({ opId: mv.opId, toM: mv.toM })),
      });
    } catch (e) {
      useToastStore
        .getState()
        .actions.addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 5000);
    }
    setCascRunning(false);
  }, [failures, blocks, applyMove, selectedStrategy, onReplanComplete]);

  return {
    state: {
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
      selectedStrategy,
    },
    actions: {
      setShowFailureForm,
      setFfResType,
      setFfResId,
      setFfSev,
      setFfCap,
      setFfStartDay,
      setFfEndDay,
      setFfDesc,
      setSelectedStrategy,
      addFailure,
      removeFailure,
      runCascadingReplan,
    },
  };
}

/**
 * useOptimizationControl — optimization via backend CP-SAT /v1/schedule/optimize.
 */

import { useCallback, useState } from 'react';
import type {
  Block,
  EngineData,
  EOp,
  MoveAction,
  ObjectiveProfile,
  OptResult,
} from '../../../lib/engine';
import { scheduleOptimizeApi } from '../../../lib/api';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import { useToastStore } from '../../../stores/useToastStore';

export interface OptimizationState {
  optRunning: boolean;
  optResults: OptResult[];
  optProgress: number;
  optN: number;
  optProfile: string;
  optMoveable: Array<{
    opId: string;
    toolId: string;
    primaryM: string;
    altM: string;
    totalPcs: number;
    hrs: number;
  }>;
}

export interface OptimizationActions {
  setOptN: React.Dispatch<React.SetStateAction<number>>;
  setOptProfile: React.Dispatch<React.SetStateAction<string>>;
  setOptResults: React.Dispatch<React.SetStateAction<OptResult[]>>;
  runOpt: () => void;
  applyOptResult: (r: OptResult) => void;
}

/**
 * Parameters kept for backward compatibility with useReplanControl call site.
 * Actual optimization now runs server-side via /v1/schedule/optimize.
 */
export function useOptimizationControl(
  _data: EngineData,
  _blocks: Block[],
  _allOps: EOp[],
  _mSt: Record<string, string>,
  _tSt: Record<string, string>,
  _moves: MoveAction[],
  applyMove: (opId: string, toM: string) => void,
  _replanTimelines: unknown,
  profiles: ObjectiveProfile[],
): { state: OptimizationState; actions: OptimizationActions } {
  const [optRunning, setOptRunning] = useState(false);
  const [optResults, setOptResults] = useState<OptResult[]>([]);
  const [optProgress, setOptProgress] = useState(0);
  const [optN, setOptN] = useState(3);
  const [optProfile, setOptProfile] = useState('balanced');

  const runOpt = useCallback(async () => {
    const nikufraData = getCachedNikufraData();
    if (!nikufraData) {
      useToastStore.getState().actions.addToast('Sem dados para optimizar', 'error', 5000);
      return;
    }
    setOptRunning(true);
    setOptProgress(10);
    setOptResults([]);

    try {
      const prof = profiles.find((p) => p.id === optProfile);
      const weights = prof
        ? (prof.weights as Record<string, number>)
        : { weighted_tardiness: 0.5, makespan: 0.3, tardiness: 0.2 };

      setOptProgress(30);
      const response = await scheduleOptimizeApi(
        {
          nikufra_data: nikufraData,
          objective_weights: weights,
          n_alternatives: Math.min(optN, 5),
        },
        120_000,
      );
      setOptProgress(90);

      // Map backend alternatives to OptResult shape
      const results: OptResult[] = response.alternatives.map((alt) => {
        const s = (alt.score as Record<string, number>) ?? {};
        return {
          blocks: alt.blocks as unknown as Block[],
          moves: [] as MoveAction[],
          score: s.score ?? 0,
          otd: s.otd ?? 0,
          otdDelivery: s.otdDelivery ?? s.otd_delivery ?? 0,
          produced: s.produced ?? 0,
          totalDemand: s.totalDemand ?? s.total_demand ?? 0,
          lostPcs: s.lostPcs ?? s.lost_pcs ?? 0,
          setupCount: s.setupCount ?? s.setup_count ?? 0,
          setupMin: s.setupMin ?? s.setup_min ?? 0,
          peakOps: s.peakOps ?? s.peak_ops ?? 0,
          overOps: s.overOps ?? s.over_ops ?? 0,
          overflows: s.overflows ?? 0,
          capUtil: s.capUtil ?? s.cap_util ?? 0,
          capVar: s.capVar ?? s.cap_var ?? 0,
          tardinessDays: s.tardinessDays ?? s.tardiness_days ?? 0,
          setupByShift: { X: 0, Y: 0, Z: 0 },
          capByMachine: {},
          workforceDemand: [],
          label: `Alt ${String.fromCharCode(65 + (response.alternatives.indexOf(alt)))}`,
          deadlineFeasible: true,
        };
      });

      setOptResults(results);
      setOptProgress(100);
      useToastStore
        .getState()
        .actions.addToast(
          `Optimização CP-SAT: ${results.length} alternativa(s) em ${response.solve_time_s.toFixed(1)}s`,
          'success',
          5000,
        );
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
  }, [optN, optProfile, profiles]);

  const applyOptResult = useCallback(
    (r: OptResult) => {
      for (const mv of r.moves) applyMove(mv.opId, mv.toM);
      useToastStore
        .getState()
        .actions.addToast(`Optimização aplicada: ${r.moves.length} movimentos`, 'success', 5000);
    },
    [applyMove],
  );

  return {
    state: {
      optRunning,
      optResults,
      optProgress,
      optN,
      optProfile,
      optMoveable: [],
    },
    actions: {
      setOptN,
      setOptProfile,
      setOptResults,
      runOpt,
      applyOptResult,
    },
  };
}

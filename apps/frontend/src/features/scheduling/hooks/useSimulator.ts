/**
 * useSimulator — unified scenario simulation hook.
 * Replaces: useAutoReplan, useFailureManagement, useRushOrders,
 *           useOptimizationControl, useWhatIf.
 */

import { useCallback, useState } from 'react';
import { getCachedNikufraData } from '../../../hooks/useScheduleData';
import type {
  SimBlockChange,
  SimDeltaReport,
  SimMutation,
  SimMutationImpact,
  SimulateResponse,
} from '../../../lib/api';
import { scheduleSimulateApi } from '../../../lib/api';
import { useSettingsStore } from '../../../stores/useSettingsStore';

export type { SimMutation, SimBlockChange, SimDeltaReport, SimMutationImpact };

export interface SimulatorState {
  mutations: SimMutation[];
  result: SimulateResponse | null;
  running: boolean;
  error: string | null;
}

export function useSimulator() {
  const [mutations, setMutations] = useState<SimMutation[]>([]);
  const [result, setResult] = useState<SimulateResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addMutation = useCallback((mut: SimMutation) => {
    setMutations((prev) => [...prev, mut]);
  }, []);

  const removeMutation = useCallback((idx: number) => {
    setMutations((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const updateMutation = useCallback((idx: number, mut: SimMutation) => {
    setMutations((prev) => prev.map((m, i) => (i === idx ? mut : m)));
  }, []);

  const clearAll = useCallback(() => {
    setMutations([]);
    setResult(null);
    setError(null);
  }, []);

  const simulate = useCallback(async () => {
    if (mutations.length === 0) return;
    const nikufraData = getCachedNikufraData();
    if (!nikufraData) {
      setError('Sem dados ISOP carregados');
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const settings = useSettingsStore.getState();
      const data = await scheduleSimulateApi({
        nikufra_data: nikufraData,
        mutations,
        settings: settings as unknown as Record<string, unknown>,
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setRunning(false);
  }, [mutations]);

  const dismissResult = useCallback(() => {
    setResult(null);
  }, []);

  return {
    mutations,
    result,
    running,
    error,
    addMutation,
    removeMutation,
    updateMutation,
    clearAll,
    simulate,
    dismissResult,
  };
}

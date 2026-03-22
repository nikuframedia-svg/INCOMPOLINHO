import { useCallback, useEffect, useMemo, useState, useTransition } from 'react';

import type { EngineData, FailureEvent } from '@/domain/types/scheduling';
import { buildResourceTimelines } from '@/utils/failure-timeline';

export interface ScheduleFiltersState {
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  failureEvents: FailureEvent[];
  isScheduling: boolean;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
}

export interface ScheduleFiltersActions {
  setMSt: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  setTSt: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  toggleM: (id: string) => void;
  toggleT: (id: string) => void;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  setFailureEvents: React.Dispatch<React.SetStateAction<FailureEvent[]>>;
  resetFilters: (machines: EngineData['machines']) => void;
}

export function useScheduleFilters(engineData: EngineData | null): {
  state: ScheduleFiltersState;
  actions: ScheduleFiltersActions;
} {
  const [mSt, setMSt] = useState<Record<string, string>>({});
  const [tSt, setTSt] = useState<Record<string, string>>({});
  const [failureEvents, setFailureEvents] = useState<FailureEvent[]>([]);
  const [isScheduling, startScheduleTransition] = useTransition();

  // Temporal down: derive timelines from failureEvents
  const replanTimelines = useMemo(() => {
    if (!engineData || failureEvents.length === 0) return null;
    return buildResourceTimelines(failureEvents, engineData.nDays, engineData.thirdShift);
  }, [failureEvents, engineData]);

  // Sync mSt/tSt from failureEvents: resource with ANY down period → 'down'
  useEffect(() => {
    if (!engineData) return;
    const feByMachine: Record<string, boolean> = {};
    const feByTool: Record<string, boolean> = {};
    for (const fe of failureEvents) {
      if (fe.resourceType === 'machine') feByMachine[fe.resourceId] = true;
      else feByTool[fe.resourceId] = true;
    }
    setMSt((prev) => {
      const next = { ...prev };
      for (const m of engineData.machines) {
        next[m.id] = feByMachine[m.id] ? 'down' : 'running';
      }
      return next;
    });
    setTSt((prev) => {
      const next: Record<string, string> = {};
      for (const [id] of Object.entries(prev)) {
        if (feByTool[id]) next[id] = 'down';
      }
      for (const id of Object.keys(feByTool)) {
        next[id] = 'down';
      }
      return next;
    });
  }, [failureEvents, engineData]);

  const toggleM = useCallback(
    (id: string) => setMSt((p) => ({ ...p, [id]: p[id] === 'down' ? 'running' : 'down' })),
    [],
  );
  const toggleT = useCallback(
    (id: string) =>
      setTSt((p) => {
        const n = { ...p };
        if (n[id] === 'down') delete n[id];
        else n[id] = 'down';
        return n;
      }),
    [],
  );

  const setResourceDown = useCallback((type: 'machine' | 'tool', id: string, days: number[]) => {
    startScheduleTransition(() => {
      setFailureEvents((prev) => {
        const filtered = prev.filter((f) => !(f.resourceType === type && f.resourceId === id));
        if (days.length === 0) return filtered;
        const sorted = [...days].sort((a, b) => a - b);
        const events: FailureEvent[] = [];
        let start = sorted[0];
        let end = sorted[0];
        for (let i = 1; i < sorted.length; i++) {
          if (sorted[i] === end + 1) {
            end = sorted[i];
          } else {
            events.push({
              id: `${type}-${id}-${start}-${end}`,
              resourceType: type,
              resourceId: id,
              startDay: start,
              endDay: end,
              startShift: null,
              endShift: null,
              severity: 'total',
              capacityFactor: 0,
            });
            start = sorted[i];
            end = sorted[i];
          }
        }
        events.push({
          id: `${type}-${id}-${start}-${end}`,
          resourceType: type,
          resourceId: id,
          startDay: start,
          endDay: end,
          startShift: null,
          endShift: null,
          severity: 'total',
          capacityFactor: 0,
        });
        return [...filtered, ...events];
      });
    });
  }, []);

  const clearResourceDown = useCallback((type: 'machine' | 'tool', id: string) => {
    startScheduleTransition(() => {
      setFailureEvents((prev) =>
        prev.filter((f) => !(f.resourceType === type && f.resourceId === id)),
      );
    });
  }, []);

  // Pre-compute down days per resource
  const downDaysCache = useMemo(() => {
    const cache: Record<string, Record<string, Set<number>>> = { machine: {}, tool: {} };
    for (const fe of failureEvents) {
      if (!cache[fe.resourceType][fe.resourceId]) cache[fe.resourceType][fe.resourceId] = new Set();
      for (let d = fe.startDay; d <= fe.endDay; d++) {
        cache[fe.resourceType][fe.resourceId].add(d);
      }
    }
    return cache;
  }, [failureEvents]);

  const getResourceDownDays = useCallback(
    (type: 'machine' | 'tool', id: string): Set<number> => {
      return downDaysCache[type]?.[id] ?? new Set();
    },
    [downDaysCache],
  );

  const resetFilters = useCallback((machines: EngineData['machines']) => {
    setMSt(Object.fromEntries(machines.map((m) => [m.id, 'running'])));
    setTSt({});
    setFailureEvents([]);
  }, []);

  return {
    state: { mSt, tSt, failureEvents, isScheduling, replanTimelines },
    actions: {
      setMSt,
      setTSt,
      toggleM,
      toggleT,
      setResourceDown,
      clearResourceDown,
      getResourceDownDays,
      setFailureEvents,
      resetFilters,
    },
  };
}

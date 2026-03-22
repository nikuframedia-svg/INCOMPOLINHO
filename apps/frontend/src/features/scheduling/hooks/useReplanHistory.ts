/**
 * useReplanHistory — Tracks replan history with multi-level undo.
 *
 * Each replan (auto, cascading, optimization) registers an entry
 * with KPIs before/after and the moves applied.
 */

import { useCallback, useState } from 'react';
import type { MoveAction } from '@/domain/types/scheduling';

export type ReplanTriggerType =
  | 'machine_down'
  | 'tool_down'
  | 'rush_order'
  | 'material_delay'
  | 'operator_absent'
  | 'manual';

export type ReplanStrategy = 'right_shift' | 'match_up' | 'partial' | 'full_regen' | 'auto_replan';

export interface ReplanKPISnapshot {
  otd: number;
  setupMin: number;
  tardiness: number;
  overflows: number;
}

export interface ReplanHistoryEntry {
  id: string;
  timestamp: number;
  trigger: string;
  triggerType: ReplanTriggerType;
  strategy: ReplanStrategy;
  strategyLabel: string;
  movesCount: number;
  moves: MoveAction[];
  kpiBefore: ReplanKPISnapshot;
  kpiAfter: ReplanKPISnapshot;
  undone: boolean;
}

export type NewReplanEntry = Omit<ReplanHistoryEntry, 'id' | 'timestamp' | 'undone'>;

export interface UseReplanHistoryReturn {
  entries: ReplanHistoryEntry[];
  addEntry: (entry: NewReplanEntry) => void;
  undoEntry: (id: string) => ReplanHistoryEntry | null;
  canUndo: boolean;
  clear: () => void;
}

export function useReplanHistory(): UseReplanHistoryReturn {
  const [entries, setEntries] = useState<ReplanHistoryEntry[]>([]);

  const addEntry = useCallback((entry: NewReplanEntry) => {
    const full: ReplanHistoryEntry = {
      ...entry,
      id: `rh-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      timestamp: Date.now(),
      undone: false,
    };
    setEntries((prev) => [full, ...prev]);
  }, []);

  const undoEntry = useCallback(
    (id: string): ReplanHistoryEntry | null => {
      const entry = entries.find((e) => e.id === id && !e.undone);
      if (!entry) return null;
      setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, undone: true } : e)));
      return entry;
    },
    [entries],
  );

  const canUndo = entries.some((e) => !e.undone);

  const clear = useCallback(() => {
    setEntries([]);
  }, []);

  return { entries, addEntry, undoEntry, canUndo, clear };
}

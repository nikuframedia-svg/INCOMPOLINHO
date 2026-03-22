/**
 * useDayData — Derives day-specific data from useScheduleData().
 *
 * Pure derivation via useMemo — no new engine calls.
 * Consumes selectedDayIdx from useUIStore (persisted).
 */

import { useMemo } from 'react';
import type { DayData } from '../lib/day-data-derive';
import { deriveDayData } from '../lib/day-data-derive';
import { useUIStore } from '../stores/useUIStore';
import { useScheduleData } from './useScheduleData';

export type { OpDay } from '@/domain/types/scheduling';
// Re-export types for consumers
export type { DayData, MachineLoad } from '../lib/day-data-derive';

export interface UseDayDataResult {
  dayData: DayData | null;
  loading: boolean;
  error: string | null;
}

export function useDayData(): UseDayDataResult {
  const {
    engine,
    blocks: allBlocks,
    cap,
    metrics,
    validation,
    feasibilityReport,
    transparencyReport,
    decisions: allDecisions,
    loading,
    error,
  } = useScheduleData();
  const selectedDayIdx = useUIStore((s) => s.selectedDayIdx);

  const dayData = useMemo((): DayData | null => {
    if (!engine || loading || error) return null;
    return deriveDayData({
      engine,
      allBlocks,
      cap,
      metrics,
      validation,
      feasibilityReport,
      transparencyReport,
      allDecisions,
      selectedDayIdx,
    });
  }, [
    engine,
    allBlocks,
    cap,
    metrics,
    validation,
    feasibilityReport,
    transparencyReport,
    allDecisions,
    selectedDayIdx,
    loading,
    error,
  ]);

  return { dayData, loading, error };
}

/**
 * useScheduleData.test.ts — Minimal tests for the schedule data hook.
 * Tests exported types and initial state behavior.
 */

import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// Mock all dependencies before importing the hook
vi.mock('../../lib/api', () => ({
  scheduleFullApi: vi.fn(),
}));

vi.mock('../../stores/useDataStore', () => ({
  useDataStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ loadedAt: null, isMerging: false, _hasHydrated: true }),
  ),
}));

vi.mock('../../stores/useMasterDataStore', () => ({
  useMasterDataStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ overridesVersion: 0 }),
  ),
  overridesVersionSelector: (s: Record<string, unknown>) => s.overridesVersion,
}));

vi.mock('../../stores/useSettingsStore', () => ({
  useSettingsStore: Object.assign(
    vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
      sel({ dispatchRule: 'EDD', thirdShiftDefault: false }),
    ),
    { getState: () => ({ dispatchRule: 'EDD', thirdShiftDefault: false }) },
  ),
}));

vi.mock('../../stores/settings-config', () => ({
  getTransformConfig: () => ({ demandSemantics: 'raw_np' }),
  settingsHashSelector: (s: Record<string, unknown>) => `${s.dispatchRule}-${s.thirdShiftDefault}`,
}));

vi.mock('../../hooks/useDataSource', () => ({
  useDataSource: () => null,
}));

import type { BackendAnalytics, CacheEntry } from '@/hooks/useScheduleData';
import { useScheduleData } from '@/hooks/useScheduleData';

describe('useScheduleData', () => {
  it('exports BackendAnalytics and CacheEntry types', () => {
    // Type-level check: these should compile without error
    const _ba: BackendAnalytics | null = null;
    const _ce: CacheEntry | null = null;
    expect(_ba).toBeNull();
    expect(_ce).toBeNull();
  });

  it('returns proper initial state when no data is loaded', () => {
    const { result } = renderHook(() => useScheduleData());
    const data = result.current;

    expect(data.loading).toBe(false);
    expect(data.engine).toBeNull();
    expect(data.blocks).toEqual([]);
    expect(data.autoMoves).toEqual([]);
    expect(data.decisions).toEqual([]);
    expect(data.feasibilityReport).toBeNull();
    expect(data.mrp).toBeNull();
    expect(data.nikufraData).toBeNull();
    expect(data.thirdShiftRecommended).toBe(false);
  });

  it('reports error when data source has no getNikufraData', () => {
    // useDataSource returns null, so ds?.getNikufraData is falsy
    const { result } = renderHook(() => useScheduleData());
    expect(result.current.error).toBe('Data source unavailable — getNikufraData not found');
    expect(result.current.loading).toBe(false);
  });
});

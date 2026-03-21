// useScheduleData — shared hook for schedule KPIs across all pages
// Module-level cache: computes once, shared across all consumers
// Reacts to useDataStore changes (ISOP upload) via dataVersion counter
// Backend CP-SAT is the ONLY scheduling path — no client-side fallback.

import { useEffect, useMemo, useState } from 'react';
import type {
  Block,
  CoverageAuditResult,
  DayLoad,
  DecisionEntry,
  EngineData,
  FeasibilityReport,
  LateDeliveryAnalysis,
  MoveAction,
  MRPResult,
  ScheduleValidationReport,
  TransparencyReport,
} from '../lib/engine';
import type { OptResult } from '../lib/engine';
import type {
  ActionMessagesSummary,
  MRPSkuViewResult,
  ROPSkuSummary,
  ROPSummary,
} from '../domain/mrp/mrp-types';
import type { CacheEntry, DataSourceLike } from '../lib/schedule-pipeline';
import { runSchedulePipeline } from '../lib/schedule-pipeline';
import { getTransformConfig, settingsHashSelector } from '../stores/settings-config';
import { useDataStore } from '../stores/useDataStore';
import { overridesVersionSelector, useMasterDataStore } from '../stores/useMasterDataStore';
import { useSettingsStore } from '../stores/useSettingsStore';
import { useDataSource } from './useDataSource';

export interface ScheduleData {
  /** Raw nikufra_data for backend API calls (optimize, what-if, replan) */
  nikufraData: Record<string, unknown> | null;
  engine: EngineData | null;
  blocks: Block[];
  autoMoves: MoveAction[];
  autoAdvances: unknown[];
  decisions: DecisionEntry[];
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  thirdShiftRecommended: boolean;
  cap: Record<string, DayLoad[]>;
  metrics: OptResult | null;
  validation: ScheduleValidationReport | null;
  coverageAudit: CoverageAuditResult | null;
  lateDeliveries: LateDeliveryAnalysis | null;
  mrp: MRPResult | null;
  mrpSkuView: MRPSkuViewResult | null;
  mrpRop: ROPSummary | null;
  mrpRopSku: ROPSkuSummary | null;
  mrpActions: ActionMessagesSummary | null;
  genDecisions: Record<string, unknown>[] | null;
  quickValidate: Record<string, unknown> | null;
  workforceForecast: Record<string, unknown> | null;
  riskGrid: Record<string, unknown> | null;
  loading: boolean;
  error: string | null;
}

// Module-level cache
let cached: CacheEntry | null = null;
let cachePromise: Promise<void> | null = null;
let cachedDataVersion: string | null = null;
let cachedOverridesVersion: number | null = null;
let cachedSettingsHash: string | null = null;
let cacheVersion = 0;

export function useScheduleData(): ScheduleData {
  // Listen for external cache invalidation (e.g. copilot recalculation)
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const handler = () => forceUpdate((v) => v + 1);
    window.addEventListener('schedule-invalidate', handler);
    return () => window.removeEventListener('schedule-invalidate', handler);
  }, []);
  const ds = useDataSource();
  const dataVersion = useDataStore((s) => s.loadedAt);
  const isMerging = useDataStore((s) => s.isMerging);
  const hasHydrated = useDataStore((s) => s._hasHydrated);
  const settingsHash = useSettingsStore(settingsHashSelector);
  const overridesVersion = useMasterDataStore(overridesVersionSelector);

  const [engine, setEngine] = useState<EngineData | null>(cached?.engine ?? null);
  const [blocks, setBlocks] = useState<Block[]>(cached?.blocks ?? []);
  const [autoMoves, setAutoMoves] = useState<MoveAction[]>(cached?.autoMoves ?? []);
  const [decisions, setDecisions] = useState<DecisionEntry[]>(cached?.decisions ?? []);
  const [feasibilityReport, setFeasibilityReport] = useState<FeasibilityReport | null>(
    cached?.feasibilityReport ?? null,
  );
  const [mrpData, setMrpData] = useState<MRPResult | null>(cached?.mrp ?? null);
  const [thirdShiftRecommended, setThirdShiftRecommended] = useState(
    cached?.thirdShiftRecommended ?? false,
  );
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Wait for Zustand persist to hydrate from localStorage before running pipeline
    if (!hasHydrated) {
      setLoading(true);
      return;
    }

    if (isMerging) {
      setLoading(true);
      return;
    }

    if (
      dataVersion !== cachedDataVersion ||
      overridesVersion !== cachedOverridesVersion ||
      settingsHash !== cachedSettingsHash
    ) {
      cached = null;
      cachePromise = null;
      cachedDataVersion = dataVersion;
      cachedOverridesVersion = overridesVersion;
      cachedSettingsHash = settingsHash;
      cacheVersion++;
    }

    const applyCache = () => {
      if (!cached) return;
      setEngine(cached.engine);
      setBlocks(cached.blocks);
      setAutoMoves(cached.autoMoves);
      setDecisions(cached.decisions);
      setFeasibilityReport(cached.feasibilityReport);
      setThirdShiftRecommended(cached.thirdShiftRecommended);
      setMrpData(cached.mrp);
    };

    if (cached) {
      applyCache();
      setLoading(false);
      return;
    }
    if (cachePromise) {
      cachePromise.then(() => {
        applyCache();
        setLoading(false);
      });
      return;
    }

    setLoading(true);
    setError(null);
    const computeVersion = cacheVersion;

    if (!ds?.getNikufraData) {
      setError('Data source unavailable — getNikufraData not found');
      setLoading(false);
      return;
    }

    cachePromise = runSchedulePipeline(ds as DataSourceLike, getTransformConfig()).then((entry) => {
      if (computeVersion === cacheVersion) cached = entry;
    });

    cachePromise
      .then(() => {
        if (computeVersion !== cacheVersion) return;
        applyCache();
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Failed to load schedule data');
        setEngine(null);
        setBlocks([]);
        setAutoMoves([]);
        setDecisions([]);
        setFeasibilityReport(null);
        setThirdShiftRecommended(false);
        setMrpData(null);
      })
      .finally(() => setLoading(false));
  }, [ds, dataVersion, settingsHash, isMerging, overridesVersion, hasHydrated]);

  // ── Use backend analytics directly — no local computation fallback ──
  const ba = cached?.backendAnalytics;

  const cap = useMemo(
    () => (ba?.cap as Record<string, DayLoad[]>) ?? {},
    [ba],
  );

  const metrics = useMemo(
    () => (ba?.score as unknown as OptResult) ?? null,
    [ba],
  );

  const validation = useMemo(
    () => (ba?.validation as unknown as ScheduleValidationReport) ?? null,
    [ba],
  );

  const coverageAudit = useMemo(
    () => (ba?.coverage as unknown as CoverageAuditResult) ?? null,
    [ba],
  );

  const lateDeliveries = useMemo(
    () => (ba?.lateDeliveries as unknown as LateDeliveryAnalysis) ?? null,
    [ba],
  );

  const mrpSkuView = useMemo(
    () => (ba?.mrpSkuView as unknown as MRPSkuViewResult) ?? null,
    [ba],
  );

  const mrpRop = useMemo(
    () => (ba?.mrpRop as unknown as ROPSummary) ?? null,
    [ba],
  );

  const mrpRopSku = useMemo(
    () => (ba?.mrpRopSku as unknown as ROPSkuSummary) ?? null,
    [ba],
  );

  const mrpActions = useMemo(
    () => (ba?.mrpActions as unknown as ActionMessagesSummary) ?? null,
    [ba],
  );

  return {
    nikufraData: cached?.nikufraData ?? null,
    engine,
    blocks,
    autoMoves,
    autoAdvances: [],
    decisions,
    feasibilityReport,
    transparencyReport: null,
    thirdShiftRecommended,
    cap,
    metrics,
    validation,
    coverageAudit,
    lateDeliveries,
    mrp: mrpData,
    mrpSkuView,
    mrpRop,
    mrpRopSku,
    mrpActions,
    genDecisions: ba?.genDecisions ?? null,
    quickValidate: ba?.quickValidate ?? null,
    workforceForecast: ba?.workforceForecast ?? null,
    riskGrid: null, // TODO: add to backend pipeline analytics
    loading,
    error,
  };
}

/** Get cached nikufra_data for backend API calls (optimize, what-if, replan). */
export function getCachedNikufraData(): Record<string, unknown> | null {
  return cached?.nikufraData ?? null;
}

// Allow external code to invalidate cache when replan happens
export function invalidateScheduleCache(): void {
  // Dispatch event so useScheduleData re-renders
  window.dispatchEvent(new Event('schedule-invalidate'));
  cached = null;
  cachePromise = null;
  cacheVersion++;
}

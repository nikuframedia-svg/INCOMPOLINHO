// useScheduleData — shared hook for schedule KPIs across all pages
// Module-level cache: computes once, shared across all consumers
// Reacts to useDataStore changes (ISOP upload) via dataVersion counter
// Backend CP-SAT is the ONLY scheduling path — no client-side fallback.
// schedule-pipeline logic inlined (was sole consumer).

import { useEffect, useMemo, useState } from 'react';
import type {
  AdvanceAction,
  Block,
  CoverageAuditResult,
  DayLoad,
  DecisionEntry,
  DispatchRule,
  EngineData,
  FeasibilityReport,
  LateDeliveryAnalysis,
  MoveAction,
  MRPResult,
  OptResult,
  ScheduleValidationReport,
  TransparencyReport,
} from '@/domain/types/scheduling';
import type {
  ActionMessagesSummary as BackendActionsSummary,
  CoverageAuditResult as BackendCoverageResult,
  DayLoad as BackendDayLoad,
  LateDeliveryAnalysis as BackendLateDeliveryAnalysis,
  MRPResult as BackendMRPResult,
  MRPSkuViewResult as BackendMRPSkuViewResult,
  ROPSummary as BackendROPSummary,
  CoverageMatrixSkuResult,
  QuickValidateResult,
  ReplanProposal,
  ScoreResult,
  ValidationResult,
  WorkforceForecastResult,
} from '../domain/api-types';
import type {
  ActionMessagesSummary,
  MRPSkuViewResult,
  ROPSkuSummary,
  ROPSummary,
} from '../domain/mrp/mrp-types';
import type { FullScheduleResponse } from '../lib/api';
import { scheduleFullApi } from '../lib/api';
import type { TransformConfigFromSettings } from '../stores/settings-config';
import { getTransformConfig, settingsHashSelector } from '../stores/settings-config';
import { useDataStore } from '../stores/useDataStore';
import { overridesVersionSelector, useMasterDataStore } from '../stores/useMasterDataStore';
import { useSettingsStore } from '../stores/useSettingsStore';
import { useDataSource } from './useDataSource';

// ── Types (inlined from schedule-pipeline.ts) ──

export interface BackendAnalytics {
  score: ScoreResult | null;
  validation: ValidationResult | null;
  coverage: BackendCoverageResult | null;
  cap: Record<string, BackendDayLoad[]> | null;
  mrpFull: BackendMRPResult | null;
  lateDeliveries: BackendLateDeliveryAnalysis | null;
  mrpSkuView: BackendMRPSkuViewResult | null;
  mrpRop: BackendROPSummary | null;
  mrpRopSku: BackendROPSummary | null;
  mrpActions: BackendActionsSummary | null;
  mrpCoverageSku: CoverageMatrixSkuResult | null;
  mrpCoverageMatrix: Record<string, unknown> | null;
  quickValidate: QuickValidateResult | null;
  genDecisions: ReplanProposal[] | null;
  workforceForecast: WorkforceForecastResult | null;
}

export interface CacheEntry {
  nikufraData: Record<string, unknown>;
  engine: EngineData;
  blocks: Block[];
  autoMoves: MoveAction[];
  autoAdvances: AdvanceAction[];
  decisions: DecisionEntry[];
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  mrp: MRPResult | null;
  resolvedDispatchRule: DispatchRule;
  thirdShiftRecommended: boolean;
  backendAnalytics: BackendAnalytics;
}

interface DataSourceLike {
  getNikufraData?: () => Record<string, unknown> | null;
  getPlanState?: () => Promise<unknown>;
}

// ── Pipeline (inlined from schedule-pipeline.ts) ──

async function runSchedulePipeline(
  ds: DataSourceLike,
  tcfg: TransformConfigFromSettings,
): Promise<CacheEntry> {
  const nikufraData = ds.getNikufraData?.();
  if (!nikufraData) {
    throw new Error(
      'NikufraData não disponível — o backend é obrigatório para scheduling. Carregue um ficheiro ISOP.',
    );
  }

  const settings = useSettingsStore.getState();

  const settingsPayload = {
    dispatchRule: settings.dispatchRule === 'AUTO' ? 'EDD' : settings.dispatchRule,
    thirdShift: settings.thirdShiftDefault,
    maxTier: 4,
    orderBased: true,
    demandSemantics: tcfg.demandSemantics || 'raw_np',
  };

  const response: FullScheduleResponse = await scheduleFullApi(
    { nikufra_data: nikufraData, settings: settingsPayload },
    30_000,
  );

  if (!response.blocks || response.blocks.length === 0) {
    if (response.parse_warnings?.some((w: string) => w.startsWith('Erro'))) {
      throw new Error(`Pipeline errors: ${response.parse_warnings.join('; ')}`);
    }
  }

  const data = (response.engine_data ?? {}) as unknown as EngineData;

  const dispatchRule: DispatchRule =
    settings.dispatchRule === 'AUTO' ? 'EDD' : (settings.dispatchRule as DispatchRule);

  console.info(
    `[schedule-pipeline] CP-SAT: ${response.n_blocks} blocks in ${response.solve_time_s}s (${response.solver_used})`,
  );

  const feas = response.feasibility_report as Record<string, unknown> | null;
  const remediations = feas?.remediations as Array<{ type: string }> | undefined;
  const mrp = (response.mrp ?? null) as unknown as MRPResult | null;

  const entry: CacheEntry = {
    nikufraData,
    engine: data,
    blocks: response.blocks as unknown as Block[],
    autoMoves: (response.auto_moves ?? []) as unknown as MoveAction[],
    autoAdvances: (response.auto_advances ?? []) as unknown as AdvanceAction[],
    decisions: (response.decisions ?? []) as unknown as DecisionEntry[],
    feasibilityReport: (response.feasibility_report ?? null) as unknown as FeasibilityReport | null,
    transparencyReport: null,
    mrp,
    resolvedDispatchRule: dispatchRule,
    thirdShiftRecommended: remediations?.some((r) => r.type === 'THIRD_SHIFT') ?? false,
    backendAnalytics: {
      score: response.score ?? null,
      validation: response.validation ?? null,
      coverage: response.coverage ?? null,
      cap: response.cap ?? null,
      mrpFull: response.mrp ?? null,
      lateDeliveries: response.late_deliveries ?? null,
      mrpSkuView: response.mrp_sku_view ?? null,
      mrpRop: response.mrp_rop ?? null,
      mrpRopSku: response.mrp_rop_sku ?? null,
      mrpActions: response.mrp_actions ?? null,
      mrpCoverageSku: response.mrp_coverage_sku ?? null,
      mrpCoverageMatrix: response.mrp_coverage_matrix ?? null,
      quickValidate: response.quick_validate ?? null,
      genDecisions: response.gen_decisions ?? null,
      workforceForecast: response.workforce_forecast ?? null,
    },
  };

  return applyPreStart(entry, data);
}

function applyPreStart(entry: CacheEntry, data: EngineData): CacheEntry {
  const preN = data._preStartDays ?? 0;
  if (preN > 0) {
    for (const b of entry.blocks) {
      if (b.dayIdx < preN) {
        b.preStart = true;
        b.preStartReason = `Produção antecipada ${preN - b.dayIdx} dia(s) antes do ISOP`;
      }
    }
  }
  return entry;
}

// ── Public interface ──

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
  genDecisions: ReplanProposal[] | null;
  quickValidate: QuickValidateResult | null;
  workforceForecast: WorkforceForecastResult | null;
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

  const cap = useMemo(() => (ba?.cap as Record<string, DayLoad[]>) ?? {}, []);

  const metrics = useMemo(() => (ba?.score as unknown as OptResult) ?? null, []);

  const validation = useMemo(
    () => (ba?.validation as unknown as ScheduleValidationReport) ?? null,
    [],
  );

  const coverageAudit = useMemo(() => (ba?.coverage as unknown as CoverageAuditResult) ?? null, []);

  const lateDeliveries = useMemo(
    () => (ba?.lateDeliveries as unknown as LateDeliveryAnalysis) ?? null,
    [],
  );

  const mrpSkuView = useMemo(() => (ba?.mrpSkuView as unknown as MRPSkuViewResult) ?? null, []);

  const mrpRop = useMemo(() => (ba?.mrpRop as unknown as ROPSummary) ?? null, []);

  const mrpRopSku = useMemo(() => (ba?.mrpRopSku as unknown as ROPSkuSummary) ?? null, []);

  const mrpActions = useMemo(
    () => (ba?.mrpActions as unknown as ActionMessagesSummary) ?? null,
    [],
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
    riskGrid: null,
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
  window.dispatchEvent(new Event('schedule-invalidate'));
  cached = null;
  cachePromise = null;
  cacheVersion++;
}

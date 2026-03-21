/**
 * schedule-pipeline.ts — Scheduling pipeline via backend CP-SAT.
 *
 * SINGLE PATH: Backend CP-SAT pipeline (/v1/pipeline/schedule/full).
 * No client-side computation — backend returns everything including EngineData.
 */

import type { TransformConfigFromSettings } from '../stores/settings-config';
import { useSettingsStore } from '../stores/useSettingsStore';

import type {
  AdvanceAction,
  Block,
  DecisionEntry,
  DispatchRule,
  EngineData,
  FeasibilityReport,
  MoveAction,
  MRPResult,
  TransparencyReport,
} from './engine';

import { type FullScheduleResponse, scheduleFullApi } from './api';

export interface CacheEntry {
  /** Raw nikufra_data — pass to backend endpoints (optimize, what-if, replan) */
  nikufraData: Record<string, unknown>;
  engine: EngineData;
  blocks: Block[];
  autoMoves: MoveAction[];
  autoAdvances: AdvanceAction[];
  decisions: DecisionEntry[];
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  mrp: MRPResult | null;
  /** The actual dispatch rule used (resolves AUTO to concrete rule) */
  resolvedDispatchRule: DispatchRule;
  /** True when feasibility report includes THIRD_SHIFT remediation */
  thirdShiftRecommended: boolean;
  /** Backend-computed analytics */
  backendAnalytics: {
    score: Record<string, unknown> | null;
    validation: Record<string, unknown> | null;
    coverage: Record<string, unknown> | null;
    cap: Record<string, unknown[]> | null;
    mrpFull: Record<string, unknown> | null;
    lateDeliveries: Record<string, unknown> | null;
    mrpSkuView: Record<string, unknown> | null;
    mrpRop: Record<string, unknown> | null;
    mrpRopSku: Record<string, unknown> | null;
    mrpActions: Record<string, unknown> | null;
    mrpCoverageSku: Record<string, unknown> | null;
    mrpCoverageMatrix: Record<string, unknown> | null;
    quickValidate: Record<string, unknown> | null;
    genDecisions: Record<string, unknown>[] | null;
    workforceForecast: Record<string, unknown> | null;
  };
}

export interface DataSourceLike {
  /** NikufraData for backend pipeline */
  getNikufraData?: () => Record<string, unknown> | null;
  /** Legacy — kept for interface compatibility but no longer used */
  getPlanState?: () => Promise<unknown>;
}

/**
 * Run the full scheduling pipeline via backend CP-SAT solver.
 *
 * 1. Get NikufraData from data source
 * 2. POST to /v1/pipeline/schedule/full
 * 3. Backend returns blocks + EngineData + all analytics
 * 4. Return CacheEntry — zero local computation
 */
export async function runSchedulePipeline(
  ds: DataSourceLike,
  tcfg: TransformConfigFromSettings,
): Promise<CacheEntry> {
  // NikufraData is required for backend pipeline
  const nikufraData = ds.getNikufraData?.();
  if (!nikufraData) {
    throw new Error(
      'NikufraData não disponível — o backend é obrigatório para scheduling. Carregue um ficheiro ISOP.',
    );
  }

  const settings = useSettingsStore.getState();

  // ── Call backend (returns everything — blocks, engine_data, analytics) ──
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

  // ── Validate response ──
  if (!response.blocks || response.blocks.length === 0) {
    if (response.parse_warnings?.some((w: string) => w.startsWith('Erro'))) {
      throw new Error(`Pipeline errors: ${response.parse_warnings.join('; ')}`);
    }
  }

  // ── Use backend-provided EngineData (camelCase from Python by_alias=True) ──
  const data = (response.engine_data ?? {}) as unknown as EngineData;

  const dispatchRule: DispatchRule =
    settings.dispatchRule === 'AUTO'
      ? 'EDD'
      : (settings.dispatchRule as DispatchRule);

  console.info(
    `[schedule-pipeline] CP-SAT: ${response.n_blocks} blocks in ${response.solve_time_s}s (${response.solver_used})`,
  );

  const feas = response.feasibility_report as Record<string, unknown> | null;
  const remediations = feas?.remediations as Array<{ type: string }> | undefined;

  // Backend MRP result (null if backend MRP failed or not available)
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

/** Mark pre-start blocks and third-shift recommendation. */
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

/**
 * schedule-pipeline.ts — Scheduling pipeline with backend-first strategy.
 *
 * PRIMARY: Backend pipeline (/v1/pipeline/schedule) — sends NikufraData JSON.
 * FALLBACK: Client-side TS engine (autoRouteOverflow) — when backend down.
 *
 * The backend handles: transform → MRP → scheduling → copilot state.
 * Frontend only does client-side scheduling as fallback.
 */

import { config } from '../config';
import {
  engineDataToSolverRequest,
  solverResultToBlocks,
} from '../features/scheduling/api/solver-bridge';
import type { OptimalResult } from '../features/scheduling/api/solverApi';
import { callOptimalPipeline } from '../features/scheduling/api/solverApi';
import type { TransformConfigFromSettings } from '../stores/settings-config';
import { useSettingsStore } from '../stores/useSettingsStore';

/** Fast health check — returns true if backend responds within 2s. */
let _backendAlive: boolean | null = null;
let _healthCheckPromise: Promise<boolean> | null = null;

async function isBackendAlive(): Promise<boolean> {
  if (_backendAlive !== null) return _backendAlive;
  if (_healthCheckPromise) return _healthCheckPromise;
  _healthCheckPromise = (async () => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const res = await fetch(`${config.apiBaseURL}/health`, { signal: ctrl.signal });
      clearTimeout(t);
      _backendAlive = res.ok;
    } catch {
      _backendAlive = false;
    }
    // Re-check every 30s
    setTimeout(() => {
      _backendAlive = null;
      _healthCheckPromise = null;
    }, 30_000);
    return _backendAlive!;
  })();
  return _healthCheckPromise;
}

import type {
  AdvanceAction,
  AutoReplanResult,
  Block,
  DecisionEntry,
  DispatchRule,
  EngineData,
  FeasibilityReport,
  MoveAction,
  MRPResult,
  PlanState,
  TransformConfig,
  TransparencyReport,
} from './engine';
import {
  autoReplan,
  autoRouteOverflow,
  computeMRP,
  computeSupplyPriority,
  DEFAULT_AUTO_REPLAN_CONFIG,
  DISPATCH_BANDIT,
  transformPlanState,
} from './engine';

export interface CacheEntry {
  engine: EngineData;
  blocks: Block[];
  autoMoves: MoveAction[];
  autoAdvances: AdvanceAction[];
  decisions: DecisionEntry[];
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  mrp: MRPResult;
  /** The actual dispatch rule used (resolves AUTO to concrete rule) */
  resolvedDispatchRule: DispatchRule;
  /** True when feasibility report includes THIRD_SHIFT remediation */
  thirdShiftRecommended: boolean;
  /** Monte Carlo robustness data from optimal pipeline (null if not available) */
  robustness?: OptimalResult['robustness'];
}

export interface DataSourceLike {
  getPlanState: () => Promise<PlanState>;
  /** NikufraData for backend pipeline (if available) */
  getNikufraData?: () => Record<string, unknown> | null;
}

/**
 * Try the backend pipeline first — sends NikufraData to /v1/pipeline/schedule.
 * Returns CacheEntry on success, null if backend unavailable.
 */
async function tryBackendPipeline(
  ds: DataSourceLike,
  planState: PlanState,
  tcfg: TransformConfigFromSettings,
): Promise<CacheEntry | null> {
  // Need NikufraData for backend pipeline
  const nikufraData = ds.getNikufraData?.();
  if (!nikufraData) return null;

  const settings = useSettingsStore.getState();

  try {
    const { callBackendPipeline } = await import('../features/scheduling/api/pipelineApi');

    const settingsPayload = {
      dispatchRule: settings.dispatchRule === 'AUTO' ? 'EDD' : settings.dispatchRule,
      thirdShift: planState.thirdShift ?? settings.thirdShiftDefault,
      maxTier: 4,
      orderBased: true,
      demandSemantics: tcfg.demandSemantics || 'raw_np',
    };

    const response = await callBackendPipeline(nikufraData, settingsPayload);

    if (!response.blocks || response.blocks.length === 0) {
      // Backend returned empty — check for errors
      if (response.parse_warnings?.some((w: string) => w.startsWith('Erro'))) {
        console.warn('[schedule-pipeline] Backend pipeline error:', response.parse_warnings);
        return null;
      }
    }

    // We still need local EngineData for analytics (cap, score, validate, etc.)
    const transformConfig: TransformConfig = {
      moStrategy: tcfg.moStrategy,
      moNominalPG1: tcfg.moNominalPG1,
      moNominalPG2: tcfg.moNominalPG2,
      moCustomPG1: tcfg.moCustomPG1,
      moCustomPG2: tcfg.moCustomPG2,
      demandSemantics: tcfg.demandSemantics || 'raw_np',
      preStartBufferDays: tcfg.preStartBufferDays,
    };
    const data = transformPlanState(planState, transformConfig);
    const mrp = computeMRP(data);

    const dispatchRule: DispatchRule =
      settings.dispatchRule === 'AUTO'
        ? DISPATCH_BANDIT.select()
        : (settings.dispatchRule as DispatchRule);

    const thirdShiftRecommended = !!response.feasibility_report?.remediations?.some(
      (r: { type: string }) => r.type === 'THIRD_SHIFT',
    );

    console.info(
      `[schedule-pipeline] Backend pipeline OK: ${response.n_blocks} blocks in ${response.solve_time_s}s`,
    );

    return {
      engine: data,
      blocks: response.blocks,
      autoMoves: response.auto_moves ?? [],
      autoAdvances: response.auto_advances ?? [],
      decisions: response.decisions ?? [],
      feasibilityReport: response.feasibility_report ?? null,
      transparencyReport: null,
      mrp,
      resolvedDispatchRule: dispatchRule,
      thirdShiftRecommended,
    };
  } catch (e) {
    console.warn(
      '[schedule-pipeline] Backend pipeline unavailable, falling back to client-side:',
      e instanceof Error ? e.message : String(e),
    );
    return null;
  }
}

/**
 * Try the optimal pipeline (CP-SAT + Recovery + Monte Carlo).
 * Returns CacheEntry on success, null if backend unavailable.
 */
async function tryOptimalPipeline(
  data: EngineData,
  mrp: MRPResult,
  dispatchRule: DispatchRule,
  settings: ReturnType<typeof useSettingsStore.getState>,
): Promise<CacheEntry | null> {
  if (!settings.useServerSolver) return null;

  try {
    const request = engineDataToSolverRequest(data, {
      oee: settings.oee,
      timeLimit: settings.serverSolverTimeLimit,
      objective: settings.serverSolverObjective,
    });

    const optimalResult = await callOptimalPipeline({
      solver_request: request,
      frozen_ops: [],
      alt_machines: null,
      run_monte_carlo: true,
      n_scenarios: 200,
    });

    const blocks = solverResultToBlocks(optimalResult.solver_result, data);

    console.info(
      `[schedule-pipeline] Optimal pipeline OK: ${blocks.length} blocks, ` +
        `solver=${optimalResult.solver_result.solver_used}, ` +
        `status=${optimalResult.solver_result.status}, ` +
        `tardiness=${optimalResult.solver_result.total_tardiness_min}min, ` +
        `recovery=${optimalResult.recovery_used ? `L${optimalResult.recovery_level}` : 'none'}, ` +
        `P(OTD=100%)=${optimalResult.robustness?.p_otd_100 ?? 'N/A'}%`,
    );

    return {
      engine: data,
      blocks,
      autoMoves: [],
      autoAdvances: [],
      decisions: [],
      feasibilityReport: null,
      transparencyReport: null,
      mrp,
      resolvedDispatchRule: dispatchRule,
      thirdShiftRecommended: false,
      robustness: optimalResult.robustness,
    };
  } catch (e) {
    console.warn(
      '[schedule-pipeline] Optimal pipeline failed:',
      e instanceof Error ? e.message : String(e),
    );
    return null;
  }
}

/**
 * Run the full scheduling pipeline:
 * 1. Try optimal pipeline (CP-SAT + Recovery + Monte Carlo)
 * 2. Try backend Python ATCS pipeline
 * 3. Fallback: client-side TS engine (autoRouteOverflow)
 */
export async function runSchedulePipeline(
  ds: DataSourceLike,
  tcfg: TransformConfigFromSettings,
): Promise<CacheEntry> {
  let planState;
  try {
    planState = await ds.getPlanState();
  } catch (e) {
    throw new Error(`Falha ao carregar dados: ${e instanceof Error ? e.message : String(e)}`);
  }

  const settings = useSettingsStore.getState();

  // ── Always transform locally (needed for analytics + fallbacks) ──
  const transformConfig: TransformConfig = {
    moStrategy: tcfg.moStrategy,
    moNominalPG1: tcfg.moNominalPG1,
    moNominalPG2: tcfg.moNominalPG2,
    moCustomPG1: tcfg.moCustomPG1,
    moCustomPG2: tcfg.moCustomPG2,
    demandSemantics: tcfg.demandSemantics,
    preStartBufferDays: tcfg.preStartBufferDays,
  };

  if (!transformConfig.demandSemantics) {
    transformConfig.demandSemantics = 'raw_np';
    console.warn('[schedule-pipeline] demandSemantics was falsy — forced to raw_np');
  }

  const data = transformPlanState(planState, transformConfig);

  if (transformConfig.demandSemantics === 'raw_np') {
    const hasInput = planState.operations.some((o) =>
      o.daily_qty.some((v) => v != null && v !== 0),
    );
    const hasDemand = data.ops.some((o) => o.d.some((v) => v > 0));
    if (hasInput && !hasDemand) {
      console.warn(
        '[schedule-pipeline] ZERO_DEMAND: rawNPtoOrderDemand produced 0 demand.',
        'demandSemantics:',
        transformConfig.demandSemantics,
        'sample daily_qty:',
        planState.operations[0]?.daily_qty.slice(0, 5),
        'sample engine d:',
        data.ops[0]?.d.slice(0, 5),
      );
    }
  }

  const mrp = computeMRP(data);
  const supplyBoosts = computeSupplyPriority(data, mrp);

  const dispatchRule: DispatchRule =
    settings.dispatchRule === 'AUTO'
      ? DISPATCH_BANDIT.select()
      : (settings.dispatchRule as DispatchRule);

  // ── Health check: skip backend steps if server unreachable ──
  const wantBackend = settings.useServerSolver || settings.usePythonScheduler;
  const backendOk = wantBackend ? await isBackendAlive() : false;

  // ── STEP 1: Optimal Pipeline (CP-SAT + Recovery + Monte Carlo) ──
  if (backendOk) {
    const optimalResult = await tryOptimalPipeline(data, mrp, dispatchRule, settings);
    if (optimalResult) {
      return applyPreStart(optimalResult, data);
    }
  }

  // ── STEP 2: Backend Python ATCS pipeline ──
  if (backendOk && settings.usePythonScheduler) {
    const backendResult = await tryBackendPipeline(ds, planState, tcfg);
    if (backendResult) return backendResult;
  }

  // ── STEP 3: Client-side TS engine ──
  let resultBlocks: Block[];
  let resultMoves: MoveAction[] = [];
  let resultAdvances: AdvanceAction[] = [];
  let resultDecisions: DecisionEntry[] = [];
  let resultFeasibility: FeasibilityReport | null = null;
  let resultTransparency: TransparencyReport | null = null;

  if (settings.enableAutoReplan) {
    const replanResult: AutoReplanResult = autoReplan(
      {
        ops: data.ops,
        mSt: data.mSt,
        tSt: data.tSt,
        moves: [],
        machines: data.machines,
        toolMap: data.toolMap,
        workdays: data.workdays,
        nDays: data.nDays,
        workforceConfig: data.workforceConfig,
        rule: dispatchRule,
        supplyBoosts: supplyBoosts.size > 0 ? supplyBoosts : undefined,
        thirdShift: planState.thirdShift ?? settings.thirdShiftDefault,
        machineTimelines: data.machineTimelines,
        toolTimelines: data.toolTimelines,
        dates: data.dates,
        twinValidationReport: data.twinValidationReport,
        orderBased: data.orderBased,
      },
      { ...DEFAULT_AUTO_REPLAN_CONFIG, ...settings.autoReplanConfig },
    );
    resultBlocks = replanResult.blocks;
    resultMoves = replanResult.autoMoves;
    resultAdvances = replanResult.autoAdvances ?? [];
    resultDecisions = replanResult.decisions;
    resultFeasibility = replanResult.scheduleResult?.feasibilityReport ?? null;
    resultTransparency = replanResult.scheduleResult?.transparencyReport ?? null;
  } else {
    const overflowResult = autoRouteOverflow({
      ops: data.ops,
      mSt: data.mSt,
      tSt: data.tSt,
      userMoves: [],
      machines: data.machines,
      toolMap: data.toolMap,
      workdays: data.workdays,
      nDays: data.nDays,
      workforceConfig: data.workforceConfig,
      rule: dispatchRule,
      supplyBoosts: supplyBoosts.size > 0 ? supplyBoosts : undefined,
      thirdShift: planState.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: data.machineTimelines,
      toolTimelines: data.toolTimelines,
      twinValidationReport: data.twinValidationReport,
      dates: data.dates,
      orderBased: data.orderBased,
    });
    resultBlocks = overflowResult.blocks;
    resultMoves = overflowResult.autoMoves;
    resultAdvances = overflowResult.autoAdvances ?? [];
    resultDecisions = overflowResult.decisions ?? [];
    resultFeasibility = overflowResult.feasibilityReport ?? null;
  }

  const entry: CacheEntry = {
    engine: data,
    blocks: resultBlocks,
    autoMoves: resultMoves,
    autoAdvances: resultAdvances,
    decisions: resultDecisions,
    feasibilityReport: resultFeasibility,
    transparencyReport: resultTransparency,
    mrp,
    resolvedDispatchRule: dispatchRule,
    thirdShiftRecommended: !!resultFeasibility?.remediations?.some((r) => r.type === 'THIRD_SHIFT'),
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
        b.preStartReason = `Producao antecipada ${preN - b.dayIdx} dia(s) antes do ISOP`;
      }
    }
  }
  return entry;
}

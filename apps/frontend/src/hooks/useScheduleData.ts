// useScheduleData — shared hook for schedule KPIs across all pages
// Loads nikufra_data.json (or user-uploaded ISOP) → transforms → schedules → computes KPIs
// Module-level cache: computes once, shared across all consumers
// Reacts to useDataStore changes (ISOP upload) via dataVersion counter
//
// INCOMPOL PLAN integration: uses incompol-plan library as SOLE scheduling engine.
// All functions are pure, synchronous, and side-effect-free.

import { useEffect, useMemo, useState } from 'react';
import type {
  AdvanceAction,
  AutoReplanResult,
  Block,
  CoverageAuditResult,
  DayLoad,
  DecisionEntry,
  DispatchRule,
  EngineData,
  FeasibilityReport,
  MoveAction,
  MRPResult,
  OptResult,
  ScheduleValidationReport,
  TransformConfig,
  TransparencyReport,
} from '../lib/engine';
import {
  auditCoverage,
  autoReplan,
  autoRouteOverflow,
  capAnalysis,
  computeMRP,
  computeSupplyPriority,
  DEFAULT_AUTO_REPLAN_CONFIG,
  DEFAULT_WORKFORCE_CONFIG,
  scoreSchedule,
  transformPlanState,
  validateSchedule,
} from '../lib/engine';
import { useDataStore } from '../stores/useDataStore';
import { getTransformConfig, useSettingsStore } from '../stores/useSettingsStore';
import { useDataSource } from './useDataSource';

export interface ScheduleData {
  engine: EngineData | null;
  blocks: Block[];
  autoMoves: MoveAction[];
  autoAdvances: AdvanceAction[];
  decisions: DecisionEntry[];
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  cap: Record<string, DayLoad[]>;
  metrics: (OptResult & { blocks: Block[] }) | null;
  validation: ScheduleValidationReport | null;
  coverageAudit: CoverageAuditResult | null;
  mrp: MRPResult | null;
  loading: boolean;
  error: string | null;
}

// Module-level cache — computed once per session, invalidated on data change
interface CacheEntry {
  engine: EngineData;
  blocks: Block[];
  autoMoves: MoveAction[];
  autoAdvances: AdvanceAction[];
  decisions: DecisionEntry[];
  feasibilityReport: FeasibilityReport | null;
  transparencyReport: TransparencyReport | null;
  mrp: MRPResult;
}

let cached: CacheEntry | null = null;
let cachePromise: Promise<void> | null = null;
let cachedDataVersion: string | null = null;
// Cache version counter to detect stale computations
let cacheVersion = 0;

export function useScheduleData(): ScheduleData {
  const ds = useDataSource();
  // Subscribe to data store changes — loadedAt changes when user uploads new ISOP
  const dataVersion = useDataStore((s) => s.loadedAt);
  // Block scheduling while merge is in progress to prevent stale renders
  const isMerging = useDataStore((s) => s.isMerging);
  // Subscribe to ALL settings changes — schedule must recompute when any setting changes.
  // Using a composite hash avoids 30+ individual selectors.
  const settingsHash = useSettingsStore((s) => {
    const {
      shiftXStart,
      shiftChange,
      shiftYEnd,
      oee,
      thirdShiftDefault,
      dispatchRule,
      bucketWindowDays,
      maxEddGapDays,
      defaultSetupHours,
      optimizationProfile,
      wTardiness,
      wSetupCount,
      wSetupTime,
      wSetupBalance,
      wChurn,
      wOverflow,
      wBelowMinBatch,
      wCapacityVariance,
      wSetupDensity,
      moStrategy,
      moNominalPG1,
      moNominalPG2,
      moCustomPG1,
      moCustomPG2,
      altUtilThreshold,
      maxAutoMoves,
      maxOverflowIter,
      otdTolerance,
      loadBalanceThreshold,
      enableAutoReplan,
      enableShippingCutoff,
      demandSemantics,
      serviceLevel,
      coverageThresholdDays,
      abcThresholdA,
      abcThresholdB,
      xyzThresholdX,
      xyzThresholdY,
    } = s;
    return JSON.stringify({
      shiftXStart,
      shiftChange,
      shiftYEnd,
      oee,
      thirdShiftDefault,
      dispatchRule,
      bucketWindowDays,
      maxEddGapDays,
      defaultSetupHours,
      optimizationProfile,
      wTardiness,
      wSetupCount,
      wSetupTime,
      wSetupBalance,
      wChurn,
      wOverflow,
      wBelowMinBatch,
      wCapacityVariance,
      wSetupDensity,
      moStrategy,
      moNominalPG1,
      moNominalPG2,
      moCustomPG1,
      moCustomPG2,
      altUtilThreshold,
      maxAutoMoves,
      maxOverflowIter,
      otdTolerance,
      loadBalanceThreshold,
      enableAutoReplan,
      enableShippingCutoff,
      demandSemantics,
      serviceLevel,
      coverageThresholdDays,
      abcThresholdA,
      abcThresholdB,
      xyzThresholdX,
      xyzThresholdY,
    });
  });

  const [engine, setEngine] = useState<EngineData | null>(cached?.engine ?? null);
  const [blocks, setBlocks] = useState<Block[]>(cached?.blocks ?? []);
  const [autoMoves, setAutoMoves] = useState<MoveAction[]>(cached?.autoMoves ?? []);
  const [autoAdvances, setAutoAdvances] = useState<AdvanceAction[]>(cached?.autoAdvances ?? []);
  const [decisions, setDecisions] = useState<DecisionEntry[]>(cached?.decisions ?? []);
  const [feasibilityReport, setFeasibilityReport] = useState<FeasibilityReport | null>(
    cached?.feasibilityReport ?? null,
  );
  const [transparencyReport, setTransparencyReport] = useState<TransparencyReport | null>(
    cached?.transparencyReport ?? null,
  );
  const [mrpData, setMrpData] = useState<MRPResult | null>(cached?.mrp ?? null);
  const [loading, setLoading] = useState(!cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Block scheduling while merge is in progress to prevent stale renders
    if (isMerging) {
      setLoading(true);
      return;
    }

    // If data version changed, invalidate cache
    if (dataVersion !== cachedDataVersion) {
      cached = null;
      cachePromise = null;
      cachedDataVersion = dataVersion;
      cacheVersion++;
    }

    if (cached) {
      setEngine(cached.engine);
      setBlocks(cached.blocks);
      setAutoMoves(cached.autoMoves);
      setAutoAdvances(cached.autoAdvances);
      setDecisions(cached.decisions);
      setFeasibilityReport(cached.feasibilityReport);
      setTransparencyReport(cached.transparencyReport);
      setMrpData(cached.mrp);
      setLoading(false);
      return;
    }
    if (cachePromise) {
      cachePromise.then(() => {
        if (cached) {
          setEngine(cached.engine);
          setBlocks(cached.blocks);
          setAutoMoves(cached.autoMoves);
          setAutoAdvances(cached.autoAdvances);
          setDecisions(cached.decisions);
          setFeasibilityReport(cached.feasibilityReport);
          setTransparencyReport(cached.transparencyReport);
          setMrpData(cached.mrp);
        }
        setLoading(false);
      });
      return;
    }

    setLoading(true);
    setError(null);
    // Capture version at start of computation to detect staleness
    const computeVersion = cacheVersion;
    cachePromise = (async () => {
      // Guard against missing data source method
      if (!ds?.getPlanState) {
        throw new Error('Data source unavailable — getPlanState not found');
      }

      let planState;
      try {
        planState = await ds.getPlanState();
      } catch (e) {
        throw new Error(`Falha ao carregar dados: ${e instanceof Error ? e.message : String(e)}`);
      }

      // If version changed during async computation, discard result
      if (computeVersion !== cacheVersion) return;

      // ── 1. Transform PlanState → EngineData ──
      // Build TransformConfig from user settings
      const tcfg = getTransformConfig();
      const transformConfig: TransformConfig = {
        moStrategy: tcfg.moStrategy,
        moNominalPG1: tcfg.moNominalPG1,
        moNominalPG2: tcfg.moNominalPG2,
        moCustomPG1: tcfg.moCustomPG1,
        moCustomPG2: tcfg.moCustomPG2,
        demandSemantics: tcfg.demandSemantics,
      };
      const data = transformPlanState(planState, transformConfig);

      // ── 2. Compute MRP + supply priority ──
      const mrp = computeMRP(data);
      const supplyBoosts = computeSupplyPriority(data, mrp);

      // ── 3. Read scheduling settings ──
      const settings = useSettingsStore.getState();
      const dispatchRule: DispatchRule = settings.dispatchRule as DispatchRule;
      // ── 4. Schedule: autoRouteOverflow or autoReplan ──
      let resultBlocks: Block[];
      let resultMoves: MoveAction[] = [];
      let resultAdvances: AdvanceAction[] = [];
      let resultDecisions: DecisionEntry[] = [];
      let resultFeasibility: FeasibilityReport | null = null;
      let resultTransparency: TransparencyReport | null = null;

      if (settings.enableAutoReplan) {
        // Full auto-replan path (5 strategies)
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
        // Standard overflow routing path
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
      }

      // Only write cache if still the current version
      if (computeVersion === cacheVersion) {
        cached = {
          engine: data,
          blocks: resultBlocks,
          autoMoves: resultMoves,
          autoAdvances: resultAdvances,
          decisions: resultDecisions,
          feasibilityReport: resultFeasibility,
          transparencyReport: resultTransparency,
          mrp,
        };
      }
    })();

    cachePromise
      .then(() => {
        // B1+B2 fix: guard against stale computation results
        if (computeVersion !== cacheVersion) return;
        if (cached) {
          setEngine(cached.engine);
          setBlocks(cached.blocks);
          setAutoMoves(cached.autoMoves);
          setAutoAdvances(cached.autoAdvances);
          setDecisions(cached.decisions);
          setFeasibilityReport(cached.feasibilityReport);
          setTransparencyReport(cached.transparencyReport);
          setMrpData(cached.mrp);
        }
      })
      .catch((e) => {
        // B5 fix: clear ALL state on error to avoid showing stale data
        setError(e instanceof Error ? e.message : 'Failed to load schedule data');
        setEngine(null);
        setBlocks([]);
        setAutoMoves([]);
        setAutoAdvances([]);
        setDecisions([]);
        setFeasibilityReport(null);
        setTransparencyReport(null);
        setMrpData(null);
      })
      .finally(() => setLoading(false));
  }, [ds, dataVersion, settingsHash, isMerging]);

  const cap = useMemo(
    () => (engine ? capAnalysis(blocks, engine.machines, engine.nDays) : {}),
    [blocks, engine],
  );

  const metrics = useMemo(() => {
    if (!engine || blocks.length === 0) return null;
    // Use workforceConfig from EngineData (includes MO array per day),
    // falling back to DEFAULT_WORKFORCE_CONFIG
    const wfc = engine.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG;
    return scoreSchedule(
      blocks,
      engine.ops,
      engine.mSt,
      wfc,
      engine.machines,
      engine.toolMap,
      undefined,
      undefined,
      engine.nDays,
    );
  }, [blocks, engine]);

  const validation = useMemo(() => {
    if (!engine || blocks.length === 0) return null;
    return validateSchedule(
      blocks,
      engine.machines,
      engine.toolMap,
      engine.ops,
      engine.thirdShift,
      engine.nDays,
    );
  }, [blocks, engine]);

  const coverageAudit = useMemo(() => {
    if (!engine || blocks.length === 0) return null;
    return auditCoverage(blocks, engine.ops, engine.toolMap, engine.twinGroups);
  }, [blocks, engine]);

  return {
    engine,
    blocks,
    autoMoves,
    autoAdvances,
    decisions,
    feasibilityReport,
    transparencyReport,
    cap,
    metrics,
    validation,
    coverageAudit,
    mrp: mrpData,
    loading,
    error,
  };
}

// Allow external code to invalidate cache when replan happens
export function invalidateScheduleCache(): void {
  cached = null;
  cachePromise = null;
  cacheVersion++;
}

import { Check, X, Zap } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDataSource } from '../../../hooks/useDataSource';
import type {
  Block,
  DecisionEntry,
  DispatchRule,
  EngineData,
  EOp,
  MoveAction,
} from '../../../lib/engine';
import {
  autoReplan,
  autoRouteOverflow,
  C,
  capAnalysis,
  DEFAULT_AUTO_REPLAN_CONFIG,
  DEFAULT_WORKFORCE_CONFIG,
  getReplanActions,
  scoreSchedule,
  transformPlanState,
} from '../../../lib/engine';
import useReplanStore from '../../../stores/useReplanStore';
import useSettingsStore, { getTransformConfig } from '../../../stores/useSettingsStore';
import useToastStore from '../../../stores/useToastStore';
import { useScheduleFilters } from '../hooks/useScheduleFilters';
import { useScheduleValidation } from '../hooks/useScheduleValidation';
import { dot, Pill } from './atoms';
import GanttView from './GanttChart/GanttChart';
import ReplanView from './ReplanPanel';
import PlanView from './ScheduleKPIs';
import WhatIfView from './WhatIfPanel';
import '../../planning/NikufraEngine.css';

export default function SchedulingPage() {
  const ds = useDataSource();
  const [engineData, setEngineData] = useState<EngineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { state: filters, actions: filterActions } = useScheduleFilters(engineData);
  const { mSt, tSt, failureEvents, isScheduling, replanTimelines } = filters;
  const {
    setMSt,
    setTSt,
    toggleM,
    toggleT,
    setResourceDown,
    clearResourceDown,
    getResourceDownDays,
  } = filterActions;
  const [moves, setMoves] = useState<MoveAction[]>([]);
  const [view, setView] = useState('plan');
  const [isSaving, setIsSaving] = useState(false);
  const [rushOrders, setRushOrders] = useState<
    Array<{ toolId: string; sku: string; qty: number; deadline: number }>
  >([]);
  const [isopBanner, setIsopBanner] = useState<string | null>(null);
  const prevOpsRef = useRef<EOp[] | null>(null);

  const loadData = useCallback(async () => {
    if (!ds.getPlanState) {
      setError('Planning engine not available in this data source');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const tcfg = getTransformConfig();
      const data = transformPlanState(await ds.getPlanState(), {
        moStrategy: tcfg.moStrategy,
        moNominalPG1: tcfg.moNominalPG1,
        moNominalPG2: tcfg.moNominalPG2,
        moCustomPG1: tcfg.moCustomPG1,
        moCustomPG2: tcfg.moCustomPG2,
        demandSemantics: tcfg.demandSemantics,
      });
      setEngineData(data);
      filterActions.resetFilters(data.machines);
      setMoves([]);
      setIsopBanner(null);
      prevOpsRef.current = data.ops;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load plan state');
    } finally {
      setLoading(false);
    }
  }, [ds]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const applyMove = useCallback(
    (opId: string, toM: string) =>
      setMoves((p) => (p.find((m) => m.opId === opId) ? p : [...p, { opId, toM }])),
    [],
  );
  const undoMove = useCallback(
    (opId: string) => setMoves((p) => p.filter((m) => m.opId !== opId)),
    [],
  );
  const handleApplyAndSave = useCallback(
    async (
      movesToApply?: MoveAction[],
      scenarioState?: { mSt: Record<string, string>; tSt: Record<string, string> },
    ) => {
      const applyMoves = movesToApply || moves;
      const appliedMSt = scenarioState?.mSt || mSt;
      const appliedTSt = scenarioState?.tSt || tSt;
      if (applyMoves.length === 0 && Object.values(appliedMSt).every((s) => s !== 'down')) return;
      if (ds.applyReplan) {
        setIsSaving(true);
        try {
          const backendMoves = applyMoves.map((mv) => {
            const origM = engineData?.ops.find((o) => o.id === mv.opId)?.m || '';
            return { op_id: mv.opId, from_machine: origM, to_machine: mv.toM };
          });
          const machineStatus: Record<string, string> = {};
          for (const [id, st] of Object.entries(appliedMSt)) {
            if (st === 'down') machineStatus[id] = 'down';
          }
          const toolStatus: Record<string, string> = {};
          for (const [id, st] of Object.entries(appliedTSt)) {
            if (st === 'down') toolStatus[id] = 'down';
          }
          await ds.applyReplan({
            moves: backendMoves,
            machine_status: machineStatus,
            tool_status: toolStatus,
            author: 'planner-001',
            description: `Replan: ${applyMoves.length} movimentos`,
          });
          await loadData();
          useToastStore
            .getState()
            .addToast(
              `Replan aplicado: ${applyMoves.length} movimentos guardados`,
              'success',
              5000,
            );
          setView('plan');
        } catch (e) {
          useToastStore
            .getState()
            .addToast(
              `Erro ao aplicar replan: ${e instanceof Error ? e.message : String(e)}`,
              'error',
              6000,
            );
        } finally {
          setIsSaving(false);
        }
      } else {
        if (scenarioState) {
          setMSt(scenarioState.mSt);
          setTSt(scenarioState.tSt);
        }
        setMoves(applyMoves);
        useToastStore
          .getState()
          .addToast(`Plano aplicado: ${applyMoves.length} movimentos`, 'success', 5000);
        setView('gantt');
      }
    },
    [ds, moves, mSt, tSt, engineData, loadData],
  );

  useEffect(() => {
    useReplanStore.getState().onApplyCallback = loadData;
    return () => {
      useReplanStore.getState().onApplyCallback = null;
    };
  }, [loadData]);

  const rushOps = useMemo((): EOp[] => {
    if (!engineData || rushOrders.length === 0) return [];
    return rushOrders
      .map((ro, idx): EOp | null => {
        const tool = engineData.toolMap[ro.toolId];
        if (!tool) return null;
        const d = Array(engineData.nDays).fill(0) as number[];
        d[ro.deadline] = -ro.qty;
        return {
          id: `rush-${ro.toolId}-${ro.deadline}-${ro.qty}-${idx}`,
          t: ro.toolId,
          m: tool.m,
          sku: ro.sku,
          nm: `RUSH: ${tool.nm || ro.sku}`,
          atr: 0,
          d,
        };
      })
      .filter((op): op is EOp => op !== null);
  }, [engineData, rushOrders]);
  const allOps = useMemo(
    () =>
      !engineData
        ? ([] as EOp[])
        : rushOps.length > 0
          ? [...engineData.ops, ...rushOps]
          : engineData.ops,
    [engineData, rushOps],
  );

  const {
    blocks,
    autoMoves,
    decisions: schedDecisions,
  } = useMemo(() => {
    if (!engineData)
      return {
        blocks: [] as Block[],
        autoMoves: [] as MoveAction[],
        decisions: [] as DecisionEntry[],
      };
    const settings = useSettingsStore.getState();
    const isInteractive = failureEvents.length > 0 || moves.length > 0;
    return autoRouteOverflow({
      ops: allOps,
      mSt,
      tSt,
      userMoves: moves,
      machines: engineData.machines,
      toolMap: engineData.toolMap,
      workdays: engineData.workdays,
      nDays: engineData.nDays,
      workforceConfig: engineData.workforceConfig,
      rule: (settings.dispatchRule as DispatchRule) || 'EDD',
      thirdShift: engineData.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? engineData.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? engineData.toolTimelines,
      twinValidationReport: engineData.twinValidationReport,
      dates: engineData.dates,
      orderBased: engineData.orderBased,
      maxTier: isInteractive ? 2 : undefined,
    });
  }, [engineData, allOps, mSt, tSt, moves, replanTimelines, failureEvents.length]);
  const cap = useMemo(
    () => (engineData ? capAnalysis(blocks, engineData.machines) : {}),
    [blocks, engineData],
  );
  const neMetrics = useMemo(() => {
    if (!engineData || blocks.length === 0) return null;
    return scoreSchedule(
      blocks,
      allOps,
      engineData.mSt,
      engineData.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
      engineData.machines,
      engineData.toolMap,
      undefined,
      undefined,
      engineData.nDays,
    );
  }, [blocks, allOps, engineData]);
  const { validation, audit, feasibility } = useScheduleValidation(blocks, allOps, engineData);
  const handlePlanAutoReplan = useCallback(() => {
    if (!engineData) return null;
    try {
      const settings = useSettingsStore.getState();
      const rule = (settings.dispatchRule || 'EDD') as DispatchRule;
      const result = autoReplan(
        {
          ops: allOps,
          mSt,
          tSt,
          moves: [] as MoveAction[],
          machines: engineData.machines,
          toolMap: engineData.toolMap,
          workdays: engineData.workdays,
          nDays: engineData.nDays,
          workforceConfig: engineData.workforceConfig,
          rule,
          thirdShift: engineData.thirdShift ?? settings.thirdShiftDefault,
          machineTimelines: replanTimelines?.machineTimelines ?? engineData.machineTimelines,
          toolTimelines: replanTimelines?.toolTimelines ?? engineData.toolTimelines,
          dates: engineData.dates,
          twinValidationReport: engineData.twinValidationReport,
          orderBased: engineData.orderBased,
        },
        DEFAULT_AUTO_REPLAN_CONFIG,
      );
      return {
        actions: getReplanActions(result),
        moveCount: result.autoMoves.length,
        unresolvedCount: result.unresolved.length,
      };
    } catch (e) {
      useToastStore
        .getState()
        .addToast(
          `Erro no auto-replan: ${e instanceof Error ? e.message : String(e)}`,
          'error',
          5000,
        );
      return null;
    }
  }, [engineData, allOps, mSt, tSt, replanTimelines]);

  const downC = Object.values(mSt).filter((s) => s === 'down').length;
  const blkOps = new Set(blocks.filter((b) => b.type === 'blocked').map((b) => b.opId)).size;
  const tabs = [
    { id: 'plan', l: 'Plan' },
    { id: 'gantt', l: 'Gantt' },
    { id: 'replan', l: 'Replan' },
    { id: 'whatif', l: 'What-If' },
  ];
  if (loading)
    return (
      <div className="ne-shell ne-loading">
        <div className="ne-loading__spinner" />
        <div className="ne-loading__text">A carregar planning engine...</div>
      </div>
    );
  if (error || !engineData)
    return (
      <div className="ne-shell ne-error">
        <div className="ne-error__icon" style={{ color: C.rd }}>
          ERROR
        </div>
        <div className="ne-error__msg">{error || 'Engine indisponível'}</div>
        <button className="ne-error__retry" onClick={loadData}>
          Tentar novamente
        </button>
      </div>
    );
  return (
    <div style={{ fontFamily: "'Plus Jakarta Sans','Inter',system-ui,sans-serif", color: C.t1 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: `1px solid ${C.bd}`,
          padding: '0 20px',
        }}
      >
        <div style={{ display: 'flex', gap: 2 }}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setView(tab.id)}
              style={{
                padding: '8px 18px',
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                fontSize: 11,
                fontWeight: 600,
                color: view === tab.id ? C.ac : C.t3,
                borderBottom: `2px solid ${view === tab.id ? C.ac : 'transparent'}`,
                fontFamily: 'inherit',
                letterSpacing: '.02em',
                transition: 'all .15s',
              }}
            >
              {tab.l}
              {tab.id === 'replan' && (moves.length > 0 || blkOps > 0) && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 5,
                    height: 5,
                    borderRadius: '50%',
                    background: blkOps > 0 ? C.rd : C.ac,
                    marginLeft: 6,
                  }}
                />
              )}
              {tab.id === 'gantt' && validation && !validation.valid && (
                <span
                  style={{
                    display: 'inline-block',
                    width: 5,
                    height: 5,
                    borderRadius: '50%',
                    background: C.rd,
                    marginLeft: 6,
                  }}
                />
              )}
            </button>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {downC > 0 && (
            <Pill color={C.rd} active>
              <span style={dot(C.rd, true)} />
              {downC} DOWN
            </Pill>
          )}
          {moves.length > 0 && (
            <Pill color={C.ac} active>
              <Check
                size={10}
                strokeWidth={2}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />{' '}
              {moves.length}
            </Pill>
          )}
          {autoMoves.length > 0 && (
            <Pill color={C.bl} active>
              <Zap
                size={10}
                strokeWidth={1.5}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />{' '}
              {autoMoves.length} auto
            </Pill>
          )}
          {blkOps > 0 && (
            <Pill color={C.rd} active>
              {blkOps} bloq
            </Pill>
          )}
          <Pill color={C.pp} active>
            {allOps.length} ops
          </Pill>
          <Pill color={C.bl} active>
            {engineData.machines.length} máq
          </Pill>
        </div>
      </div>
      <div style={{ padding: '16px 20px', maxWidth: 1320, margin: '0 auto' }}>
        <p className="page-desc" style={{ marginBottom: 12 }}>
          Motor de escalonamento: Gantt visual, replan manual e optimização automática.
        </p>
        {isopBanner && (
          <div
            style={{
              padding: '8px 16px',
              borderRadius: 6,
              marginBottom: 12,
              background: C.ylS,
              border: `1px solid ${C.yl}40`,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span style={{ fontSize: 12, color: C.yl, fontWeight: 500 }}>{isopBanner}</span>
            <button
              onClick={() => setIsopBanner(null)}
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: C.t3,
                padding: 2,
              }}
            >
              <X size={14} strokeWidth={1.5} />
            </button>
          </div>
        )}
        {isScheduling && (
          <div
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              background: `${C.ac}15`,
              border: `1px solid ${C.ac}33`,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              marginBottom: 8,
            }}
          >
            <div
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: C.ac,
                animation: 'pulse 1s infinite',
              }}
            />
            <span style={{ fontSize: 10, color: C.ac, fontWeight: 600 }}>
              A recalcular schedule...
            </span>
          </div>
        )}
        {view === 'plan' && (
          <PlanView
            blocks={blocks}
            cap={cap}
            mSt={mSt}
            data={engineData}
            audit={audit}
            decisions={schedDecisions}
            feasibility={feasibility}
            onRunAutoReplan={handlePlanAutoReplan}
            onSwitchToReplan={() => setView('replan')}
          />
        )}
        {view === 'gantt' && (
          <GanttView
            blocks={blocks}
            mSt={mSt}
            cap={cap}
            data={engineData}
            applyMove={applyMove}
            undoMove={undoMove}
            validation={validation}
          />
        )}
        {view === 'replan' && (
          <ReplanView
            mSt={mSt}
            tSt={tSt}
            toggleM={toggleM}
            toggleT={toggleT}
            moves={moves}
            applyMove={applyMove}
            undoMove={undoMove}
            blocks={blocks}
            cap={cap}
            data={engineData}
            onApplyAndSave={() => handleApplyAndSave()}
            isSaving={isSaving}
            setResourceDown={setResourceDown}
            clearResourceDown={clearResourceDown}
            getResourceDownDays={getResourceDownDays}
            replanTimelines={replanTimelines}
            rushOrders={rushOrders}
            setRushOrders={setRushOrders}
            allOps={allOps}
            neMetrics={neMetrics}
          />
        )}
        {view === 'whatif' && (
          <WhatIfView
            data={engineData}
            onApplyMoves={(mvs, sc) => handleApplyAndSave(mvs, sc)}
            isSaving={isSaving}
            setResourceDown={setResourceDown}
            clearResourceDown={clearResourceDown}
            getResourceDownDays={getResourceDownDays}
            replanTimelines={replanTimelines}
          />
        )}
      </div>
    </div>
  );
}

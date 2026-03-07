// ═══════════════════════════════════════════════════════════════
//  NIKUFRA.AI — Production Planning Engine v4 · API Edition
//  UI shell for scheduling, Gantt, replan, and optimization.
//  ALL scheduling logic imported from incompol-plan via lib/engine.
// ═══════════════════════════════════════════════════════════════

import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  Eye,
  GitCommit,
  GitCompareArrows,
  History,
  Layers,
  Save,
  Sparkles,
  Star,
  Undo2,
  X,
  Zap,
} from 'lucide-react';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useDataSource } from '../../hooks/useDataSource';
import type { PlanVersionParams } from '../../stores/usePlanVersionStore';
import usePlanVersionStore from '../../stores/usePlanVersionStore';
import useReplanStore from '../../stores/useReplanStore';
import useSettingsStore, { getTransformConfig } from '../../stores/useSettingsStore';
import useToastStore from '../../stores/useToastStore';
import { gridDensityVars } from '../../utils/gridDensity';
import { computePlanDiff } from '../../utils/planDiff';
import { useGanttInteraction } from '../scheduling/hooks/useGanttInteraction';
import { useScheduleFilters } from '../scheduling/hooks/useScheduleFilters';
import './NikufraEngine.css';

import type {
  AlternativeAction,
  AreaCaps,
  AutoReplanConfig,
  AutoReplanResult,
  Block,
  CoverageAuditResult,
  DayLoad,
  DecisionEntry,
  DispatchRule,
  EMachine,
  EngineData,
  EOp,
  ETool,
  FailureEvent,
  ImpactReport,
  MoveAction,
  ObjectiveProfile,
  OptimizationInput,
  OptResult,
  ReplanActionDetail,
  ReplanSimulation,
  ScheduleValidationReport,
  ScheduleViolation,
  ScoreWeights,
} from '../../lib/engine';
// ── All types and functions from incompol-plan via lib/engine ──
import {
  // Failure analysis
  analyzeAllFailures,
  applyAlternative,
  auditCoverage,
  autoReplan,
  autoRouteOverflow,
  type buildResourceTimelines,
  // Color/UI constants
  C,
  // Analysis
  capAnalysis,
  cascadingReplan,
  DAY_CAP,
  DEFAULT_AUTO_REPLAN_CONFIG,
  DEFAULT_SCORE_WEIGHTS,
  DEFAULT_WORKFORCE_CONFIG,
  genDecisions,
  // Auto-Replan control
  getReplanActions,
  moveableOps,
  // Compat helpers
  opsByDayFromWorkforce,
  quickValidate,
  // Optimization
  runOptimization,
  // Constants (THE TRUTH: S0=420, DAY_CAP=1020)
  S0,
  S1,
  scoreSchedule,
  simulateWithout,
  T1,
  TC,
  // Utility functions
  tci,
  // Core scheduling
  transformPlanState,
  undoReplanActions,
  validateSchedule,
} from '../../lib/engine';

// §2. TRANSFORM + UTILS: All imported from incompol-plan via lib/engine
// transformPlanState, tci, mulberry32, etc. are now imported above

// §3-6. SCHEDULING ENGINE, CONSTRAINTS, ANALYTICS, OPTIMIZATION
// ALL removed — imported from incompol-plan via lib/engine.
// Functions: scheduleAll, autoRouteOverflow, autoReplan,
//   createSetupCrew, createCalcoTimeline, createToolTimeline, createOperatorPool,
//   validateSchedule, auditCoverage, quickValidate,
//   capAnalysis, genDecisions, scoreSchedule,
//   moveableOps, twoOptResequence, runOptimization

// ── OBJECTIVE_PROFILES — UI-only constant for WhatIfView ──
const OBJECTIVE_PROFILES: ObjectiveProfile[] = [
  {
    id: 'balanced',
    label: 'Equilibrado',
    weights: { ...DEFAULT_SCORE_WEIGHTS },
  },
  {
    id: 'otd',
    label: 'Entregar a Tempo',
    weights: {
      tardiness: 200,
      setup_count: 5,
      setup_time: 0.5,
      setup_balance: 10,
      churn: 2,
      overflow: 80,
      below_min_batch: 2,
    },
  },
  {
    id: 'setup',
    label: 'Minimizar Setups',
    weights: {
      tardiness: 30,
      setup_count: 50,
      setup_time: 5,
      setup_balance: 40,
      churn: 3,
      overflow: 20,
      below_min_batch: 1,
    },
  },
];

// Local wrapper: old toolColor(tools,toolId) → color string. New tci(toolId, allIds) → index.
function toolColor(tools: ETool[], toolId: string): string {
  return (
    TC[
      tci(
        toolId,
        tools.map((t) => t.id),
      )
    ] ?? TC[0]
  );
}

// §7. UI ATOMS
function Pill({
  children,
  color,
  active,
  onClick,
  size = 'sm',
}: {
  children: React.ReactNode;
  color: string;
  active?: boolean;
  onClick?: () => void;
  size?: 'sm' | 'md';
}) {
  const s = size === 'sm';
  return (
    <button
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: s ? '3px 8px' : '5px 12px',
        borderRadius: 20,
        fontSize: s ? 10 : 11,
        fontWeight: 600,
        background: active ? color + '20' : 'transparent',
        border: `1.5px solid ${active ? color + '55' : C.bd}`,
        color: active ? color : C.t2,
        cursor: onClick ? 'pointer' : 'default',
        fontFamily: 'inherit',
        transition: 'all .15s',
        letterSpacing: '.01em',
      }}
    >
      {children}
    </button>
  );
}

function Tag({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span
      style={{
        fontSize: 9,
        fontWeight: 600,
        color,
        letterSpacing: '.04em',
        textTransform: 'uppercase',
      }}
    >
      {children}
    </span>
  );
}

function Metric({
  label,
  value,
  sub,
  color,
  large,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  color?: string;
  large?: boolean;
}) {
  return (
    <div style={{ padding: large ? '16px' : '12px 14px' }}>
      <div
        style={{
          fontSize: 10,
          color: C.t3,
          fontWeight: 500,
          marginBottom: 4,
          letterSpacing: '.02em',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: large ? 24 : 20,
          fontWeight: 600,
          color: color || C.t1,
          fontFamily: "'JetBrains Mono',monospace",
          lineHeight: 1,
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: 10, color: C.t3, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function Card({ children, style: sx, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div style={{ background: C.s2, borderRadius: 8, border: `1px solid ${C.bd}`, ...sx }} {...p}>
      {children}
    </div>
  );
}

const fmtT = (min: number) =>
  `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(Math.round(min % 60)).padStart(2, '0')}`;
const dot = (c: string, _pulse?: boolean): React.CSSProperties => ({
  display: 'inline-block',
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: c,
});

// §7b. OPERATION DETAIL PANEL (Gantt side panel)
function OpDetailPanel({
  block: b,
  tool,
  op,
  dayLoad,
  dnames,
  selDay,
  machines,
  mSt,
  tools,
  onMove,
  onUndo,
  onClose,
}: {
  block: Block;
  tool: ETool | undefined;
  op: EOp | undefined;
  dayLoad: DayLoad | undefined;
  dnames: string[];
  selDay: number;
  machines: EMachine[];
  mSt: Record<string, string>;
  tools: ETool[];
  onMove: (opId: string, toM: string) => void;
  onUndo: (opId: string) => void;
  onClose: () => void;
}) {
  const Sec = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div style={{ borderTop: `1px solid ${C.bd}`, padding: '10px 14px' }}>
      <div
        style={{
          fontSize: 9,
          fontWeight: 600,
          color: C.t4,
          letterSpacing: '.06em',
          textTransform: 'uppercase',
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
  const Row = ({ k, v, color }: { k: string; v: React.ReactNode; color?: string }) => (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        padding: '2px 0',
      }}
    >
      <span style={{ fontSize: 10, color: C.t3 }}>{k}</span>
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: color || C.t1,
          fontFamily: "'JetBrains Mono',monospace",
        }}
      >
        {v}
      </span>
    </div>
  );
  const col = toolColor(tools, b.toolId);
  const mc = machines.find((m) => m.id === b.machineId);
  const total = dayLoad ? dayLoad.prod + dayLoad.setup : 0;
  const util = total / DAY_CAP;
  const maxQty = op ? Math.max(...op.d, 1) : 1;

  return (
    <div
      style={{
        width: 320,
        minWidth: 320,
        background: C.s2,
        border: `1px solid ${C.bd}`,
        borderRadius: 8,
        overflow: 'hidden',
        alignSelf: 'flex-start',
        maxHeight: 520,
        overflowY: 'auto',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
        }}
      >
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: col }}>
            {b.toolId} <span style={{ color: C.t2, fontWeight: 500 }}>—</span>{' '}
            <span style={{ color: C.t1 }}>{b.sku}</span>
          </div>
          <div style={{ fontSize: 11, color: C.t2, marginTop: 2 }}>{b.nm}</div>
          <div style={{ fontSize: 10, color: C.t3, marginTop: 2 }}>
            <span style={{ fontWeight: 600, fontFamily: 'monospace', color: C.t1 }}>
              {b.machineId}
            </span>
            {mc && <span> · {mc.area}</span>}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: C.t3,
            cursor: 'pointer',
            fontSize: 16,
            padding: '0 2px',
            fontFamily: 'inherit',
            lineHeight: 1,
          }}
        >
          <X size={14} strokeWidth={2} />
        </button>
      </div>

      {/* Production */}
      <Sec label="Produção">
        <Row k="Quantidade" v={`${b.qty.toLocaleString()} pcs`} />
        <Row k="Tempo" v={`${(b.endMin - b.startMin).toFixed(0)} min`} />
        <Row k="Início" v={fmtT(b.startMin)} />
        <Row k="Fim" v={fmtT(b.endMin)} />
        {tool && <Row k="pcs/H" v={tool.pH.toLocaleString()} />}
        <Row k="Operadores" v={b.operators} />
        {b.type === 'blocked' && (
          <div style={{ fontSize: 10, color: C.rd, fontWeight: 600, marginTop: 4 }}>
            BLOQUEADA — {b.reason === 'tool_down' ? 'ferramenta avariada' : 'máquina DOWN'}
          </div>
        )}
        {b.overflow && (
          <div style={{ fontSize: 10, color: C.yl, fontWeight: 600, marginTop: 4 }}>
            OVERFLOW — +{b.overflowMin?.toFixed(0)}min
          </div>
        )}
      </Sec>

      {/* Twin Co-Production */}
      {b.isTwinProduction && b.outputs && (
        <Sec label="Co-Produção">
          <div
            style={{
              fontSize: 10,
              color: C.t3,
              marginBottom: 6,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <Layers size={11} strokeWidth={1.5} color={col} />
            <span>Produção simultânea de 2 SKUs</span>
          </div>
          {b.outputs.map((o, oi) => (
            <div
              key={oi}
              style={{
                borderTop: oi > 0 ? `1px solid ${C.bd}44` : undefined,
                paddingTop: oi > 0 ? 6 : 0,
                marginTop: oi > 0 ? 6 : 0,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: C.t1,
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {o.sku}
              </div>
              <Row k="Quantidade" v={`${o.qty.toLocaleString()} pcs`} />
            </div>
          ))}
        </Sec>
      )}

      {/* Setup */}
      {b.setupS != null && b.setupE != null && (
        <Sec label="Setup">
          <Row k="Tempo" v={`${(b.setupE - b.setupS).toFixed(0)} min`} />
          <Row k="Início Setup" v={fmtT(b.setupS)} />
          <Row k="Fim Setup" v={fmtT(b.setupE)} />
        </Sec>
      )}

      {/* Stock & Backlog */}
      <Sec label="Stock & Backlog">
        <Row
          k="Stock"
          v={`${b.stk.toLocaleString()} pcs`}
          color={b.stk === 0 && b.lt > 0 ? C.yl : undefined}
        />
        {b.lt > 0 && <Row k="Lote Económico" v={`${b.lt.toLocaleString()} pcs`} />}
        <Row
          k="Atraso"
          v={b.atr > 0 ? `${b.atr.toLocaleString()} pcs` : '—'}
          color={b.atr > 0 ? C.rd : C.t3}
        />
      </Sec>

      {/* Weekly schedule mini barchart */}
      {op && (
        <Sec label="Programação Semanal">
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end' }}>
            {op.d.map((qty, i) => (
              <div key={i} style={{ flex: 1, textAlign: 'center' }}>
                <div
                  style={{
                    height: 40,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'flex-end',
                  }}
                >
                  {qty > 0 && (
                    <div
                      style={{
                        height: `${Math.min((qty / maxQty) * 100, 100)}%`,
                        background: i === selDay ? C.ac : C.bl + '55',
                        borderRadius: '2px 2px 0 0',
                        minHeight: 2,
                      }}
                    />
                  )}
                </div>
                {qty > 0 && (
                  <div style={{ fontSize: 7, color: C.t3, fontFamily: 'monospace', marginTop: 1 }}>
                    {(qty / 1000).toFixed(0)}K
                  </div>
                )}
                <div
                  style={{
                    fontSize: 8,
                    color: i === selDay ? C.ac : C.t4,
                    fontWeight: i === selDay ? 700 : 400,
                  }}
                >
                  {dnames[i]}
                </div>
              </div>
            ))}
          </div>
        </Sec>
      )}

      {/* Machine */}
      <Sec label="Máquina">
        <Row k="Primária" v={b.origM} />
        {b.hasAlt && b.altM && <Row k="Alternativa" v={b.altM} />}
        <Row
          k="Estado"
          v={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span
                style={dot(mSt[b.machineId] === 'down' ? C.rd : C.ac, mSt[b.machineId] === 'down')}
              />
              {mSt[b.machineId] === 'down' ? 'DOWN' : 'RUN'}
            </span>
          }
          color={mSt[b.machineId] === 'down' ? C.rd : C.ac}
        />
        {total > 0 && (
          <>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '2px 0',
                marginTop: 2,
              }}
            >
              <span style={{ fontSize: 10, color: C.t3 }}>Utilização</span>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: util > 1 ? C.rd : util > 0.85 ? C.yl : C.ac,
                  fontFamily: 'monospace',
                }}
              >
                {(util * 100).toFixed(0)}%
              </span>
            </div>
            <div
              style={{
                height: 4,
                background: C.bg,
                borderRadius: 2,
                overflow: 'hidden',
                marginTop: 2,
              }}
            >
              <div
                style={{
                  height: '100%',
                  width: `${Math.min(util * 100, 100)}%`,
                  background: util > 1 ? C.rd : util > 0.85 ? C.yl : C.ac,
                  borderRadius: 2,
                }}
              />
            </div>
          </>
        )}
      </Sec>

      {/* Actions */}
      <div style={{ padding: '10px 14px' }}>
        {b.moved && (
          <div style={{ marginBottom: 8 }}>
            <div
              style={{
                fontSize: 10,
                color: C.ac,
                fontWeight: 600,
                marginBottom: 6,
                display: 'flex',
                alignItems: 'center',
                gap: 3,
              }}
            >
              <Sparkles size={10} strokeWidth={1.5} /> Replaneado de {b.origM}
            </div>
            <button
              onClick={() => onUndo(b.opId)}
              style={{
                width: '100%',
                padding: '7px 0',
                borderRadius: 6,
                border: `1px solid ${C.yl}33`,
                background: C.ylS,
                color: C.yl,
                fontSize: 10,
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              <Undo2
                size={10}
                strokeWidth={1.5}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />{' '}
              Desfazer
            </button>
          </div>
        )}
        {!b.moved && b.hasAlt && b.altM && mSt[b.altM] !== 'down' && (
          <button
            onClick={() => onMove(b.opId, b.altM!)}
            style={{
              width: '100%',
              padding: '7px 0',
              borderRadius: 6,
              border: 'none',
              background: C.ac,
              color: C.bg,
              fontSize: 10,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Mover para {b.altM}
          </button>
        )}
      </div>
    </div>
  );
}

// §7c. VALIDATION PANEL (collapsible constraint check results)
function ValidationPanel({
  validation,
  dnames,
  dates,
  applyMove,
}: {
  validation: ScheduleValidationReport;
  dnames: string[];
  dates: string[];
  applyMove?: (opId: string, toM: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const critC = validation.violations.filter((v) => v.severity === 'critical').length;
  const highC = validation.violations.filter((v) => v.severity === 'high').length;
  const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const sevColor: Record<string, string> = { critical: C.rd, high: C.yl, medium: C.bl, low: C.t3 };
  const sevBg: Record<string, string> = {
    critical: C.rdS,
    high: C.ylS,
    medium: C.blS,
    low: 'transparent',
  };
  const dayLabel = (v: ScheduleViolation): string | null => {
    const days = [...new Set(v.affectedOps.map((o) => o.dayIdx))].sort((a, b) => a - b);
    if (days.length === 0) return null;
    return days.map((d) => `${dnames[d] ?? '?'} ${dates[d] ?? ''}`).join(', ');
  };

  if (validation.violations.length === 0)
    return (
      <div
        style={{
          padding: '6px 12px',
          borderRadius: 6,
          background: C.acS,
          border: `1px solid ${C.acM}`,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: 8,
        }}
      >
        <Check size={12} strokeWidth={2} style={{ color: C.ac }} />
        <span style={{ fontSize: 11, fontWeight: 600, color: C.ac }}>
          Schedule válido — 0 violações
        </span>
      </div>
    );

  return (
    <Card style={{ marginBottom: 8, padding: 0, overflow: 'hidden' }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '6px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          background: validation.valid ? C.acS : C.rdS,
          borderBottom: expanded ? `1px solid ${C.bd}` : undefined,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle
            size={12}
            strokeWidth={2}
            style={{ color: validation.valid ? C.yl : C.rd }}
          />
          <span style={{ fontSize: 11, fontWeight: 600, color: validation.valid ? C.yl : C.rd }}>
            {validation.violations.length} violaç{validation.violations.length === 1 ? 'ão' : 'ões'}
          </span>
          {critC > 0 && <Tag color={C.rd}>{critC} crít</Tag>}
          {highC > 0 && (
            <Tag color={C.yl}>
              {highC} alta{highC > 1 ? 's' : ''}
            </Tag>
          )}
        </div>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </div>
      {expanded && (
        <div style={{ maxHeight: 240, overflowY: 'auto', padding: '6px 8px' }}>
          {validation.violations
            .sort((a, b) => (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3))
            .map((v) => (
              <div
                key={v.id}
                style={{
                  padding: '5px 8px',
                  marginBottom: 3,
                  borderRadius: 4,
                  background: sevBg[v.severity],
                  borderLeft: `3px solid ${sevColor[v.severity]}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      color: sevColor[v.severity],
                      textTransform: 'uppercase',
                      letterSpacing: '.04em',
                    }}
                  >
                    {v.severity}
                  </span>
                  {dayLabel(v) && (
                    <span
                      style={{
                        fontSize: 8,
                        fontWeight: 600,
                        color: C.t3,
                        background: C.s2,
                        padding: '1px 4px',
                        borderRadius: 3,
                        fontFamily: "'JetBrains Mono',monospace",
                      }}
                    >
                      {dayLabel(v)}
                    </span>
                  )}
                  <span style={{ fontSize: 10, fontWeight: 600, color: C.t1 }}>{v.title}</span>
                </div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t2,
                    marginTop: 1,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {v.detail}
                </div>
                {v.suggestedFix && (
                  <div style={{ fontSize: 9, color: C.ac, marginTop: 1 }}>{v.suggestedFix}</div>
                )}
                {v.action && applyMove && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      applyMove(v.action!.opId, v.action!.toM);
                    }}
                    style={{
                      marginTop: 2,
                      fontSize: 9,
                      fontWeight: 600,
                      color: C.bg,
                      background: C.ac,
                      border: 'none',
                      borderRadius: 3,
                      padding: '2px 8px',
                      cursor: 'pointer',
                    }}
                  >
                    Mover para {v.action.toM}
                  </button>
                )}
              </div>
            ))}
        </div>
      )}
    </Card>
  );
}

// §8. GANTT VIEW
function GanttView({
  blocks,
  mSt,
  cap,
  data,
  applyMove,
  undoMove,
  validation,
}: {
  blocks: Block[];
  mSt: Record<string, string>;
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  validation?: ScheduleValidationReport | null;
}) {
  const { machines, dates, dnames, tools } = data;
  const { state: gantt, actions: ganttActions } = useGanttInteraction(
    blocks,
    machines,
    mSt,
    data.workdays,
    validation,
  );
  const {
    hov,
    selDay,
    selM,
    zoom,
    selOp,
    selBlock,
    dayB,
    dayBlkN,
    activeM,
    wdi,
    ppm,
    totalW,
    violationsByDay,
  } = gantt;
  const { setHov, setSelDay, setSelM, setZoom, setSelOp } = ganttActions;
  const hours: number[] = [];
  for (let h = 7; h <= 24; h++) hours.push(h);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {validation && (
        <ValidationPanel
          validation={validation}
          dnames={dnames}
          dates={dates}
          applyMove={applyMove}
        />
      )}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 6,
        }}
      >
        <div
          className="ne-day-strip"
          style={{ display: 'flex', gap: 3, overflowX: 'auto', flex: '1 1 0', minWidth: 0 }}
        >
          {wdi.map((i) => {
            const has = blocks.some((b) => b.dayIdx === i && b.type !== 'blocked');
            return (
              <Pill
                key={i}
                active={selDay === i}
                color={C.ac}
                onClick={() => setSelDay(i)}
                size="sm"
              >
                <span style={{ opacity: has ? 1 : 0.4 }}>
                  {dnames[i]} {dates[i]}
                </span>
                {violationsByDay[i] > 0 && (
                  <span
                    style={{
                      fontSize: 7,
                      fontWeight: 700,
                      color: C.t1,
                      background: C.rd,
                      borderRadius: '50%',
                      width: 14,
                      height: 14,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginLeft: 3,
                      flexShrink: 0,
                    }}
                  >
                    {violationsByDay[i]}
                  </span>
                )}
              </Pill>
            );
          })}
        </div>
        <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
          <Pill active={!selM} color={C.ac} onClick={() => setSelM(null)}>
            Todas
          </Pill>
          {machines
            .filter(
              (m) =>
                blocks.some((b) => b.dayIdx === selDay && b.machineId === m.id) ||
                mSt[m.id] === 'down',
            )
            .map((m) => (
              <Pill
                key={m.id}
                active={selM === m.id}
                color={mSt[m.id] === 'down' ? C.rd : C.ac}
                onClick={() => setSelM(selM === m.id ? null : m.id)}
              >
                {m.id}
              </Pill>
            ))}
          <span style={{ width: 1, height: 16, background: C.bd, margin: '0 2px' }} />
          {[0.6, 1, 1.5, 2].map((z) => (
            <Pill key={z} active={zoom === z} color={C.bl} onClick={() => setZoom(z)}>
              {z}×
            </Pill>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Card style={{ overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 520 }}>
              <div style={{ minWidth: 100 + totalW, position: 'relative' }}>
                <div
                  style={{
                    display: 'flex',
                    position: 'sticky',
                    top: 0,
                    zIndex: 10,
                    background: C.s1,
                    borderBottom: `1px solid ${C.bd}`,
                  }}
                >
                  <div
                    style={{
                      width: 100,
                      minWidth: 100,
                      padding: '8px 10px',
                      borderRight: `1px solid ${C.bd}`,
                      fontSize: 11,
                      fontWeight: 600,
                      color: C.t2,
                    }}
                  >
                    {dnames[selDay]} {dates[selDay]}
                  </div>
                  <div style={{ position: 'relative', height: 28, flex: 1 }}>
                    {hours.map((h) => {
                      const x = (h * 60 - S0) * ppm;
                      return (
                        <div
                          key={h}
                          style={{
                            position: 'absolute',
                            left: x,
                            top: 0,
                            height: '100%',
                            borderLeft: `1px solid ${C.bd}${h % 2 === 0 ? '' : '44'}`,
                          }}
                        >
                          <span
                            style={{
                              fontSize: 9,
                              color: h % 2 === 0 ? C.t3 : C.t4,
                              fontFamily: 'monospace',
                              position: 'absolute',
                              bottom: 3,
                              left: 4,
                            }}
                          >
                            {String(h).padStart(2, '0')}:00
                          </span>
                        </div>
                      );
                    })}
                    <div
                      style={{
                        position: 'absolute',
                        left: 0,
                        top: 0,
                        width: (T1 - S0) * ppm,
                        height: '100%',
                        background: `${C.ac}04`,
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        left: (T1 - S0) * ppm,
                        top: 0,
                        width: (S1 - T1) * ppm,
                        height: '100%',
                        background: `${C.bl}04`,
                      }}
                    />
                    <div
                      style={{
                        position: 'absolute',
                        left: (T1 - S0) * ppm,
                        top: 0,
                        height: '100%',
                        borderLeft: `2px solid ${C.yl}66`,
                      }}
                    >
                      <span
                        style={{
                          fontSize: 7,
                          color: C.yl,
                          position: 'absolute',
                          top: 2,
                          left: 4,
                          fontWeight: 600,
                        }}
                      >
                        T.Y
                      </span>
                    </div>
                    <span
                      style={{
                        position: 'absolute',
                        top: 2,
                        left: 4,
                        fontSize: 7,
                        color: C.ac,
                        fontWeight: 600,
                        opacity: 0.6,
                      }}
                    >
                      T.X
                    </span>
                  </div>
                </div>

                {activeM.length === 0 && dayB.length === 0 && (
                  <div
                    style={{ padding: '24px 16px', textAlign: 'center', color: C.t3, fontSize: 11 }}
                  >
                    Sem operações agendadas para {dnames[selDay]} {dates[selDay]}.
                  </div>
                )}
                {activeM.map((mc) => {
                  const mB = dayB.filter((b) => b.machineId === mc.id);
                  const isDown = mSt[mc.id] === 'down';
                  const rowH = Math.max(44, mB.length * 22 + 10);
                  const mC = cap[mc.id]?.[selDay];
                  const total = mC ? mC.prod + mC.setup : 0;
                  const u = total / DAY_CAP;
                  return (
                    <div
                      key={mc.id}
                      style={{
                        display: 'flex',
                        borderBottom: `1px solid ${C.bd}`,
                        minHeight: rowH,
                      }}
                    >
                      <div
                        style={{
                          width: 100,
                          minWidth: 100,
                          padding: '6px 10px',
                          borderRight: `1px solid ${C.bd}`,
                          background: C.s1,
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'center',
                          gap: 2,
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                          <span style={dot(isDown ? C.rd : C.ac, isDown)} />
                          <span
                            style={{
                              fontSize: 12,
                              fontWeight: 600,
                              color: isDown ? C.rd : C.t1,
                              fontFamily: 'monospace',
                            }}
                          >
                            {mc.id}
                          </span>
                        </div>
                        <div style={{ fontSize: 9, color: C.t3 }}>
                          {mc.area} · {mB.length} ops
                        </div>
                        {total > 0 && (
                          <div
                            style={{
                              fontSize: 10,
                              color: u > 1 ? C.rd : u > 0.85 ? C.yl : C.ac,
                              fontWeight: 600,
                            }}
                          >
                            {(u * 100).toFixed(0)}%
                          </div>
                        )}
                      </div>
                      <div
                        style={{
                          position: 'relative',
                          flex: 1,
                          height: rowH,
                          background: isDown ? C.rdS : 'transparent',
                        }}
                      >
                        {hours.map((h) => (
                          <div
                            key={h}
                            style={{
                              position: 'absolute',
                              left: (h * 60 - S0) * ppm,
                              top: 0,
                              bottom: 0,
                              borderLeft: `1px solid ${C.bd}22`,
                            }}
                          />
                        ))}
                        <div
                          style={{
                            position: 'absolute',
                            left: (T1 - S0) * ppm,
                            top: 0,
                            bottom: 0,
                            borderLeft: `2px solid ${C.yl}33`,
                          }}
                        />
                        {isDown && (
                          <div
                            style={{
                              position: 'absolute',
                              inset: 0,
                              background: `repeating-linear-gradient(45deg,transparent,transparent 8px,${C.rd}08 8px,${C.rd}08 16px)`,
                            }}
                          />
                        )}
                        {mB.map((b, bi) => {
                          const col = toolColor(tools, b.toolId);
                          const isH = hov === `${b.opId}-${selDay}`;
                          const isSel = selOp === b.opId;
                          const y = 5 + bi * 22;
                          return (
                            <React.Fragment key={`${b.opId}-${bi}`}>
                              {b.setupS != null && b.setupE != null && (
                                <div
                                  style={{
                                    position: 'absolute',
                                    left: (b.setupS - S0) * ppm,
                                    width: Math.max((b.setupE - b.setupS) * ppm, 4),
                                    top: y,
                                    height: 17,
                                    background: `repeating-linear-gradient(45deg,${col}40,${col}40 3px,${col}70 3px,${col}70 6px)`,
                                    borderRadius: '4px 0 0 4px',
                                    border: `1px solid ${col}66`,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                  }}
                                >
                                  <span style={{ fontSize: 8, color: col, fontWeight: 700 }}>
                                    SET
                                  </span>
                                </div>
                              )}
                              <div
                                onClick={() => setSelOp(selOp === b.opId ? null : b.opId)}
                                onMouseEnter={() => setHov(`${b.opId}-${selDay}`)}
                                onMouseLeave={() => setHov(null)}
                                style={{
                                  position: 'absolute',
                                  left: (b.startMin - S0) * ppm,
                                  width: Math.max((b.endMin - b.startMin) * ppm, 12),
                                  top: y,
                                  height: 17,
                                  background: isSel ? col : isH ? col : `${col}CC`,
                                  borderRadius: b.setupS != null ? '0 4px 4px 0' : 4,
                                  border: isSel
                                    ? `2px solid ${C.ac}`
                                    : b.moved
                                      ? `2px solid ${C.ac}`
                                      : `1px solid ${col}44`,
                                  cursor: 'pointer',
                                  display: 'flex',
                                  alignItems: 'center',
                                  paddingLeft: 4,
                                  overflow: 'hidden',
                                  zIndex: isSel ? 25 : isH ? 20 : 1,
                                }}
                              >
                                <span
                                  style={{
                                    fontSize: 9,
                                    color: C.t1,
                                    fontWeight: 600,
                                    whiteSpace: 'nowrap',
                                    textShadow: '0 1px 3px #0009',
                                  }}
                                >
                                  {b.toolId}
                                </span>
                                {(b.endMin - b.startMin) * ppm > 70 && (
                                  <span style={{ fontSize: 8, color: C.t2, marginLeft: 5 }}>
                                    {b.qty.toLocaleString()}
                                  </span>
                                )}
                                {b.overflow && (
                                  <span
                                    style={{
                                      color: C.yl,
                                      marginLeft: 3,
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                    }}
                                  >
                                    <AlertTriangle size={8} strokeWidth={2} />
                                  </span>
                                )}
                                {b.isTwinProduction && (b.endMin - b.startMin) * ppm > 40 && (
                                  <span
                                    style={{
                                      color: '#fff9',
                                      marginLeft: 'auto',
                                      paddingRight: 3,
                                      display: 'inline-flex',
                                      alignItems: 'center',
                                    }}
                                  >
                                    <Layers size={9} strokeWidth={2} />
                                  </span>
                                )}
                                {isH && (
                                  <div
                                    onClick={(e) => e.stopPropagation()}
                                    style={{
                                      position: 'absolute',
                                      bottom: 'calc(100% + 6px)',
                                      left: 0,
                                      background: C.s3,
                                      border: `1px solid ${col}44`,
                                      borderRadius: 8,
                                      padding: 10,
                                      zIndex: 30,
                                      width: 240,
                                    }}
                                  >
                                    <div style={{ fontSize: 11, fontWeight: 600, color: col }}>
                                      {b.toolId}
                                    </div>
                                    <div style={{ fontSize: 9, color: C.t2, marginBottom: 6 }}>
                                      {b.nm} · {b.sku}
                                    </div>
                                    <div
                                      style={{
                                        display: 'grid',
                                        gridTemplateColumns: '1fr 1fr',
                                        gap: '4px 12px',
                                        fontSize: 9,
                                      }}
                                    >
                                      {(
                                        [
                                          ['Qtd', `${b.qty.toLocaleString()}`],
                                          ['Tempo', `${(b.endMin - b.startMin).toFixed(0)}min`],
                                          ['Início', fmtT(b.startMin)],
                                          ['Fim', fmtT(b.endMin)],
                                          ['pcs/H', data.toolMap[b.toolId]?.pH],
                                          [
                                            'Setup',
                                            b.setupS != null && b.setupE != null
                                              ? `${b.setupE - b.setupS}min`
                                              : '—',
                                          ],
                                          ['Ops', b.operators],
                                          ['Máq', b.machineId],
                                        ] as [string, unknown][]
                                      ).map(([k, v], i) => (
                                        <div key={i} style={{ color: C.t3 }}>
                                          {k}{' '}
                                          <span style={{ color: C.t1, fontWeight: 600 }}>
                                            {String(v)}
                                          </span>
                                        </div>
                                      ))}
                                    </div>
                                    {b.moved && (
                                      <div
                                        style={{
                                          fontSize: 9,
                                          color: C.ac,
                                          marginTop: 4,
                                          fontWeight: 600,
                                          display: 'flex',
                                          alignItems: 'center',
                                          gap: 3,
                                        }}
                                      >
                                        <Sparkles size={9} strokeWidth={1.5} /> Replaneado de{' '}
                                        {b.origM}
                                      </div>
                                    )}
                                    {b.isTwinProduction && b.outputs && (
                                      <div
                                        style={{
                                          borderTop: `1px solid ${col}33`,
                                          marginTop: 6,
                                          paddingTop: 6,
                                        }}
                                      >
                                        <div
                                          style={{
                                            fontSize: 9,
                                            color: col,
                                            fontWeight: 600,
                                            marginBottom: 3,
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: 3,
                                          }}
                                        >
                                          <Layers size={9} strokeWidth={1.5} /> Co-Produção
                                        </div>
                                        {b.outputs.map((o, oi) => (
                                          <div key={oi} style={{ fontSize: 9, color: C.t3 }}>
                                            {o.sku}{' '}
                                            <span style={{ color: C.t1, fontWeight: 600 }}>
                                              {o.qty.toLocaleString()} pcs
                                            </span>
                                          </div>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            </React.Fragment>
                          );
                        })}
                        {!isDown && total > 0 && (
                          <div
                            style={{
                              position: 'absolute',
                              bottom: 0,
                              left: 0,
                              right: 0,
                              height: 3,
                            }}
                          >
                            <div
                              style={{
                                height: '100%',
                                width: `${Math.min(u * 100, 100)}%`,
                                background: u > 1 ? C.rd : C.ac,
                                opacity: 0.25,
                                borderRadius: '0 2px 0 0',
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Card>
          <div
            style={{
              display: 'flex',
              gap: 4,
              flexWrap: 'wrap',
              justifyContent: 'center',
              fontSize: 9,
              color: C.t3,
            }}
          >
            {[...new Set(dayB.map((b) => b.toolId))].slice(0, 14).map((tid) => (
              <div key={tid} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: toolColor(tools, tid),
                  }}
                />
                <span style={{ fontFamily: 'monospace', fontSize: 9 }}>{tid}</span>
              </div>
            ))}
            {dayBlkN > 0 && <Tag color={C.rd}>{dayBlkN} bloqueadas</Tag>}
          </div>
        </div>
        {selBlock && (
          <OpDetailPanel
            block={selBlock}
            tool={data.toolMap[selBlock.toolId]}
            op={data.ops.find((o) => o.id === selBlock.opId)}
            dayLoad={cap[selBlock.machineId]?.[selDay]}
            dnames={data.dnames}
            selDay={selDay}
            machines={data.machines}
            mSt={mSt}
            tools={tools}
            onMove={applyMove}
            onUndo={undoMove}
            onClose={() => setSelOp(null)}
          />
        )}
      </div>
    </div>
  );
}

// §9. PLAN VIEW

// Decision type labels & categories (28 types grouped)
const DECISION_CATEGORIES: Record<string, { label: string; types: string[] }> = {
  scheduling: {
    label: 'Escalonamento',
    types: [
      'SCHEDULE_BLOCK',
      'SPLIT_BLOCK',
      'MERGE_BLOCKS',
      'BATCH_SCHEDULE',
      'SKIP_ZERO_DEMAND',
      'LOT_SIZE_ADJUST',
    ],
  },
  routing: {
    label: 'Routing',
    types: [
      'MOVE_TO_ALT',
      'OVERFLOW_TO_ALT',
      'ROUTE_TWIN',
      'ADVANCE_PRODUCTION',
      'DEFER_PRODUCTION',
    ],
  },
  setup: {
    label: 'Setup',
    types: ['SETUP_ASSIGN', 'SETUP_RESEQUENCE', 'SETUP_DELAY', 'SETUP_CREW_CONFLICT'],
  },
  constraint: {
    label: 'Constraints',
    types: ['TOOL_CONFLICT_DEFER', 'CALCO_CONFLICT_DEFER', 'OPERATOR_LIMIT', 'CAPACITY_OVERFLOW'],
  },
  infeasibility: {
    label: 'Inviabilidade',
    types: [
      'INFEASIBLE_NO_CAPACITY',
      'INFEASIBLE_TOOL_DOWN',
      'INFEASIBLE_MACHINE_DOWN',
      'INFEASIBLE_DEADLINE',
      'INFEASIBLE_DATA_MISSING',
    ],
  },
  replan: { label: 'Replan', types: ['REPLAN_MOVE', 'REPLAN_ADVANCE', 'REPLAN_UNDO', 'USER_MOVE'] },
};

const DECISION_TYPE_LABELS: Record<string, string> = {
  SCHEDULE_BLOCK: 'Bloco escalonado',
  SPLIT_BLOCK: 'Bloco dividido',
  MERGE_BLOCKS: 'Blocos fundidos',
  BATCH_SCHEDULE: 'Batch schedule',
  SKIP_ZERO_DEMAND: 'Demand = 0',
  LOT_SIZE_ADJUST: 'Ajuste de lote',
  MOVE_TO_ALT: 'Mover para alt.',
  OVERFLOW_TO_ALT: 'Overflow → alt.',
  ROUTE_TWIN: 'Rota twin',
  ADVANCE_PRODUCTION: 'Avançar produção',
  DEFER_PRODUCTION: 'Adiar produção',
  SETUP_ASSIGN: 'Setup atribuído',
  SETUP_RESEQUENCE: 'Setup resequenciado',
  SETUP_DELAY: 'Setup adiado',
  SETUP_CREW_CONFLICT: 'Conflito crew setup',
  TOOL_CONFLICT_DEFER: 'Conflito ferramenta',
  CALCO_CONFLICT_DEFER: 'Conflito calço',
  OPERATOR_LIMIT: 'Limite operadores',
  CAPACITY_OVERFLOW: 'Overflow capacidade',
  INFEASIBLE_NO_CAPACITY: 'Sem capacidade',
  INFEASIBLE_TOOL_DOWN: 'Ferramenta down',
  INFEASIBLE_MACHINE_DOWN: 'Máquina down',
  INFEASIBLE_DEADLINE: 'Deadline impossível',
  INFEASIBLE_DATA_MISSING: 'Dados em falta',
  REPLAN_MOVE: 'Replan move',
  REPLAN_ADVANCE: 'Replan avançar',
  REPLAN_UNDO: 'Replan undo',
  USER_MOVE: 'Move manual',
};

const DECISION_CATEGORY_COLORS: Record<string, string> = {
  scheduling: C.ac,
  routing: C.bl,
  setup: C.pp,
  constraint: C.yl,
  infeasibility: C.rd,
  replan: C.cy,
};

type FeasibilitySummary = {
  totalOps: number;
  feasibleOps: number;
  infeasibleOps: number;
  score: number;
  deadlineFeasible: boolean;
};

interface AutoReplanSummary {
  actions: ReplanActionDetail[];
  moveCount: number;
  unresolvedCount: number;
}

function PlanView({
  blocks,
  cap,
  mSt,
  data,
  audit,
  decisions,
  feasibility,
  onRunAutoReplan,
  onSwitchToReplan,
}: {
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  mSt: Record<string, string>;
  data: EngineData;
  audit: CoverageAuditResult | null;
  decisions: DecisionEntry[];
  feasibility: FeasibilitySummary | null;
  onRunAutoReplan?: () => AutoReplanSummary | null;
  onSwitchToReplan?: () => void;
}) {
  const [showAuditDetail, setShowAuditDetail] = useState(false);
  const [showDecisions, setShowDecisions] = useState(false);
  const [decFilter, setDecFilter] = useState<string>('all');
  const [decExpanded, setDecExpanded] = useState<string | null>(null);
  const { machines, tools, ops, dates, dnames } = data;

  // Lookup map for enriched decision display
  const opById = useMemo(() => {
    const map: Record<string, EOp> = {};
    for (const op of data.ops) map[op.id] = op;
    return map;
  }, [data.ops]);

  // Find earliest demand day (EDD) for an operation
  const getEDD = useCallback((op: EOp): number | null => {
    for (let i = 0; i < op.d.length; i++) {
      if (op.d[i] > 0) return i;
    }
    return null;
  }, []);

  // Auto-replan quick access
  const [arRunning, setArRunning] = useState(false);
  const [arSummary, setArSummary] = useState<AutoReplanSummary | null>(null);
  const handleQuickReplan = useCallback(() => {
    if (!onRunAutoReplan) return;
    setArRunning(true);
    setArSummary(null);
    try {
      const result = onRunAutoReplan();
      setArSummary(result);
    } finally {
      setArRunning(false);
    }
  }, [onRunAutoReplan]);

  // Working day indices — filter weekends from display
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );
  const ok = blocks.filter((b) => b.type !== 'blocked');
  // Twin-aware qty: sum outputs[] for co-production, b.qty for regular
  const bQty = (b: Block) =>
    b.isTwinProduction && b.outputs ? b.outputs.reduce((s, o) => s + o.qty, 0) : b.qty;
  const tPcs = ok.reduce((a, b) => a + bQty(b), 0);
  const tProd = ok.reduce((a, b) => a + (b.endMin - b.startMin), 0);
  const tSetup = ok
    .filter((b) => b.setupS != null)
    .reduce((a, b) => a + ((b.setupE || 0) - (b.setupS || 0)), 0);
  const blkN = new Set(blocks.filter((b) => b.type === 'blocked').map((b) => b.opId)).size;
  const prodByDay = wdi.map((i) =>
    blocks.filter((b) => b.dayIdx === i && b.type !== 'blocked').reduce((a, b) => a + bQty(b), 0),
  );
  const maxPd = Math.max(...prodByDay, 1);
  const hC = (u: number) =>
    u === 0
      ? 'transparent'
      : u < 0.3
        ? C.ac + '15'
        : u < 0.6
          ? C.ac + '25'
          : u < 0.85
            ? C.yl + '25'
            : u < 1
              ? C.yl + '40'
              : C.rd + '35';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 8 }}>
        {[
          {
            l: 'Cobertura',
            v: audit ? `${audit.globalCoveragePct.toFixed(1)}%` : '—',
            s: audit
              ? `${audit.rows.length} ops (${audit.rows.filter((r) => r.totalDemand > 0).length} c/ demand)`
              : '',
            c: audit?.isComplete ? C.ac : C.rd,
          },
          { l: 'Peças', v: `${(tPcs / 1000).toFixed(0)}K`, s: `${wdi.length} dias úteis`, c: C.ac },
          {
            l: 'Produção',
            v: `${(tProd / 60).toFixed(0)}h`,
            s: `${Math.round(tProd)}min`,
            c: C.ac,
          },
          {
            l: 'Setup',
            v: `${(tSetup / 60).toFixed(1)}h`,
            s: `${ok.filter((b) => b.setupS != null).length} setups`,
            c: C.pp,
          },
          {
            l: 'Balance',
            v: (() => {
              const sX = ok.filter((b) => b.setupS != null && b.setupS < T1).length;
              const sY = ok.filter((b) => b.setupS != null && b.setupS >= T1).length;
              return `${sX}/${sY}`;
            })(),
            s: 'T.X/T.Y',
            c: (() => {
              const sX = ok.filter((b) => b.setupS != null && b.setupS < T1).length;
              const sY = ok.filter((b) => b.setupS != null && b.setupS >= T1).length;
              return Math.abs(sX - sY) > 3 ? C.yl : C.ac;
            })(),
          },
          {
            l: 'Bloqueadas',
            v: blkN,
            s: blkN > 0 ? 'ações pendentes' : '—',
            c: blkN > 0 ? C.rd : C.ac,
          },
        ].map((k, i) => (
          <Card key={i}>
            <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
          </Card>
        ))}
      </div>

      {audit && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 8,
            background: audit.isComplete ? C.acS : C.rdS,
            border: `1px solid ${audit.isComplete ? C.ac + '33' : C.rd + '33'}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: audit.isComplete ? C.ac : C.rd }}>
              {audit.isComplete
                ? 'COBERTURA 100%'
                : `COBERTURA ${audit.globalCoveragePct.toFixed(1)}%`}
            </span>
            <span style={{ fontSize: 10, color: audit.isComplete ? C.ac : C.t2 }}>
              {audit.isComplete
                ? `${audit.rows.length} operações ISOP · ${audit.rows.filter((r) => r.totalDemand > 0).length} com demand · todas cobertas`
                : `${audit.rows.length} ops ISOP · ${audit.totalDemand.toLocaleString()} demand · ${audit.totalProduced.toLocaleString()} produzidas · ${(audit.totalDemand - audit.totalProduced).toLocaleString()} em falta`}
            </span>
            {!audit.isComplete && (
              <span style={{ fontSize: 10, color: C.rd, fontWeight: 600 }}>
                {audit.zeroCovered > 0 ? `${audit.zeroCovered} ops sem produção` : ''}
                {audit.zeroCovered > 0 && audit.partiallyCovered > 0 ? ' · ' : ''}
                {audit.partiallyCovered > 0 ? `${audit.partiallyCovered} ops parciais` : ''}
              </span>
            )}
          </div>
          {!audit.isComplete && (
            <button
              onClick={() => setShowAuditDetail(!showAuditDetail)}
              style={{
                padding: '4px 10px',
                borderRadius: 6,
                border: `1px solid ${C.rd}33`,
                background: 'transparent',
                color: C.rd,
                fontSize: 10,
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              {showAuditDetail ? 'Esconder' : 'Ver detalhe'}
            </button>
          )}
        </div>
      )}

      {audit && !audit.isComplete && showAuditDetail && (
        <Card style={{ padding: 14, maxHeight: 320, overflow: 'auto' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Operações com cobertura incompleta (
            {audit.rows.filter((r) => r.coveragePct < 100 && r.totalDemand > 0).length})
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '60px 80px 70px 60px 80px 80px 50px 90px',
              gap: '2px 6px',
              fontSize: 10,
            }}
          >
            <div style={{ fontWeight: 600, color: C.t3 }}>Op</div>
            <div style={{ fontWeight: 600, color: C.t3 }}>SKU</div>
            <div style={{ fontWeight: 600, color: C.t3 }}>Tool</div>
            <div style={{ fontWeight: 600, color: C.t3 }}>Máq.</div>
            <div style={{ fontWeight: 600, color: C.t3, textAlign: 'right' }}>Demand</div>
            <div style={{ fontWeight: 600, color: C.t3, textAlign: 'right' }}>Produzido</div>
            <div style={{ fontWeight: 600, color: C.t3, textAlign: 'right' }}>%</div>
            <div style={{ fontWeight: 600, color: C.t3 }}>Razão</div>
            {audit.rows
              .filter((r) => r.coveragePct < 100 && r.totalDemand > 0)
              .sort((a, b) => b.gap - a.gap)
              .map((r) => (
                <React.Fragment key={r.opId}>
                  <div style={{ fontFamily: 'monospace', color: C.t2 }}>{r.opId}</div>
                  <div
                    style={{
                      color: C.t2,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.sku}
                  </div>
                  <div style={{ fontFamily: 'monospace', color: C.t2 }}>{r.toolId}</div>
                  <div style={{ fontFamily: 'monospace', color: C.t2 }}>{r.machineId}</div>
                  <div style={{ fontFamily: 'monospace', textAlign: 'right', color: C.t1 }}>
                    {r.totalDemand.toLocaleString()}
                  </div>
                  <div
                    style={{
                      fontFamily: 'monospace',
                      textAlign: 'right',
                      color: r.produced > 0 ? C.yl : C.rd,
                    }}
                  >
                    {r.produced.toLocaleString()}
                  </div>
                  <div
                    style={{
                      fontFamily: 'monospace',
                      textAlign: 'right',
                      fontWeight: 600,
                      color: r.coveragePct === 0 ? C.rd : C.yl,
                    }}
                  >
                    {r.coveragePct}%
                  </div>
                  <div style={{ color: C.t3 }}>
                    {
                      {
                        overflow: 'Sem capacidade',
                        blocked: 'Ferramenta/Máq. down',
                        partial: 'Cobertura parcial',
                        rate_zero: 'Rate = 0',
                        ok: '—',
                        no_demand: '—',
                      }[r.reason]
                    }
                    {r.hasAlt ? ` (alt: ${r.altM})` : ''}
                  </div>
                </React.Fragment>
              ))}
          </div>
        </Card>
      )}

      {/* Feasibility Score + Coverage Segmented Bar */}
      {(feasibility || audit) && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: feasibility && audit ? '1fr 1.5fr' : '1fr',
            gap: 10,
          }}
        >
          {feasibility && (
            <Card style={{ padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <div
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: '50%',
                    background:
                      feasibility.score >= 0.95 ? C.acS : feasibility.score >= 0.8 ? C.ylS : C.rdS,
                    border: `2px solid ${feasibility.score >= 0.95 ? C.ac : feasibility.score >= 0.8 ? C.yl : C.rd}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <span
                    style={{
                      fontSize: 16,
                      fontWeight: 700,
                      fontFamily: 'monospace',
                      color:
                        feasibility.score >= 0.95 ? C.ac : feasibility.score >= 0.8 ? C.yl : C.rd,
                    }}
                  >
                    {(feasibility.score * 100).toFixed(0)}%
                  </span>
                </div>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>Viabilidade</div>
                  <div style={{ fontSize: 10, color: C.t3 }}>
                    {feasibility.feasibleOps}/{feasibility.totalOps} operações viáveis
                  </div>
                  {feasibility.infeasibleOps > 0 && (
                    <div style={{ fontSize: 10, color: C.rd, fontWeight: 500 }}>
                      {feasibility.infeasibleOps} inviáveis
                    </div>
                  )}
                </div>
              </div>
              {!feasibility.deadlineFeasible && (
                <div
                  style={{
                    padding: '5px 10px',
                    borderRadius: 4,
                    background: C.rdS,
                    border: `1px solid ${C.rd}33`,
                    fontSize: 10,
                    color: C.rd,
                    fontWeight: 500,
                  }}
                >
                  Deadline comprometida — operações em falta
                </div>
              )}
            </Card>
          )}

          {audit && (
            <Card style={{ padding: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                Cobertura — Detalhe
              </div>
              {/* Segmented bar */}
              <div
                style={{
                  display: 'flex',
                  height: 20,
                  borderRadius: 6,
                  overflow: 'hidden',
                  marginBottom: 8,
                  background: C.s1,
                }}
              >
                {audit.fullyCovered > 0 && (
                  <div
                    style={{
                      width: `${(audit.fullyCovered / audit.rows.length) * 100}%`,
                      background: C.ac,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <span style={{ fontSize: 8, color: C.t1, fontWeight: 600 }}>
                      {audit.fullyCovered}
                    </span>
                  </div>
                )}
                {audit.partiallyCovered > 0 && (
                  <div
                    style={{
                      width: `${(audit.partiallyCovered / audit.rows.length) * 100}%`,
                      background: C.yl,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <span style={{ fontSize: 8, color: C.bg, fontWeight: 600 }}>
                      {audit.partiallyCovered}
                    </span>
                  </div>
                )}
                {audit.zeroCovered > 0 && (
                  <div
                    style={{
                      width: `${(audit.zeroCovered / audit.rows.length) * 100}%`,
                      background: C.rd,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <span style={{ fontSize: 8, color: C.t1, fontWeight: 600 }}>
                      {audit.zeroCovered}
                    </span>
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 12, fontSize: 9, color: C.t3 }}>
                <span>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: 2,
                      background: C.ac,
                      marginRight: 4,
                      verticalAlign: 'middle',
                    }}
                  />
                  {audit.fullyCovered} completas
                </span>
                <span>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: 2,
                      background: C.yl,
                      marginRight: 4,
                      verticalAlign: 'middle',
                    }}
                  />
                  {audit.partiallyCovered} parciais
                </span>
                <span>
                  <span
                    style={{
                      display: 'inline-block',
                      width: 8,
                      height: 8,
                      borderRadius: 2,
                      background: C.rd,
                      marginRight: 4,
                      verticalAlign: 'middle',
                    }}
                  />
                  {audit.zeroCovered} sem cobertura
                </span>
              </div>
              <div style={{ marginTop: 8, fontSize: 10, color: C.t2, fontFamily: 'monospace' }}>
                {audit.totalDemand.toLocaleString()} demand · {audit.totalProduced.toLocaleString()}{' '}
                produzidas · {Math.round(audit.globalCoveragePct)}% cobertura
              </div>
            </Card>
          )}
        </div>
      )}

      {/* Quick Auto-Replan */}
      {onRunAutoReplan && (
        <Card style={{ padding: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Zap size={14} strokeWidth={1.5} style={{ color: C.ac }} />
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>Auto-Replan Rápido</div>
                <div style={{ fontSize: 9, color: C.t3 }}>
                  Analisa operações e sugere movimentos de optimização
                </div>
              </div>
            </div>
            <button
              onClick={handleQuickReplan}
              disabled={arRunning}
              data-testid="plan-quick-replan"
              style={{
                padding: '6px 16px',
                borderRadius: 6,
                border: 'none',
                background: arRunning ? C.s3 : C.ac,
                color: arRunning ? C.t3 : C.bg,
                fontSize: 11,
                fontWeight: 600,
                cursor: arRunning ? 'wait' : 'pointer',
                fontFamily: 'inherit',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <Zap
                size={11}
                strokeWidth={1.5}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />
              {arRunning ? 'A executar...' : 'Executar'}
            </button>
          </div>
          {arSummary && (
            <div
              style={{
                marginTop: 10,
                padding: '8px 12px',
                borderRadius: 6,
                background: arSummary.actions.length > 0 ? C.s1 : C.acS,
                border: `1px solid ${arSummary.actions.length > 0 ? C.bd : C.ac + '33'}`,
              }}
            >
              {arSummary.actions.length === 0 ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Check size={12} strokeWidth={2} style={{ color: C.ac }} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: C.ac }}>
                    Plano óptimo — sem acções necessárias
                  </span>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: C.t1, marginBottom: 4 }}>
                    {arSummary.actions.length} acções encontradas · {arSummary.moveCount} movimentos
                    {arSummary.unresolvedCount > 0 && (
                      <span style={{ color: C.rd, marginLeft: 6 }}>
                        {arSummary.unresolvedCount} não resolvidos
                      </span>
                    )}
                  </div>
                  {arSummary.actions.slice(0, 3).map((act, ai) => (
                    <div
                      key={ai}
                      style={{
                        fontSize: 10,
                        color: C.t2,
                        padding: '2px 0',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                      }}
                    >
                      <span
                        style={{
                          fontFamily: "'JetBrains Mono',monospace",
                          color: C.ac,
                          fontSize: 8,
                          padding: '1px 4px',
                          borderRadius: 3,
                          background: C.acS,
                        }}
                      >
                        {act.strategy.replace(/_/g, ' ')}
                      </span>
                      <span
                        style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {act.summary}
                      </span>
                    </div>
                  ))}
                  {arSummary.actions.length > 3 && (
                    <div style={{ fontSize: 9, color: C.t4, marginTop: 2 }}>
                      +{arSummary.actions.length - 3} mais...
                    </div>
                  )}
                  {onSwitchToReplan && (
                    <button
                      onClick={onSwitchToReplan}
                      style={{
                        marginTop: 8,
                        padding: '5px 14px',
                        borderRadius: 6,
                        border: `1px solid ${C.ac}44`,
                        background: C.acS,
                        color: C.ac,
                        fontSize: 10,
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                      }}
                    >
                      <ArrowRight size={10} strokeWidth={1.5} />
                      Ver e aplicar no Replan
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* Decisions Panel */}
      {decisions.length > 0 && (
        <Card style={{ padding: 14 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: showDecisions ? 10 : 0,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>Decisões do Engine</span>
              <span style={{ fontSize: 9, color: C.t3, fontFamily: 'monospace' }}>
                {decisions.length} total
              </span>
              {/* Category counts as mini pills */}
              {Object.entries(DECISION_CATEGORIES).map(([catKey, cat]) => {
                const count = decisions.filter((d) => cat.types.includes(d.type)).length;
                if (count === 0) return null;
                return (
                  <span
                    key={catKey}
                    style={{
                      padding: '1px 6px',
                      borderRadius: 4,
                      fontSize: 8,
                      fontWeight: 600,
                      background: DECISION_CATEGORY_COLORS[catKey] + '15',
                      color: DECISION_CATEGORY_COLORS[catKey],
                    }}
                  >
                    {cat.label} {count}
                  </span>
                );
              })}
            </div>
            <button
              onClick={() => setShowDecisions(!showDecisions)}
              style={{
                padding: '3px 10px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: 'transparent',
                color: C.t3,
                fontSize: 10,
                fontWeight: 500,
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              {showDecisions ? 'Esconder' : 'Expandir'}
            </button>
          </div>

          {showDecisions && (
            <>
              {/* Filter by category */}
              <div style={{ display: 'flex', gap: 3, marginBottom: 10, flexWrap: 'wrap' }}>
                <button
                  onClick={() => setDecFilter('all')}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 4,
                    border: 'none',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    fontSize: 9,
                    fontWeight: 600,
                    background: decFilter === 'all' ? C.ac + '25' : C.s1,
                    color: decFilter === 'all' ? C.ac : C.t3,
                  }}
                >
                  Todas ({decisions.length})
                </button>
                {Object.entries(DECISION_CATEGORIES).map(([catKey, cat]) => {
                  const count = decisions.filter((d) => cat.types.includes(d.type)).length;
                  if (count === 0) return null;
                  return (
                    <button
                      key={catKey}
                      onClick={() => setDecFilter(catKey)}
                      style={{
                        padding: '3px 10px',
                        borderRadius: 4,
                        border: 'none',
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        fontSize: 9,
                        fontWeight: 600,
                        background:
                          decFilter === catKey ? DECISION_CATEGORY_COLORS[catKey] + '25' : C.s1,
                        color: decFilter === catKey ? DECISION_CATEGORY_COLORS[catKey] : C.t3,
                      }}
                    >
                      {cat.label} ({count})
                    </button>
                  );
                })}
              </div>

              {/* Decision list */}
              <div
                style={{
                  maxHeight: 400,
                  overflow: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 3,
                }}
              >
                {decisions
                  .filter(
                    (d) =>
                      decFilter === 'all' || DECISION_CATEGORIES[decFilter]?.types.includes(d.type),
                  )
                  .slice(0, 100)
                  .map((d, i) => {
                    const catEntry = Object.entries(DECISION_CATEGORIES).find(([, cat]) =>
                      cat.types.includes(d.type),
                    );
                    const catKey = catEntry?.[0] ?? 'scheduling';
                    const catColor = DECISION_CATEGORY_COLORS[catKey] || C.t3;
                    const isExpanded = decExpanded === d.id;
                    return (
                      <div
                        key={d.id || i}
                        style={{
                          padding: '6px 10px',
                          borderRadius: 4,
                          background: C.s1,
                          borderLeft: `3px solid ${catColor}`,
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: 6,
                            cursor: 'pointer',
                          }}
                          onClick={() => setDecExpanded(isExpanded ? null : d.id)}
                        >
                          {isExpanded ? (
                            <ChevronDown
                              size={10}
                              color={C.t3}
                              style={{ marginTop: 2, flexShrink: 0 }}
                            />
                          ) : (
                            <ChevronRight
                              size={10}
                              color={C.t3}
                              style={{ marginTop: 2, flexShrink: 0 }}
                            />
                          )}
                          <div style={{ flex: 1, minWidth: 0 }}>
                            {/* Line 1: type, opId, SKU, machine, date */}
                            <div
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 6,
                                flexWrap: 'wrap',
                              }}
                            >
                              <span
                                style={{
                                  fontSize: 9,
                                  fontWeight: 600,
                                  color: catColor,
                                  fontFamily: 'monospace',
                                  minWidth: 110,
                                }}
                              >
                                {DECISION_TYPE_LABELS[d.type] || d.type}
                              </span>
                              {d.opId &&
                                (() => {
                                  const op = opById[d.opId];
                                  return (
                                    <>
                                      <span
                                        style={{
                                          fontSize: 9,
                                          color: C.t2,
                                          fontFamily: 'monospace',
                                        }}
                                      >
                                        {d.opId}
                                      </span>
                                      {op?.sku && (
                                        <span
                                          style={{
                                            fontSize: 8,
                                            color: C.t3,
                                            fontFamily: 'monospace',
                                            opacity: 0.8,
                                          }}
                                        >
                                          {op.sku}
                                        </span>
                                      )}
                                    </>
                                  );
                                })()}
                              {d.toolId && (
                                <span style={{ fontSize: 8, color: C.t3, fontFamily: 'monospace' }}>
                                  {d.toolId}
                                </span>
                              )}
                              {d.machineId && (
                                <span style={{ fontSize: 9, color: C.t3, fontFamily: 'monospace' }}>
                                  → {d.machineId}
                                </span>
                              )}
                              {d.dayIdx != null && (
                                <span style={{ fontSize: 8, color: C.t4, fontFamily: 'monospace' }}>
                                  {dates[d.dayIdx] ?? `d${d.dayIdx}`}
                                  {dnames[d.dayIdx] ? ` ${dnames[d.dayIdx]}` : ''}
                                </span>
                              )}
                              {d.reversible && (
                                <span
                                  style={{
                                    fontSize: 7,
                                    padding: '1px 4px',
                                    borderRadius: 3,
                                    background: C.acS,
                                    color: C.ac,
                                    fontWeight: 600,
                                    marginLeft: 'auto',
                                    flexShrink: 0,
                                  }}
                                >
                                  reversível
                                </span>
                              )}
                            </div>
                            {/* Line 2: item name, EDD, tool pH */}
                            {d.opId &&
                              (() => {
                                const op = opById[d.opId];
                                if (!op) return null;
                                const edd = getEDD(op);
                                const tool = data.toolMap[op.t];
                                return (
                                  <div
                                    style={{
                                      display: 'flex',
                                      alignItems: 'center',
                                      gap: 8,
                                      marginTop: 2,
                                    }}
                                  >
                                    <span
                                      style={{
                                        fontSize: 9,
                                        color: C.t3,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        maxWidth: 220,
                                      }}
                                    >
                                      {op.nm}
                                    </span>
                                    {edd != null && (
                                      <span style={{ fontSize: 8, color: C.yl, fontWeight: 500 }}>
                                        EDD: {dates[edd] ?? `d${edd}`}
                                      </span>
                                    )}
                                    {tool && (
                                      <span
                                        style={{
                                          fontSize: 8,
                                          color: C.t4,
                                          fontFamily: 'monospace',
                                        }}
                                      >
                                        {tool.pH.toLocaleString()} pcs/h
                                      </span>
                                    )}
                                  </div>
                                );
                              })()}
                          </div>
                        </div>
                        {isExpanded && (
                          <div style={{ marginTop: 6, paddingLeft: 16, fontSize: 9 }}>
                            {d.detail && (
                              <div style={{ color: C.t2, marginBottom: 3 }}>{d.detail}</div>
                            )}
                            {d.shift && <div style={{ color: C.t3 }}>Turno: {d.shift}</div>}
                            {d.alternatives && d.alternatives.length > 0 && (
                              <div style={{ marginTop: 4 }}>
                                <div
                                  style={{
                                    fontSize: 8,
                                    fontWeight: 600,
                                    color: C.t3,
                                    textTransform: 'uppercase',
                                    letterSpacing: '.04em',
                                    marginBottom: 3,
                                  }}
                                >
                                  Alternativas ({d.alternatives.length})
                                </div>
                                {d.alternatives.map((alt: AlternativeAction, ai: number) => (
                                  <div
                                    key={ai}
                                    style={{
                                      padding: '3px 8px',
                                      borderRadius: 3,
                                      background: C.s2,
                                      marginBottom: 2,
                                      display: 'flex',
                                      gap: 6,
                                      alignItems: 'center',
                                    }}
                                  >
                                    <span
                                      style={{ fontFamily: 'monospace', color: C.bl, fontSize: 8 }}
                                    >
                                      {alt.actionType}
                                    </span>
                                    <span style={{ color: C.t2, flex: 1 }}>{alt.description}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            </>
          )}
        </Card>
      )}

      <Card style={{ padding: 16, overflow: 'auto' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 10 }}>
          Capacidade Máquina × Dia
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `100px repeat(${wdi.length},1fr)`,
            gap: 3,
            ...gridDensityVars(wdi.length),
          }}
        >
          <div />
          {wdi.map((i) => (
            <div key={i} style={{ textAlign: 'center', fontSize: 9, color: C.t3, fontWeight: 600 }}>
              {dnames[i]} <span style={{ color: C.t4 }}>{dates[i]}</span>
            </div>
          ))}
          {machines
            .filter(
              (m) =>
                Object.values(cap[m.id] || []).some((d: DayLoad) => d.prod > 0) ||
                mSt[m.id] === 'down',
            )
            .map((mc) => (
              <React.Fragment key={mc.id}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '2px 0' }}>
                  <span style={dot(mSt[mc.id] === 'down' ? C.rd : C.ac, mSt[mc.id] === 'down')} />
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: mSt[mc.id] === 'down' ? C.rd : C.t1,
                      fontFamily: 'monospace',
                    }}
                  >
                    {mc.id}
                  </span>
                  <span style={{ fontSize: 8, color: C.t4 }}>{mc.area}</span>
                </div>
                {wdi.map((di) => {
                  const dc = cap[mc.id]?.[di] || { prod: 0, setup: 0, ops: 0, pcs: 0 };
                  const tot = dc.prod + dc.setup;
                  const u = tot / DAY_CAP;
                  const isD = mSt[mc.id] === 'down';
                  return (
                    <div
                      key={di}
                      style={{
                        background: isD ? C.rdS : hC(u),
                        borderRadius: 6,
                        padding: '5px 4px',
                        textAlign: 'center',
                        minHeight: 44,
                      }}
                    >
                      <div
                        style={{
                          fontSize: 12,
                          fontWeight: 600,
                          color: tot > 0 ? C.t1 : C.t4,
                          fontFamily: 'monospace',
                        }}
                      >
                        {tot > 0 ? Math.round(tot) : '—'}
                      </div>
                      {tot > 0 && (
                        <>
                          <div
                            style={{
                              fontSize: 9,
                              color: u > 1 ? C.rd : u > 0.85 ? C.yl : C.ac,
                              fontWeight: 600,
                            }}
                          >
                            {(u * 100).toFixed(0)}%
                          </div>
                          <div style={{ fontSize: 8, color: C.t4 }}>
                            {dc.ops}op · {(dc.pcs / 1000).toFixed(0)}K
                          </div>
                        </>
                      )}
                    </div>
                  );
                })}
              </React.Fragment>
            ))}
        </div>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 10 }}>
        <Card style={{ padding: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 10 }}>
            Volume / Dia
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 90 }}>
            {prodByDay.map((p, idx) => (
              <div
                key={idx}
                style={{
                  flex: 1,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 2,
                }}
              >
                <span
                  style={{ fontSize: 9, color: C.ac, fontFamily: 'monospace', fontWeight: 600 }}
                >
                  {p > 0 ? `${(p / 1000).toFixed(0)}K` : ''}
                </span>
                <div
                  style={{
                    width: '80%',
                    height: Math.max((p / maxPd) * 65, 2),
                    background: C.ac,
                    borderRadius: '4px 4px 0 0',
                  }}
                />
                <span style={{ fontSize: 9, color: C.t4 }}>{dates[wdi[idx]]}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card style={{ padding: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Top Atrasos
          </div>
          {ops
            .filter((o) => o.atr > 0)
            .sort((a, b) => b.atr - a.atr)
            .slice(0, 8)
            .map((o, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '4px 2px',
                  borderBottom: i < 7 ? `1px solid ${C.bd}` : undefined,
                }}
              >
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: toolColor(tools, o.t),
                    fontFamily: 'monospace',
                    minWidth: 52,
                  }}
                >
                  {o.t}
                </span>
                <span
                  style={{
                    flex: 1,
                    fontSize: 10,
                    color: C.t3,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {o.sku}
                </span>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: o.atr > 10000 ? C.rd : C.yl,
                    fontFamily: 'monospace',
                  }}
                >
                  {(o.atr / 1000).toFixed(1)}K
                </span>
              </div>
            ))}
        </Card>
      </div>
    </div>
  );
}

// §10. REPLAN VIEW
function ReplanView({
  mSt,
  tSt,
  moves,
  applyMove,
  undoMove,
  blocks,
  cap,
  data,
  onApplyAndSave,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
  rushOrders,
  setRushOrders,
  allOps,
  neMetrics,
}: {
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  toggleM?: (id: string) => void;
  toggleT?: (id: string) => void;
  moves: MoveAction[];
  applyMove: (opId: string, toM: string) => void;
  undoMove: (opId: string) => void;
  blocks: Block[];
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  onApplyAndSave?: () => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
  rushOrders: Array<{ toolId: string; sku: string; qty: number; deadline: number }>;
  setRushOrders: React.Dispatch<
    React.SetStateAction<Array<{ toolId: string; sku: string; qty: number; deadline: number }>>
  >;
  allOps: EOp[];
  neMetrics: (OptResult & { blocks: Block[] }) | null;
}) {
  const { machines, tools, ops, dates, dnames, toolMap: TM, focusIds } = data;
  // Pre-compute block counts per machine to avoid O(blocks) filter per button
  const blockCountByMachine = useMemo(() => {
    const map: Record<string, number> = {};
    for (const b of blocks) {
      if (b.type !== 'blocked') map[b.machineId] = (map[b.machineId] ?? 0) + 1;
    }
    return map;
  }, [blocks]);
  const [xai, setXai] = useState<string | null>(null);
  // Day range picker for temporal down
  const [editingDown, setEditingDown] = useState<{ type: 'machine' | 'tool'; id: string } | null>(
    null,
  );

  // ── Auto-Replan state ──
  const [arResult, setArResult] = useState<AutoReplanResult | null>(null);
  const [arActions, setArActions] = useState<ReplanActionDetail[]>([]);
  const [arRunning, setArRunning] = useState(false);
  const [arSim, setArSim] = useState<ReplanSimulation | null>(null);
  const [arSimId, setArSimId] = useState<string | null>(null);
  const [arExclude, setArExclude] = useState<Set<string>>(new Set());
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );
  const [downStartDay, setDownStartDay] = useState(() => wdi[0] ?? 0);
  const [downEndDay, setDownEndDay] = useState(() => wdi[0] ?? 0);
  const [arDayFrom, setArDayFrom] = useState(() => wdi[0] ?? 0);
  const [arDayTo, setArDayTo] = useState(() => wdi[wdi.length - 1] ?? data.nDays - 1);
  const [arExpanded, setArExpanded] = useState<string | null>(null);
  const [arShowExclude, setArShowExclude] = useState(false);
  const arInputRef = useRef<unknown>(null);

  // Build the scheduling input for auto-replan (same shape as useScheduleData)
  const buildArInput = useCallback(() => {
    const settings = useSettingsStore.getState();
    const rule = (settings.dispatchRule || 'EDD') as DispatchRule;
    return {
      ops: allOps,
      mSt,
      tSt,
      moves: [] as MoveAction[],
      machines: data.machines,
      toolMap: data.toolMap,
      workdays: data.workdays,
      nDays: data.nDays,
      workforceConfig: data.workforceConfig,
      rule,
      thirdShift: data.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      dates: data.dates,
      twinValidationReport: data.twinValidationReport,
      orderBased: data.orderBased,
    };
  }, [data, allOps, mSt, tSt, replanTimelines]);

  const runAutoReplan = useCallback(() => {
    setArRunning(true);
    setArSim(null);
    setArSimId(null);
    // Defer heavy computation to next tick so React renders loading state first
    setTimeout(() => {
      const input = buildArInput();
      const excludeOpIds = allOps.filter((o) => arExclude.has(o.t)).map((o) => o.id);
      const config: Partial<AutoReplanConfig> = {
        ...DEFAULT_AUTO_REPLAN_CONFIG,
        excludeOps: excludeOpIds,
      };
      try {
        const result = autoReplan(input, config as AutoReplanConfig);
        const actions = getReplanActions(result);
        arInputRef.current = input;
        setArResult(result);
        setArActions(actions);
      } catch (e) {
        useToastStore
          .getState()
          .addToast(
            `Erro no auto-replan: ${e instanceof Error ? e.message : String(e)}`,
            'error',
            5000,
          );
      }
      setArRunning(false);
    }, 0);
  }, [buildArInput, allOps, arExclude]);

  const handleArUndo = useCallback(
    (decisionId: string) => {
      if (!arInputRef.current || !arResult) return;
      try {
        const inp = arInputRef.current as Parameters<typeof undoReplanActions>[0];
        const newResult = undoReplanActions(inp, arResult, [decisionId]);
        setArResult(newResult);
        setArActions(getReplanActions(newResult));
        setArSim(null);
        setArSimId(null);
        useToastStore.getState().addToast('Acção desfeita', 'success', 3000);
      } catch (e) {
        useToastStore
          .getState()
          .addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 4000);
      }
    },
    [arResult],
  );

  const handleArAlt = useCallback(
    (decisionId: string, alt: AlternativeAction) => {
      if (!arInputRef.current || !arResult) return;
      try {
        const inp = arInputRef.current as Parameters<typeof applyAlternative>[0];
        const newResult = applyAlternative(inp, arResult, decisionId, alt);
        setArResult(newResult);
        setArActions(getReplanActions(newResult));
        setArSim(null);
        setArSimId(null);
        useToastStore.getState().addToast('Alternativa aplicada', 'success', 3000);
      } catch (e) {
        useToastStore
          .getState()
          .addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 4000);
      }
    },
    [arResult],
  );

  const handleArSimulate = useCallback(
    (decisionId: string) => {
      if (!arInputRef.current || !arResult) return;
      try {
        const inp = arInputRef.current as Parameters<typeof simulateWithout>[0];
        const sim = simulateWithout(inp, arResult, [decisionId]);
        setArSim(sim);
        setArSimId(decisionId);
      } catch (e) {
        useToastStore
          .getState()
          .addToast(
            `Erro na simulação: ${e instanceof Error ? e.message : String(e)}`,
            'error',
            4000,
          );
      }
    },
    [arResult],
  );

  const handleArUndoAll = useCallback(() => {
    if (!arInputRef.current || !arResult || arActions.length === 0) return;
    try {
      const inp = arInputRef.current as Parameters<typeof undoReplanActions>[0];
      const allIds = arActions.map((a) => a.decisionId);
      const newResult = undoReplanActions(inp, arResult, allIds);
      setArResult(newResult);
      setArActions(getReplanActions(newResult));
      setArSim(null);
      setArSimId(null);
    } catch (e) {
      useToastStore
        .getState()
        .addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 4000);
    }
  }, [arResult, arActions]);

  const handleArApplyAll = useCallback(() => {
    if (!arResult) return;
    for (const mv of arResult.autoMoves) applyMove(mv.opId, mv.toM);
    useToastStore
      .getState()
      .addToast(`Auto-replan aplicado: ${arResult.autoMoves.length} movimentos`, 'success', 5000);
  }, [arResult, applyMove]);

  // ── Failure/Breakdown state ──
  const [failures, setFailures] = useState<FailureEvent[]>([]);
  const [failureImpacts, setFailureImpacts] = useState<ImpactReport[]>([]);
  const [showFailureForm, setShowFailureForm] = useState(false);
  const [ffResType, setFfResType] = useState<'machine' | 'tool'>('machine');
  const [ffResId, setFfResId] = useState('');
  const [ffSev, setFfSev] = useState<'total' | 'partial' | 'degraded'>('total');
  const [ffCap, setFfCap] = useState(50);
  const [ffStartDay, setFfStartDay] = useState(() => wdi[0] ?? 0);
  const [ffEndDay, setFfEndDay] = useState(() => wdi[0] ?? 0);
  const [ffDesc, setFfDesc] = useState('');

  const addFailure = useCallback(() => {
    if (!ffResId) return;
    const f: FailureEvent = {
      id: `f-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      resourceType: ffResType,
      resourceId: ffResId,
      startDay: ffStartDay,
      endDay: ffEndDay,
      startShift: null,
      endShift: null,
      severity: ffSev,
      capacityFactor: ffSev === 'total' ? 0 : ffCap / 100,
      description: ffDesc || undefined,
    };
    const newF = [...failures, f];
    setFailures(newF);
    setFailureImpacts(analyzeAllFailures(newF, blocks, data.nDays));
    setShowFailureForm(false);
    setFfDesc('');
  }, [
    ffResType,
    ffResId,
    ffSev,
    ffCap,
    ffStartDay,
    ffEndDay,
    ffDesc,
    failures,
    blocks,
    data.nDays,
  ]);

  const removeFailure = useCallback(
    (id: string) => {
      const newF = failures.filter((f) => f.id !== id);
      setFailures(newF);
      setFailureImpacts(newF.length > 0 ? analyzeAllFailures(newF, blocks, data.nDays) : []);
    },
    [failures, blocks, data.nDays],
  );

  const [cascRunning, setCascRunning] = useState(false);
  const runCascadingReplan = useCallback(() => {
    if (failures.length === 0) return;
    setCascRunning(true);
    setTimeout(() => {
      const input = buildArInput();
      try {
        const result = cascadingReplan(
          input as Parameters<typeof cascadingReplan>[0],
          failures,
          blocks,
        );
        for (const mv of result.mitigationMoves) applyMove(mv.opId, mv.toM);
        useToastStore
          .getState()
          .addToast(
            `Replan cascata: ${result.mitigationMoves.length} movimentos, ${result.unrecoverableBlocks.length} irrecuperáveis`,
            result.unrecoverableBlocks.length > 0 ? 'warning' : 'success',
            5000,
          );
      } catch (e) {
        useToastStore
          .getState()
          .addToast(`Erro: ${e instanceof Error ? e.message : String(e)}`, 'error', 5000);
      }
      setCascRunning(false);
    }, 0);
  }, [failures, blocks, buildArInput, applyMove]);

  // ── Optimization state (Phase 3) ──
  const [optRunning, setOptRunning] = useState(false);
  const [optResults, setOptResults] = useState<OptResult[]>([]);
  const [optProgress, setOptProgress] = useState(0);
  const [optN, setOptN] = useState(200);
  const [optProfile, setOptProfile] = useState('balanced');
  const optMoveable = useMemo(() => moveableOps(allOps, mSt, tSt, TM), [allOps, mSt, tSt, TM]);

  const runOpt = useCallback(() => {
    setOptRunning(true);
    setOptProgress(0);
    setOptResults([]);
    const settings = useSettingsStore.getState();
    const rule = (settings.dispatchRule || 'EDD') as DispatchRule;
    const prof = OBJECTIVE_PROFILES.find((p) => p.id === optProfile);
    const weights = prof ? (prof.weights as unknown as ScoreWeights) : undefined;
    const input: OptimizationInput = {
      ops: allOps,
      mSt,
      tSt,
      machines,
      TM,
      focusIds,
      tools,
      workforceConfig: data.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
      weights,
      seed: 42,
      workdays: data.workdays,
      nDays: data.nDays,
      rule,
      baselineBlocks: blocks,
      N: optN,
      K: 5,
      thirdShift: data.thirdShift ?? settings.thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      twinValidationReport: data.twinValidationReport,
      dates: data.dates,
      orderBased: data.orderBased,
    };
    try {
      const setup = runOptimization(input);
      setup.run(
        (batch) => {
          setOptResults(batch);
        },
        (pct) => {
          setOptProgress(pct);
        },
      );
      setOptResults(setup.top);
    } catch (e) {
      useToastStore
        .getState()
        .addToast(
          `Erro na optimização: ${e instanceof Error ? e.message : String(e)}`,
          'error',
          5000,
        );
    }
    setOptRunning(false);
  }, [
    allOps,
    mSt,
    tSt,
    machines,
    TM,
    focusIds,
    tools,
    data,
    blocks,
    optN,
    optProfile,
    replanTimelines,
  ]);

  const applyOptResult = useCallback(
    (r: OptResult) => {
      for (const mv of r.moves) applyMove(mv.opId, mv.toM);
      useToastStore
        .getState()
        .addToast(`Optimização aplicada: ${r.moves.length} movimentos`, 'success', 5000);
    },
    [applyMove],
  );

  // ── Rush Order form state (data lifted to NikufraEngine) ──
  const [roTool, setRoTool] = useState('');
  const [roQty, setRoQty] = useState(500);
  const [roDeadline, setRoDeadline] = useState(() => wdi[2] ?? 2);

  const addRushOrder = useCallback(() => {
    if (!roTool) return;
    // ETool has nm (singular string), find first matching op's sku
    const matchOp = ops.find((o) => o.t === roTool);
    const sku = matchOp?.sku ?? roTool;
    setRushOrders((prev) => [...prev, { toolId: roTool, sku, qty: roQty, deadline: roDeadline }]);
    setRoTool('');
    useToastStore
      .getState()
      .addToast(`Rush order adicionada: ${roTool} · ${roQty} pcs`, 'success', 3000);
  }, [roTool, roQty, roDeadline, TM]);

  const removeRushOrder = useCallback((idx: number) => {
    setRushOrders((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const decs = useMemo(
    () => genDecisions(allOps, mSt, tSt, moves, blocks, machines, TM, focusIds, tools),
    [allOps, mSt, tSt, moves, blocks, machines, TM, focusIds, tools],
  );
  const rp = decs.filter((d) => d.type === 'replan'),
    blk = decs.filter((d) => d.type === 'blocked');
  const lP = blk.reduce((a, d) => a + ((d.impact?.pcsLost as number) || 0), 0);
  const otd = neMetrics ? neMetrics.otdDelivery.toFixed(1) : '—';
  const sC = (s: string) => ({ critical: C.rd, high: C.yl, medium: C.bl, low: C.ac })[s] || C.t3;
  const qv = useMemo(() => quickValidate(blocks, machines, TM), [blocks, machines, TM]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {(qv.criticalCount > 0 || qv.highCount > 0) && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '6px 12px',
            borderRadius: 6,
            background: qv.criticalCount > 0 ? C.rdS : `${C.yl}18`,
            borderLeft: `3px solid ${qv.criticalCount > 0 ? C.rd : C.yl}`,
          }}
        >
          <AlertTriangle
            size={13}
            style={{ color: qv.criticalCount > 0 ? C.rd : C.yl, flexShrink: 0 }}
          />
          <span
            style={{ fontSize: 10, fontWeight: 600, color: qv.criticalCount > 0 ? C.rd : C.yl }}
          >
            {qv.criticalCount > 0
              ? `${qv.criticalCount} conflito${qv.criticalCount > 1 ? 's' : ''} crítico${qv.criticalCount > 1 ? 's' : ''}`
              : ''}
            {qv.criticalCount > 0 && qv.highCount > 0 ? ' · ' : ''}
            {qv.highCount > 0 ? `${qv.highCount} alerta${qv.highCount > 1 ? 's' : ''}` : ''}
          </span>
          {qv.warnings.length > 0 && (
            <span style={{ fontSize: 9, color: C.t3, marginLeft: 'auto' }}>{qv.warnings[0]}</span>
          )}
        </div>
      )}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>
            Replaneamento{' '}
            <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>Remove & Repair</span>
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {moves.length > 0 && (
              <Pill color={C.rd} active onClick={() => moves.forEach((m) => undoMove(m.opId))}>
                <Undo2
                  size={10}
                  strokeWidth={1.5}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Todos ({moves.length})
              </Pill>
            )}
            {rp.length > 0 && (
              <Pill
                color={C.ac}
                active
                onClick={() =>
                  rp.forEach((d) => d.action && applyMove(d.action.opId, d.action.toM))
                }
              >
                <Zap
                  size={10}
                  strokeWidth={1.5}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Auto ({rp.length})
              </Pill>
            )}
            {moves.length > 0 && onApplyAndSave && (
              <button
                onClick={onApplyAndSave}
                disabled={isSaving}
                style={{
                  padding: '5px 14px',
                  borderRadius: 8,
                  border: 'none',
                  cursor: isSaving ? 'wait' : 'pointer',
                  background: C.ac,
                  color: C.bg,
                  fontSize: 10,
                  fontWeight: 600,
                  fontFamily: 'inherit',
                  opacity: isSaving ? 0.6 : 1,
                }}
              >
                {isSaving ? 'A guardar...' : `Aplicar & Guardar (${moves.length})`}
              </button>
            )}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 6 }}>
            Máquinas
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {machines.map((m) => {
              const isD = mSt[m.id] === 'down';
              const n = blockCountByMachine[m.id] ?? 0;
              const mDownDays = getResourceDownDays('machine', m.id);
              return (
                <button
                  key={m.id}
                  onClick={() => {
                    if (mDownDays.size > 0) {
                      // Quick restore: clear all down days and close panel
                      clearResourceDown('machine', m.id);
                      setEditingDown(null);
                    } else {
                      // Open/close day picker to set down periods
                      setEditingDown(
                        editingDown?.type === 'machine' && editingDown.id === m.id
                          ? null
                          : { type: 'machine', id: m.id },
                      );
                    }
                  }}
                  style={{
                    padding: '6px 10px',
                    borderRadius: 8,
                    cursor: 'pointer',
                    textAlign: 'center',
                    minWidth: 80,
                    background: isD
                      ? C.rdS
                      : editingDown?.type === 'machine' && editingDown.id === m.id
                        ? `${C.ac}12`
                        : 'transparent',
                    border: `1.5px solid ${isD ? C.rd + '44' : editingDown?.type === 'machine' && editingDown.id === m.id ? C.ac + '44' : C.bd}`,
                    fontFamily: 'inherit',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 4,
                    }}
                  >
                    <span style={dot(isD ? C.rd : C.ac, isD)} />
                    <span style={{ fontSize: 9, fontWeight: 600, color: isD ? C.rd : C.ac }}>
                      {mDownDays.size > 0 ? `DOWN ${mDownDays.size}d` : 'RUN'}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: isD ? C.rd : C.t1,
                      fontFamily: 'monospace',
                      marginTop: 2,
                    }}
                  >
                    {m.id}
                  </div>
                  <div style={{ fontSize: 9, color: C.t4 }}>
                    {m.area} · {n} ops
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 5 }}>
            Ferramentas
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
            {tools
              .filter(
                (t) =>
                  focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
              )
              .map((t) => {
                const tDownDays = getResourceDownDays('tool', t.id);
                return (
                  <Pill
                    key={t.id}
                    active={tSt[t.id] === 'down'}
                    color={C.rd}
                    onClick={() => {
                      if (tDownDays.size > 0) {
                        clearResourceDown('tool', t.id);
                        setEditingDown(null);
                      } else {
                        setEditingDown(
                          editingDown?.type === 'tool' && editingDown.id === t.id
                            ? null
                            : { type: 'tool', id: t.id },
                        );
                      }
                    }}
                    size="sm"
                  >
                    {t.id}
                    {tDownDays.size > 0 ? ` ${tDownDays.size}d` : ''}
                  </Pill>
                );
              })}
          </div>
        </div>

        {/* Day range picker for temporal down */}
        {editingDown &&
          (() => {
            const currentDown = getResourceDownDays(editingDown.type, editingDown.id);
            return (
              <div
                style={{
                  marginTop: 10,
                  padding: 10,
                  borderRadius: 8,
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${C.bd}`,
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 8,
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>
                    Período DOWN:{' '}
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", color: C.rd }}>
                      {editingDown.id}
                    </span>
                    <span style={{ fontSize: 9, fontWeight: 400, color: C.t4, marginLeft: 6 }}>
                      ({editingDown.type === 'machine' ? 'máquina' : 'ferramenta'})
                    </span>
                  </span>
                  <button
                    onClick={() => setEditingDown(null)}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      color: C.t4,
                      padding: 2,
                    }}
                  >
                    <X size={12} />
                  </button>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 10, color: C.t3, minWidth: 30 }}>De:</span>
                  <select
                    value={downStartDay}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setDownStartDay(v);
                      if (downEndDay < v) setDownEndDay(v);
                    }}
                    style={{
                      padding: '3px 6px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.bg,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi.map((i) => (
                      <option key={i} value={i}>
                        {dnames[i]} {dates[i]}
                      </option>
                    ))}
                  </select>
                  <span style={{ fontSize: 10, color: C.t4 }}>até</span>
                  <select
                    value={downEndDay}
                    onChange={(e) => setDownEndDay(Number(e.target.value))}
                    style={{
                      padding: '3px 6px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.bg,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi
                      .filter((i) => i >= downStartDay)
                      .map((i) => (
                        <option key={i} value={i}>
                          {dnames[i]} {dates[i]}
                        </option>
                      ))}
                  </select>
                  <button
                    onClick={() => {
                      const days: number[] = [];
                      for (let d = downStartDay; d <= downEndDay; d++) days.push(d);
                      setResourceDown(editingDown.type, editingDown.id, days);
                    }}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: 'none',
                      background: C.rd,
                      color: C.t1,
                      fontSize: 9,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Aplicar
                  </button>
                </div>
                {/* Visual preview of which days are DOWN */}
                {currentDown.size > 0 && (
                  <div style={{ display: 'flex', gap: 2, marginBottom: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 9, color: C.t4, minWidth: 30 }}>Dias:</span>
                    {dates.map((_d: string, i: number) => (
                      <div
                        key={i}
                        style={{
                          width: 6,
                          height: 18,
                          borderRadius: 2,
                          background: currentDown.has(i) ? C.rd : `${C.bd}44`,
                        }}
                        title={`${dnames[i]} ${dates[i]}${currentDown.has(i) ? ' — DOWN' : ''}`}
                      />
                    ))}
                    <span style={{ fontSize: 9, color: C.rd, fontWeight: 600, marginLeft: 4 }}>
                      {currentDown.size}d
                    </span>
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    onClick={() =>
                      setResourceDown(
                        editingDown.type,
                        editingDown.id,
                        dates.map((_: string, i: number) => i),
                      )
                    }
                    style={{
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: `1px solid ${C.rd}44`,
                      background: C.rdS,
                      color: C.rd,
                      fontSize: 9,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      fontWeight: 600,
                    }}
                  >
                    Tudo DOWN
                  </button>
                  <button
                    onClick={() => clearResourceDown(editingDown.type, editingDown.id)}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: 'transparent',
                      color: C.t3,
                      fontSize: 9,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Limpar
                  </button>
                </div>
              </div>
            );
          })()}
      </Card>

      {/* ── Auto-Replan Panel ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            Auto-Replan{' '}
            <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>5 estratégias</span>
          </div>
          {arActions.length > 0 && <Tag color={C.ac}>{arActions.length} acções</Tag>}
        </div>

        {/* Date range */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 10, color: C.t3, minWidth: 56 }}>Horizonte:</span>
          <select
            value={arDayFrom}
            onChange={(e) => {
              setArDayFrom(Number(e.target.value));
              setArResult(null);
            }}
            style={{
              padding: '3px 6px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: C.bg,
              color: C.t1,
              fontSize: 10,
              fontFamily: 'inherit',
            }}
          >
            {wdi.map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 10, color: C.t4 }}>até</span>
          <select
            value={arDayTo}
            onChange={(e) => {
              setArDayTo(Number(e.target.value));
              setArResult(null);
            }}
            style={{
              padding: '3px 6px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: C.bg,
              color: C.t1,
              fontSize: 10,
              fontFamily: 'inherit',
            }}
          >
            {wdi.map((i) => (
              <option key={i} value={i}>
                {dnames[i]} {dates[i]}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              setArDayFrom(wdi[0] ?? 0);
              setArDayTo(wdi[wdi.length - 1] ?? data.nDays - 1);
              setArResult(null);
            }}
            style={{
              padding: '2px 8px',
              borderRadius: 4,
              border: `1px solid ${C.bd}`,
              background: 'transparent',
              color: C.t3,
              fontSize: 9,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Tudo
          </button>
        </div>

        {/* Exclude tools */}
        <div style={{ marginBottom: 10 }}>
          <button
            onClick={() => setArShowExclude(!arShowExclude)}
            style={{
              padding: '3px 10px',
              borderRadius: 4,
              border: `1px solid ${arExclude.size > 0 ? C.yl + '44' : C.bd}`,
              background: arExclude.size > 0 ? C.ylS : 'transparent',
              color: arExclude.size > 0 ? C.yl : C.t3,
              fontSize: 10,
              cursor: 'pointer',
              fontFamily: 'inherit',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 3,
            }}
          >
            {arExclude.size > 0 ? `${arExclude.size} ferramentas excluídas` : 'Excluir ferramentas'}
            {arShowExclude ? (
              <ChevronDown size={10} strokeWidth={1.5} />
            ) : (
              <ChevronRight size={10} strokeWidth={1.5} />
            )}
          </button>
          {arShowExclude && (
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 3,
                marginTop: 6,
                maxHeight: 80,
                overflowY: 'auto',
              }}
            >
              {tools
                .filter(
                  (t) =>
                    focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                )
                .map((t) => (
                  <Pill
                    key={t.id}
                    active={arExclude.has(t.id)}
                    color={C.yl}
                    onClick={() => {
                      setArExclude((prev) => {
                        const n = new Set(prev);
                        if (n.has(t.id)) n.delete(t.id);
                        else n.add(t.id);
                        return n;
                      });
                      setArResult(null);
                    }}
                    size="sm"
                  >
                    {t.id}
                  </Pill>
                ))}
            </div>
          )}
        </div>

        {/* Run button */}
        <button
          onClick={runAutoReplan}
          disabled={arRunning}
          data-testid="run-auto-replan"
          style={{
            width: '100%',
            padding: 10,
            borderRadius: 6,
            border: 'none',
            background: arRunning ? C.s3 : C.ac,
            color: arRunning ? C.t3 : C.bg,
            fontSize: 12,
            fontWeight: 600,
            cursor: arRunning ? 'wait' : 'pointer',
            fontFamily: 'inherit',
          }}
        >
          <Zap
            size={12}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}
          />
          {arRunning ? 'A executar...' : 'Executar Auto-Replan'}
        </button>
      </Card>

      {/* ── Auto-Replan Actions ── */}
      {arResult && arActions.length > 0 && (
        <Card style={{ padding: 16 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 12,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
              Acções Auto-Replan <Tag color={C.ac}>{arActions.length}</Tag>
            </div>
            <div style={{ display: 'flex', gap: 4 }}>
              <Pill color={C.ac} active onClick={handleArApplyAll}>
                <Check
                  size={10}
                  strokeWidth={2}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Aplicar Todas
              </Pill>
              <Pill color={C.rd} active onClick={handleArUndoAll}>
                <Undo2
                  size={10}
                  strokeWidth={1.5}
                  style={{ display: 'inline', verticalAlign: 'middle' }}
                />{' '}
                Desfazer Todas
              </Pill>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {arActions.map((act) => {
              const isExp = arExpanded === act.decisionId;
              const isSim = arSimId === act.decisionId;
              const stratColor: Record<string, string> = {
                ADVANCE_PRODUCTION: C.ac,
                MOVE_ALT_MACHINE: C.bl,
                SPLIT_OPERATION: C.pp,
                OVERTIME: C.yl,
                THIRD_SHIFT: C.cy,
              };
              const sc2 = stratColor[act.strategy] || C.t3;
              return (
                <div
                  key={act.decisionId}
                  style={{
                    padding: 12,
                    borderRadius: 6,
                    background: isSim ? `${C.bl}08` : C.bg,
                    border: `1px solid ${isSim ? C.bl + '33' : C.bd}`,
                    borderLeft: `3px solid ${sc2}`,
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      marginBottom: 4,
                      flexWrap: 'wrap',
                    }}
                  >
                    <Tag color={sc2}>{act.strategy.replace(/_/g, ' ')}</Tag>
                    <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>
                      {act.summary}
                    </span>
                    {act.reversible && (
                      <span
                        style={{
                          fontSize: 8,
                          color: C.ac,
                          fontWeight: 600,
                          background: C.acS,
                          padding: '1px 4px',
                          borderRadius: 3,
                        }}
                      >
                        REVERSÍVEL
                      </span>
                    )}
                    <span
                      style={{ fontSize: 9, color: C.t4, fontFamily: "'JetBrains Mono',monospace" }}
                    >
                      {act.opId}
                    </span>
                  </div>
                  <div style={{ fontSize: 10, color: C.t3, marginBottom: 8 }}>{act.detail}</div>

                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {act.alternatives.length > 0 && (
                      <button
                        onClick={() => setArExpanded(isExp ? null : act.decisionId)}
                        style={{
                          padding: '3px 8px',
                          borderRadius: 4,
                          border: `1px solid ${C.pp}33`,
                          background: isExp ? C.ppS : 'transparent',
                          color: C.pp,
                          fontSize: 9,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 3,
                        }}
                      >
                        {isExp ? (
                          <ChevronDown size={9} strokeWidth={1.5} />
                        ) : (
                          <ChevronRight size={9} strokeWidth={1.5} />
                        )}
                        {act.alternatives.length} alt.
                      </button>
                    )}
                    <button
                      onClick={() => handleArUndo(act.decisionId)}
                      style={{
                        padding: '3px 8px',
                        borderRadius: 4,
                        border: `1px solid ${C.rd}33`,
                        background: 'transparent',
                        color: C.rd,
                        fontSize: 9,
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                      }}
                    >
                      <Undo2 size={9} strokeWidth={1.5} /> Desfazer
                    </button>
                    <button
                      onClick={() => handleArSimulate(act.decisionId)}
                      style={{
                        padding: '3px 8px',
                        borderRadius: 4,
                        border: `1px solid ${C.bl}33`,
                        background: isSim ? C.blS : 'transparent',
                        color: C.bl,
                        fontSize: 9,
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                      }}
                    >
                      <Eye size={9} strokeWidth={1.5} /> Simular
                    </button>
                  </div>

                  {/* Alternatives expand */}
                  {isExp && act.alternatives.length > 0 && (
                    <div style={{ marginTop: 8, padding: 8, background: C.s2, borderRadius: 4 }}>
                      {act.alternatives.map((alt, ai) => (
                        <div
                          key={ai}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            padding: '4px 0',
                            borderBottom:
                              ai < act.alternatives.length - 1 ? `1px solid ${C.bd}` : 'none',
                          }}
                        >
                          <div>
                            <div style={{ fontSize: 10, color: C.t1 }}>{alt.description}</div>
                            <div style={{ fontSize: 9, color: C.t4 }}>
                              {alt.actionType.replace(/_/g, ' ')}
                            </div>
                          </div>
                          <button
                            onClick={() => handleArAlt(act.decisionId, alt)}
                            style={{
                              padding: '3px 8px',
                              borderRadius: 4,
                              border: 'none',
                              background: C.ac,
                              color: C.bg,
                              fontSize: 9,
                              fontWeight: 600,
                              cursor: 'pointer',
                              fontFamily: 'inherit',
                            }}
                          >
                            Aplicar
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Simulation preview */}
                  {isSim && arSim && (
                    <div
                      style={{
                        marginTop: 8,
                        padding: 8,
                        background: `${C.bl}08`,
                        borderRadius: 4,
                        border: `1px solid ${C.bl}22`,
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 600, color: C.bl, marginBottom: 4 }}>
                        <Eye
                          size={10}
                          strokeWidth={1.5}
                          style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }}
                        />
                        Simulação: sem esta acção
                      </div>
                      <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.t2 }}>
                        <span>
                          Overflow: {arSim.overflowBefore} → {arSim.overflowAfter}{' '}
                          <span
                            style={{
                              color:
                                arSim.overflowDelta > 0
                                  ? C.rd
                                  : arSim.overflowDelta < 0
                                    ? C.ac
                                    : C.t3,
                              fontWeight: 600,
                            }}
                          >
                            ({arSim.overflowDelta > 0 ? '+' : ''}
                            {arSim.overflowDelta})
                          </span>
                        </span>
                      </div>
                      {arSim.unresolved.length > 0 && (
                        <div style={{ marginTop: 4 }}>
                          <div style={{ fontSize: 9, color: C.rd, fontWeight: 600 }}>
                            {arSim.unresolved.length} não resolvido
                            {arSim.unresolved.length > 1 ? 's' : ''}
                          </div>
                          {arSim.unresolved.slice(0, 5).map((u, i) => (
                            <div
                              key={i}
                              style={{
                                fontSize: 9,
                                color: C.t3,
                                fontFamily: "'JetBrains Mono',monospace",
                              }}
                            >
                              {u.opId}: {u.reason} (deficit: {u.deficit})
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div style={{ display: 'flex', gap: 12, marginTop: 12, fontSize: 10, color: C.t3 }}>
            <span>{arResult.autoMoves.length} movimentos</span>
            <span>{arResult.autoAdvances?.length ?? 0} adiantamentos</span>
            <span>{arResult.decisions.length} decisões</span>
          </div>
        </Card>
      )}

      {arResult && arActions.length === 0 && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 6,
            background: C.acS,
            border: `1px solid ${C.ac}33`,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <Check size={12} strokeWidth={2} style={{ color: C.ac }} />
          <span style={{ fontSize: 11, fontWeight: 600, color: C.ac }}>
            Auto-replan concluído — sem acções necessárias
          </span>
        </div>
      )}

      {/* ── Failures / Breakdowns Panel ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: failures.length > 0 || showFailureForm ? 10 : 0,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            Avarias / Indisponibilidades{' '}
            {failures.length > 0 && <Tag color={C.rd}>{failures.length}</Tag>}
          </div>
          <button
            onClick={() => setShowFailureForm(!showFailureForm)}
            style={{
              padding: '4px 10px',
              borderRadius: 4,
              border: `1px solid ${C.rd}33`,
              background: showFailureForm ? C.rdS : 'transparent',
              color: C.rd,
              fontSize: 10,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            {showFailureForm ? 'Cancelar' : '+ Registar Avaria'}
          </button>
        </div>

        {/* Registration form */}
        {showFailureForm && (
          <div
            style={{
              padding: 12,
              background: C.bg,
              borderRadius: 6,
              border: `1px solid ${C.bd}`,
              marginBottom: 10,
            }}
          >
            <div
              style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}
            >
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Tipo
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {(['machine', 'tool'] as const).map((t) => (
                    <Pill
                      key={t}
                      active={ffResType === t}
                      color={C.bl}
                      onClick={() => {
                        setFfResType(t);
                        setFfResId('');
                      }}
                      size="sm"
                    >
                      {t === 'machine' ? 'Máquina' : 'Ferramenta'}
                    </Pill>
                  ))}
                </div>
              </div>
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Recurso
                </div>
                <select
                  value={ffResId}
                  onChange={(e) => setFfResId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '4px 6px',
                    borderRadius: 4,
                    border: `1px solid ${C.bd}`,
                    background: C.s2,
                    color: C.t1,
                    fontSize: 10,
                    fontFamily: 'inherit',
                  }}
                >
                  <option value="">Selecionar...</option>
                  {ffResType === 'machine'
                    ? machines.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.id} ({m.area})
                        </option>
                      ))
                    : tools
                        .filter(
                          (t) =>
                            focusIds.includes(t.m) ||
                            (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                        )
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.id}
                          </option>
                        ))}
                </select>
              </div>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr',
                gap: 10,
                marginBottom: 8,
              }}
            >
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Severidade
                </div>
                <div style={{ display: 'flex', gap: 3 }}>
                  {(
                    [
                      ['total', C.rd],
                      ['partial', C.yl],
                      ['degraded', C.bl],
                    ] as const
                  ).map(([s, c]) => (
                    <Pill
                      key={s}
                      active={ffSev === s}
                      color={c}
                      onClick={() => setFfSev(s)}
                      size="sm"
                    >
                      {s === 'total' ? 'Total' : s === 'partial' ? 'Parcial' : 'Degradada'}
                    </Pill>
                  ))}
                </div>
              </div>
              {ffSev !== 'total' && (
                <div>
                  <div
                    style={{
                      fontSize: 9,
                      color: C.t4,
                      marginBottom: 3,
                      fontWeight: 600,
                      textTransform: 'uppercase',
                      letterSpacing: '.04em',
                    }}
                  >
                    Capacidade restante
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <input
                      type="number"
                      value={ffCap}
                      onChange={(e) => setFfCap(Math.max(0, Math.min(99, Number(e.target.value))))}
                      style={{
                        width: 50,
                        padding: '3px 6px',
                        borderRadius: 4,
                        border: `1px solid ${C.bd}`,
                        background: C.s2,
                        color: C.t1,
                        fontSize: 10,
                        fontFamily: "'JetBrains Mono',monospace",
                        textAlign: 'center',
                      }}
                    />
                    <span style={{ fontSize: 10, color: C.t3 }}>%</span>
                  </div>
                </div>
              )}
              <div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t4,
                    marginBottom: 3,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}
                >
                  Período
                </div>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <select
                    value={ffStartDay}
                    onChange={(e) => setFfStartDay(Number(e.target.value))}
                    style={{
                      padding: '3px 4px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.s2,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi.map((i) => (
                      <option key={i} value={i}>
                        {dnames[i]} {dates[i]}
                      </option>
                    ))}
                  </select>
                  <span style={{ fontSize: 9, color: C.t4 }}>—</span>
                  <select
                    value={ffEndDay}
                    onChange={(e) => setFfEndDay(Number(e.target.value))}
                    style={{
                      padding: '3px 4px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      background: C.s2,
                      color: C.t1,
                      fontSize: 10,
                      fontFamily: 'inherit',
                    }}
                  >
                    {wdi
                      .filter((i) => i >= ffStartDay)
                      .map((i) => (
                        <option key={i} value={i}>
                          {dnames[i]} {dates[i]}
                        </option>
                      ))}
                  </select>
                </div>
              </div>
            </div>
            <div style={{ marginBottom: 8 }}>
              <div
                style={{
                  fontSize: 9,
                  color: C.t4,
                  marginBottom: 3,
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '.04em',
                }}
              >
                Descrição
              </div>
              <input
                type="text"
                value={ffDesc}
                onChange={(e) => setFfDesc(e.target.value)}
                placeholder="Ex: Manutenção preventiva"
                style={{
                  width: '100%',
                  padding: '4px 8px',
                  borderRadius: 4,
                  border: `1px solid ${C.bd}`,
                  background: C.s2,
                  color: C.t1,
                  fontSize: 10,
                  fontFamily: 'inherit',
                }}
              />
            </div>
            <button
              onClick={addFailure}
              disabled={!ffResId}
              style={{
                padding: '6px 16px',
                borderRadius: 4,
                border: 'none',
                background: ffResId ? C.rd : C.s3,
                color: ffResId ? C.t1 : C.t4,
                fontSize: 10,
                fontWeight: 600,
                cursor: ffResId ? 'pointer' : 'default',
                fontFamily: 'inherit',
              }}
            >
              Registar
            </button>
          </div>
        )}

        {/* Active failures list */}
        {failures.map((f, fi) => {
          const imp = failureImpacts[fi];
          return (
            <div
              key={f.id}
              style={{
                padding: 10,
                background: C.rdS,
                borderRadius: 6,
                border: `1px solid ${C.rd}22`,
                marginBottom: 6,
                borderLeft: `3px solid ${C.rd}`,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 4,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: C.t1,
                      fontFamily: "'JetBrains Mono',monospace",
                    }}
                  >
                    {f.resourceId}
                  </span>
                  <Tag
                    color={f.severity === 'total' ? C.rd : f.severity === 'partial' ? C.yl : C.bl}
                  >
                    {f.severity === 'total'
                      ? 'TOTAL'
                      : f.severity === 'partial'
                        ? `PARCIAL ${Math.round(f.capacityFactor * 100)}%`
                        : `DEGRADADA ${Math.round(f.capacityFactor * 100)}%`}
                  </Tag>
                  <span style={{ fontSize: 10, color: C.t3 }}>
                    {dnames[f.startDay]} {dates[f.startDay]}
                    {f.startDay !== f.endDay ? ` — ${dnames[f.endDay]} ${dates[f.endDay]}` : ''}
                  </span>
                </div>
                <button
                  onClick={() => removeFailure(f.id)}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: C.t3,
                    cursor: 'pointer',
                    padding: '0 2px',
                  }}
                >
                  <X size={12} strokeWidth={2} />
                </button>
              </div>
              {f.description && (
                <div style={{ fontSize: 10, color: C.t3, marginBottom: 4 }}>{f.description}</div>
              )}
              {imp && imp.summary.totalBlocksAffected > 0 && (
                <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.t2 }}>
                  <span>
                    <span style={{ fontWeight: 600, color: C.rd }}>
                      {imp.summary.totalBlocksAffected}
                    </span>{' '}
                    blocos afectados
                  </span>
                  <span>
                    <span style={{ fontWeight: 600, color: C.rd }}>
                      {imp.summary.totalQtyAtRisk.toLocaleString()}
                    </span>{' '}
                    pcs em risco
                  </span>
                  <span>{imp.summary.blocksWithAlternative} c/ alternativa</span>
                  <span style={{ color: C.rd, fontWeight: 600 }}>
                    {imp.summary.blocksWithoutAlternative} s/ alternativa
                  </span>
                </div>
              )}
              {imp && imp.summary.totalBlocksAffected === 0 && (
                <div style={{ fontSize: 10, color: C.ac }}>Sem impacto no schedule actual</div>
              )}
            </div>
          );
        })}

        {/* Cascading replan button */}
        {failures.length > 0 && (
          <button
            onClick={runCascadingReplan}
            disabled={cascRunning}
            data-testid="cascading-replan"
            style={{
              width: '100%',
              padding: 8,
              borderRadius: 6,
              border: 'none',
              background: cascRunning ? C.s3 : C.rd,
              color: cascRunning ? C.t3 : C.t1,
              fontSize: 11,
              fontWeight: 600,
              cursor: cascRunning ? 'wait' : 'pointer',
              fontFamily: 'inherit',
              marginTop: 6,
            }}
          >
            {cascRunning ? 'A replanificar...' : `Replanificar com Avarias (${failures.length})`}
          </button>
        )}

        {failures.length === 0 && !showFailureForm && (
          <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
            Sem avarias registadas
          </div>
        )}
      </Card>

      {/* ── Optimization Panel (Phase 3) ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            <Sparkles
              size={12}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4, color: C.pp }}
            />
            Optimização{' '}
            <span style={{ fontSize: 10, color: C.t4, fontWeight: 400 }}>
              {optMoveable.length} ops movíveis
            </span>
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            marginBottom: 10,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Perfil
            </div>
            <div style={{ display: 'flex', gap: 3 }}>
              {OBJECTIVE_PROFILES.map((p) => (
                <Pill
                  key={p.id}
                  active={optProfile === p.id}
                  color={C.pp}
                  onClick={() => {
                    setOptProfile(p.id);
                    setOptResults([]);
                  }}
                  size="sm"
                >
                  {p.label}
                </Pill>
              ))}
            </div>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Iterações
            </div>
            <div style={{ display: 'flex', gap: 3 }}>
              {[100, 200, 500].map((n) => (
                <Pill
                  key={n}
                  active={optN === n}
                  color={C.bl}
                  onClick={() => {
                    setOptN(n);
                    setOptResults([]);
                  }}
                  size="sm"
                >
                  {n}
                </Pill>
              ))}
            </div>
          </div>
          <div style={{ flex: 1 }} />
          <button
            onClick={runOpt}
            disabled={optRunning}
            data-testid="run-optimization"
            style={{
              padding: '8px 20px',
              borderRadius: 6,
              border: 'none',
              background: optRunning ? C.s3 : C.pp,
              color: optRunning ? C.t3 : C.t1,
              fontSize: 11,
              fontWeight: 600,
              cursor: optRunning ? 'wait' : 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <Sparkles
              size={11}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4 }}
            />
            {optRunning ? `A optimizar... ${Math.round(optProgress * 100)}%` : 'Otimizar'}
          </button>
        </div>

        {/* Moveable ops summary */}
        {optMoveable.length > 0 && !optResults.length && (
          <div style={{ maxHeight: 120, overflowY: 'auto', marginBottom: 6 }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '70px 60px 50px 50px 1fr',
                gap: '2px 8px',
                fontSize: 10,
              }}
            >
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Ferramenta</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Prim.</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Alt.</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Pcs</div>
              <div style={{ color: C.t4, fontSize: 9, fontWeight: 600 }}>Horas</div>
              {optMoveable.slice(0, 12).map((mo) => (
                <React.Fragment key={mo.opId}>
                  <div
                    style={{
                      fontFamily: "'JetBrains Mono',monospace",
                      color: toolColor(tools, mo.toolId),
                      fontWeight: 600,
                    }}
                  >
                    {mo.toolId}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t2 }}>
                    {mo.primaryM}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.ac }}>
                    {mo.altM}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t1 }}>
                    {mo.totalPcs.toLocaleString()}
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono',monospace", color: C.t3 }}>
                    {mo.hrs.toFixed(1)}h
                  </div>
                </React.Fragment>
              ))}
            </div>
            {optMoveable.length > 12 && (
              <div style={{ fontSize: 9, color: C.t4, textAlign: 'center', marginTop: 4 }}>
                +{optMoveable.length - 12} mais
              </div>
            )}
          </div>
        )}

        {/* Optimization results */}
        {optResults.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {optResults.slice(0, 5).map((r, ri) => {
              return (
                <div
                  key={ri}
                  style={{
                    padding: 10,
                    borderRadius: 6,
                    background: ri === 0 ? `${C.pp}08` : C.bg,
                    border: `1px solid ${ri === 0 ? C.pp + '33' : C.bd}`,
                    borderLeft: `3px solid ${ri === 0 ? C.pp : C.t4}`,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      {ri === 0 && <Star size={12} strokeWidth={1.5} style={{ color: C.pp }} />}
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: ri === 0 ? C.pp : C.t1,
                          fontFamily: "'JetBrains Mono',monospace",
                        }}
                      >
                        #{ri + 1}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, fontSize: 10 }}>
                      <span style={{ color: C.t3 }}>
                        OTD{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: r.otd >= 95 ? C.ac : C.rd,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.otd.toFixed(1)}%
                        </span>
                      </span>
                      <span style={{ color: C.t3 }}>
                        Setups{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: C.t1,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.setupCount}
                        </span>
                      </span>
                      <span style={{ color: C.t3 }}>
                        Tard.{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: r.tardinessDays > 0 ? C.yl : C.ac,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.tardinessDays.toFixed(1)}d
                        </span>
                      </span>
                      <span style={{ color: C.t3 }}>
                        Moves{' '}
                        <span
                          style={{
                            fontWeight: 600,
                            color: C.bl,
                            fontFamily: "'JetBrains Mono',monospace",
                          }}
                        >
                          {r.moves.length}
                        </span>
                      </span>
                    </div>
                    {r.label && <span style={{ fontSize: 9, color: C.t4 }}>{r.label}</span>}
                  </div>
                  <button
                    onClick={() => applyOptResult(r)}
                    data-testid={`apply-opt-${ri}`}
                    style={{
                      padding: '4px 12px',
                      borderRadius: 4,
                      border: 'none',
                      background: ri === 0 ? C.pp : C.s3,
                      color: C.t1,
                      fontSize: 10,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    Aplicar
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {optMoveable.length === 0 && (
          <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
            Sem operações movíveis (todas as ferramentas numa só máquina)
          </div>
        )}
      </Card>

      {/* ── Rush Orders Panel (Phase 4) ── */}
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: rushOrders.length > 0 ? 10 : 0,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 600, color: C.t1 }}>
            <Zap
              size={12}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 4, color: C.yl }}
            />
            Encomendas Urgentes{' '}
            {rushOrders.length > 0 && <Tag color={C.yl}>{rushOrders.length}</Tag>}
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'flex-end',
            marginBottom: rushOrders.length > 0 ? 10 : 0,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Ferramenta
            </div>
            <select
              value={roTool}
              onChange={(e) => setRoTool(e.target.value)}
              style={{
                padding: '4px 6px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 10,
                fontFamily: 'inherit',
                minWidth: 100,
              }}
            >
              <option value="">Selecionar...</option>
              {tools
                .filter(
                  (t) =>
                    focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
                )
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.id}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Qtd
            </div>
            <input
              type="number"
              value={roQty}
              onChange={(e) => setRoQty(Math.max(1, Number(e.target.value)))}
              style={{
                width: 70,
                padding: '4px 6px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 10,
                fontFamily: "'JetBrains Mono',monospace",
                textAlign: 'center',
              }}
            />
          </div>
          <div>
            <div
              style={{
                fontSize: 9,
                color: C.t4,
                marginBottom: 2,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '.04em',
              }}
            >
              Deadline
            </div>
            <select
              value={roDeadline}
              onChange={(e) => setRoDeadline(Number(e.target.value))}
              style={{
                padding: '4px 6px',
                borderRadius: 4,
                border: `1px solid ${C.bd}`,
                background: C.s2,
                color: C.t1,
                fontSize: 10,
                fontFamily: 'inherit',
              }}
            >
              {wdi.map((i) => (
                <option key={i} value={i}>
                  {dnames[i]} {dates[i]}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={addRushOrder}
            disabled={!roTool}
            style={{
              padding: '5px 14px',
              borderRadius: 4,
              border: 'none',
              background: roTool ? C.yl : C.s3,
              color: roTool ? C.bg : C.t4,
              fontSize: 10,
              fontWeight: 600,
              cursor: roTool ? 'pointer' : 'default',
              fontFamily: 'inherit',
            }}
          >
            + Adicionar
          </button>
        </div>

        {rushOrders.map((ro, i) => {
          const tool = TM[ro.toolId];
          const hrs = tool ? ro.qty / tool.pH : 0;
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 10px',
                background: `${C.yl}08`,
                borderRadius: 4,
                border: `1px solid ${C.yl}22`,
                borderLeft: `3px solid ${C.yl}`,
                marginBottom: 4,
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: toolColor(tools, ro.toolId),
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {ro.toolId}
              </span>
              <span style={{ fontSize: 10, color: C.t2 }}>{ro.sku}</span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: C.t1,
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {ro.qty.toLocaleString()} pcs
              </span>
              <span style={{ fontSize: 10, color: C.t3 }}>{hrs.toFixed(1)}h</span>
              <span style={{ fontSize: 10, color: C.yl, fontWeight: 600 }}>
                até {dnames[ro.deadline]} {dates[ro.deadline]}
              </span>
              <span style={{ flex: 1 }} />
              <button
                onClick={() => removeRushOrder(i)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: C.t3,
                  cursor: 'pointer',
                  padding: '0 2px',
                }}
              >
                <X size={12} strokeWidth={2} />
              </button>
            </div>
          );
        })}

        {rushOrders.length === 0 && (
          <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
            Sem encomendas urgentes
          </div>
        )}
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
        {[
          { l: 'OTD', v: `${otd}%`, c: parseFloat(otd) < 95 ? C.rd : C.ac },
          {
            l: 'Decisões',
            v: decs.length,
            s: `${rp.length} replaneáveis`,
            c: decs.length > 0 ? C.yl : C.ac,
          },
          { l: 'Aplicadas', v: moves.length, c: moves.length > 0 ? C.ac : C.t3 },
          { l: 'Bloqueadas', v: blk.length, c: blk.length > 0 ? C.rd : C.ac },
          {
            l: 'Perdidas',
            v: lP > 0 ? `${(lP / 1000).toFixed(0)}K` : '0',
            c: lP > 0 ? C.rd : C.ac,
          },
        ].map((k, i) => (
          <Card key={i}>
            <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
          </Card>
        ))}
      </div>

      <div
        style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 12, alignItems: 'start' }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {moves.length > 0 && (
            <Card style={{ padding: 12, background: C.acS, borderColor: C.ac + '22' }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: C.ac, marginBottom: 4 }}>
                Aplicadas ({moves.length})
              </div>
              {moves.map((mv) => {
                const op = ops.find((o) => o.id === mv.opId);
                return (
                  <div
                    key={mv.opId}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0' }}
                  >
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        color: toolColor(tools, op?.t || ''),
                        fontFamily: 'monospace',
                      }}
                    >
                      {op?.t}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: C.rd,
                        textDecoration: 'line-through',
                        fontFamily: 'monospace',
                      }}
                    >
                      {TM[op?.t || '']?.m}
                    </span>
                    <span style={{ color: C.ac, display: 'inline-flex', alignItems: 'center' }}>
                      <ArrowRight size={12} strokeWidth={1.5} />
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        color: C.ac,
                        fontFamily: 'monospace',
                        fontWeight: 600,
                      }}
                    >
                      {mv.toM}
                    </span>
                    <span style={{ flex: 1, fontSize: 9, color: C.t3 }}>{op?.nm}</span>
                    <Pill color={C.rd} active onClick={() => undoMove(mv.opId)} size="sm">
                      <Undo2 size={9} strokeWidth={1.5} />
                    </Pill>
                  </div>
                );
              })}
            </Card>
          )}

          {decs.length === 0 && moves.length === 0 && (
            <Card style={{ padding: 40, textAlign: 'center' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: C.t3 }}>Sem ações pendentes</div>
              <div style={{ fontSize: 10, color: C.t4, marginTop: 4 }}>
                Marca máquinas/ferramentas DOWN para ativar
              </div>
            </Card>
          )}

          {decs.map((d) => {
            const imp = d.impact as Record<string, unknown> | null;
            const dLoad = imp?.dLoad as
              | Array<{ day: number; current: number; added: number; total: number; util: number }>
              | undefined;
            return (
              <Card key={d.id} style={{ padding: 14, borderLeft: `3px solid ${sC(d.severity)}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <Tag color={sC(d.severity)}>{d.severity}</Tag>
                  <Tag color={d.type === 'replan' ? C.ac : C.rd}>
                    {d.type === 'replan' ? 'REPLAN' : 'BLOQUEADA'}
                  </Tag>
                  <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{d.title}</span>
                </div>
                <div style={{ fontSize: 10, color: C.t3, marginBottom: 6 }}>{d.desc}</div>
                {}

                {d.type === 'replan' && imp && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                    {(
                      [
                        { l: 'De', v: imp.fromM, c: C.rd },
                        { l: 'Para', v: imp.toM, c: C.ac },
                        { l: 'Setup', v: `+${imp.setupMin}m`, c: C.pp },
                        {
                          l: 'Peças',
                          v:
                            (imp.pcs as number) > 999
                              ? `${((imp.pcs as number) / 1000).toFixed(1)}K`
                              : imp.pcs,
                          c: C.t1,
                        },
                        { l: 'Horas', v: `${imp.hrs}h` },
                        {
                          l: 'Pico',
                          v: `${imp.destPeak}%`,
                          c: parseInt(imp.destPeak as string) > 85 ? C.yl : C.ac,
                        },
                      ] as Array<{ l: string; v: unknown; c?: string }>
                    ).map((m, i) => (
                      <div
                        key={i}
                        style={{ background: C.bg, borderRadius: 6, padding: '4px 8px' }}
                      >
                        <div style={{ fontSize: 8, color: C.t4 }}>{m.l}</div>
                        <div
                          style={{
                            fontSize: 11,
                            fontWeight: 600,
                            color: m.c || C.t1,
                            fontFamily: 'monospace',
                          }}
                        >
                          {String(m.v)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {!!imp?.stockRisk && (
                  <div
                    style={{
                      fontSize: 10,
                      color: C.yl,
                      fontWeight: 600,
                      marginBottom: 4,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 3,
                    }}
                  >
                    <AlertTriangle size={10} strokeWidth={1.5} /> STOCK ZERO — OTD em risco
                  </div>
                )}
                {!!imp?.sharedMP && (
                  <div style={{ fontSize: 10, color: C.cy, marginBottom: 4 }}>
                    MP partilhada — oportunidade agrupar
                  </div>
                )}

                {d.type === 'replan' && dLoad && (
                  <div style={{ display: 'flex', gap: 2, marginBottom: 6 }}>
                    {dLoad
                      .filter((dl) => dl.total > 0 || dl.added > 0)
                      .slice(0, 6)
                      .map((dl) => (
                        <div key={dl.day} style={{ flex: 1, textAlign: 'center' }}>
                          <div style={{ fontSize: 8, color: C.t4 }}>{dnames[dl.day]}</div>
                          <div
                            style={{
                              height: 24,
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'flex-end',
                              background: C.bg,
                              borderRadius: 3,
                              overflow: 'hidden',
                            }}
                          >
                            <div
                              style={{
                                height: `${Math.min((dl.current / DAY_CAP) * 100, 100)}%`,
                                background: C.bl + '44',
                                minHeight: dl.current > 0 ? 1 : 0,
                              }}
                            />
                            {dl.added > 0 && (
                              <div
                                style={{
                                  height: `${Math.min((dl.added / DAY_CAP) * 100, 50)}%`,
                                  background: C.ac,
                                  minHeight: 1,
                                }}
                              />
                            )}
                          </div>
                          <div
                            style={{
                              fontSize: 8,
                              color: dl.util > 1 ? C.rd : C.ac,
                              fontWeight: 600,
                            }}
                          >
                            {(dl.util * 100).toFixed(0)}%
                          </div>
                        </div>
                      ))}
                  </div>
                )}

                <div
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                >
                  <button
                    onClick={() => setXai(xai === d.id ? null : d.id)}
                    style={{
                      padding: '3px 10px',
                      borderRadius: 6,
                      border: `1px solid ${C.pp}33`,
                      background: xai === d.id ? C.ppS : 'transparent',
                      color: C.pp,
                      fontSize: 10,
                      fontWeight: 600,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    {xai === d.id ? (
                      <ChevronDown
                        size={10}
                        strokeWidth={1.5}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />
                    ) : (
                      <ChevronRight
                        size={10}
                        strokeWidth={1.5}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />
                    )}{' '}
                    Raciocínio ({d.reasoning.length})
                  </button>
                  {d.type === 'replan' && d.action && (
                    <Pill
                      color={C.ac}
                      active
                      onClick={() => applyMove(d.action!.opId, d.action!.toM)}
                    >
                      <Check
                        size={10}
                        strokeWidth={2}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />{' '}
                      Aplicar{' '}
                      <ArrowRight
                        size={10}
                        strokeWidth={1.5}
                        style={{ display: 'inline', verticalAlign: 'middle' }}
                      />{' '}
                      {d.action.toM}
                    </Pill>
                  )}
                  {d.type === 'blocked' && <Tag color={C.rd}>MANUAL</Tag>}
                </div>
                {xai === d.id && (
                  <div style={{ marginTop: 8, padding: 10, background: C.bg, borderRadius: 6 }}>
                    {d.reasoning.map((r, i) => (
                      <div
                        key={i}
                        style={{
                          display: 'flex',
                          gap: 6,
                          padding: '3px 0',
                          borderBottom: i < d.reasoning.length - 1 ? `1px solid ${C.bd}` : 'none',
                        }}
                      >
                        <span style={{ fontSize: 10, color: C.pp, fontWeight: 600, minWidth: 16 }}>
                          {i + 1}.
                        </span>
                        <span
                          style={{
                            fontSize: 10,
                            color: r.startsWith('→')
                              ? C.ac
                              : r.startsWith('⚠')
                                ? C.yl
                                : r.startsWith('✓')
                                  ? C.ac
                                  : C.t2,
                            lineHeight: 1.5,
                          }}
                        >
                          {r}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            );
          })}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>Impacto Capacidade</div>
          {machines
            .filter((m) => {
              const d = mSt[m.id] === 'down';
              const h = blocks.some(
                (b) => (b.moved && b.machineId === m.id) || (b.moved && b.origM === m.id),
              );
              return d || h;
            })
            .slice(0, 6)
            .map((mc) => {
              const isD = mSt[mc.id] === 'down';
              const mc_c = cap[mc.id];
              return (
                <Card key={mc.id} style={{ padding: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                    <span style={dot(isD ? C.rd : C.ac, isD)} />
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: isD ? C.rd : C.t1,
                        fontFamily: 'monospace',
                      }}
                    >
                      {mc.id}
                    </span>
                    <Tag color={isD ? C.rd : C.ac}>{isD ? 'OFF' : 'ON'}</Tag>
                  </div>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: `repeat(${data.nDays},1fr)`,
                      gap: 2,
                      ...gridDensityVars(data.nDays),
                    }}
                  >
                    {dates.map((_, di) => {
                      const dc = mc_c?.[di] || { prod: 0, setup: 0 };
                      const tot = dc.prod + dc.setup;
                      const u = tot / DAY_CAP;
                      return (
                        <div key={di} style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: 8, color: C.t4 }}>{dnames[di]}</div>
                          <div
                            style={{
                              height: 32,
                              display: 'flex',
                              flexDirection: 'column',
                              justifyContent: 'flex-end',
                              background: C.bg,
                              borderRadius: 3,
                              overflow: 'hidden',
                            }}
                          >
                            {dc.setup > 0 && (
                              <div
                                style={{
                                  height: `${Math.min((dc.setup / DAY_CAP) * 100, 30)}%`,
                                  background: C.pp + '66',
                                  minHeight: 1,
                                }}
                              />
                            )}
                            {dc.prod > 0 && (
                              <div
                                style={{
                                  height: `${Math.min((dc.prod / DAY_CAP) * 100, 100)}%`,
                                  background: isD ? C.rd + '44' : u > 1 ? C.rd + '66' : C.ac + '66',
                                  minHeight: 1,
                                }}
                              />
                            )}
                          </div>
                          {tot > 0 && (
                            <div
                              style={{ fontSize: 8, color: u > 1 ? C.rd : C.ac, fontWeight: 600 }}
                            >
                              {(u * 100).toFixed(0)}%
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </Card>
              );
            })}
          {Object.values(mSt).every((s) => s !== 'down') && moves.length === 0 && (
            <Card style={{ padding: 24, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: C.t4 }}>Marca DOWN para ver impacto</div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// §11. WHAT-IF VIEW — Monte Carlo Optimization
function WhatIfView({
  data,
  onApplyMoves,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
}: {
  data: EngineData;
  onApplyMoves?: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
}) {
  const { machines, tools, ops, dates, dnames, toolMap: TM, focusIds } = data;
  const [sc, setSc] = useState({ t1: 6, p1: 2, t2: 8, p2: 3, seed: 42 });
  const [N, setN] = useState(300);
  const [dispatchRule, setDispatchRule] = useState<DispatchRule>('EDD');
  const [objProfile, setObjProfile] = useState<string>('balanced');
  const [res, setRes] = useState<{
    top3: OptResult[];
    moveable: ReturnType<typeof moveableOps>;
  } | null>(null);
  const [run, setRun] = useState(false);
  const [prog, setProg] = useState(0);
  const [editingDown, setEditingDown] = useState<{ type: 'machine' | 'tool'; id: string } | null>(
    null,
  );
  const wdiWI = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );
  const [wiDownStartDay, setWiDownStartDay] = useState(() => wdiWI[0] ?? 0);
  const [wiDownEndDay, setWiDownEndDay] = useState(() => wdiWI[0] ?? 0);
  const [sel, setSel] = useState(0);
  const [showHistory, setShowHistory] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [diffPair, setDiffPair] = useState<[string, string] | null>(null);
  const versions = usePlanVersionStore((s) => s.versions);
  const currentId = usePlanVersionStore((s) => s.currentId);
  const focusT = tools.filter(
    (t) => focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
  );
  const areaCaps: AreaCaps = { PG1: sc.t1 + sc.p1, PG2: sc.t2 + sc.p2 };
  const avOps = areaCaps.PG1 + areaCaps.PG2;

  const optimize = useCallback(() => {
    setRun(true);
    setProg(0);
    setRes(null);
    setSel(0);
    const bM = Object.fromEntries(
      machines.map((m) => [
        m.id,
        getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
      ]),
    );
    const bT = Object.fromEntries(
      focusT.filter((t) => getResourceDownDays('tool', t.id).size > 0).map((t) => [t.id, 'down']),
    );
    const profile = OBJECTIVE_PROFILES.find((p) => p.id === objProfile);
    const wts = profile ? { ...profile.weights } : null;
    const opt = runOptimization({
      ops,
      mSt: bM,
      tSt: bT,
      machines,
      TM,
      focusIds,
      tools,
      workforceConfig: data.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG,
      weights: wts ? (wts as Partial<ScoreWeights>) : undefined,
      seed: sc.seed,
      workdays: data.workdays,
      nDays: data.nDays,
      rule: dispatchRule,
      N,
      K: 3,
      thirdShift: data.thirdShift ?? useSettingsStore.getState().thirdShiftDefault,
      machineTimelines: replanTimelines?.machineTimelines ?? data.machineTimelines,
      toolTimelines: replanTimelines?.toolTimelines ?? data.toolTimelines,
      twinValidationReport: data.twinValidationReport,
      dates: data.dates,
      orderBased: data.orderBased,
    });
    opt.run(
      (top3) => {
        setRes({ top3, moveable: opt.moveable });
        setRun(false);
      },
      (p) => setProg(p),
    );
  }, [sc, N, machines, ops, TM, focusIds, tools, dispatchRule, objProfile, data, replanTimelines]);

  const rankColor = (i: number) => (i === 0 ? C.ac : i === 1 ? C.bl : C.pp);
  const rankLabel = (i: number) =>
    i === 0 ? '#1 MELHOR' : i === 1 ? '#2' : i === 2 ? '#3' : `#${i + 1}`;
  const selBlocks = res?.top3[sel]?.blocks ?? [];
  const qvWI = useMemo(() => quickValidate(selBlocks, machines, TM), [selBlocks, machines, TM]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card style={{ padding: 16 }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 12,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>Otimização Monte Carlo</div>
          <div style={{ display: 'flex', gap: 4 }}>
            {(() => {
              const n = machines.filter(
                (m) => getResourceDownDays('machine', m.id).size > 0,
              ).length;
              return n > 0 ? <Tag color={C.rd}>{n} máq DOWN</Tag> : null;
            })()}
            {(() => {
              const n = focusT.filter((t) => getResourceDownDays('tool', t.id).size > 0).length;
              return n > 0 ? <Tag color={C.yl}>{n} tool DOWN</Tag> : null;
            })()}
            <Tag color={C.pp}>N={N}</Tag>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 6 }}>
              Máquinas
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
              {focusIds.map((id) => {
                const downDays = getResourceDownDays('machine', id);
                return (
                  <Pill
                    key={id}
                    active={downDays.size > 0}
                    color={C.rd}
                    onClick={() => {
                      setEditingDown(
                        editingDown?.type === 'machine' && editingDown.id === id
                          ? null
                          : { type: 'machine', id },
                      );
                      setRes(null);
                    }}
                    size="sm"
                  >
                    <span style={dot(downDays.size > 0 ? C.rd : C.ac, downDays.size > 0)} />
                    {id}
                    {downDays.size > 0 ? ` ${downDays.size}d` : ''}
                  </Pill>
                );
              })}
            </div>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 6 }}>
              Ferramentas
            </div>
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 3,
                maxHeight: 60,
                overflowY: 'auto',
              }}
            >
              {focusT.map((t) => {
                const tDown = getResourceDownDays('tool', t.id);
                return (
                  <Pill
                    key={t.id}
                    active={tDown.size > 0}
                    color={C.rd}
                    onClick={() => {
                      setEditingDown(
                        editingDown?.type === 'tool' && editingDown.id === t.id
                          ? null
                          : { type: 'tool', id: t.id },
                      );
                      setRes(null);
                    }}
                    size="sm"
                  >
                    {t.id}
                    {tDown.size > 0 ? ` ${tDown.size}d` : ''}
                  </Pill>
                );
              })}
            </div>
            {/* Day range picker for temporal down */}
            {editingDown &&
              (() => {
                const currentDown = getResourceDownDays(editingDown.type, editingDown.id);
                return (
                  <div
                    style={{
                      marginTop: 10,
                      padding: 10,
                      borderRadius: 8,
                      background: 'rgba(255,255,255,0.03)',
                      border: `1px solid ${C.bd}`,
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 8,
                      }}
                    >
                      <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>
                        Período DOWN:{' '}
                        <span style={{ fontFamily: "'JetBrains Mono',monospace", color: C.rd }}>
                          {editingDown.id}
                        </span>
                        <span style={{ fontSize: 9, fontWeight: 400, color: C.t4, marginLeft: 6 }}>
                          ({editingDown.type === 'machine' ? 'máquina' : 'ferramenta'})
                        </span>
                      </span>
                      <button
                        onClick={() => setEditingDown(null)}
                        style={{
                          background: 'none',
                          border: 'none',
                          cursor: 'pointer',
                          color: C.t4,
                          padding: 2,
                        }}
                      >
                        <X size={12} />
                      </button>
                    </div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
                      <span style={{ fontSize: 10, color: C.t3, minWidth: 30 }}>De:</span>
                      <select
                        value={wiDownStartDay}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          setWiDownStartDay(v);
                          if (wiDownEndDay < v) setWiDownEndDay(v);
                        }}
                        style={{
                          padding: '3px 6px',
                          borderRadius: 4,
                          border: `1px solid ${C.bd}`,
                          background: C.bg,
                          color: C.t1,
                          fontSize: 10,
                          fontFamily: 'inherit',
                        }}
                      >
                        {wdiWI.map((i) => (
                          <option key={i} value={i}>
                            {dnames[i]} {dates[i]}
                          </option>
                        ))}
                      </select>
                      <span style={{ fontSize: 10, color: C.t4 }}>até</span>
                      <select
                        value={wiDownEndDay}
                        onChange={(e) => setWiDownEndDay(Number(e.target.value))}
                        style={{
                          padding: '3px 6px',
                          borderRadius: 4,
                          border: `1px solid ${C.bd}`,
                          background: C.bg,
                          color: C.t1,
                          fontSize: 10,
                          fontFamily: 'inherit',
                        }}
                      >
                        {wdiWI
                          .filter((i) => i >= wiDownStartDay)
                          .map((i) => (
                            <option key={i} value={i}>
                              {dnames[i]} {dates[i]}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => {
                          const days: number[] = [];
                          for (let d = wiDownStartDay; d <= wiDownEndDay; d++) days.push(d);
                          setResourceDown(editingDown.type, editingDown.id, days);
                          setRes(null);
                        }}
                        style={{
                          padding: '3px 10px',
                          borderRadius: 4,
                          border: 'none',
                          background: C.rd,
                          color: C.t1,
                          fontSize: 9,
                          fontWeight: 600,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        Aplicar
                      </button>
                    </div>
                    {currentDown.size > 0 && (
                      <div
                        style={{ display: 'flex', gap: 2, marginBottom: 8, alignItems: 'center' }}
                      >
                        <span style={{ fontSize: 9, color: C.t4, minWidth: 30 }}>Dias:</span>
                        {dates.map((_d: string, i: number) => (
                          <div
                            key={i}
                            style={{
                              width: 6,
                              height: 18,
                              borderRadius: 2,
                              background: currentDown.has(i) ? C.rd : `${C.bd}44`,
                            }}
                            title={`${dnames[i]} ${dates[i]}${currentDown.has(i) ? ' — DOWN' : ''}`}
                          />
                        ))}
                        <span style={{ fontSize: 9, color: C.rd, fontWeight: 600, marginLeft: 4 }}>
                          {currentDown.size}d
                        </span>
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        onClick={() => {
                          setResourceDown(
                            editingDown.type,
                            editingDown.id,
                            dates.map((_: string, i: number) => i),
                          );
                          setRes(null);
                        }}
                        style={{
                          padding: '3px 10px',
                          borderRadius: 4,
                          border: `1px solid ${C.rd}44`,
                          background: C.rdS,
                          color: C.rd,
                          fontSize: 9,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                          fontWeight: 600,
                        }}
                      >
                        Tudo DOWN
                      </button>
                      <button
                        onClick={() => {
                          clearResourceDown(editingDown.type, editingDown.id);
                          setRes(null);
                        }}
                        style={{
                          padding: '3px 10px',
                          borderRadius: 4,
                          border: `1px solid ${C.bd}`,
                          background: 'transparent',
                          color: C.t3,
                          fontSize: 9,
                          cursor: 'pointer',
                          fontFamily: 'inherit',
                        }}
                      >
                        Limpar
                      </button>
                    </div>
                  </div>
                );
              })()}
          </div>
          <div>
            <div style={{ fontSize: 10, fontWeight: 600, color: C.t3, marginBottom: 5 }}>
              Operadores
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr 1fr 1fr',
                gap: 6,
                marginBottom: 10,
              }}
            >
              {[
                { l: 'PG1 Eq', k: 't1' as const },
                { l: 'PG1 Pool', k: 'p1' as const },
                { l: 'PG2 Eq', k: 't2' as const },
                { l: 'PG2 Pool', k: 'p2' as const },
              ].map((f) => (
                <div key={f.k}>
                  <div style={{ fontSize: 9, color: C.t4, marginBottom: 2 }}>{f.l}</div>
                  <input
                    type="number"
                    value={sc[f.k]}
                    onChange={(e) => {
                      setSc((p) => ({ ...p, [f.k]: parseInt(e.target.value) || 0 }));
                      setRes(null);
                    }}
                    style={{
                      width: '100%',
                      padding: 5,
                      borderRadius: 6,
                      border: `1px solid ${C.bd}`,
                      background: C.bg,
                      color: C.t1,
                      fontSize: 13,
                      fontFamily: 'monospace',
                      textAlign: 'center',
                    }}
                  />
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Iterações</div>
              {[100, 300, 500, 1000].map((n) => (
                <Pill
                  key={n}
                  active={N === n}
                  color={C.pp}
                  onClick={() => {
                    setN(n);
                    setRes(null);
                  }}
                  size="sm"
                >
                  {n}
                </Pill>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Seed</div>
              <input
                type="number"
                value={sc.seed}
                onChange={(e) => {
                  setSc((p) => ({ ...p, seed: parseInt(e.target.value) || 0 }));
                  setRes(null);
                }}
                style={{
                  width: 80,
                  padding: 4,
                  borderRadius: 6,
                  border: `1px solid ${C.bd}`,
                  background: C.bg,
                  color: C.t1,
                  fontSize: 11,
                  fontFamily: 'monospace',
                  textAlign: 'center',
                }}
              />
              <div style={{ fontSize: 8, color: C.t4 }}>Mesma seed = resultados reprodutiveis</div>
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Heurística</div>
              {(['EDD', 'CR', 'WSPT', 'SPT'] as const).map((r) => (
                <Pill
                  key={r}
                  active={dispatchRule === r}
                  color={C.bl}
                  onClick={() => {
                    setDispatchRule(r);
                    setRes(null);
                  }}
                  size="sm"
                >
                  {r}
                </Pill>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: C.t4 }}>Objectivo</div>
              {OBJECTIVE_PROFILES.map((p) => (
                <Pill
                  key={p.id}
                  active={objProfile === p.id}
                  color={C.ac}
                  onClick={() => {
                    setObjProfile(p.id);
                    setRes(null);
                  }}
                  size="sm"
                >
                  {p.label}
                </Pill>
              ))}
            </div>
            <button
              onClick={optimize}
              disabled={run}
              style={{
                width: '100%',
                padding: 12,
                borderRadius: 8,
                border: 'none',
                cursor: run ? 'wait' : 'pointer',
                background: run ? C.s3 : C.ac,
                color: run ? C.t3 : C.bg,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: 'inherit',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {run && (
                <div
                  style={{
                    position: 'absolute',
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${prog}%`,
                    background: C.w + '15',
                    transition: 'width .1s',
                  }}
                />
              )}
              <span style={{ position: 'relative' }}>
                {run ? `Otimizando ${prog}%` : 'OTIMIZAR — encontrar top 3 planos'}
              </span>
            </button>
          </div>
        </div>
      </Card>

      {!res && !run && (
        <Card style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 15, marginBottom: 6, color: C.ac }}>OPTIMIZE</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t2 }}>
            Otimização de Planeamento
          </div>
          <div
            style={{
              fontSize: 10,
              color: C.t4,
              marginTop: 4,
              maxWidth: 400,
              margin: '4px auto 0',
              lineHeight: 1.6,
            }}
          >
            O motor explora {N} configurações de escalonamento diferentes — redistribuindo operações
            entre máquinas primárias e alternativas — e apresenta os 3 melhores planos otimizados
            por OTD, setups e capacidade.
          </div>
        </Card>
      )}

      {res && (
        <>
          <div style={{ display: 'flex', gap: 6 }}>
            {res.top3.map((s, i) => (
              <button
                key={i}
                onClick={() => setSel(i)}
                style={{
                  flex: 1,
                  padding: 12,
                  borderRadius: 8,
                  cursor: 'pointer',
                  textAlign: 'left',
                  fontFamily: 'inherit',
                  background: sel === i ? C.s3 : C.s2,
                  border: `2px solid ${sel === i ? rankColor(i) : C.bd}`,
                  transition: 'all .15s',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'baseline',
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: rankColor(i) }}>
                    {rankLabel(i)}
                  </span>
                  <span style={{ fontSize: 9, color: C.t4 }}>{s.label}</span>
                </div>
                <div
                  style={{
                    fontSize: 24,
                    fontWeight: 600,
                    color: s.otd < 95 ? C.rd : rankColor(i),
                    fontFamily: 'monospace',
                    lineHeight: 1,
                    marginTop: 4,
                  }}
                >
                  {s.otd.toFixed(1)}%
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: s.otdDelivery < 90 ? C.rd : C.t3,
                    marginTop: 2,
                    fontFamily: 'monospace',
                  }}
                >
                  OTD-D {s.otdDelivery.toFixed(1)}%
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 9, color: C.t3 }}>
                  <span>{s.setupCount} setups</span>
                  <span>{s.moves.length} moves</span>
                  <span style={{ color: C.yl }}>{s.tardinessDays.toFixed(1)}d tard.</span>
                </div>
              </button>
            ))}
          </div>

          {(qvWI.criticalCount > 0 || qvWI.highCount > 0) && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '6px 12px',
                borderRadius: 6,
                background: qvWI.criticalCount > 0 ? C.rdS : `${C.yl}18`,
                borderLeft: `3px solid ${qvWI.criticalCount > 0 ? C.rd : C.yl}`,
              }}
            >
              <AlertTriangle
                size={13}
                style={{ color: qvWI.criticalCount > 0 ? C.rd : C.yl, flexShrink: 0 }}
              />
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: qvWI.criticalCount > 0 ? C.rd : C.yl,
                }}
              >
                {qvWI.criticalCount > 0
                  ? `${qvWI.criticalCount} conflito${qvWI.criticalCount > 1 ? 's' : ''} crítico${qvWI.criticalCount > 1 ? 's' : ''}`
                  : ''}
                {qvWI.criticalCount > 0 && qvWI.highCount > 0 ? ' · ' : ''}
                {qvWI.highCount > 0
                  ? `${qvWI.highCount} alerta${qvWI.highCount > 1 ? 's' : ''}`
                  : ''}
              </span>
              {qvWI.warnings.length > 0 && (
                <span style={{ fontSize: 9, color: C.t3, marginLeft: 'auto' }}>
                  {qvWI.warnings[0]}
                </span>
              )}
            </div>
          )}

          {onApplyMoves && res.top3[sel]?.moves.length > 0 && (
            <button
              onClick={() => {
                const mStNow = Object.fromEntries(
                  machines.map((m) => [
                    m.id,
                    getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
                  ]),
                );
                const tStNow = Object.fromEntries(
                  focusT
                    .filter((t) => getResourceDownDays('tool', t.id).size > 0)
                    .map((t) => [t.id, 'down']),
                );
                onApplyMoves(res.top3[sel].moves, { mSt: mStNow, tSt: tStNow });
              }}
              disabled={isSaving}
              style={{
                width: '100%',
                padding: 12,
                borderRadius: 8,
                border: 'none',
                cursor: isSaving ? 'wait' : 'pointer',
                background: isSaving ? C.s3 : C.ac,
                color: isSaving ? C.t3 : C.bg,
                fontSize: 13,
                fontWeight: 600,
                fontFamily: 'inherit',
                opacity: isSaving ? 0.6 : 1,
              }}
            >
              {isSaving
                ? 'A guardar plano...'
                : `Aplicar Plano Selecionado (${res.top3[sel].moves.length} movimentos)`}
            </button>
          )}

          {/* WS2.3: Save/Commit/History buttons */}
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              onClick={() => {
                const s = res.top3[sel];
                if (!s) return;
                const mStSave = Object.fromEntries(
                  machines.map((m) => [
                    m.id,
                    getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
                  ]),
                );
                const tStSave = Object.fromEntries(
                  focusT
                    .filter((t) => getResourceDownDays('tool', t.id).size > 0)
                    .map((t) => [t.id, 'down']),
                );
                const params: PlanVersionParams = {
                  machineStatus: mStSave,
                  toolStatus: tStSave,
                  areaCaps,
                  moves: s.moves,
                  seed: sc.seed,
                };
                const decs = genDecisions(
                  ops,
                  mStSave,
                  tStSave,
                  s.moves,
                  s.blocks,
                  machines,
                  TM,
                  focusIds,
                  tools,
                );
                const id = usePlanVersionStore.getState().savePlan(s as any, decs, params, s.label);
                useToastStore
                  .getState()
                  .addToast(`Versão guardada: ${s.label} (${id.slice(0, 8)})`, 'success', 4000);
              }}
              style={{
                flex: 1,
                padding: '8px 16px',
                borderRadius: 6,
                border: `1px solid ${C.bd}`,
                cursor: 'pointer',
                background: 'transparent',
                color: C.t1,
                fontSize: 12,
                fontWeight: 500,
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
              }}
            >
              <Save size={14} strokeWidth={1.5} />
              Guardar Versão
            </button>
            {versions.length > 0 && (
              <button
                onClick={() => {
                  const last = versions[versions.length - 1];
                  usePlanVersionStore.getState().commitPlan(last.id);
                  useToastStore
                    .getState()
                    .addToast(`Plano committed: ${last.label}`, 'success', 4000);
                }}
                style={{
                  padding: '8px 16px',
                  borderRadius: 6,
                  border: `1px solid ${C.acM}`,
                  cursor: 'pointer',
                  background: C.acS,
                  color: C.ac,
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: 'inherit',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <GitCommit size={14} strokeWidth={1.5} />
                Commit
              </button>
            )}
            <button
              onClick={() => setShowHistory((h) => !h)}
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                border: `1px solid ${showHistory ? C.acM : C.bd}`,
                cursor: 'pointer',
                background: showHistory ? C.acS : 'transparent',
                color: showHistory ? C.ac : C.t2,
                fontSize: 12,
                fontWeight: 500,
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <History size={14} strokeWidth={1.5} />
              {versions.length}
            </button>
            {versions.length >= 2 && (
              <button
                onClick={() => {
                  setShowCompare((c) => !c);
                  setShowHistory(false);
                }}
                style={{
                  padding: '8px 12px',
                  borderRadius: 6,
                  border: `1px solid ${showCompare ? C.blS : C.bd}`,
                  cursor: 'pointer',
                  background: showCompare ? C.blS : 'transparent',
                  color: showCompare ? C.bl : C.t2,
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: 'inherit',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                }}
              >
                <GitCompareArrows size={14} strokeWidth={1.5} />
                Comparar
              </button>
            )}
          </div>

          {/* WS2.3: Version History Panel */}
          {showHistory && versions.length > 0 && (
            <Card style={{ padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
                Histórico de Versões <Tag color={C.pp}>{versions.length}</Tag>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0, paddingLeft: 12 }}>
                {[...versions].reverse().map((v, i) => {
                  const isCurrent = v.id === currentId;
                  const isFirst = i === versions.length - 1;
                  return (
                    <div
                      key={v.id}
                      style={{ position: 'relative', paddingLeft: 20, paddingBottom: 16 }}
                    >
                      {/* Timeline connector */}
                      {i < versions.length - 1 && (
                        <div
                          style={{
                            position: 'absolute',
                            left: 3,
                            top: 10,
                            bottom: 0,
                            width: 1,
                            background: 'rgba(255,255,255,0.06)',
                          }}
                        />
                      )}
                      {/* Timeline dot */}
                      <div
                        style={{
                          position: 'absolute',
                          left: 0,
                          top: 2,
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          background: isCurrent ? C.ac : isFirst ? C.t4 : C.t3,
                        }}
                      />
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <button
                            onClick={() =>
                              usePlanVersionStore.getState().setFavorite(v.id, !v.isFavorite)
                            }
                            style={{
                              background: 'none',
                              border: 'none',
                              cursor: 'pointer',
                              padding: 0,
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            <Star
                              size={12}
                              strokeWidth={1.5}
                              fill={v.isFavorite ? C.yl : 'none'}
                              style={{ color: v.isFavorite ? C.yl : C.t4 }}
                            />
                          </button>
                          <span style={{ fontSize: 13, fontWeight: 500, color: C.t1 }}>
                            {v.label}
                          </span>
                          {v.branchLabel && (
                            <span
                              style={{
                                fontSize: 9,
                                fontWeight: 600,
                                color: C.pp,
                                background: C.ppS,
                                padding: '1px 6px',
                                borderRadius: 3,
                              }}
                            >
                              {v.branchLabel}
                            </span>
                          )}
                          {isCurrent && (
                            <span
                              style={{
                                padding: '2px 8px',
                                borderRadius: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                background: C.acS,
                                color: C.ac,
                                textTransform: 'uppercase',
                                letterSpacing: '0.04em',
                              }}
                            >
                              COMMITTED
                            </span>
                          )}
                        </div>
                        <span style={{ fontSize: 11, color: C.t3, fontFamily: 'var(--font-mono)' }}>
                          {v.id.slice(0, 8)}
                        </span>
                      </div>
                      <div style={{ fontSize: 11, color: C.t3, marginTop: 2 }}>
                        {new Date(v.timestamp).toLocaleTimeString('pt-PT', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                        {' · '}OTD {v.kpis.otd.toFixed(1)}% · OTD-D {v.kpis.otdDelivery.toFixed(1)}%
                        · {v.kpis.setupCount} setups · tard {v.kpis.tardinessDays.toFixed(1)}d
                      </div>
                      <div style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
                        {!isCurrent && (
                          <button
                            onClick={() => usePlanVersionStore.getState().commitPlan(v.id)}
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              border: `1px solid ${C.bd}`,
                              cursor: 'pointer',
                              background: 'transparent',
                              color: C.t2,
                              fontSize: 10,
                              fontFamily: 'inherit',
                            }}
                          >
                            Commit
                          </button>
                        )}
                        {i < versions.length - 1 && (
                          <button
                            onClick={() => {
                              const prev = [...versions].reverse()[i + 1];
                              if (prev) setDiffPair([prev.id, v.id]);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: 4,
                              border: `1px solid ${C.bd}`,
                              cursor: 'pointer',
                              background: 'transparent',
                              color: C.t2,
                              fontSize: 10,
                              fontFamily: 'inherit',
                            }}
                          >
                            Diff
                          </button>
                        )}
                        <input
                          placeholder="branch..."
                          defaultValue={v.branchLabel ?? ''}
                          onBlur={(e) =>
                            usePlanVersionStore
                              .getState()
                              .setBranchLabel(v.id, e.target.value.trim())
                          }
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                          }}
                          style={{
                            marginLeft: 'auto',
                            width: 80,
                            padding: '2px 6px',
                            borderRadius: 4,
                            border: `1px solid ${C.bd}`,
                            background: 'transparent',
                            color: C.t3,
                            fontSize: 9,
                            fontFamily: 'inherit',
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
              {/* Diff display */}
              {diffPair &&
                (() => {
                  const vA = usePlanVersionStore.getState().getVersion(diffPair[0]);
                  const vB = usePlanVersionStore.getState().getVersion(diffPair[1]);
                  if (!vA || !vB) return null;
                  const diff = computePlanDiff(vA, vB);
                  return (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 12,
                        background: C.bg,
                        borderRadius: 6,
                        border: `1px solid ${C.bd}`,
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          marginBottom: 8,
                        }}
                      >
                        <span style={{ fontSize: 11, fontWeight: 600, color: C.t1 }}>
                          {vA.label} → {vB.label}
                        </span>
                        <button
                          onClick={() => setDiffPair(null)}
                          style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            color: C.t3,
                            padding: 2,
                          }}
                        >
                          <X size={12} strokeWidth={1.5} />
                        </button>
                      </div>
                      <div style={{ fontSize: 11, color: C.t2, marginBottom: 8 }}>
                        {diff.summary}
                      </div>
                      <div
                        style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}
                      >
                        {[
                          {
                            l: 'OTD',
                            v: `${diff.kpiDelta.otd > 0 ? '+' : ''}${diff.kpiDelta.otd.toFixed(1)}%`,
                            c: diff.kpiDelta.otd >= 0 ? C.ac : C.rd,
                          },
                          {
                            l: 'Setups',
                            v: `${diff.kpiDelta.setupCount > 0 ? '+' : ''}${diff.kpiDelta.setupCount}`,
                            c: diff.kpiDelta.setupCount <= 0 ? C.ac : C.rd,
                          },
                          {
                            l: 'Tardiness',
                            v: `${diff.kpiDelta.tardinessDays > 0 ? '+' : ''}${diff.kpiDelta.tardinessDays.toFixed(1)}d`,
                            c: diff.kpiDelta.tardinessDays <= 0 ? C.ac : C.rd,
                          },
                        ].map((k, i) => (
                          <div key={i} style={{ textAlign: 'center' }}>
                            <div style={{ fontSize: 9, color: C.t4 }}>{k.l}</div>
                            <div
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                color: k.c,
                                fontFamily: 'monospace',
                              }}
                            >
                              {k.v}
                            </div>
                          </div>
                        ))}
                      </div>
                      {diff.moved.length > 0 && (
                        <div style={{ marginTop: 8, fontSize: 10, color: C.t3 }}>
                          {diff.moved.length} ops movidas · Churn: {diff.churn.toFixed(0)} min
                        </div>
                      )}
                    </div>
                  );
                })()}
            </Card>
          )}

          {showCompare && <PlanComparePanel data={data} />}

          {(() => {
            const s = res.top3[sel];
            if (!s) return null;
            const rc = rankColor(sel);
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
                  {[
                    {
                      l: 'OTD Produção',
                      v: `${s.otd.toFixed(1)}%`,
                      s: 'qty produzida',
                      c: s.otd < 95 ? C.rd : rc,
                    },
                    {
                      l: 'OTD Entrega',
                      v: `${s.otdDelivery.toFixed(1)}%`,
                      s: 'cumprimento datas',
                      c: s.otdDelivery < 90 ? C.rd : s.otdDelivery < 95 ? C.yl : rc,
                    },
                    {
                      l: 'Produção',
                      v: `${(s.produced / 1000).toFixed(0)}K`,
                      s: `de ${(s.totalDemand / 1000).toFixed(0)}K`,
                      c: rc,
                    },
                    {
                      l: 'Setups',
                      v: s.setupCount,
                      s: `T.X ${s.setupByShift.X} / T.Y ${s.setupByShift.Y}${s.setupByShift.Z ? ` / T.Z ${s.setupByShift.Z}` : ''}`,
                      c: s.setupCount > 20 ? C.yl : rc,
                    },
                    {
                      l: 'Tardiness',
                      v: `${s.tardinessDays.toFixed(1)}d`,
                      s: 'atraso acumulado',
                      c: s.tardinessDays > 0 ? C.rd : rc,
                    },
                  ].map((k, i) => (
                    <Card key={i}>
                      <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
                    </Card>
                  ))}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 10 }}>
                  <Card style={{ padding: 14 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                      Movimentos <Tag color={rc}>{s.moves.length}</Tag>
                    </div>
                    {s.moves.length === 0 ? (
                      <div style={{ fontSize: 10, color: C.t4, padding: 12, textAlign: 'center' }}>
                        Sem movimentos — plano original
                      </div>
                    ) : (
                      s.moves.map((mv, i) => {
                        const op = ops.find((o) => o.id === mv.opId);
                        return (
                          <div
                            key={i}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                              padding: '5px 0',
                              borderBottom: i < s.moves.length - 1 ? `1px solid ${C.bd}` : 'none',
                            }}
                          >
                            <span
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                color: toolColor(tools, op?.t || ''),
                                fontFamily: 'monospace',
                                minWidth: 52,
                              }}
                            >
                              {op?.t}
                            </span>
                            <span
                              style={{
                                fontSize: 10,
                                color: C.rd,
                                fontFamily: 'monospace',
                                textDecoration: 'line-through',
                              }}
                            >
                              {op?.m}
                            </span>
                            <span
                              style={{
                                color: rc,
                                fontWeight: 600,
                                display: 'inline-flex',
                                alignItems: 'center',
                              }}
                            >
                              <ArrowRight size={12} strokeWidth={1.5} />
                            </span>
                            <span
                              style={{
                                fontSize: 10,
                                color: rc,
                                fontFamily: 'monospace',
                                fontWeight: 600,
                              }}
                            >
                              {mv.toM}
                            </span>
                            <span
                              style={{
                                flex: 1,
                                fontSize: 9,
                                color: C.t3,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {op?.nm}
                            </span>
                          </div>
                        );
                      })
                    )}
                    {res.moveable.length > 0 && (
                      <div
                        style={{
                          fontSize: 9,
                          color: C.t4,
                          marginTop: 6,
                          padding: '6px 0',
                          borderTop: `1px solid ${C.bd}`,
                        }}
                      >
                        {res.moveable.length} operações movíveis ·{' '}
                        {
                          res.moveable.filter((m) => s.moves.find((mv) => mv.opId === m.opId))
                            .length
                        }{' '}
                        movidas
                      </div>
                    )}
                  </Card>

                  <Card style={{ padding: 14, overflow: 'auto' }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                      Capacidade por Máquina
                    </div>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: `80px repeat(${data.nDays},1fr)`,
                        gap: 3,
                        ...gridDensityVars(data.nDays),
                      }}
                    >
                      <div />
                      {dates.map((_d, i) => (
                        <div key={i} style={{ textAlign: 'center', fontSize: 9, color: C.t4 }}>
                          {dnames[i]}
                        </div>
                      ))}
                      {machines
                        .filter((mc) => {
                          const cm = s.capByMachine[mc.id];
                          return cm && cm.days.some((d) => d.prod > 0 || d.setup > 0);
                        })
                        .map((mc) => {
                          const isD = getResourceDownDays('machine', mc.id).size > 0;
                          return (
                            <React.Fragment key={mc.id}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                                <span style={dot(isD ? C.rd : C.ac, isD)} />
                                <span
                                  style={{
                                    fontSize: 10,
                                    fontWeight: 600,
                                    color: isD ? C.rd : C.t1,
                                    fontFamily: 'monospace',
                                  }}
                                >
                                  {mc.id}
                                </span>
                              </div>
                              {s.capByMachine[mc.id].days.map((d, di) => {
                                const u = d.util;
                                const hCap = isD
                                  ? C.rdS
                                  : u === 0
                                    ? 'transparent'
                                    : u < 0.6
                                      ? rc + '18'
                                      : u < 0.85
                                        ? rc + '30'
                                        : u < 1
                                          ? C.yl + '35'
                                          : C.rd + '35';
                                return (
                                  <div
                                    key={di}
                                    style={{
                                      background: hCap,
                                      borderRadius: 4,
                                      padding: '3px 2px',
                                      textAlign: 'center',
                                      minHeight: 36,
                                    }}
                                  >
                                    {d.prod + d.setup > 0 ? (
                                      <>
                                        <div
                                          style={{
                                            fontSize: 11,
                                            fontWeight: 600,
                                            color: C.t1,
                                            fontFamily: 'monospace',
                                          }}
                                        >
                                          {(u * 100).toFixed(0)}%
                                        </div>
                                        <div style={{ fontSize: 8, color: C.t4 }}>
                                          {d.pcs > 0 ? `${(d.pcs / 1000).toFixed(0)}K` : ''}
                                        </div>
                                      </>
                                    ) : (
                                      <div style={{ fontSize: 10, color: C.t4 }}>—</div>
                                    )}
                                  </div>
                                );
                              })}
                            </React.Fragment>
                          );
                        })}
                    </div>
                  </Card>
                </div>

                <Card style={{ padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                    Operadores / Dia
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    {opsByDayFromWorkforce(s.workforceDemand, data.nDays).map((d, i) => (
                      <div key={i} style={{ flex: 1, textAlign: 'center' }}>
                        <div style={{ fontSize: 9, color: C.t4, marginBottom: 4 }}>
                          {dnames[i]} {dates[i]}
                        </div>
                        <div
                          style={{
                            height: 50,
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'flex-end',
                            gap: 1,
                          }}
                        >
                          {d.pg1 > 0 && (
                            <div
                              style={{
                                height: `${Math.min((d.pg1 / avOps) * 50, 48)}px`,
                                background: C.ac + '55',
                                borderRadius: '3px 3px 0 0',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}
                            >
                              <span style={{ fontSize: 8, color: C.ac, fontWeight: 600 }}>
                                {d.pg1}
                              </span>
                            </div>
                          )}
                          {d.pg2 > 0 && (
                            <div
                              style={{
                                height: `${Math.min((d.pg2 / avOps) * 50, 48)}px`,
                                background: C.bl + '55',
                                borderRadius: '0 0 3px 3px',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                              }}
                            >
                              <span style={{ fontSize: 8, color: C.bl, fontWeight: 600 }}>
                                {d.pg2}
                              </span>
                            </div>
                          )}
                        </div>
                        <div
                          style={{
                            fontSize: 10,
                            fontWeight: 600,
                            color: d.total > avOps ? C.rd : rc,
                            marginTop: 2,
                          }}
                        >
                          {d.total}
                        </div>
                        {d.total > avOps && (
                          <div style={{ fontSize: 8, color: C.rd }}>+{d.total - avOps}</div>
                        )}
                      </div>
                    ))}
                  </div>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'center',
                      gap: 12,
                      marginTop: 6,
                      fontSize: 9,
                      color: C.t3,
                    }}
                  >
                    <span>
                      <span
                        style={{
                          display: 'inline-block',
                          width: 8,
                          height: 8,
                          borderRadius: 2,
                          background: C.ac + '55',
                          marginRight: 3,
                        }}
                      />
                      PG1
                    </span>
                    <span>
                      <span
                        style={{
                          display: 'inline-block',
                          width: 8,
                          height: 8,
                          borderRadius: 2,
                          background: C.bl + '55',
                          marginRight: 3,
                        }}
                      />
                      PG2
                    </span>
                    <span>Disponíveis: {avOps}</span>
                  </div>
                </Card>

                <Card style={{ padding: 14 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                    Comparação Cenários
                  </div>
                  <div
                    style={{ display: 'grid', gridTemplateColumns: '120px repeat(3,1fr)', gap: 3 }}
                  >
                    <div />
                    {res.top3.map((_, i) => (
                      <div key={i} style={{ textAlign: 'center', padding: 4 }}>
                        <span style={{ fontSize: 10, fontWeight: 600, color: rankColor(i) }}>
                          {rankLabel(i)}
                        </span>
                      </div>
                    ))}
                    {[
                      {
                        l: 'OTD Produção',
                        f: (s2: OptResult) => `${s2.otd.toFixed(1)}%`,
                        best: (s2: OptResult) => s2.otd,
                      },
                      {
                        l: 'OTD Entrega',
                        f: (s2: OptResult) => `${s2.otdDelivery.toFixed(1)}%`,
                        best: (s2: OptResult) => s2.otdDelivery,
                      },
                      {
                        l: 'Produção',
                        f: (s2: OptResult) => `${(s2.produced / 1000).toFixed(0)}K`,
                        best: (s2: OptResult) => s2.produced,
                      },
                      {
                        l: 'Peças Perdidas',
                        f: (s2: OptResult) =>
                          s2.lostPcs > 0 ? `${(s2.lostPcs / 1000).toFixed(1)}K` : '0',
                        best: (s2: OptResult) => -s2.lostPcs,
                      },
                      {
                        l: 'Setups',
                        f: (s2: OptResult) => s2.setupCount,
                        best: (s2: OptResult) => -s2.setupCount,
                      },
                      {
                        l: 'Setup Time',
                        f: (s2: OptResult) => `${Math.round(s2.setupMin)}min`,
                        best: (s2: OptResult) => -s2.setupMin,
                      },
                      {
                        l: 'Movimentos',
                        f: (s2: OptResult) => s2.moves.length,
                        best: (s2: OptResult) => -s2.moves.length,
                      },
                      {
                        l: 'Pico Operadores',
                        f: (s2: OptResult) => s2.peakOps,
                        best: (s2: OptResult) => -s2.peakOps,
                      },
                      {
                        l: 'Over Capacity',
                        f: (s2: OptResult) => s2.overflows,
                        best: (s2: OptResult) => -s2.overflows,
                      },
                      {
                        l: 'Score',
                        f: (s2: OptResult) => s2.score.toFixed(1),
                        best: (s2: OptResult) => s2.score,
                      },
                    ].map((row, ri) => (
                      <React.Fragment key={ri}>
                        <div
                          style={{ fontSize: 10, color: C.t3, padding: '4px 0', fontWeight: 500 }}
                        >
                          {row.l}
                        </div>
                        {res.top3.map((s2, ci) => {
                          const isBest = res.top3.every((s3) => row.best(s2) >= row.best(s3));
                          return (
                            <div
                              key={ci}
                              style={{
                                textAlign: 'center',
                                fontSize: 11,
                                fontWeight: isBest ? 800 : 500,
                                color: isBest ? rankColor(ci) : C.t2,
                                fontFamily: 'monospace',
                                padding: '4px 0',
                                background: ci === sel ? C.s3 : 'transparent',
                                borderRadius: 4,
                              }}
                            >
                              {String(row.f(s2))}
                            </div>
                          );
                        })}
                      </React.Fragment>
                    ))}
                  </div>
                </Card>
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}

// §11b. PLAN COMPARE PANEL — side-by-side version comparison
function PlanComparePanel({ data }: { data: EngineData }) {
  const versions = usePlanVersionStore((s) => s.versions);
  const [idA, setIdA] = useState<string | null>(null);
  const [idB, setIdB] = useState<string | null>(null);

  const diff = useMemo(() => {
    if (!idA || !idB || idA === idB) return null;
    const vA = usePlanVersionStore.getState().getVersion(idA);
    const vB = usePlanVersionStore.getState().getVersion(idB);
    if (!vA || !vB) return null;
    return { a: vA, b: vB, diff: computePlanDiff(vA, vB) };
  }, [idA, idB]);

  // Compute per-machine capacity delta
  const capDelta = useMemo(() => {
    if (!diff) return null;
    const { a, b } = diff;
    const loadMap = (blocks: typeof a.blocks) => {
      const m: Record<string, number[]> = {};
      for (const blk of blocks) {
        if (blk.type !== 'ok') continue;
        if (!m[blk.machineId]) m[blk.machineId] = Array(data.nDays).fill(0);
        let dur = blk.endMin - blk.startMin;
        if (blk.setupS != null && blk.setupE != null) dur += blk.setupE - blk.setupS;
        m[blk.machineId][blk.dayIdx] += dur;
      }
      return m;
    };
    const la = loadMap(a.blocks),
      lb = loadMap(b.blocks);
    const allM = new Set([...Object.keys(la), ...Object.keys(lb)]);
    const result: Array<{ mid: string; days: Array<{ a: number; b: number; delta: number }> }> = [];
    for (const mid of [...allM].sort()) {
      const days: Array<{ a: number; b: number; delta: number }> = [];
      for (let d = 0; d < data.nDays; d++) {
        const va = ((la[mid]?.[d] ?? 0) / DAY_CAP) * 100;
        const vb = ((lb[mid]?.[d] ?? 0) / DAY_CAP) * 100;
        days.push({ a: Math.round(va), b: Math.round(vb), delta: Math.round(vb - va) });
      }
      result.push({ mid, days });
    }
    return result;
  }, [diff, data.nDays]);

  if (versions.length < 2) {
    return (
      <Card style={{ padding: 24, textAlign: 'center' }}>
        <div style={{ fontSize: 11, color: C.t4 }}>
          Guarde pelo menos 2 versões para comparar planos.
        </div>
      </Card>
    );
  }

  const vSel = (val: string | null, onChange: (v: string | null) => void, label: string) => (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 9, color: C.t4, marginBottom: 4 }}>{label}</div>
      <select
        value={val ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        style={{
          width: '100%',
          padding: 6,
          borderRadius: 6,
          border: `1px solid ${C.bd}`,
          background: C.bg,
          color: C.t1,
          fontSize: 11,
          fontFamily: 'inherit',
        }}
      >
        <option value="">Selecionar...</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {v.label} ({v.id.slice(0, 6)})
          </option>
        ))}
      </select>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Card style={{ padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 10 }}>
          Comparar Planos
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          {vSel(idA, setIdA, 'Versão A (base)')}
          <ArrowRight size={16} style={{ color: C.t4, flexShrink: 0, marginBottom: 6 }} />
          {vSel(idB, setIdB, 'Versão B (nova)')}
        </div>
      </Card>

      {diff && (
        <>
          {/* KPI Delta Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 6 }}>
            {[
              {
                l: 'OTD Prod',
                v: diff.diff.kpiDelta.otd,
                fmt: (n: number) => `${n > 0 ? '+' : ''}${n.toFixed(1)}%`,
                good: (n: number) => n >= 0,
              },
              {
                l: 'OTD Entrega',
                v: diff.diff.kpiDelta.otdDelivery,
                fmt: (n: number) => `${n > 0 ? '+' : ''}${n.toFixed(1)}%`,
                good: (n: number) => n >= 0,
              },
              {
                l: 'Setups',
                v: diff.diff.kpiDelta.setupCount,
                fmt: (n: number) => `${n > 0 ? '+' : ''}${n}`,
                good: (n: number) => n <= 0,
              },
              {
                l: 'Setup Min',
                v: diff.diff.kpiDelta.setupMin,
                fmt: (n: number) => `${n > 0 ? '+' : ''}${Math.round(n)}`,
                good: (n: number) => n <= 0,
              },
              {
                l: 'Tardiness',
                v: diff.diff.kpiDelta.tardinessDays,
                fmt: (n: number) => `${n > 0 ? '+' : ''}${n.toFixed(1)}d`,
                good: (n: number) => n <= 0,
              },
              {
                l: 'Cap. Util',
                v: diff.diff.kpiDelta.capUtil,
                fmt: (n: number) => `${n > 0 ? '+' : ''}${(n * 100).toFixed(0)}%`,
                good: (n: number) => n >= 0,
              },
            ].map((k, i) => (
              <Card key={i} style={{ textAlign: 'center', padding: 10 }}>
                <div style={{ fontSize: 9, color: C.t4, marginBottom: 2 }}>{k.l}</div>
                <div
                  style={{
                    fontSize: 16,
                    fontWeight: 700,
                    color: k.v === 0 ? C.t3 : k.good(k.v) ? C.ac : C.rd,
                    fontFamily: 'monospace',
                  }}
                >
                  {k.fmt(k.v)}
                </div>
              </Card>
            ))}
          </div>

          {/* Summary */}
          <div style={{ fontSize: 11, color: C.t2, padding: '4px 8px' }}>
            {diff.diff.summary} · Churn: {diff.diff.churn.toFixed(0)} min
          </div>

          {/* Movements Table */}
          {diff.diff.moved.length > 0 && (
            <Card style={{ padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                Operações Movidas <Tag color={C.bl}>{diff.diff.moved.length}</Tag>
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '80px 70px 20px 70px 50px',
                  gap: 4,
                  alignItems: 'center',
                }}
              >
                <div style={{ fontSize: 9, color: C.t4, fontWeight: 600 }}>Op</div>
                <div style={{ fontSize: 9, color: C.t4, fontWeight: 600 }}>De</div>
                <div />
                <div style={{ fontSize: 9, color: C.t4, fontWeight: 600 }}>Para</div>
                <div style={{ fontSize: 9, color: C.t4, fontWeight: 600 }}>Dia</div>
                {diff.diff.moved.map((mv, i) => (
                  <React.Fragment key={i}>
                    <div style={{ fontSize: 10, fontFamily: 'monospace', color: C.t1 }}>
                      {mv.opId.slice(0, 10)}
                    </div>
                    <div style={{ fontSize: 10, fontFamily: 'monospace', color: C.rd }}>
                      {mv.fromM}
                    </div>
                    <ArrowRight size={10} style={{ color: C.t4 }} />
                    <div
                      style={{
                        fontSize: 10,
                        fontFamily: 'monospace',
                        color: C.ac,
                        fontWeight: 600,
                      }}
                    >
                      {mv.toM}
                    </div>
                    <div style={{ fontSize: 10, fontFamily: 'monospace', color: C.t3 }}>
                      {mv.fromDay !== mv.toDay ? `${mv.fromDay}→${mv.toDay}` : `d${mv.toDay}`}
                    </div>
                  </React.Fragment>
                ))}
              </div>
            </Card>
          )}

          {/* Capacity Delta Heatmap */}
          {capDelta && capDelta.length > 0 && (
            <Card style={{ padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
                Delta Capacidade por Máquina
              </div>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: `60px repeat(${data.nDays},1fr)`,
                  gap: 3,
                  ...gridDensityVars(data.nDays),
                }}
              >
                <div />
                {data.dates.map((_d, i) => (
                  <div key={i} style={{ textAlign: 'center', fontSize: 9, color: C.t4 }}>
                    {data.dnames[i]}
                  </div>
                ))}
                {capDelta.map((row) => (
                  <React.Fragment key={row.mid}>
                    <div
                      style={{
                        fontSize: 10,
                        fontWeight: 600,
                        color: C.t1,
                        fontFamily: 'monospace',
                        display: 'flex',
                        alignItems: 'center',
                      }}
                    >
                      {row.mid}
                    </div>
                    {row.days.map((d, di) => {
                      const bg =
                        d.delta === 0
                          ? 'transparent'
                          : d.delta > 0
                            ? `${C.rd}${Math.min(Math.round((Math.abs(d.delta) / 30) * 255), 200)
                                .toString(16)
                                .padStart(2, '0')}`
                            : `${C.ac}${Math.min(Math.round((Math.abs(d.delta) / 30) * 255), 200)
                                .toString(16)
                                .padStart(2, '0')}`;
                      return (
                        <div
                          key={di}
                          style={{
                            background: bg,
                            borderRadius: 4,
                            padding: '4px 2px',
                            textAlign: 'center',
                          }}
                        >
                          <div
                            style={{
                              fontSize: 10,
                              fontWeight: 600,
                              color: d.delta === 0 ? C.t4 : d.delta > 0 ? C.rd : C.ac,
                              fontFamily: 'monospace',
                            }}
                          >
                            {d.delta > 0 ? '+' : ''}
                            {d.delta}%
                          </div>
                          <div style={{ fontSize: 8, color: C.t4 }}>
                            {d.a}→{d.b}
                          </div>
                        </div>
                      );
                    })}
                  </React.Fragment>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

// §12. MAIN COMPONENT — API-wired
export default function NikufraEngine() {
  const ds = useDataSource();

  // ── Data from API ──
  const [engineData, setEngineData] = useState<EngineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Schedule Filters (machine/tool status, failure events, temporal down) ──
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

  // ── Core State ──
  const [moves, setMoves] = useState<MoveAction[]>([]);
  const [view, setView] = useState('plan');
  const [isSaving, setIsSaving] = useState(false);
  // ── Rush Order state (lifted from ReplanView for scheduling integration) ──
  const [rushOrders, setRushOrders] = useState<
    Array<{ toolId: string; sku: string; qty: number; deadline: number }>
  >([]);
  // WS3: Stateful batch — track ISOP changes
  const [isopBanner, setIsopBanner] = useState<string | null>(null);
  const prevOpsRef = useRef<EOp[] | null>(null);

  // ── Load data from API ──
  const loadData = useCallback(async () => {
    if (!ds.getPlanState) {
      setError('Planning engine not available in this data source');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const planState = await ds.getPlanState();
      const tcfg = getTransformConfig();
      const data = transformPlanState(planState, {
        moStrategy: tcfg.moStrategy,
        moNominalPG1: tcfg.moNominalPG1,
        moNominalPG2: tcfg.moNominalPG2,
        moCustomPG1: tcfg.moCustomPG1,
        moCustomPG2: tcfg.moCustomPG2,
        demandSemantics: tcfg.demandSemantics,
      });
      setEngineData(data);
      // Initialize machine/tool status via schedule filters
      filterActions.resetFilters(data.machines);
      setMoves([]);

      // Snapshot change detection (simplified — DemandDelta/SnapshotHash modules removed)
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

  // (machine/tool status, timelines, down days — managed by useScheduleFilters)

  const applyMove = useCallback(
    (opId: string, toM: string) =>
      setMoves((p) => (p.find((m) => m.opId === opId) ? p : [...p, { opId, toM }])),
    [],
  );
  const undoMove = useCallback(
    (opId: string) => setMoves((p) => p.filter((m) => m.opId !== opId)),
    [],
  );

  // ── Apply & Save ──
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
        // API mode: save to backend then reload
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
        // Mock mode: apply locally — triggers reactive scheduling pipeline
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

  // ── Legacy Replan Store — auto-refresh on apply ──
  useEffect(() => {
    useReplanStore.getState().onApplyCallback = loadData;
    return () => {
      useReplanStore.getState().onApplyCallback = null;
    };
  }, [loadData]);

  // ── Rush order → EOp conversion ──
  const rushOps = useMemo((): EOp[] => {
    if (!engineData || rushOrders.length === 0) return [];
    return rushOrders
      .map((ro, idx): EOp | null => {
        const tool = engineData.toolMap[ro.toolId];
        if (!tool) return null;
        const d = Array(engineData.nDays).fill(0) as number[];
        d[ro.deadline] = -ro.qty; // NP negativo = encomenda de |qty| pcs
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

  // ── Scheduling (client-side) ──
  // Auto-route overflow to alternatives for maximum efficiency (bdmestre §10)
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
    // Skip expensive Tier 3+4 during interactive replan (machine DOWN, moves, etc.)
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
    const wfc = engineData.workforceConfig ?? DEFAULT_WORKFORCE_CONFIG;
    return scoreSchedule(
      blocks,
      allOps,
      engineData.mSt,
      wfc,
      engineData.machines,
      engineData.toolMap,
      undefined,
      undefined,
      engineData.nDays,
    );
  }, [blocks, allOps, engineData]);

  const validation = useMemo(() => {
    if (!engineData) return null;
    return validateSchedule(
      blocks,
      engineData.machines,
      engineData.toolMap,
      allOps,
      engineData.thirdShift,
    );
  }, [blocks, engineData, allOps]);

  const audit = useMemo(() => {
    if (!engineData) return null;
    return auditCoverage(blocks, allOps, engineData.toolMap, engineData.twinGroups);
  }, [blocks, allOps, engineData]);

  // Derive feasibility summary from blocks
  const feasibility = useMemo(() => {
    if (!blocks.length || !engineData) return null;
    const okOps = new Set<string>();
    const infOps = new Set<string>();
    for (const b of blocks) {
      if (b.type === 'ok' && b.qty > 0) okOps.add(b.opId);
      if (b.type === 'infeasible' || b.type === 'blocked') infOps.add(b.opId);
    }
    // Ops that have at least one ok block are considered feasible
    for (const id of okOps) infOps.delete(id);
    const total = okOps.size + infOps.size;
    return {
      totalOps: total,
      feasibleOps: okOps.size,
      infeasibleOps: infOps.size,
      score: total > 0 ? okOps.size / total : 1,
      deadlineFeasible: infOps.size === 0,
    };
  }, [blocks, engineData]);

  // ── Quick Auto-Replan for PlanView ──
  const handlePlanAutoReplan = useCallback((): AutoReplanSummary | null => {
    if (!engineData) return null;
    try {
      const settings = useSettingsStore.getState();
      const rule = (settings.dispatchRule || 'EDD') as DispatchRule;
      const input = {
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
      };
      const result = autoReplan(input, DEFAULT_AUTO_REPLAN_CONFIG);
      const actions = getReplanActions(result);
      return {
        actions,
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

  // ── Loading state ──
  if (loading) {
    return (
      <div className="ne-shell ne-loading">
        <div className="ne-loading__spinner" />
        <div className="ne-loading__text">A carregar planning engine...</div>
      </div>
    );
  }

  // ── Error state ──
  if (error || !engineData) {
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
  }

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
                    opacity: 1,
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
                    opacity: 1,
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
        {/* WS3.2: ISOP change banner */}
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

// Named exports for testing and external use — re-exported from lib/engine
export { OBJECTIVE_PROFILES };

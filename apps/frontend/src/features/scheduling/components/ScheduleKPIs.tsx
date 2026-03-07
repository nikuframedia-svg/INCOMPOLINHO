import { ArrowRight, Check, ChevronDown, ChevronRight, Zap } from 'lucide-react';
import React, { useCallback, useMemo, useState } from 'react';
import type {
  AlternativeAction,
  Block,
  CoverageAuditResult,
  DayLoad,
  DecisionEntry,
  EngineData,
  EOp,
  ReplanActionDetail,
} from '../../../lib/engine';
import { C, DAY_CAP, T1 } from '../../../lib/engine';
import { gridDensityVars } from '../../../utils/gridDensity';
import type { FeasibilitySummary } from '../hooks/useScheduleValidation';
import { Card, dot, Metric, toolColor } from './atoms';

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

interface AutoReplanSummary {
  actions: ReplanActionDetail[];
  moveCount: number;
  unresolvedCount: number;
}

export default function PlanView({
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

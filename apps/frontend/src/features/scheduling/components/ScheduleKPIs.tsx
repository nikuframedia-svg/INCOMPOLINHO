import React, { useCallback, useMemo, useState } from 'react';
import type {
  Block,
  CoverageAuditResult,
  DayLoad,
  DecisionEntry,
  EngineData,
} from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { useClassifications } from '../../../hooks/useClassifications';
import type { FeasibilitySummary } from '../hooks/useScheduleValidation';
import { Card } from './atoms';
import { DecisionAudit } from './DecisionAudit';
import type { AutoReplanSummary } from './decision-constants';
import { CoverageBar, FeasibilityScore, KPISummaryCards } from './KPISummaryCards';
import { CapacityGrid, QuickReplan, TopBacklogs, VolumeChart } from './PlanGrids';

// §9. PLAN VIEW

export function PlanView({
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
  const { machines, tools, ops, dates, dnames } = data;

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

  // Working day indices
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );

  const bQty = (b: Block) =>
    b.isTwinProduction && b.outputs ? b.outputs.reduce((s, o) => s + o.qty, 0) : b.qty;
  const prodByDay = wdi.map((i) =>
    blocks.filter((b) => b.dayIdx === i && b.type !== 'blocked').reduce((a, b) => a + bQty(b), 0),
  );
  const maxPd = Math.max(...prodByDay, 1);
  const hC = (u: number) =>
    u === 0
      ? 'transparent'
      : u < 0.3
        ? `${C.ac}15`
        : u < 0.6
          ? `${C.ac}25`
          : u < 0.85
            ? `${C.yl}25`
            : u < 1
              ? `${C.yl}40`
              : `${C.rd}35`;

  const { definitionCounts } = useClassifications();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <KPISummaryCards
        blocks={blocks}
        data={data}
        audit={audit}
        definitionCounts={definitionCounts}
      />

      {audit && (
        <AuditBanner
          audit={audit}
          showDetail={showAuditDetail}
          onToggle={() => setShowAuditDetail(!showAuditDetail)}
        />
      )}
      {audit && !audit.isComplete && showAuditDetail && <AuditDetailTable audit={audit} />}

      {(feasibility || audit) && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: feasibility && audit ? '1fr 1.5fr' : '1fr',
            gap: 10,
          }}
        >
          {feasibility && <FeasibilityScore feasibility={feasibility} />}
          {audit && <CoverageBar audit={audit} />}
        </div>
      )}

      {onRunAutoReplan && (
        <QuickReplan
          arRunning={arRunning}
          arSummary={arSummary}
          onRun={handleQuickReplan}
          onSwitchToReplan={onSwitchToReplan}
        />
      )}

      <DecisionAudit decisions={decisions} data={data} />

      <CapacityGrid
        machines={machines}
        wdi={wdi}
        cap={cap}
        mSt={mSt}
        dnames={dnames}
        dates={dates}
        hC={hC}
      />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 10 }}>
        <VolumeChart prodByDay={prodByDay} maxPd={maxPd} dates={dates} wdi={wdi} />
        <TopBacklogs ops={ops} tools={tools} />
      </div>
    </div>
  );
}

/* ── Private sub-components ── */

function AuditBanner({
  audit,
  showDetail,
  onToggle,
}: {
  audit: CoverageAuditResult;
  showDetail: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      style={{
        padding: '10px 14px',
        borderRadius: 8,
        background: audit.isComplete ? C.acS : C.rdS,
        border: `1px solid ${audit.isComplete ? `${C.ac}33` : `${C.rd}33`}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: audit.isComplete ? C.ac : C.rd }}>
          {audit.isComplete ? 'Tudo coberto' : `Cobertura ${audit.globalCoveragePct.toFixed(1)}%`}
        </span>
        <span style={{ fontSize: 12, color: audit.isComplete ? C.ac : C.t2 }}>
          {audit.isComplete
            ? `${audit.rows.length} operações — ${audit.rows.filter((r) => r.totalDemand > 0).length} com procura — todas cobertas`
            : `${audit.rows.length} operações — ${audit.totalDemand.toLocaleString()} peças necessárias — ${audit.totalProduced.toLocaleString()} produzidas — ${(audit.totalDemand - audit.totalProduced).toLocaleString()} em falta`}
        </span>
        {!audit.isComplete && (
          <span style={{ fontSize: 12, color: C.rd, fontWeight: 600 }}>
            {audit.zeroCovered > 0 ? `${audit.zeroCovered} sem produção` : ''}
            {audit.zeroCovered > 0 && audit.partiallyCovered > 0 ? ' · ' : ''}
            {audit.partiallyCovered > 0 ? `${audit.partiallyCovered} parciais` : ''}
          </span>
        )}
      </div>
      {!audit.isComplete && (
        <button
          onClick={onToggle}
          style={{
            padding: '4px 10px',
            borderRadius: 6,
            border: `1px solid ${C.rd}33`,
            background: 'transparent',
            color: C.rd,
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {showDetail ? 'Esconder' : 'Ver detalhe'}
        </button>
      )}
    </div>
  );
}

function AuditDetailTable({ audit }: { audit: CoverageAuditResult }) {
  return (
    <Card style={{ padding: 14, maxHeight: 320, overflow: 'auto' }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Operações com cobertura incompleta (
        {audit.rows.filter((r) => r.coveragePct < 100 && r.totalDemand > 0).length})
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '60px 80px 70px 60px 80px 80px 50px 90px',
          gap: '2px 6px',
          fontSize: 12,
        }}
      >
        {['Op', 'SKU', 'Tool', 'Máq.', 'Demand', 'Produzido', '%', 'Razão'].map((h) => (
          <div
            key={h}
            style={{
              fontWeight: 600,
              color: C.t3,
              textAlign: ['Demand', 'Produzido', '%'].includes(h) ? 'right' : undefined,
            }}
          >
            {h}
          </div>
        ))}
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
  );
}

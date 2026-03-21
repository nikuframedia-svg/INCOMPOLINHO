import { useMemo } from 'react';
import type { Block, CoverageAuditResult, EngineData } from '../../../lib/engine';
import { C, T1 } from '../../../lib/engine';
import { formatCoverage, formatSetupTime } from '../../../utils/explicitText';
import type { FeasibilitySummary } from '../hooks/useScheduleValidation';
import { Card, Metric } from './atoms';

/** Twin-aware qty: sum outputs[] for co-production, b.qty for regular */
const bQty = (b: Block) =>
  b.isTwinProduction && b.outputs ? b.outputs.reduce((s, o) => s + o.qty, 0) : b.qty;

export function KPISummaryCards({
  blocks,
  data,
  audit,
  definitionCounts,
}: {
  blocks: Block[];
  data: EngineData;
  audit: CoverageAuditResult | null;
  definitionCounts?: Record<string, number>;
}) {
  const wdi = useMemo(
    () =>
      data.workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [data.workdays],
  );

  const ok = blocks.filter((b) => b.type !== 'blocked');
  const tPcs = ok.reduce((a, b) => a + bQty(b), 0);
  const tProd = ok.reduce((a, b) => a + (b.endMin - b.startMin), 0);
  const tSetup = ok
    .filter((b) => b.setupS != null)
    .reduce((a, b) => a + ((b.setupE || 0) - (b.setupS || 0)), 0);
  const blkN = new Set(blocks.filter((b) => b.type === 'blocked').map((b) => b.opId)).size;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${definitionCounts ? 7 : 6},1fr)`, gap: 8 }}>
      {[
        (() => {
          if (!audit) return { l: 'Cobertura', v: '—', s: '', c: C.ac };
          const cov = formatCoverage(audit.globalCoveragePct, audit.totalDemand, audit.totalProduced);
          const c = cov.semantic === 'good' ? C.ac : cov.semantic === 'warning' ? C.yl : C.rd;
          return { l: 'Cobertura', v: cov.formatted, s: cov.context, c };
        })(),
        {
          l: 'Total de Peças',
          v: `${(tPcs / 1000).toFixed(0)}K`,
          s: `${wdi.length} dias uteis · ${ok.length} blocos`,
          c: C.ac,
        },
        {
          l: 'Tempo de Produção',
          v: `${(tProd / 60).toFixed(0)}h`,
          s: `${Math.round(tProd)}min`,
          c: C.ac,
        },
        (() => {
          const nSetups = ok.filter((b) => b.setupS != null).length;
          const se = formatSetupTime(tSetup, nSetups);
          const c = se.semantic === 'good' ? C.ac : C.yl;
          return { l: 'Setups', v: se.formatted, s: se.context, c };
        })(),
        {
          l: 'Equilíbrio',
          v: (() => {
            const sX = ok.filter((b) => b.setupS != null && b.setupS < T1).length;
            const sY = ok.filter((b) => b.setupS != null && b.setupS >= T1).length;
            return `${sX}/${sY}`;
          })(),
          s: (() => {
            const sX = ok.filter((b) => b.setupS != null && b.setupS < T1).length;
            const sY = ok.filter((b) => b.setupS != null && b.setupS >= T1).length;
            const balanced = Math.abs(sX - sY) <= 3;
            return balanced ? 'Turnos equilibrados' : 'Turnos desequilibrados';
          })(),
          c: (() => {
            const sX = ok.filter((b) => b.setupS != null && b.setupS < T1).length;
            const sY = ok.filter((b) => b.setupS != null && b.setupS >= T1).length;
            return Math.abs(sX - sY) <= 3 ? C.ac : C.yl;
          })(),
        },
        {
          l: 'Bloqueadas',
          v: blkN,
          s: blkN > 0
            ? `${blkN} operação${blkN > 1 ? 'ões' : ''} sem máquina viável — intervenção necessária`
            : 'Todas as operações com máquina atribuída',
          c: blkN > 0 ? C.rd : C.ac,
        },
        ...(definitionCounts
          ? [
              {
                l: 'Atrasados',
                v: definitionCounts.atrasado ?? 0,
                s: (definitionCounts.urgente ?? 0) > 0
                  ? `${definitionCounts.urgente} urgentes`
                  : 'Nenhuma operação urgente',
                c: (definitionCounts.atrasado ?? 0) > 0 ? C.rd : C.ac,
              },
            ]
          : []),
      ].map((k, i) => (
        <Card key={i}>
          <Metric label={k.l} value={k.v} sub={k.s} color={k.c} />
        </Card>
      ))}
    </div>
  );
}

export function CoverageBar({ audit }: { audit: CoverageAuditResult }) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Detalhe da Cobertura
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
            <span style={{ fontSize: 12, color: C.t1, fontWeight: 600 }}>{audit.fullyCovered}</span>
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
            <span style={{ fontSize: 12, color: C.bg, fontWeight: 600 }}>
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
            <span style={{ fontSize: 12, color: C.t1, fontWeight: 600 }}>{audit.zeroCovered}</span>
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 12, fontSize: 12, color: C.t3 }}>
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
      <div style={{ marginTop: 8, fontSize: 12, color: C.t2, fontFamily: 'monospace' }}>
        {formatCoverage(audit.globalCoveragePct, audit.totalDemand, audit.totalProduced).context}
      </div>
    </Card>
  );
}

export function FeasibilityScore({ feasibility }: { feasibility: FeasibilitySummary }) {
  return (
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
              color: feasibility.score >= 0.95 ? C.ac : feasibility.score >= 0.8 ? C.yl : C.rd,
            }}
          >
            {(feasibility.score * 100).toFixed(0)}%
          </span>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>Viabilidade do Plano</div>
          <div style={{ fontSize: 12, color: C.t3 }}>
            {feasibility.feasibleOps} de {feasibility.totalOps} operações viáveis
          </div>
          {feasibility.infeasibleOps > 0 && (
            <div style={{ fontSize: 12, color: C.rd, fontWeight: 500 }}>
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
            fontSize: 12,
            color: C.rd,
            fontWeight: 500,
          }}
        >
          Prazos em risco — operações incompletas
        </div>
      )}
    </Card>
  );
}

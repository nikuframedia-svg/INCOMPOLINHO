import { ArrowRight } from 'lucide-react';
import React from 'react';
import type { EngineData, EOp, ETool, OptResult } from '../../../../lib/engine';
import { C, opsByDayFromWorkforce } from '../../../../lib/engine';
import { Card, Metric, Tag, toolColor } from '../atoms';
import { CapacityGrid, OperatorsChart } from './CapacityViews';

export function ScenarioDetails({
  scenario,
  sel,
  rankColor,
  ops,
  tools,
  data,
  getResourceDownDays,
  moveable,
  top3,
}: {
  scenario: OptResult;
  sel: number;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
  ops: EOp[];
  tools: ETool[];
  data: EngineData;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  moveable: Array<{ opId: string }>;
  top3: OptResult[];
}) {
  const rc = rankColor(sel);
  const s = scenario;
  const { machines, dates, dnames, nDays } = data;
  const opsPerDay = opsByDayFromWorkforce(s.workforceDemand, nDays);
  const avOps = Math.round(opsPerDay.reduce((a, d) => a + d.total, 0) / nDays || 10);
  const rankLabel = (i: number) =>
    i === 0 ? '#1 MELHOR' : i === 1 ? '#2' : i === 2 ? '#3' : `#${i + 1}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <KPIRow scenario={s} rc={rc} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 10 }}>
        <MovesCard scenario={s} rc={rc} ops={ops} tools={tools} moveable={moveable} />
        <CapacityGrid
          scenario={s}
          machines={machines}
          dates={dates}
          dnames={dnames}
          nDays={nDays}
          rc={rc}
          getResourceDownDays={getResourceDownDays}
        />
      </div>
      <OperatorsChart
        scenario={s}
        dnames={dnames}
        dates={dates}
        nDays={nDays}
        rc={rc}
        avOps={avOps}
      />
      <ComparisonTable top3={top3} sel={sel} rankColor={rankColor} rankLabel={rankLabel} />
    </div>
  );
}

function KPIRow({ scenario: s, rc }: { scenario: OptResult; rc: string }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 8 }}>
      {[
        {
          l: 'OTD-D',
          v: `${s.otdDelivery.toFixed(1)}%`,
          s: 'cumprimento datas',
          c: s.otdDelivery < 90 ? C.rd : s.otdDelivery < 95 ? C.yl : rc,
        },
        {
          l: 'OTD Produção',
          v: `${s.otd.toFixed(1)}%`,
          s: 'qty produzida',
          c: s.otd < 95 ? C.rd : rc,
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
  );
}

function MovesCard({
  scenario: s,
  rc,
  ops,
  tools,
  moveable,
}: {
  scenario: OptResult;
  rc: string;
  ops: EOp[];
  tools: ETool[];
  moveable: Array<{ opId: string }>;
}) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Movimentos <Tag color={rc}>{s.moves.length}</Tag>
      </div>
      {s.moves.length === 0 ? (
        <div style={{ fontSize: 12, color: C.t4, padding: 12, textAlign: 'center' }}>
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
                  fontSize: 12,
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
                  fontSize: 12,
                  color: C.rd,
                  fontFamily: 'monospace',
                  textDecoration: 'line-through',
                }}
              >
                {op?.m}
              </span>
              <span
                style={{ color: rc, fontWeight: 600, display: 'inline-flex', alignItems: 'center' }}
              >
                <ArrowRight size={12} strokeWidth={1.5} />
              </span>
              <span style={{ fontSize: 12, color: rc, fontFamily: 'monospace', fontWeight: 600 }}>
                {mv.toM}
              </span>
              <span
                style={{
                  flex: 1,
                  fontSize: 12,
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
      {moveable.length > 0 && (
        <div
          style={{
            fontSize: 12,
            color: C.t4,
            marginTop: 6,
            padding: '6px 0',
            borderTop: `1px solid ${C.bd}`,
          }}
        >
          {moveable.length} operações movíveis ·{' '}
          {moveable.filter((m) => s.moves.find((mv) => mv.opId === m.opId)).length} movidas
        </div>
      )}
    </Card>
  );
}

function ComparisonTable({
  top3,
  sel,
  rankColor,
  rankLabel,
}: {
  top3: OptResult[];
  sel: number;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
}) {
  const rows = [
    {
      l: 'OTD-D',
      f: (s2: OptResult) => `${s2.otdDelivery.toFixed(1)}%`,
      best: (s2: OptResult) => s2.otdDelivery,
    },
    {
      l: 'OTD Produção',
      f: (s2: OptResult) => `${s2.otd.toFixed(1)}%`,
      best: (s2: OptResult) => s2.otd,
    },
    {
      l: 'Produção',
      f: (s2: OptResult) => `${(s2.produced / 1000).toFixed(0)}K`,
      best: (s2: OptResult) => s2.produced,
    },
    {
      l: 'Peças Perdidas',
      f: (s2: OptResult) => (s2.lostPcs > 0 ? `${(s2.lostPcs / 1000).toFixed(1)}K` : '0'),
      best: (s2: OptResult) => -s2.lostPcs,
    },
    { l: 'Setups', f: (s2: OptResult) => s2.setupCount, best: (s2: OptResult) => -s2.setupCount },
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
    { l: 'Score', f: (s2: OptResult) => s2.score.toFixed(1), best: (s2: OptResult) => s2.score },
  ];

  return (
    <Card style={{ padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Comparação Cenários
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '120px repeat(3,1fr)', gap: 3 }}>
        <div />
        {top3.map((_, i) => (
          <div key={i} style={{ textAlign: 'center', padding: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: rankColor(i) }}>
              {rankLabel(i)}
            </span>
          </div>
        ))}
        {rows.map((row, ri) => (
          <React.Fragment key={ri}>
            <div style={{ fontSize: 12, color: C.t3, padding: '4px 0', fontWeight: 500 }}>
              {row.l}
            </div>
            {top3.map((s2, ci) => {
              const isBest = top3.every((s3) => row.best(s2) >= row.best(s3));
              return (
                <div
                  key={ci}
                  style={{
                    textAlign: 'center',
                    fontSize: 12,
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
  );
}

/**
 * DecisionCard — Single replan/blocked decision card with XAI reasoning toggle.
 */
import { AlertTriangle, ArrowRight, Check, ChevronDown, ChevronRight } from 'lucide-react';
import { C, DAY_CAP } from '../../../../lib/engine';
import { Card, Pill, Tag } from '../atoms';
import type { ReplanProposal } from './types';

export interface DecisionCardProps {
  d: ReplanProposal;
  dnames: string[];
  xai: string | null;
  setXai: (id: string | null) => void;
  applyMove: (opId: string, toM: string) => void;
  sC: (s: string) => string;
}

export function DecisionCard({ d, dnames, xai, setXai, applyMove, sC }: DecisionCardProps) {
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
      <div style={{ fontSize: 12, color: C.t3, marginBottom: 6 }}>{d.desc}</div>

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
            <div key={i} style={{ background: C.bg, borderRadius: 6, padding: '4px 8px' }}>
              <div style={{ fontSize: 12, color: C.t4 }}>{m.l}</div>
              <div
                style={{
                  fontSize: 12,
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
            fontSize: 12,
            color: C.yl,
            fontWeight: 600,
            marginBottom: 4,
            display: 'flex',
            alignItems: 'center',
            gap: 3,
          }}
        >
          <AlertTriangle size={10} strokeWidth={1.5} /> STOCK ZERO — OTD-D em risco
        </div>
      )}
      {!!imp?.sharedMP && (
        <div style={{ fontSize: 12, color: C.cy, marginBottom: 4 }}>
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
                <div style={{ fontSize: 12, color: C.t4 }}>{dnames[dl.day]}</div>
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
                    fontSize: 12,
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

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <button
          onClick={() => setXai(xai === d.id ? null : d.id)}
          style={{
            padding: '3px 10px',
            borderRadius: 6,
            border: `1px solid ${C.pp}33`,
            background: xai === d.id ? C.ppS : 'transparent',
            color: C.pp,
            fontSize: 12,
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
          <Pill color={C.ac} active onClick={() => applyMove(d.action!.opId, d.action!.toM)}>
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
              <span style={{ fontSize: 12, color: C.pp, fontWeight: 600, minWidth: 16 }}>
                {i + 1}.
              </span>
              <span
                style={{
                  fontSize: 12,
                  color: r.startsWith('\u2192')
                    ? C.ac
                    : r.startsWith('\u26A0')
                      ? C.yl
                      : r.startsWith('\u2713')
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
}

import { ArrowRight } from 'lucide-react';
import React, { useMemo, useState } from 'react';
import type { EngineData } from '../../../lib/engine';
import { C, DAY_CAP } from '../../../lib/engine';
import { usePlanVersionStore } from '../../../stores/usePlanVersionStore';
import { gridDensityVars } from '../../../utils/gridDensity';
import { computePlanDiff } from '../../../utils/planDiff';
import { Card, Tag } from './atoms';

export function PlanComparePanel({ data }: { data: EngineData }) {
  const versions = usePlanVersionStore((s) => s.versions);
  const [idA, setIdA] = useState<string | null>(null);
  const [idB, setIdB] = useState<string | null>(null);

  const diff = useMemo(() => {
    if (!idA || !idB || idA === idB) return null;
    const vA = usePlanVersionStore.getState().actions.getVersion(idA);
    const vB = usePlanVersionStore.getState().actions.getVersion(idB);
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

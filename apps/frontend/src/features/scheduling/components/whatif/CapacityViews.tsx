import React from 'react';
import type { EngineData, OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { opsByDayFromWorkforce } from '@/utils/workforce';
import { gridDensityVars } from '../../../../utils/gridDensity';
import { Card, dot } from '../atoms';

export function CapacityGrid({
  scenario: s,
  machines,
  dates,
  dnames,
  nDays,
  rc,
  getResourceDownDays,
}: {
  scenario: OptResult;
  machines: EngineData['machines'];
  dates: string[];
  dnames: string[];
  nDays: number;
  rc: string;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
}) {
  return (
    <Card style={{ padding: 14, overflow: 'auto' }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Capacidade por Máquina
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `80px repeat(${nDays},1fr)`,
          gap: 3,
          ...gridDensityVars(nDays),
        }}
      >
        <div />
        {dates.map((_d, i) => (
          <div key={i} style={{ textAlign: 'center', fontSize: 12, color: C.t4 }}>
            {dnames[i]}
          </div>
        ))}
        {machines
          .filter((mc) => {
            const cm = s.capByMachine[mc.id];
            return cm?.days.some((d) => d.prod > 0 || d.setup > 0);
          })
          .map((mc) => {
            const isD = getResourceDownDays('machine', mc.id).size > 0;
            return (
              <React.Fragment key={mc.id}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
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
                </div>
                {s.capByMachine[mc.id].days.map((d, di) => {
                  const u = d.util;
                  const hCap = isD
                    ? C.rdS
                    : u === 0
                      ? 'transparent'
                      : u < 0.6
                        ? `${rc}18`
                        : u < 0.85
                          ? `${rc}30`
                          : u < 1
                            ? `${C.yl}35`
                            : `${C.rd}35`;
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
                              fontSize: 12,
                              fontWeight: 600,
                              color: C.t1,
                              fontFamily: 'monospace',
                            }}
                          >
                            {(u * 100).toFixed(0)}%
                          </div>
                          <div style={{ fontSize: 12, color: C.t4 }}>
                            {d.pcs > 0 ? `${(d.pcs / 1000).toFixed(0)}K` : ''}
                          </div>
                        </>
                      ) : (
                        <div style={{ fontSize: 12, color: C.t4 }}>—</div>
                      )}
                    </div>
                  );
                })}
              </React.Fragment>
            );
          })}
      </div>
    </Card>
  );
}

export function OperatorsChart({
  scenario: s,
  dnames,
  dates,
  nDays,
  rc,
  avOps,
}: {
  scenario: OptResult;
  dnames: string[];
  dates: string[];
  nDays: number;
  rc: string;
  avOps: number;
}) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Operadores / Dia
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {opsByDayFromWorkforce(s.workforceDemand, nDays).map((d, i) => (
          <div key={i} style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: C.t4, marginBottom: 4 }}>
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
                    background: `${C.ac}55`,
                    borderRadius: '3px 3px 0 0',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <span style={{ fontSize: 12, color: C.ac, fontWeight: 600 }}>{d.pg1}</span>
                </div>
              )}
              {d.pg2 > 0 && (
                <div
                  style={{
                    height: `${Math.min((d.pg2 / avOps) * 50, 48)}px`,
                    background: `${C.bl}55`,
                    borderRadius: '0 0 3px 3px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <span style={{ fontSize: 12, color: C.bl, fontWeight: 600 }}>{d.pg2}</span>
                </div>
              )}
            </div>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: d.total > avOps ? C.rd : rc,
                marginTop: 2,
              }}
            >
              {d.total}
            </div>
            {d.total > avOps && <div style={{ fontSize: 12, color: C.rd }}>+{d.total - avOps}</div>}
          </div>
        ))}
      </div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          gap: 12,
          marginTop: 6,
          fontSize: 12,
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
              background: `${C.ac}55`,
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
              background: `${C.bl}55`,
              marginRight: 3,
            }}
          />
          PG2
        </span>
        <span>Disponíveis: {avOps}</span>
      </div>
    </Card>
  );
}

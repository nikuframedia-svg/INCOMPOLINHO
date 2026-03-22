import React, { useMemo, useState } from 'react';
import { C } from '@/theme/color-bridge';
import type { IntelData } from '../../compute';
import { HeatLegend, StatRow } from '../intel-atoms';
import { fmtDate, fmtMin, fmtPct, heatColor, MC, mono } from '../intel-helpers';

export function HeatmapView({ data }: { data: IntelData }) {
  const { heatmap, machines, workingDates } = data;
  const [hover, setHover] = useState<{ mi: number; di: number } | null>(null);

  const CW = 36,
    CH = 34;
  const LW = 72,
    TH = 34;
  const W = LW + workingDates.length * CW;
  const H = TH + machines.length * CH;

  const flat = useMemo(() => heatmap.flat(), [heatmap]);
  const totalOverflow = flat.filter((c) => c.pct > 100).length;
  const peakCell = flat.reduce((mx, c) => (c.pct > mx.pct ? c : mx), flat[0]);
  const avgUtil = flat.reduce((s, c) => s + c.pct, 0) / (flat.length || 1);

  return (
    <div>
      <StatRow
        items={[
          { label: 'Avg Utilization', value: fmtPct(avgUtil), color: avgUtil > 80 ? C.yl : C.ac },
          { label: 'Overflow Cells', value: totalOverflow, color: totalOverflow > 0 ? C.rd : C.ac },
          { label: 'Peak Load', value: fmtPct(peakCell?.pct || 0), color: C.rd },
          {
            label: 'Peak Machine',
            value: peakCell?.machine || '-',
            color: MC[peakCell?.machine] || C.t1,
          },
        ]}
      />
      <HeatLegend />
      <div style={{ overflowX: 'auto', paddingBottom: 8 }}>
        <svg width={W} height={H} style={{ display: 'block' }}>
          {/* Date headers */}
          {workingDates.map((d, di) => {
            const dt = new Date(d);
            const dayLetter = ['D', 'S', 'T', 'Q', 'Q', 'S', 'S'][dt.getDay()];
            return (
              <React.Fragment key={d}>
                <text
                  x={LW + di * CW + CW / 2}
                  y={13}
                  textAnchor="middle"
                  style={{ fill: C.t3, fontSize: 12, ...mono }}
                >
                  {fmtDate(d)}
                </text>
                <text
                  x={LW + di * CW + CW / 2}
                  y={25}
                  textAnchor="middle"
                  style={{ fill: C.t4, fontSize: 12 }}
                >
                  {dayLetter}
                </text>
              </React.Fragment>
            );
          })}
          {/* Machine rows */}
          {machines.map((m, mi) => (
            <g key={m}>
              <text
                x={LW - 8}
                y={TH + mi * CH + CH / 2 + 4}
                textAnchor="end"
                style={{ fill: MC[m], fontSize: 12, ...mono, fontWeight: 600 }}
              >
                {m}
              </text>
              {heatmap[mi]?.map((cell, di) => {
                const isH = hover?.mi === mi && hover?.di === di;
                return (
                  <g
                    key={di}
                    onMouseEnter={() => setHover({ mi, di })}
                    onMouseLeave={() => setHover(null)}
                    style={{ cursor: 'pointer' }}
                  >
                    <rect
                      x={LW + di * CW + 1}
                      y={TH + mi * CH + 1}
                      width={CW - 2}
                      height={CH - 2}
                      rx={4}
                      fill={heatColor(cell.pct)}
                      opacity={cell.loadMin > 0 ? 1 : 0.15}
                      stroke={isH ? C.w : 'none'}
                      strokeWidth={isH ? 1.5 : 0}
                    />
                    {cell.pct >= 1 && (
                      <text
                        x={LW + di * CW + CW / 2}
                        y={TH + mi * CH + CH / 2 + 4}
                        textAnchor="middle"
                        style={{
                          fill: cell.pct > 60 ? C.w : C.t2,
                          fontSize: 12,
                          ...mono,
                          fontWeight: 600,
                          pointerEvents: 'none' as const,
                        }}
                      >
                        {fmtPct(cell.pct)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          ))}
          {/* Hover tooltip */}
          {hover &&
            (() => {
              const cell = heatmap[hover.mi]?.[hover.di];
              if (!cell) return null;
              const tx = Math.min(LW + hover.di * CW + CW / 2, W - 80);
              const ty = TH + hover.mi * CH - 6;
              return (
                <g>
                  <rect
                    x={tx - 68}
                    y={ty - 38}
                    width={136}
                    height={34}
                    rx={6}
                    fill={C.s1}
                    stroke={C.bd}
                    strokeWidth={1}
                  />
                  <text
                    x={tx}
                    y={ty - 22}
                    textAnchor="middle"
                    style={{ fill: C.t1, fontSize: 12, ...mono }}
                  >
                    {cell.machine} {fmtDate(cell.date)}: {fmtMin(cell.loadMin)}
                  </text>
                  <text x={tx} y={ty - 10} textAnchor="middle" style={{ fill: C.t3, fontSize: 12 }}>
                    {fmtPct(cell.pct)} load, {cell.skuCount} SKU{cell.skuCount !== 1 ? 's' : ''}
                  </text>
                </g>
              );
            })()}
        </svg>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
//  VIEW 2: CAPACITY HORIZON — 35-day stacked bars
// ══════════════════════════════════════════════════════════════

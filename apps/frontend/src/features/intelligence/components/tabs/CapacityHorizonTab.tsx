import React, { useState } from 'react';
import { C, DAY_CAP } from '../../../../lib/engine';
import type { IntelData } from '../../intel-compute';
import { MachineLegend, StatRow } from '../intel-atoms';
import { fmtDate, fmtMin, MC, mono } from '../intel-helpers';

export function HorizonView({ data }: { data: IntelData }) {
  const { horizon, machines } = data;
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const colW = 26;
  const PAD = { l: 48, r: 12, t: 24, b: 42 };
  const maxH = 240;
  const W = PAD.l + horizon.length * colW + PAD.r;
  const H = PAD.t + maxH + PAD.b;

  const maxTotal = Math.max(DAY_CAP, ...horizon.map((b) => b.total));
  const scale = (v: number) => Math.max(0, (v / maxTotal) * maxH);
  const capY = PAD.t + maxH - scale(DAY_CAP);

  // Y-axis ticks
  const yTicks = [
    0,
    Math.round(DAY_CAP * 0.25),
    Math.round(DAY_CAP * 0.5),
    Math.round(DAY_CAP * 0.75),
    DAY_CAP,
  ].filter((v) => v <= maxTotal * 1.1);

  return (
    <div>
      <StatRow
        items={[
          { label: 'Total Days', value: horizon.length },
          { label: 'Working Days', value: data.workingDates.length, color: C.ac },
          {
            label: 'Peak Day Load',
            value: fmtMin(Math.max(...horizon.map((b) => b.total))),
            color: C.yl,
          },
          { label: 'Capacity/Day', value: `${DAY_CAP}m (07h–24h)`, color: C.t2 },
        ]}
      />
      <MachineLegend machines={machines} />
      <div style={{ overflowX: 'auto', paddingBottom: 8 }}>
        <svg width={W} height={H} style={{ display: 'block' }}>
          {/* Y-axis labels */}
          {yTicks.map((v) => {
            const y = PAD.t + maxH - scale(v);
            return (
              <React.Fragment key={v}>
                <text
                  x={PAD.l - 6}
                  y={y + 3}
                  textAnchor="end"
                  style={{ fill: C.t4, fontSize: 8, ...mono }}
                >
                  {fmtMin(v)}
                </text>
                <line
                  x1={PAD.l}
                  y1={y}
                  x2={W - PAD.r}
                  y2={y}
                  stroke={C.bd}
                  strokeWidth={0.5}
                  strokeDasharray={v === DAY_CAP ? '0' : '3,3'}
                />
              </React.Fragment>
            );
          })}
          {/* Capacity line at 990 min */}
          <line
            x1={PAD.l}
            y1={capY}
            x2={W - PAD.r}
            y2={capY}
            stroke={C.rd}
            strokeWidth={1.5}
            strokeDasharray="6,3"
            opacity={0.7}
          />
          <text x={W - PAD.r + 4} y={capY + 3} style={{ fill: C.rd, fontSize: 8, ...mono }}>
            CAP
          </text>
          {/* Bars */}
          {horizon.map((bar, i) => {
            const x = PAD.l + i * colW;
            const isH = hoverIdx === i;
            let cumH = 0;
            return (
              <g
                key={bar.date}
                onMouseEnter={() => setHoverIdx(i)}
                onMouseLeave={() => setHoverIdx(null)}
                style={{ cursor: 'pointer' }}
              >
                {/* Background for non-working */}
                {!bar.isWorking && (
                  <rect
                    x={x}
                    y={PAD.t}
                    width={colW - 2}
                    height={maxH}
                    fill={C.s3}
                    opacity={0.3}
                    rx={2}
                  />
                )}
                {/* Stacked machine bars */}
                {machines.map((m) => {
                  const min = bar.machines[m] || 0;
                  const h = scale(min);
                  cumH += h;
                  return h > 0.5 ? (
                    <rect
                      key={m}
                      x={x + 1}
                      y={PAD.t + maxH - cumH}
                      width={colW - 4}
                      height={h}
                      rx={1}
                      fill={MC[m]}
                      opacity={bar.isWorking ? 0.85 : 0.15}
                      stroke={isH ? C.w : 'none'}
                      strokeWidth={isH ? 0.5 : 0}
                    />
                  ) : null;
                })}
                {/* Date label */}
                <text
                  x={x + (colW - 2) / 2}
                  y={PAD.t + maxH + 14}
                  textAnchor="middle"
                  style={{ fill: bar.isWorking ? C.t3 : C.t4, fontSize: 7, ...mono }}
                >
                  {fmtDate(bar.date)}
                </text>
                <text
                  x={x + (colW - 2) / 2}
                  y={PAD.t + maxH + 24}
                  textAnchor="middle"
                  style={{ fill: C.t4, fontSize: 6 }}
                >
                  {bar.dayName}
                </text>
              </g>
            );
          })}
          {/* Hover tooltip */}
          {hoverIdx !== null &&
            (() => {
              const bar = horizon[hoverIdx];
              if (!bar) return null;
              const tx = Math.max(80, Math.min(PAD.l + hoverIdx * colW + colW / 2, W - 80));
              return (
                <g>
                  <rect
                    x={tx - 70}
                    y={PAD.t - 6}
                    width={140}
                    height={22}
                    rx={5}
                    fill={C.s1}
                    stroke={C.bd}
                    strokeWidth={1}
                  />
                  <text
                    x={tx}
                    y={PAD.t + 9}
                    textAnchor="middle"
                    style={{ fill: C.t1, fontSize: 9, ...mono }}
                  >
                    {bar.fmtDate} {bar.dayName}: {fmtMin(bar.total)}
                    {!bar.isWorking ? ' (off)' : ''}
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
//  VIEW 3: URGENCY MATRIX — Priority scatter plot
// ══════════════════════════════════════════════════════════════

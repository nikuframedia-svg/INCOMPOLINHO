import React, { useMemo, useState } from 'react';
import { C } from '../../../../lib/engine';
import type { IntelData } from '../../intel-compute';
import { StatRow } from '../intel-atoms';
import { clientColorMap, fmtQty, mono } from '../intel-helpers';

export function UrgencyView({ data }: { data: IntelData }) {
  const { urgency } = data;
  const [hoverSku, setHoverSku] = useState<string | null>(null);

  const PAD = { l: 60, r: 30, t: 36, b: 50 };
  const W = 740,
    H = 430;
  const PW = W - PAD.l - PAD.r;
  const PH = H - PAD.t - PAD.b;

  const maxDays = Math.max(...urgency.map((p) => p.daysToDeficit), 10);
  const maxDef = Math.max(...urgency.map((p) => p.maxDeficit), 1000);

  const xScale = (d: number) => PAD.l + Math.min(d / maxDays, 1) * PW;
  const yScale = (d: number) => PAD.t + PH - Math.min(d / maxDef, 1) * PH;

  const cc = useMemo(() => clientColorMap(urgency.map((p) => p.clientCode)), [urgency]);

  const criticalCount = urgency.filter(
    (p) => p.daysToDeficit <= 3 && p.maxDeficit > maxDef * 0.3,
  ).length;
  const monitorCount = urgency.filter((p) => p.daysToDeficit > 10).length;

  return (
    <div>
      <StatRow
        items={[
          { label: 'Total SKUs at Risk', value: urgency.length, color: C.yl },
          { label: 'Critical (< 3d)', value: criticalCount, color: C.rd },
          { label: 'Monitor (> 10d)', value: monitorCount, color: C.ac },
          { label: 'Worst Deficit', value: fmtQty(maxDef) + ' pcs', color: C.rd },
        ]}
      />
      {/* Client legend */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        {Object.entries(cc).map(([code, color]) => (
          <div key={code} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
            <span style={{ color: C.t3, fontSize: 9, ...mono }}>{code}</span>
          </div>
        ))}
      </div>
      <div style={{ overflowX: 'auto' }}>
        <svg width={W} height={H} style={{ display: 'block' }}>
          {/* Quadrant backgrounds */}
          <rect
            x={PAD.l}
            y={PAD.t}
            width={xScale(5) - PAD.l}
            height={PH * 0.5}
            fill={C.rd}
            opacity={0.04}
          />
          {/* Quadrant labels */}
          <text
            x={PAD.l + 8}
            y={PAD.t + 16}
            style={{ fill: C.rd, fontSize: 10, fontWeight: 600, opacity: 0.6 }}
          >
            CRITICAL
          </text>
          <text
            x={W - PAD.r - 70}
            y={PAD.t + PH - 8}
            style={{ fill: C.ac, fontSize: 10, fontWeight: 600, opacity: 0.6 }}
          >
            MONITOR
          </text>
          {/* Grid lines */}
          {[0, 5, 10, 15, 20]
            .filter((v) => v <= maxDays)
            .map((v) => (
              <React.Fragment key={`x-${v}`}>
                <line
                  x1={xScale(v)}
                  y1={PAD.t}
                  x2={xScale(v)}
                  y2={PAD.t + PH}
                  stroke={C.bd}
                  strokeWidth={0.5}
                  strokeDasharray={v === 5 ? '4,2' : '2,4'}
                />
                <text
                  x={xScale(v)}
                  y={H - 10}
                  textAnchor="middle"
                  style={{ fill: C.t3, fontSize: 9, ...mono }}
                >
                  {v}d
                </text>
              </React.Fragment>
            ))}
          {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
            const v = frac * maxDef;
            return (
              <React.Fragment key={`y-${frac}`}>
                <line
                  x1={PAD.l}
                  y1={yScale(v)}
                  x2={PAD.l + PW}
                  y2={yScale(v)}
                  stroke={C.bd}
                  strokeWidth={0.5}
                  strokeDasharray="2,4"
                />
                <text
                  x={PAD.l - 6}
                  y={yScale(v) + 3}
                  textAnchor="end"
                  style={{ fill: C.t3, fontSize: 8, ...mono }}
                >
                  {fmtQty(v)}
                </text>
              </React.Fragment>
            );
          })}
          {/* Axis labels */}
          <text
            x={PAD.l + PW / 2}
            y={H - 2}
            textAnchor="middle"
            style={{ fill: C.t2, fontSize: 10 }}
          >
            Days to Deficit
          </text>
          <text
            x={12}
            y={PAD.t + PH / 2}
            textAnchor="middle"
            style={{ fill: C.t2, fontSize: 10 }}
            transform={`rotate(-90, 12, ${PAD.t + PH / 2})`}
          >
            Max Deficit (pcs)
          </text>
          {/* Points */}
          {urgency.map((p) => {
            const r = Math.max(4, Math.min(18, Math.sqrt(p.recoveryHours) * 2.5));
            const isH = hoverSku === p.sku;
            return (
              <g
                key={p.sku}
                onMouseEnter={() => setHoverSku(p.sku)}
                onMouseLeave={() => setHoverSku(null)}
                style={{ cursor: 'pointer' }}
              >
                <circle
                  cx={xScale(p.daysToDeficit)}
                  cy={yScale(p.maxDeficit)}
                  r={isH ? r * 1.3 : r}
                  fill={cc[p.clientCode] || C.t3}
                  opacity={isH ? 1 : 0.7}
                  stroke={isH ? C.w : 'none'}
                  strokeWidth={1.5}
                />
              </g>
            );
          })}
          {/* Hover tooltip */}
          {hoverSku &&
            (() => {
              const p = urgency.find((u) => u.sku === hoverSku);
              if (!p) return null;
              const tx = Math.max(100, Math.min(xScale(p.daysToDeficit), W - 120));
              const ty = yScale(p.maxDeficit) - 16;
              return (
                <g>
                  <rect
                    x={tx - 95}
                    y={ty - 40}
                    width={190}
                    height={38}
                    rx={6}
                    fill={C.s1}
                    stroke={C.bd}
                    strokeWidth={1}
                  />
                  <text
                    x={tx}
                    y={ty - 26}
                    textAnchor="middle"
                    style={{ fill: C.t1, fontSize: 9, ...mono, fontWeight: 600 }}
                  >
                    {p.sku}
                  </text>
                  <text x={tx} y={ty - 14} textAnchor="middle" style={{ fill: C.t2, fontSize: 8 }}>
                    {p.daysToDeficit}d to deficit | {fmtQty(p.maxDeficit)} pcs | {p.machine}
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
//  VIEW 4: CLIENT RISK RADAR — Per-client delivery risk
// ══════════════════════════════════════════════════════════════

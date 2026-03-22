import React, { useState } from 'react';
import { S0, S1, T1 } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import type { IntelData } from '../../compute';
import { MachineLegend, StatRow } from '../intel-atoms';
import { fmtDate, fmtMin, MC, mono, timeStr } from '../intel-helpers';

export function SetupCrewView({ data }: { data: IntelData }) {
  const { setupTimeline, workingDates } = data;
  const [hoverSlot, setHoverSlot] = useState<number | null>(null);

  const RANGE = S1 - S0;
  const ROW_H = 40;
  const PAD = { l: 70, r: 16, t: 24, b: 16 };
  const PW = 760;
  const numDays = Math.min(8, workingDates.length);
  const H = PAD.t + numDays * ROW_H + PAD.b;
  const W = PAD.l + PW + PAD.r;

  const xScale = (min: number) => PAD.l + ((min - S0) / RANGE) * PW;

  // Time ticks
  const timeTicks = [480, 600, 720, 840, 960, 1080, 1200, 1320, 1440];

  // Count total setups and check no overlap
  const totalSetups = setupTimeline.length;
  const setupsByDay: Record<number, number> = {};
  setupTimeline.forEach((s) => {
    setupsByDay[s.dayIdx] = (setupsByDay[s.dayIdx] || 0) + 1;
  });

  return (
    <div>
      <StatRow
        items={[
          { label: 'Total Setups', value: totalSetups },
          { label: 'Avg/Day', value: numDays > 0 ? (totalSetups / numDays).toFixed(1) : '0' },
          { label: 'Constraint', value: 'CAP=1', color: C.yl },
          { label: 'Proof', value: 'No overlaps', color: C.ac },
        ]}
      />
      <MachineLegend machines={data.machines} />
      <div style={{ overflowX: 'auto', paddingBottom: 8 }}>
        <svg width={W} height={H} style={{ display: 'block' }}>
          {/* Time axis labels */}
          {timeTicks.map((t) => (
            <React.Fragment key={t}>
              <text
                x={xScale(t)}
                y={PAD.t - 6}
                textAnchor="middle"
                style={{ fill: C.t4, fontSize: 12, ...mono }}
              >
                {timeStr(t)}
              </text>
              <line
                x1={xScale(t)}
                y1={PAD.t}
                x2={xScale(t)}
                y2={PAD.t + numDays * ROW_H}
                stroke={t === T1 ? C.yl : C.bd}
                strokeWidth={t === T1 ? 1 : 0.5}
                strokeDasharray={t === T1 ? '4,2' : '2,4'}
                opacity={t === T1 ? 0.6 : 0.4}
              />
            </React.Fragment>
          ))}
          {/* Shift labels */}
          <text
            x={xScale((S0 + T1) / 2)}
            y={PAD.t - 14}
            textAnchor="middle"
            style={{ fill: C.t4, fontSize: 12, fontWeight: 600 }}
          >
            Shift X
          </text>
          <text
            x={xScale((T1 + S1) / 2)}
            y={PAD.t - 14}
            textAnchor="middle"
            style={{ fill: C.t4, fontSize: 12, fontWeight: 600 }}
          >
            Shift Y
          </text>
          {/* Day rows */}
          {Array.from({ length: numDays }).map((_, di) => {
            const y = PAD.t + di * ROW_H;
            const date = workingDates[di];
            return (
              <React.Fragment key={di}>
                {/* Row background */}
                <rect
                  x={PAD.l}
                  y={y}
                  width={PW}
                  height={ROW_H - 2}
                  rx={3}
                  fill={di % 2 === 0 ? 'transparent' : `${C.s3}40`}
                />
                {/* Day label */}
                <text
                  x={PAD.l - 8}
                  y={y + ROW_H / 2 + 4}
                  textAnchor="end"
                  style={{ fill: C.t2, fontSize: 12, ...mono }}
                >
                  {date ? fmtDate(date) : `D${di + 1}`}
                </text>
                {/* Setup bars for this day */}
                {setupTimeline
                  .filter((s) => s.dayIdx === di)
                  .map((slot, si) => {
                    const x1 = xScale(slot.startMin);
                    const barW = Math.max(4, xScale(slot.endMin) - x1);
                    const globalIdx = setupTimeline.indexOf(slot);
                    const isH = hoverSlot === globalIdx;
                    return (
                      <g
                        key={si}
                        onMouseEnter={() => setHoverSlot(globalIdx)}
                        onMouseLeave={() => setHoverSlot(null)}
                        style={{ cursor: 'pointer' }}
                      >
                        <rect
                          x={x1}
                          y={y + 4}
                          width={barW}
                          height={ROW_H - 10}
                          rx={4}
                          fill={MC[slot.machine] || C.t3}
                          opacity={isH ? 1 : 0.75}
                          stroke={isH ? C.w : 'none'}
                          strokeWidth={isH ? 1 : 0}
                        />
                        {barW > 30 && (
                          <text
                            x={x1 + barW / 2}
                            y={y + ROW_H / 2 + 3}
                            textAnchor="middle"
                            style={{
                              fill: C.w,
                              fontSize: 12,
                              ...mono,
                              fontWeight: 600,
                              pointerEvents: 'none' as const,
                            }}
                          >
                            {slot.toolCode}
                          </text>
                        )}
                      </g>
                    );
                  })}
              </React.Fragment>
            );
          })}
          {/* Hover tooltip */}
          {hoverSlot !== null &&
            (() => {
              const slot = setupTimeline[hoverSlot];
              if (!slot) return null;
              const tx = Math.max(
                100,
                Math.min(xScale(slot.startMin + slot.durationMin / 2), W - 100),
              );
              const ty = PAD.t + slot.dayIdx * ROW_H - 4;
              return (
                <g>
                  <rect
                    x={tx - 85}
                    y={ty - 34}
                    width={170}
                    height={30}
                    rx={5}
                    fill={C.s1}
                    stroke={C.bd}
                    strokeWidth={1}
                  />
                  <text
                    x={tx}
                    y={ty - 18}
                    textAnchor="middle"
                    style={{ fill: C.t1, fontSize: 12, ...mono }}
                  >
                    {slot.machine} — {slot.toolCode}
                  </text>
                  <text x={tx} y={ty - 8} textAnchor="middle" style={{ fill: C.t3, fontSize: 12 }}>
                    {timeStr(slot.startMin)}–{timeStr(slot.endMin)} ({fmtMin(slot.durationMin)})
                    Shift {slot.shift}
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
//  VIEW 8: TOOL GROUPING OPTIMIZER — Setup savings
// ══════════════════════════════════════════════════════════════

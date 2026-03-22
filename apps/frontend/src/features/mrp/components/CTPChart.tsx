import { DAY_CAP } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { mono } from '../utils/mrp-helpers';

interface CTPChartProps {
  timeline: Array<{
    dayIndex: number;
    existingLoad: number;
    newOrderLoad: number;
    capacity: number;
  }>;
  dates: string[];
  dnames: string[];
  targetDay: number;
}

export function CTPChart({ timeline, dates, dnames, targetDay }: CTPChartProps) {
  if (timeline.length === 0) return null;
  const PAD = { t: 20, r: 20, b: 30, l: 50 };
  const colW = timeline.length > 30 ? 36 : 60;
  const W = PAD.l + timeline.length * colW + PAD.r;
  const maxH = 180;
  const H = PAD.t + maxH + PAD.b;
  const maxTotal = Math.max(DAY_CAP, ...timeline.map((t) => t.existingLoad + t.newOrderLoad)) * 1.1;
  const scale = (v: number) => Math.max(0, (v / maxTotal) * maxH);
  const capY = PAD.t + maxH - scale(DAY_CAP);

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <line
        x1={PAD.l}
        y1={capY}
        x2={W - PAD.r}
        y2={capY}
        stroke={C.rd}
        strokeWidth={1.5}
        strokeDasharray="6,3"
        opacity={0.6}
      />
      <text
        x={PAD.l - 4}
        y={capY + 3}
        textAnchor="end"
        style={{ fontSize: 12, fill: C.rd, ...mono }}
      >
        {DAY_CAP}
      </text>

      {timeline.map((bar, i) => {
        const x = PAD.l + i * colW;
        const existH = scale(bar.existingLoad);
        const newH = scale(bar.newOrderLoad);
        const isTarget = bar.dayIndex === targetDay;
        return (
          <g key={i}>
            {isTarget && (
              <rect x={x} y={PAD.t} width={colW - 2} height={maxH} fill={C.acS} rx={2} />
            )}
            <rect
              x={x + 4}
              y={PAD.t + maxH - existH}
              width={colW - 10}
              height={existH}
              rx={2}
              fill={`${C.t1}14`}
            />
            {newH > 0 && (
              <rect
                x={x + 4}
                y={PAD.t + maxH - existH - newH}
                width={colW - 10}
                height={newH}
                rx={2}
                fill={bar.existingLoad + bar.newOrderLoad > DAY_CAP ? C.rdM : C.acM}
              />
            )}
            <text
              x={x + colW / 2 - 1}
              y={H - 8}
              textAnchor="middle"
              style={{
                fontSize: 12,
                fill: isTarget ? C.ac : C.t3,
                fontWeight: isTarget ? 700 : 400,
                ...mono,
              }}
            >
              {dnames[i] ?? ''} {dates[i] ?? ''}
            </text>
            <text
              x={x + colW / 2 - 1}
              y={PAD.t + maxH - existH - newH - 4}
              textAnchor="middle"
              style={{ fontSize: 12, fill: C.t2, ...mono }}
            >
              {bar.existingLoad + bar.newOrderLoad > 0
                ? Math.round(bar.existingLoad + bar.newOrderLoad)
                : ''}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

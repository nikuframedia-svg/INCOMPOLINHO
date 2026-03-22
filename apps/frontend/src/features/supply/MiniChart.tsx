/**
 * MiniChart — Mini stock projection SVG chart for supply detail row.
 */

import { C } from '@/theme/color-bridge';
import { fmtQty } from './supply-compute';

const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

export function MiniChart({
  projection,
  dnames,
}: {
  projection: Array<{ day: number; projected: number; ropLine: number; ssLine: number }>;
  dnames: string[];
}) {
  if (projection.length === 0) return null;

  const W = 280,
    H = 80;
  const PAD = { t: 8, r: 8, b: 16, l: 36 };
  const chartW = W - PAD.l - PAD.r;
  const chartH = H - PAD.t - PAD.b;

  const allVals = projection.flatMap((p) => [p.projected, p.ropLine, p.ssLine]);
  const maxV = Math.max(...allVals, 1);
  const minV = Math.min(...allVals, 0);
  const range = maxV - minV || 1;

  const scaleY = (v: number) => PAD.t + chartH - ((v - minV) / range) * chartH;
  const scaleX = (i: number) => PAD.l + (i / (projection.length - 1 || 1)) * chartW;

  const projLine = projection
    .map(
      (p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(i).toFixed(1)},${scaleY(p.projected).toFixed(1)}`,
    )
    .join(' ');

  const ropY = scaleY(projection[0].ropLine);
  const ssY = scaleY(projection[0].ssLine);
  const zeroY = scaleY(0);

  const belowZeroPath = projection.reduce((acc, p, i) => {
    if (p.projected < 0) {
      const x = scaleX(i);
      const y = scaleY(p.projected);
      if (acc === '')
        return `M${x.toFixed(1)},${zeroY.toFixed(1)} L${x.toFixed(1)},${y.toFixed(1)}`;
      return `${acc} L${x.toFixed(1)},${y.toFixed(1)}`;
    }
    if (acc !== '' && i > 0 && projection[i - 1].projected < 0) {
      return `${acc} L${scaleX(i - 1).toFixed(1)},${zeroY.toFixed(1)} Z`;
    }
    return acc;
  }, '');

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <line
        x1={PAD.l}
        y1={zeroY}
        x2={W - PAD.r}
        y2={zeroY}
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={0.5}
      />
      {projection[0].ropLine > 0 && (
        <line
          x1={PAD.l}
          y1={ropY}
          x2={W - PAD.r}
          y2={ropY}
          stroke={C.yl}
          strokeWidth={0.8}
          strokeDasharray="4,2"
          opacity={0.6}
        />
      )}
      {projection[0].ssLine > 0 && (
        <line
          x1={PAD.l}
          y1={ssY}
          x2={W - PAD.r}
          y2={ssY}
          stroke={C.rd}
          strokeWidth={0.8}
          strokeDasharray="2,2"
          opacity={0.4}
        />
      )}
      {belowZeroPath && <path d={belowZeroPath} fill="rgba(239,68,68,0.15)" />}
      <path d={projLine} fill="none" stroke={C.ac} strokeWidth={1.5} />
      {projection.map((p, i) => (
        <circle
          key={i}
          cx={scaleX(i)}
          cy={scaleY(p.projected)}
          r={2}
          fill={p.projected < 0 ? C.rd : p.projected < p.ssLine ? C.yl : C.ac}
        />
      ))}
      {projection.map((_, i) => (
        <text
          key={i}
          x={scaleX(i)}
          y={H - 2}
          textAnchor="middle"
          style={{ fontSize: 12, fill: C.t4, ...mono }}
        >
          {dnames[i] ?? ''}
        </text>
      ))}
      <text
        x={PAD.l - 4}
        y={PAD.t + 4}
        textAnchor="end"
        style={{ fontSize: 12, fill: C.t4, ...mono }}
      >
        {fmtQty(maxV)}
      </text>
      <text
        x={PAD.l - 4}
        y={PAD.t + chartH}
        textAnchor="end"
        style={{ fontSize: 12, fill: C.t4, ...mono }}
      >
        {fmtQty(minV)}
      </text>
    </svg>
  );
}

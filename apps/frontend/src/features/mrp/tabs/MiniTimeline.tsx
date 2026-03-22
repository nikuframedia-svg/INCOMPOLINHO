/**
 * MiniTimeline — Compact production timeline for order rows.
 */
import { C } from '@/theme/color-bridge';

export function MiniTimeline({
  productionDays,
  numDays,
}: {
  productionDays: Array<{ dayIdx: number; qty: number }>;
  numDays: number;
}) {
  const daySet = new Set(productionDays.map((p) => p.dayIdx));
  const cellW = Math.min(10, Math.max(4, 120 / numDays));
  const w = numDays * (cellW + 1);

  return (
    <svg width={w} height={12} style={{ display: 'block' }}>
      {Array.from({ length: numDays }).map((_, i) => (
        <rect
          key={i}
          x={i * (cellW + 1)}
          y={1}
          width={cellW}
          height={10}
          rx={1}
          fill={daySet.has(i) ? C.ac : `${C.t3}20`}
          opacity={daySet.has(i) ? 0.8 : 1}
        />
      ))}
    </svg>
  );
}

/**
 * SummaryText — executive summary lines from the simulation result.
 */

import { C } from '@/theme/color-bridge';

interface Props {
  lines: string[];
}

export function SummaryText({ lines }: Props) {
  if (lines.length === 0) return null;
  return (
    <div
      style={{
        padding: '8px 12px',
        borderRadius: 6,
        background: `${C.ac}08`,
        border: `1px solid ${C.ac}22`,
      }}
    >
      {lines.map((line, i) => (
        <div key={i} style={{ fontSize: 12, color: C.t2, lineHeight: 1.6 }}>
          {line}
        </div>
      ))}
    </div>
  );
}

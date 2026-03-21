/**
 * KCard — KPI card for supply monitor.
 */

import { C } from '../../lib/engine';

const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

export function KCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="supply__kcard" style={{ borderLeft: `3px solid ${color}` }}>
      <span
        style={{
          fontSize: 12,
          fontWeight: 500,
          color: C.t3,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 22, fontWeight: 700, color, ...mono, lineHeight: 1.1 }}>
        {value}
      </span>
      <span style={{ fontSize: 12, color: C.t3 }}>{sub}</span>
    </div>
  );
}

import { C } from '@/lib/engine';
import { mono } from '../utils/mrp-helpers';

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
    <div className="mrp__kcard" style={{ borderLeft: `3px solid ${color}` }}>
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

import { C } from '@/theme/color-bridge';
import { AREA, heatColor, labelSt, MC, mono } from './intel-helpers';

export function StatRow({
  items,
}: {
  items: Array<{ label: string; value: string | number; color?: string }>;
}) {
  return (
    <div style={{ display: 'flex', gap: 24, marginBottom: 16, flexWrap: 'wrap' }}>
      {items.map((item, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={labelSt}>{item.label}</span>
          <span
            style={{
              color: item.color || C.t1,
              fontSize: 20,
              fontWeight: 600,
              ...mono,
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export function MachineLegend({ machines }: { machines: readonly string[] }) {
  return (
    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 12 }}>
      {machines.map((m) => (
        <div key={m} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: MC[m] }} />
          <span style={{ color: C.t2, fontSize: 12, ...mono }}>{m}</span>
          <span style={{ color: C.t4, fontSize: 12 }}>{AREA[m]}</span>
        </div>
      ))}
    </div>
  );
}

export function HeatLegend() {
  const stops = [
    { pct: 0, label: '0%' },
    { pct: 40, label: '40%' },
    { pct: 60, label: '60%' },
    { pct: 80, label: '80%' },
    { pct: 95, label: '95%' },
    { pct: 110, label: '>100%' },
  ];
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
      <span style={{ color: C.t3, fontSize: 12 }}>Load:</span>
      {stops.map((s) => (
        <div key={s.pct} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <div style={{ width: 14, height: 10, borderRadius: 2, background: heatColor(s.pct) }} />
          <span style={{ color: C.t3, fontSize: 12, ...mono }}>{s.label}</span>
        </div>
      ))}
    </div>
  );
}

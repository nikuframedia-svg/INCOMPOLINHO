/**
 * DeltaTable — before/after KPI comparison table.
 */

import { C } from '@/theme/color-bridge';
import type { SimDeltaReport } from '../../hooks/useSimulator';

interface Props {
  delta: SimDeltaReport;
}

function DeltaCell({
  before,
  after,
  suffix = '',
  invert = false,
}: {
  before: number;
  after: number;
  suffix?: string;
  invert?: boolean;
}) {
  const diff = after - before;
  const improved = invert ? diff < 0 : diff > 0;
  const degraded = invert ? diff > 0 : diff < 0;
  const color = Math.abs(diff) < 0.01 ? C.t3 : improved ? C.ac : degraded ? C.rd : C.t3;
  const sign = diff > 0 ? '+' : '';
  return (
    <td style={{ textAlign: 'right', padding: '4px 8px' }}>
      <span style={{ color, fontWeight: 600, fontSize: 12 }}>
        {after.toFixed(1)}
        {suffix}
      </span>
      {Math.abs(diff) >= 0.01 && (
        <span style={{ fontSize: 10, color, marginLeft: 4 }}>
          ({sign}
          {diff.toFixed(1)}
          {suffix})
        </span>
      )}
    </td>
  );
}

export function DeltaTable({ delta }: Props) {
  const rows: Array<{
    label: string;
    before: number;
    after: number;
    suffix: string;
    invert?: boolean;
  }> = [
    { label: 'OTD-D', before: delta.otd_d_before, after: delta.otd_d_after, suffix: '%' },
    { label: 'OTD Global', before: delta.otd_before, after: delta.otd_after, suffix: '%' },
    {
      label: 'Tardiness',
      before: delta.tardiness_before,
      after: delta.tardiness_after,
      suffix: ' dias',
      invert: true,
    },
    {
      label: 'Overflow',
      before: delta.overflow_before,
      after: delta.overflow_after,
      suffix: ' min',
      invert: true,
    },
    {
      label: 'Setups',
      before: delta.setups_before,
      after: delta.setups_after,
      suffix: '',
      invert: true,
    },
  ];

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
      <thead>
        <tr style={{ borderBottom: `1px solid ${C.bd}` }}>
          <th
            style={{
              textAlign: 'left',
              padding: '4px 8px',
              color: C.t3,
              fontWeight: 600,
              fontSize: 11,
            }}
          >
            Métrica
          </th>
          <th
            style={{
              textAlign: 'right',
              padding: '4px 8px',
              color: C.t3,
              fontWeight: 600,
              fontSize: 11,
            }}
          >
            Antes
          </th>
          <th
            style={{
              textAlign: 'right',
              padding: '4px 8px',
              color: C.t3,
              fontWeight: 600,
              fontSize: 11,
            }}
          >
            Depois
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} style={{ borderBottom: `1px solid ${C.bd}22` }}>
            <td style={{ padding: '4px 8px', color: C.t2, fontWeight: 500 }}>{r.label}</td>
            <td style={{ textAlign: 'right', padding: '4px 8px', color: C.t3 }}>
              {r.before.toFixed(1)}
              {r.suffix}
            </td>
            <DeltaCell before={r.before} after={r.after} suffix={r.suffix} invert={r.invert} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

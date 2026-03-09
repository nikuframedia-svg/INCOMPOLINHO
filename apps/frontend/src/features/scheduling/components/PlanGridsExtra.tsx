/**
 * PlanGridsExtra — VolumeChart and TopBacklogs sub-components for PlanGrids.
 */
import type { EngineData } from '../../../lib/engine';
import { C } from '../../../lib/engine';
import { Card, toolColor } from './atoms';

export function VolumeChart({
  prodByDay,
  maxPd,
  dates,
  wdi,
}: {
  prodByDay: number[];
  maxPd: number;
  dates: string[];
  wdi: number[];
}) {
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 10 }}>
        Volume / Dia
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 90 }}>
        {prodByDay.map((p, idx) => (
          <div
            key={idx}
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
            }}
          >
            <span style={{ fontSize: 9, color: C.ac, fontFamily: 'monospace', fontWeight: 600 }}>
              {p > 0 ? `${(p / 1000).toFixed(0)}K` : ''}
            </span>
            <div
              style={{
                width: '80%',
                height: Math.max((p / maxPd) * 65, 2),
                background: C.ac,
                borderRadius: '4px 4px 0 0',
              }}
            />
            <span style={{ fontSize: 9, color: C.t4 }}>{dates[wdi[idx]]}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

export function TopBacklogs({
  ops,
  tools,
}: {
  ops: EngineData['ops'];
  tools: EngineData['tools'];
}) {
  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>Top Atrasos</div>
      {ops
        .filter((o) => o.atr > 0)
        .sort((a, b) => b.atr - a.atr)
        .slice(0, 8)
        .map((o, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 2px',
              borderBottom: i < 7 ? `1px solid ${C.bd}` : undefined,
            }}
          >
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: toolColor(tools, o.t),
                fontFamily: 'monospace',
                minWidth: 52,
              }}
            >
              {o.t}
            </span>
            <span
              style={{
                flex: 1,
                fontSize: 10,
                color: C.t3,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {o.sku}
            </span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: o.atr > 10000 ? C.rd : C.yl,
                fontFamily: 'monospace',
              }}
            >
              {(o.atr / 1000).toFixed(1)}K
            </span>
          </div>
        ))}
    </Card>
  );
}

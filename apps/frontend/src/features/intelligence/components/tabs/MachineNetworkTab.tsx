import { C } from '../../../../lib/engine';
import type { IntelData } from '../../intel-compute';
import { StatRow } from '../intel-atoms';
import { cardSt, mono } from '../intel-helpers';

export function NetworkView({ data }: { data: IntelData }) {
  const { nodes, edges } = data.network;

  const SVG_W = 560,
    SVG_H = 440;
  const GRAPH_W = 500,
    GRAPH_H = 400;
  const areaColor = (area: string) => (area === 'PG1' ? C.ac : C.pp);

  const isolated = nodes.filter((n) => n.isolated);
  const connected = nodes.filter((n) => !n.isolated);

  return (
    <div>
      <StatRow
        items={[
          { label: 'Machines', value: nodes.length },
          { label: 'Connected', value: connected.length, color: C.ac },
          { label: 'Isolated', value: isolated.length, color: isolated.length > 0 ? C.rd : C.ac },
          { label: 'Alt Links', value: edges.length, color: C.bl },
        ]}
      />
      {/* Area legend */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div
            style={{ width: 12, height: 12, borderRadius: '50%', background: C.ac, opacity: 0.3 }}
          />
          <span style={{ color: C.t2, fontSize: 10 }}>PG1</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div
            style={{ width: 12, height: 12, borderRadius: '50%', background: C.pp, opacity: 0.3 }}
          />
          <span style={{ color: C.t2, fontSize: 10 }}>PG2</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: '50%',
              border: `2px solid ${C.rd}`,
              background: 'transparent',
            }}
          />
          <span style={{ color: C.t2, fontSize: 10 }}>Isolated (no alt)</span>
        </div>
      </div>
      <div
        style={{
          ...cardSt,
          padding: 0,
          overflow: 'hidden',
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <svg width={SVG_W} height={SVG_H} style={{ display: 'block' }}>
          {/* Edges */}
          {edges.map((e, i) => {
            const s = nodes.find((n) => n.id === e.from);
            const t = nodes.find((n) => n.id === e.to);
            if (!s || !t) return null;
            const sx = (s.x * SVG_W) / GRAPH_W,
              sy = (s.y * SVG_H) / GRAPH_H;
            const tx = (t.x * SVG_W) / GRAPH_W,
              ty = (t.y * SVG_H) / GRAPH_H;
            const mx = (sx + tx) / 2,
              my = (sy + ty) / 2;
            return (
              <g key={i}>
                <line
                  x1={sx}
                  y1={sy}
                  x2={tx}
                  y2={ty}
                  stroke={C.bh}
                  strokeWidth={Math.max(1.5, e.weight * 0.9)}
                  opacity={0.5}
                />
                {/* Tool count on midpoint */}
                <rect
                  x={mx - 14}
                  y={my - 8}
                  width={28}
                  height={14}
                  rx={3}
                  fill={C.s1}
                  stroke={C.bd}
                  strokeWidth={0.5}
                />
                <text
                  x={mx}
                  y={my + 3}
                  textAnchor="middle"
                  style={{ fill: C.t3, fontSize: 8, ...mono }}
                >
                  {e.weight}T
                </text>
              </g>
            );
          })}
          {/* Nodes */}
          {nodes.map((n) => {
            const x = (n.x * SVG_W) / GRAPH_W;
            const y = (n.y * SVG_H) / GRAPH_H;
            const r = 26 + n.toolCount * 1.2;
            const color = n.isolated ? C.rd : areaColor(n.area);
            return (
              <g key={n.id}>
                {/* Glow */}
                <circle
                  cx={x}
                  cy={y}
                  r={r + 4}
                  fill="none"
                  stroke={color}
                  strokeWidth={1}
                  opacity={0.15}
                />
                {/* Node circle */}
                <circle cx={x} cy={y} r={r} fill={`${color}18`} stroke={color} strokeWidth={2.5} />
                {/* Machine code */}
                <text
                  x={x}
                  y={y - 4}
                  textAnchor="middle"
                  style={{ fill: C.w, fontSize: 12, ...mono, fontWeight: 600 }}
                >
                  {n.id}
                </text>
                {/* Info */}
                <text x={x} y={y + 10} textAnchor="middle" style={{ fill: C.t3, fontSize: 9 }}>
                  {n.area} | {n.toolCount}T
                </text>
                {/* Isolated warning */}
                {n.isolated && (
                  <text
                    x={x}
                    y={y + 22}
                    textAnchor="middle"
                    style={{ fill: C.rd, fontSize: 8, fontWeight: 600 }}
                  >
                    NO ALT
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
//  VIEW 10: EXPLAIN TRACE — Decision tree per SKU
// ══════════════════════════════════════════════════════════════

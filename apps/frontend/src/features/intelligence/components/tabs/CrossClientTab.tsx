import { useMemo } from 'react';
import { C } from '@/theme/color-bridge';
import type { IntelData } from '../../compute';
import { StatRow } from '../intel-atoms';
import { cardSt, clientColorMap, fmtMin, fmtQty, MC, mono } from '../intel-helpers';

export function CrossClientView({ data }: { data: IntelData }) {
  const { crossClient } = data;

  const cc = useMemo(
    () => clientColorMap(crossClient.flatMap((s) => s.clients.map((c) => c.code))),
    [crossClient],
  );

  return (
    <div>
      <StatRow
        items={[
          { label: 'Cross-Client SKUs', value: crossClient.length, color: C.pp },
          {
            label: 'Total Demand',
            value: `${fmtQty(crossClient.reduce((s, c) => s + c.totalDemand, 0))} pcs`,
          },
          {
            label: 'Clients Involved',
            value: new Set(crossClient.flatMap((s) => s.clients.map((c) => c.code))).size,
          },
          {
            label: 'Production Hours',
            value: fmtMin(crossClient.reduce((s, c) => s + c.requiredHours * 60, 0)),
          },
        ]}
      />
      {/* Client legend */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        {Object.entries(cc).map(([code, color]) => (
          <div key={code} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
            <span style={{ color: C.t2, fontSize: 12, ...mono }}>{code}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {crossClient.map((sku) => (
          <div key={sku.sku} style={cardSt}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
              <span style={{ color: C.t1, fontSize: 13, fontWeight: 600, ...mono }}>{sku.sku}</span>
              <span style={{ color: MC[sku.machine] || C.t3, fontSize: 12, ...mono }}>
                {sku.machine}
              </span>
              <span style={{ color: C.t3, fontSize: 12 }}>{sku.tool}</span>
              <span style={{ marginLeft: 'auto', color: C.t2, fontSize: 12, ...mono }}>
                {fmtQty(sku.totalDemand)} pcs | {sku.requiredHours.toFixed(1)}h
              </span>
            </div>
            <div style={{ color: C.t3, fontSize: 12, marginBottom: 6 }}>{sku.name}</div>
            {/* Stacked demand bar */}
            <div
              style={{
                display: 'flex',
                height: 18,
                borderRadius: 4,
                overflow: 'hidden',
                marginBottom: 6,
              }}
            >
              {sku.clients.map((c) => {
                const pct = sku.totalDemand > 0 ? (c.totalDemand / sku.totalDemand) * 100 : 0;
                return pct > 0.5 ? (
                  <div
                    key={c.code}
                    style={{
                      width: `${pct}%`,
                      background: cc[c.code],
                      minWidth: 2,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    {pct > 15 && (
                      <span style={{ color: C.s1, fontSize: 12, fontWeight: 600, ...mono }}>
                        {c.code}
                      </span>
                    )}
                  </div>
                ) : null;
              })}
            </div>
            {/* Client details */}
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {sku.clients.map((c) => (
                <div key={c.code} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div
                    style={{ width: 6, height: 6, borderRadius: '50%', background: cc[c.code] }}
                  />
                  <span style={{ color: C.t2, fontSize: 12, ...mono }}>{c.code}</span>
                  <span style={{ color: C.t3, fontSize: 12 }}>{fmtQty(c.totalDemand)} pcs</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
//  VIEW 6: BOTTLENECK CASCADE — Overflow + relief paths
// ══════════════════════════════════════════════════════════════

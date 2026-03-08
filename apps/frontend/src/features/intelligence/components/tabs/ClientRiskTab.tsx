import { useCallback, useState } from 'react';
import { C } from '../../../../lib/engine';
import type { IntelData } from '../../intel-compute';
import { StatRow } from '../intel-atoms';
import { cardSt, fmtQty, MC, mono } from '../intel-helpers';

export function RiskView({ data }: { data: IntelData }) {
  const { clientRisk } = data;
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = useCallback((code: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const statusColor = (s: 'ok' | 'tight' | 'late') =>
    s === 'ok' ? C.ac : s === 'tight' ? C.yl : C.rd;

  const lateCount = clientRisk.filter((c) => c.overallStatus === 'late').length;
  const tightCount = clientRisk.filter((c) => c.overallStatus === 'tight').length;

  return (
    <div>
      <StatRow
        items={[
          { label: 'Total Clients', value: clientRisk.length },
          { label: 'Late', value: lateCount, color: C.rd },
          { label: 'Tight', value: tightCount, color: C.yl },
          { label: 'OK', value: clientRisk.length - lateCount - tightCount, color: C.ac },
        ]}
      />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 10,
        }}
      >
        {clientRisk.map((client) => {
          const isOpen = expanded.has(client.clientCode);
          return (
            <div
              key={client.clientCode}
              style={{
                ...cardSt,
                borderColor:
                  client.overallStatus !== 'ok' ? `${statusColor(client.overallStatus)}44` : C.bd,
                cursor: 'pointer',
              }}
              onClick={() => toggle(client.clientCode)}
            >
              {/* Header */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  marginBottom: isOpen ? 10 : 0,
                }}
              >
                {/* Traffic light */}
                <div
                  style={{
                    width: 16,
                    height: 16,
                    borderRadius: '50%',
                    background: statusColor(client.overallStatus),
                    boxShadow: `0 0 8px ${statusColor(client.overallStatus)}66`,
                  }}
                />
                <div style={{ flex: 1 }}>
                  <div style={{ color: C.t1, fontSize: 13, fontWeight: 600, ...mono }}>
                    {client.clientCode}
                  </div>
                  <div style={{ color: C.t3, fontSize: 10 }}>{client.clientName}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ color: C.t1, fontSize: 14, fontWeight: 600, ...mono }}>
                    {client.totalSKUs}
                  </div>
                  <div style={{ color: C.t3, fontSize: 9 }}>
                    {client.atRiskSKUs > 0 ? (
                      <span style={{ color: C.rd }}>{client.atRiskSKUs} at risk</span>
                    ) : (
                      'all clear'
                    )}
                  </div>
                </div>
                <span
                  style={{
                    color: C.t4,
                    fontSize: 10,
                    transform: isOpen ? 'rotate(90deg)' : 'none',
                    transition: 'transform 0.15s',
                  }}
                >
                  ▶
                </span>
              </div>
              {/* Expanded SKU list */}
              {isOpen && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {client.skus.map((sku) => (
                    <div
                      key={sku.sku}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '5px 8px',
                        background:
                          sku.status !== 'ok' ? `${statusColor(sku.status)}08` : 'transparent',
                        borderRadius: 5,
                      }}
                    >
                      <div
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: '50%',
                          background: statusColor(sku.status),
                        }}
                      />
                      <span
                        style={{
                          color: C.t1,
                          fontSize: 11,
                          ...mono,
                          flex: 1,
                          minWidth: 0,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {sku.sku}
                      </span>
                      <span style={{ color: MC[sku.machine] || C.t3, fontSize: 10, ...mono }}>
                        {sku.machine}
                      </span>
                      <span style={{ color: C.t3, fontSize: 9 }}>
                        {sku.firstDeficitDate ? `${sku.daysToDeficit}d` : 'ok'}
                      </span>
                      {sku.maxDeficit > 0 && (
                        <span style={{ color: C.rd, fontSize: 9, ...mono }}>
                          {fmtQty(sku.maxDeficit)}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
//  VIEW 5: CROSS-CLIENT SKU — Shared SKU aggregation
// ══════════════════════════════════════════════════════════════

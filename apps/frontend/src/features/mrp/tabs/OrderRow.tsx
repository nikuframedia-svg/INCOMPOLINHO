/**
 * OrderRow — Expandable order row for EncomendasTab.
 */

import { AlertTriangle, ChevronDown, ChevronRight, Link2 } from 'lucide-react';
import { C } from '@/lib/engine';
import { useUIStore } from '@/stores/useUIStore';
import type { OrderRiskEntry } from '../utils/encomendas-compute';
import { fmtQty, mono } from '../utils/mrp-helpers';
import { MiniTimeline } from './MiniTimeline';

const RISK_DOT: Record<string, string> = {
  critical: 'var(--semantic-red)',
  warning: 'var(--semantic-amber)',
  ok: 'var(--accent)',
};

export function OrderRow({
  entry: e,
  isExpanded,
  onToggle,
  numDays,
  dates,
  dnames,
}: {
  entry: OrderRiskEntry;
  isExpanded: boolean;
  onToggle: () => void;
  numDays: number;
  dates: string[];
  dnames: string[];
}) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);

  return (
    <>
      <tr
        style={{ cursor: 'pointer' }}
        onClick={onToggle}
        className={e.riskLevel === 'critical' ? 'mrp__row--stockout' : ''}
      >
        <td style={{ width: 20 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
        </td>
        <td style={{ width: 20 }}>
          <span className="mrp__enc-risk-dot" style={{ background: RISK_DOT[e.riskLevel] }} />
        </td>
        <td>
          <span
            style={{ ...mono, fontSize: 12, fontWeight: 600, color: C.t1, cursor: 'pointer' }}
            onClick={(ev) => {
              ev.stopPropagation();
              openContextPanel({ type: 'tool', id: e.toolCode });
              setFocus({ toolId: e.toolCode });
            }}
          >
            {e.sku}
          </span>
          {e.isTwin && (
            <span className="mrp__twin-badge" title={`Peça gémea: ${e.twinSku}`}>
              <Link2 size={10} />
            </span>
          )}
        </td>
        <td>
          <span style={{ fontSize: 12, color: C.t2 }}>{e.skuName}</span>
        </td>
        <td>
          {e.customerName ? (
            <span className="mrp__enc-client-badge">{e.customerName}</span>
          ) : (
            <span style={{ fontSize: 12, color: C.t4 }}>-</span>
          )}
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: e.shortfallQty > 0 ? C.rd : C.t3 }}>
            {e.shortfallQty > 0 ? fmtQty(e.shortfallQty) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span
            style={{
              fontSize: 12,
              color: e.coverageDays < 1 ? C.rd : e.coverageDays < 3 ? C.yl : C.ac,
            }}
          >
            {e.coverageDays.toFixed(1)}d
          </span>
        </td>
        <td>
          <MiniTimeline productionDays={e.productionDays} numDays={numDays} />
        </td>
      </tr>

      {isExpanded && (
        <tr className="mrp__detail-row">
          <td colSpan={8}>
            <div className="mrp__enc-detail">
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 500, color: C.t2 }}>
                  Produção agendada
                </span>
                <span style={{ fontSize: 12, color: C.t3, marginLeft: 8 }}>
                  Total: <span style={{ ...mono, color: C.t1 }}>{fmtQty(e.totalScheduledQty)}</span>{' '}
                  pcs
                </span>
              </div>
              <div className="mrp__enc-timeline-detail">
                {Array.from({ length: numDays }).map((_, i) => {
                  const dayProds = e.productionDays.filter((p) => p.dayIdx === i);
                  const dayQty = dayProds.reduce((s, p) => s + p.qty, 0);
                  return (
                    <div
                      key={i}
                      className={`mrp__enc-timeline-day-detail${dayQty > 0 ? ' mrp__enc-timeline-day-detail--active' : ''}`}
                    >
                      <span className="mrp__enc-timeline-day-label">
                        {dnames[i]} {dates[i]}
                      </span>
                      {dayQty > 0 && (
                        <span style={{ ...mono, fontSize: 12, color: C.ac }}>{fmtQty(dayQty)}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {e.suggestions.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 500,
                    color: C.t2,
                    marginBottom: 4,
                    display: 'block',
                  }}
                >
                  Sugestões
                </span>
                <div className="mrp__enc-suggestions">
                  {e.suggestions.map((s) => (
                    <div
                      key={s.id}
                      className={`mrp__enc-suggestion mrp__enc-suggestion--${s.severity}`}
                    >
                      <AlertTriangle size={11} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, fontWeight: 500, color: C.t1 }}>{s.title}</div>
                        <div style={{ fontSize: 12, color: C.t2 }}>{s.suggestedAction}</div>
                      </div>
                      <span style={{ ...mono, fontSize: 12, color: C.t3 }}>
                        {fmtQty(s.impact.qtyAffected)} pcs
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ marginTop: 8, fontSize: 12, color: C.t3, display: 'flex', gap: 16 }}>
              <span>
                Tool: <span style={{ ...mono, color: C.t2 }}>{e.toolCode}</span>
              </span>
              <span>
                Máq: <span style={{ ...mono, color: C.t2 }}>{e.machineId}</span>
              </span>
              {e.altMachine && (
                <span>
                  Alt: <span style={{ ...mono, color: C.t2 }}>{e.altMachine}</span>
                </span>
              )}
              {!e.altMachine && <span style={{ color: C.rd }}>Sem alternativa</span>}
              {e.isTwin && <span style={{ color: C.ac }}>Twin: {e.twinSku}</span>}
              {e.stockoutDay !== null && (
                <span style={{ color: C.rd }}>Stockout dia {e.stockoutDay}</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

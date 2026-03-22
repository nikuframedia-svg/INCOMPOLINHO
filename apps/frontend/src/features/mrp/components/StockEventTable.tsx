/**
 * StockEventTable — Chronological table of stock events for a SKU.
 * Shows production, shipment, and receipt events with stock after.
 */

import { C } from '@/theme/color-bridge';
import { fmtQty, mono } from '../utils/mrp-helpers';
import type { StockEvent, StockEventType } from '../utils/stock-detail-compute';

const TYPE_CONFIG: Record<StockEventType, { label: string; color: string; sign: string }> = {
  production: { label: 'Produção', color: C.ac, sign: '+' },
  shipment: { label: 'Expedição', color: C.rd, sign: '-' },
  receipt: { label: 'Receção', color: 'var(--semantic-blue)', sign: '+' },
};

interface StockEventTableProps {
  events: StockEvent[];
}

export function StockEventTable({ events }: StockEventTableProps) {
  if (events.length === 0) {
    return (
      <div
        className="mrp__card"
        style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}
      >
        Sem eventos de stock para este SKU
      </div>
    );
  }

  return (
    <div className="mrp__card">
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.t2,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
          padding: '12px 12px 6px',
        }}
      >
        Eventos de Stock
      </div>
      <table className="mrp__table">
        <thead>
          <tr>
            <th>Data</th>
            <th>Tipo</th>
            <th style={{ textAlign: 'right' }}>Quantidade</th>
            <th style={{ textAlign: 'right' }}>Stock Resultante</th>
            <th>Máquina</th>
          </tr>
        </thead>
        <tbody>
          {events.map((ev, i) => {
            const cfg = TYPE_CONFIG[ev.type];
            return (
              <tr key={`${ev.dayIndex}-${ev.type}-${i}`}>
                <td style={{ ...mono, fontSize: 12, color: C.t2 }}>{ev.dateLabel}</td>
                <td>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      padding: '2px 6px',
                      borderRadius: 3,
                      background: `${cfg.color}18`,
                      color: cfg.color,
                    }}
                  >
                    {cfg.label}
                  </span>
                </td>
                <td
                  style={{
                    textAlign: 'right',
                    ...mono,
                    fontSize: 12,
                    color: cfg.color,
                    fontWeight: 600,
                  }}
                >
                  {cfg.sign}
                  {fmtQty(ev.qty)}
                </td>
                <td
                  style={{
                    textAlign: 'right',
                    ...mono,
                    fontSize: 12,
                    fontWeight: 600,
                    color: ev.stockAfter < 0 ? C.rd : C.t1,
                  }}
                >
                  {fmtQty(ev.stockAfter)}
                </td>
                <td style={{ ...mono, fontSize: 12, color: C.t3 }}>{ev.machineId ?? '-'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

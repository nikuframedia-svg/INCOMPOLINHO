/**
 * StockDayTable — Day-by-day stock projection table.
 * Shows opening stock, production (machine + qty), per-client shipments, closing stock.
 */

import { C } from '@/theme/color-bridge';
import { fmtQty, mono } from '../utils/mrp-helpers';
import type { StockDayRow } from '../utils/stock-detail-compute';

interface StockDayTableProps {
  rows: StockDayRow[];
  ecoLot: number;
}

function closingColor(closing: number, ecoLot: number): string | undefined {
  if (closing < 0) return C.rd;
  if (ecoLot > 0 && closing < ecoLot) return C.yl;
  if (ecoLot > 0 && closing > ecoLot * 3) return 'var(--semantic-blue)';
  return undefined;
}

function closingBg(closing: number, ecoLot: number): string | undefined {
  if (closing < 0) return `${C.rd}12`;
  if (ecoLot > 0 && closing < ecoLot) return `${C.yl}08`;
  if (ecoLot > 0 && closing > ecoLot * 3) return 'var(--semantic-blue-bg, rgba(59,130,246,0.06))';
  return undefined;
}

export function StockDayTable({ rows, ecoLot }: StockDayTableProps) {
  // Collapse empty days (no production, no shipments)
  const hasActivity = (r: StockDayRow) => r.production.length > 0 || r.shipments.length > 0;

  return (
    <div className="mrp__card" style={{ overflow: 'auto' }}>
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
        Projecção Diária de Stock
      </div>
      <table className="mrp__table">
        <thead>
          <tr>
            <th style={{ width: 35 }}>Dia</th>
            <th style={{ width: 70 }}>Data</th>
            <th style={{ textAlign: 'right', width: 80 }}>Stock Início</th>
            <th style={{ minWidth: 140 }}>Produção</th>
            <th style={{ minWidth: 180 }}>Expedição</th>
            <th style={{ textAlign: 'right', width: 80 }}>Stock Fim</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = hasActivity(row);
            const cc = closingColor(row.closing, ecoLot);
            const bg = active ? (row.production.length > 0 ? `${C.ac}06` : undefined) : `${C.t4}05`;

            return (
              <tr
                key={row.dayIdx}
                style={{
                  background: closingBg(row.closing, ecoLot) ?? bg,
                  opacity: !active && row.closing >= 0 ? 0.7 : 1,
                }}
              >
                <td style={{ ...mono, fontSize: 12, color: C.t3 }}>{row.dayIdx}</td>
                <td style={{ ...mono, fontSize: 12, color: row.isWorkday ? C.t2 : C.t3 }}>
                  {row.date}
                  {row.dayName && !row.isWorkday && (
                    <span style={{ fontSize: 12, color: C.t4, marginLeft: 4 }}>{row.dayName}</span>
                  )}
                </td>
                <td style={{ textAlign: 'right', ...mono, fontSize: 12, color: C.t2 }}>
                  {row.opening !== 0 ? fmtQty(row.opening) : '-'}
                </td>
                <td>
                  {row.production.map((p, i) => (
                    <div key={i} style={{ fontSize: 12, color: C.ac, fontWeight: 600, ...mono }}>
                      +{fmtQty(p.qty)} ({p.machine})
                      {p.isTwin && (
                        <span style={{ fontSize: 12, color: C.yl, marginLeft: 4 }}>gémea</span>
                      )}
                    </div>
                  ))}
                </td>
                <td>
                  {row.shipments.map((sh, i) => (
                    <div key={i} style={{ fontSize: 12, ...mono }}>
                      <span style={{ color: C.rd, fontWeight: 600 }}>-{fmtQty(sh.qty)}</span>
                      <span style={{ color: C.t3, marginLeft: 6 }}>{sh.client}</span>
                    </div>
                  ))}
                </td>
                <td
                  style={{
                    textAlign: 'right',
                    ...mono,
                    fontSize: 12,
                    fontWeight: 700,
                    color: cc ?? C.t1,
                  }}
                >
                  {fmtQty(row.closing)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

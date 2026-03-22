/**
 * SupplyTableRow — Expandable table row for supply monitor.
 */

import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { C } from '@/theme/color-bridge';
import { useUIStore } from '../../stores/useUIStore';
import { MiniChart } from './MiniChart';
import type { SupplyRow } from './supply-compute';
import { fmtQty } from './supply-compute';

const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

export function SupplyTableRow({
  row,
  isExpanded,
  onToggle,
  dnames,
}: {
  row: SupplyRow;
  isExpanded: boolean;
  onToggle: () => void;
  dnames: string[];
}) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const skuLabel =
    row.skus.length === 1 ? row.skus[0].name : `${row.skus[0].name} +${row.skus.length - 1}`;

  const stockColor = row.belowSS ? C.rd : row.belowROP ? C.yl : row.currentStock > 0 ? C.ac : C.t3;
  const covColor = row.coverageDays < 1 ? C.rd : row.coverageDays < 3 ? C.yl : C.ac;

  const statusBadge = (() => {
    if (row.stockoutDay !== null && !row.canMeetDelivery)
      return { label: 'FALHA', cls: 'supply__badge--fail' };
    if (row.stockoutDay !== null) return { label: 'RISCO', cls: 'supply__badge--risk' };
    if (row.belowSS) return { label: '< SS', cls: 'supply__badge--below-ss' };
    if (row.belowROP) return { label: '< ROP', cls: 'supply__badge--below-rop' };
    return { label: 'OK', cls: 'supply__badge--ok' };
  })();

  const actionCount = row.actions.length;
  const hasCritical = row.actions.some((a) => a.severity === 'critical');

  return (
    <>
      <tr className={`supply__row supply__row--${row.risk}`} onClick={onToggle}>
        <td style={{ width: 20 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
        </td>
        <td>
          <span
            style={{ ...mono, fontSize: 12, fontWeight: 600, color: C.t1, cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'tool', id: row.toolCode });
              setFocus({ toolId: row.toolCode });
            }}
          >
            {row.toolCode}
          </span>
        </td>
        <td>
          <span
            style={{ fontSize: 12, color: C.t2 }}
            title={row.skus.map((s) => `${s.sku}: ${s.name}`).join('\n')}
          >
            {skuLabel}
          </span>
        </td>
        <td>
          <span
            style={{ ...mono, fontSize: 12, color: C.t2, cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'machine', id: row.machine });
              setFocus({ machine: row.machine });
            }}
          >
            {row.machine}
          </span>
          {!row.altMachine && (
            <span className="supply__no-alt" title="Sem máquina alternativa">
              !
            </span>
          )}
        </td>
        <td style={{ textAlign: 'center' }}>
          <span className={`supply__abc-badge supply__abc-badge--${row.abcClass.toLowerCase()}`}>
            {row.abcClass}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: stockColor }}>
            {fmtQty(row.currentStock)}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: row.backlog > 0 ? C.yl : C.t4 }}>
            {row.backlog > 0 ? fmtQty(row.backlog) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: row.belowSS ? C.rd : C.t3 }}>
            {row.safetyStock > 0 ? fmtQty(row.safetyStock) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: row.belowROP ? C.yl : C.t3 }}>
            {row.rop > 0 ? fmtQty(row.rop) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: covColor }}>
            {row.totalDemand > 0 ? `${row.coverageDays.toFixed(1)}d` : '-'}
          </span>
        </td>
        <td>
          {row.stockoutDay !== null ? (
            <span style={{ ...mono, fontSize: 12, color: C.rd, fontWeight: 600 }}>
              D{row.stockoutDay}
              {row.stockoutDate && (
                <span style={{ fontWeight: 400, color: C.t3 }}> ({row.stockoutDate})</span>
              )}
            </span>
          ) : (
            <span style={{ fontSize: 12, color: C.t4 }}>—</span>
          )}
        </td>
        <td>
          <span className={`supply__badge ${statusBadge.cls}`}>{statusBadge.label}</span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: row.totalPlannedQty > 0 ? C.ac : C.t4 }}>
            {row.totalPlannedQty > 0 ? fmtQty(row.totalPlannedQty) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'center' }}>
          {actionCount > 0 && (
            <span
              className="supply__action-count"
              style={{
                background: hasCritical ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.12)',
                color: hasCritical ? C.rd : C.yl,
              }}
            >
              {actionCount}
            </span>
          )}
        </td>
      </tr>

      {isExpanded && (
        <tr className="supply__detail">
          <td colSpan={14}>
            <div className="supply__detail-inner">
              <div className="supply__detail-actions">
                {row.actions.length > 0 ? (
                  row.actions.map((a) => (
                    <div
                      key={a.id}
                      className={`supply__action-card supply__action-card--${a.severity}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'flex-start', paddingTop: 1 }}>
                        <AlertTriangle
                          size={12}
                          color={
                            a.severity === 'critical' ? C.rd : a.severity === 'high' ? C.yl : C.bl
                          }
                        />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="supply__action-title">{a.title}</div>
                        <div className="supply__action-desc">{a.description}</div>
                        <div className="supply__action-suggestion">{a.suggestedAction}</div>
                      </div>
                      <div
                        style={{
                          fontSize: 12,
                          color: C.t3,
                          ...mono,
                          whiteSpace: 'nowrap',
                          textAlign: 'right',
                        }}
                      >
                        <div>{fmtQty(a.impact.qtyAffected)} pcs</div>
                        <div>{a.impact.daysAffected}d</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div style={{ fontSize: 12, color: C.t3, padding: '4px 0' }}>
                    Sem acções pendentes
                  </div>
                )}
                <div style={{ fontSize: 12, color: C.t3, display: 'flex', gap: 14, marginTop: 4 }}>
                  <span>Rate: {row.ratePerHour} p/h</span>
                  <span>Backlog: {row.backlog > 0 ? fmtQty(row.backlog) : '-'}</span>
                  <span>Demand total: {fmtQty(row.totalDemand)}</span>
                  <span>ABC: {row.abcClass}</span>
                  {row.altMachine ? (
                    <span>Alt: {row.altMachine}</span>
                  ) : (
                    <span style={{ color: C.rd }}>Sem alternativa</span>
                  )}
                </div>
              </div>
              <div className="supply__detail-chart">
                <MiniChart projection={row.dailyProjection} dnames={dnames} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

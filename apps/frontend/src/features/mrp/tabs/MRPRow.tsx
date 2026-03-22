import { ChevronDown, ChevronRight } from 'lucide-react';
import type { MRPRecord } from '@/domain/mrp/mrp-types';
import { useUIStore } from '@/stores/useUIStore';
import { C } from '@/theme/color-bridge';
import { fmtQty, mono, projColor } from '../utils/mrp-helpers';
import { MRPRowDetail } from './MRPRowDetail';

export interface MRPRowProps {
  record: MRPRecord;
  isExpanded: boolean;
  hasStockout: boolean;
  numDays: number;
  onToggle: () => void;
}

export function MRPRow({ record: r, isExpanded, hasStockout, numDays, onToggle }: MRPRowProps) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const skuLabel = r.skus.length === 1 ? r.skus[0].sku : `${r.skus[0].sku} +${r.skus.length - 1}`;
  return (
    <>
      <tr
        className={hasStockout ? 'mrp__row--stockout' : ''}
        style={{ cursor: 'pointer' }}
        onClick={onToggle}
      >
        <td style={{ width: 20 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
        </td>
        <td>
          <span
            className="mrp__clickable"
            style={{ ...mono, fontSize: 12, fontWeight: 600, color: C.t1 }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'tool', id: r.toolCode });
              setFocus({ toolId: r.toolCode });
            }}
          >
            {r.toolCode}
          </span>
          {!r.altMachine && (
            <span style={{ fontSize: 12, color: C.rd, marginLeft: 4 }} title="Sem alternativa">
              !
            </span>
          )}
        </td>
        <td>
          <span
            style={{ fontSize: 12, color: C.t2 }}
            title={r.skus.map((s) => `${s.sku}: ${s.name}`).join('\n')}
          >
            {skuLabel}
          </span>
        </td>
        <td>
          <span
            className="mrp__clickable"
            style={{ ...mono, fontSize: 12, color: C.t2 }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'machine', id: r.machine });
              setFocus({ machine: r.machine });
            }}
          >
            {r.machine}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: r.currentStock > 0 ? C.ac : C.t3 }}>
            {fmtQty(r.currentStock)}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 12, color: r.backlog > 0 ? C.rd : C.t3 }}>
            {r.backlog > 0 ? fmtQty(r.backlog) : '-'}
          </span>
        </td>
        {r.buckets.map((b, i) => (
          <td key={i} className="mrp__cell-day">
            {b.grossRequirement > 0 && (
              <div className="mrp__cell-gr">GR {fmtQty(b.grossRequirement)}</div>
            )}
            <div className="mrp__cell-proj" style={{ color: projColor(b.projectedAvailable) }}>
              {fmtQty(b.projectedAvailable)}
            </div>
            {b.plannedOrderReceipt > 0 && (
              <div className="mrp__cell-por" style={{ color: C.ac }}>
                POR {fmtQty(b.plannedOrderReceipt)}
              </div>
            )}
          </td>
        ))}
        <td style={{ textAlign: 'right' }}>
          <span
            style={{
              ...mono,
              fontSize: 12,
              fontWeight: 600,
              color: r.totalPlannedQty > 0 ? C.ac : C.t3,
            }}
          >
            {r.totalPlannedQty > 0 ? fmtQty(r.totalPlannedQty) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span
            style={{
              fontSize: 12,
              color: r.coverageDays < 2 ? C.rd : r.coverageDays < 4 ? C.yl : C.ac,
            }}
          >
            {r.coverageDays.toFixed(1)}d
          </span>
        </td>
      </tr>
      {isExpanded && <MRPRowDetail record={r} numDays={numDays} />}
    </>
  );
}

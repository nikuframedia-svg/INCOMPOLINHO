import type { MRPRecord } from '@/domain/mrp/mrp-types';
import { C } from '@/theme/color-bridge';
import { gridDensityVars } from '@/utils/gridDensity';
import { fmtQty, projColor } from '../utils/mrp-helpers';

export interface MRPRowDetailProps {
  record: MRPRecord;
  numDays: number;
}

export function MRPRowDetail({ record: r, numDays }: MRPRowDetailProps) {
  return (
    <tr className="mrp__detail-row">
      <td colSpan={8 + numDays}>
        <div
          className="mrp__detail-grid"
          style={
            {
              gridTemplateColumns: `120px repeat(${numDays}, 1fr)`,
              '--n-days': numDays,
              ...gridDensityVars(numDays),
            } as React.CSSProperties
          }
        >
          <div className="mrp__detail-label">Gross Req.</div>
          {r.buckets.map((b, i) => (
            <div
              key={i}
              className="mrp__detail-val"
              style={{ color: b.grossRequirement > 0 ? C.t2 : C.t4 }}
            >
              {b.grossRequirement > 0 ? fmtQty(b.grossRequirement) : '-'}
            </div>
          ))}
          <div className="mrp__detail-label">Sched. Receipts</div>
          {r.buckets.map((_, i) => (
            <div key={i} className="mrp__detail-val" style={{ color: C.t4 }}>
              -
            </div>
          ))}
          <div className="mrp__detail-label">Proj. Available</div>
          {r.buckets.map((b, i) => (
            <div
              key={i}
              className="mrp__detail-val"
              style={{ color: projColor(b.projectedAvailable), fontWeight: 600 }}
            >
              {fmtQty(b.projectedAvailable)}
            </div>
          ))}
          <div className="mrp__detail-label">Net Req.</div>
          {r.buckets.map((b, i) => (
            <div
              key={i}
              className="mrp__detail-val"
              style={{ color: b.netRequirement > 0 ? C.rd : C.t4 }}
            >
              {b.netRequirement > 0 ? fmtQty(b.netRequirement) : '-'}
            </div>
          ))}
          <div className="mrp__detail-label">POR (Receipt)</div>
          {r.buckets.map((b, i) => (
            <div
              key={i}
              className="mrp__detail-val"
              style={{ color: b.plannedOrderReceipt > 0 ? C.ac : C.t4 }}
            >
              {b.plannedOrderReceipt > 0 ? fmtQty(b.plannedOrderReceipt) : '-'}
            </div>
          ))}
          <div className="mrp__detail-label">POR (Release)</div>
          {r.buckets.map((b, i) => (
            <div
              key={i}
              className="mrp__detail-val"
              style={{ color: b.plannedOrderRelease > 0 ? C.pp : C.t4 }}
            >
              {b.plannedOrderRelease > 0 ? fmtQty(b.plannedOrderRelease) : '-'}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 8, fontSize: 12, color: C.t3, display: 'flex', gap: 16 }}>
          <span>Lote: {fmtQty(r.lotEconomicQty)}</span>
          <span>Rate: {r.ratePerHour} p/h</span>
          <span>Setup: {r.setupHours}h</span>
          <span>Ops: {r.operators}</span>
          <span>Lead: {r.productionLeadDays}d</span>
          {r.altMachine ? (
            <span>Alt: {r.altMachine}</span>
          ) : (
            <span style={{ color: C.rd }}>Sem alternativa</span>
          )}
        </div>
      </td>
    </tr>
  );
}

import { ChevronDown, ChevronRight, Link2 } from 'lucide-react';
import type { MRPSkuViewRecord } from '@/domain/mrp/mrp-types';
import { useUIStore } from '@/stores/useUIStore';
import { C } from '@/theme/color-bridge';
import { fmtQty, mono, projColor } from '../utils/mrp-helpers';
import { SKURowDetail } from './SKURowDetail';
import { SKUTableFilters } from './SKUTableFilters';

type Filter = 'all' | 'stockout' | 'backlog';

interface SKUTableTabProps {
  records: MRPSkuViewRecord[];
  allRecords: MRPSkuViewRecord[];
  dates: string[];
  dnames: string[];
  machines: Array<{ id: string; area: string }>;
  filter: Filter;
  setFilter: (f: Filter) => void;
  machineFilter: string;
  setMachineFilter: (m: string) => void;
  search: string;
  setSearch: (s: string) => void;
  expanded: Set<string>;
  toggleExpand: (key: string) => void;
}

export function SKUTableTab({
  records,
  allRecords,
  dates,
  dnames,
  machines,
  filter,
  setFilter,
  machineFilter,
  setMachineFilter,
  search,
  setSearch,
  expanded,
  toggleExpand,
}: SKUTableTabProps) {
  return (
    <>
      <SKUTableFilters
        allRecords={allRecords}
        filteredCount={records.length}
        filter={filter}
        setFilter={setFilter}
        machineFilter={machineFilter}
        setMachineFilter={setMachineFilter}
        machines={machines}
        search={search}
        setSearch={setSearch}
      />
      <div className="mrp__card">
        <table className="mrp__table">
          <thead>
            <tr>
              <th style={{ width: 20 }} />
              <th>SKU</th>
              <th>Produto</th>
              <th>Tool</th>
              <th>Máq.</th>
              <th style={{ textAlign: 'right' }}>Stock</th>
              <th style={{ textAlign: 'right' }}>Backlog</th>
              {dates.map((d, i) => (
                <th key={i} className="mrp__th-day">
                  {dnames[i]}
                  <br />
                  <span style={{ fontWeight: 400, opacity: 0.6 }}>
                    {dates.length > 30 ? d.slice(0, 2) : d}
                  </span>
                </th>
              ))}
              <th style={{ textAlign: 'right' }}>POR Total</th>
              <th style={{ textAlign: 'right' }}>Cob.</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <SKURow
                key={r.opId}
                record={r}
                isExpanded={expanded.has(r.opId)}
                numDays={dates.length}
                onToggle={() => toggleExpand(r.opId)}
              />
            ))}
          </tbody>
        </table>
        {records.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
            Nenhum SKU encontrado
          </div>
        )}
      </div>
    </>
  );
}

function SKURow({
  record: r,
  isExpanded,
  numDays,
  onToggle,
}: {
  record: MRPSkuViewRecord;
  isExpanded: boolean;
  numDays: number;
  onToggle: () => void;
}) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const hasStockout = r.stockoutDay !== null;
  const totalPOR = r.buckets.reduce((s, b) => s + b.plannedOrderReceipt, 0);

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
          <span style={{ ...mono, fontSize: 12, fontWeight: 600, color: C.t1 }}>{r.sku}</span>
          {r.isTwin && (
            <span className="mrp__twin-badge" title={`Peça gémea: ${r.twin}`}>
              <Link2 size={10} />
            </span>
          )}
        </td>
        <td>
          <span style={{ fontSize: 12, color: C.t2 }}>{r.name}</span>
          {r.customer && <span className="mrp__customer-tag">{r.customer}</span>}
        </td>
        <td>
          <span
            className="mrp__clickable"
            style={{ ...mono, fontSize: 12, color: C.t2 }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'tool', id: r.toolCode });
              setFocus({ toolId: r.toolCode });
            }}
          >
            {r.toolCode}
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
            style={{ ...mono, fontSize: 12, fontWeight: 600, color: totalPOR > 0 ? C.ac : C.t3 }}
          >
            {totalPOR > 0 ? fmtQty(totalPOR) : '-'}
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
      {isExpanded && <SKURowDetail record={r} numDays={numDays} />}
    </>
  );
}

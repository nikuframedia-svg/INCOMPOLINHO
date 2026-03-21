import { ChevronDown, ChevronRight, Link2 } from 'lucide-react';
import type { MRPSkuViewRecord } from '@/domain/mrp/mrp-types';
import { C } from '@/lib/engine';
import { useUIStore } from '@/stores/useUIStore';
import { gridDensityVars } from '@/utils/gridDensity';
import { fmtQty, mono, projColor } from '../utils/mrp-helpers';

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
  const stockoutCount = allRecords.filter((r) => r.stockoutDay !== null).length;
  const backlogCount = allRecords.filter((r) => r.backlog > 0).length;

  return (
    <>
      <div className="mrp__filters">
        <select
          className="mrp__filter-select"
          value={filter}
          onChange={(e) => setFilter(e.target.value as Filter)}
        >
          <option value="all">Todos ({allRecords.length})</option>
          <option value="stockout">Com Stockout ({stockoutCount})</option>
          <option value="backlog">Com Backlog ({backlogCount})</option>
        </select>
        <select
          className="mrp__filter-select"
          value={machineFilter}
          onChange={(e) => setMachineFilter(e.target.value)}
        >
          <option value="all">Todas máquinas</option>
          {machines.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id} ({m.area})
            </option>
          ))}
        </select>
        <input
          className="mrp__filter-input"
          type="text"
          placeholder="Procurar SKU/produto/tool..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {records.length} de {allRecords.length} SKUs
        </span>
      </div>
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
      {isExpanded && (
        <tr className="mrp__detail-row">
          <td colSpan={9 + numDays}>
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
              <span>Rate: {r.ratePerHour} p/h</span>
              <span>Setup: {r.setupHours}h</span>
              <span>Lote: {fmtQty(r.lotEconomicQty)}</span>
              {r.customerName && <span>Cliente: {r.customerName}</span>}
              {r.isTwin && <span style={{ color: C.ac }}>Twin: {r.twin}</span>}
              {!r.altMachine ? (
                <span style={{ color: C.rd }}>Sem alternativa</span>
              ) : (
                <span>Alt: {r.altMachine}</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

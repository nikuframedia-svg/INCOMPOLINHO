/**
 * StocksTab — Stock dashboard with CoverageTimeline, table, and KPIs.
 */

import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Block, EngineData, MRPResult, MRPSkuViewResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { fmtQty, mono } from '../utils/mrp-helpers';
import type { StockRow } from '../utils/stock-compute';
import { computeStockKPIs, computeStockRows, coverageColor } from '../utils/stock-compute';
import { CoverageTimeline } from './CoverageTimeline';
import { StockKPIPanel } from './StockKPIPanel';

type SortKey = 'sku' | 'stock' | 'final' | 'coverage' | 'deadline';

interface StocksTabProps {
  engine: EngineData;
  mrp: MRPResult;
  skuView: MRPSkuViewResult;
  blocks: Block[];
}

function skuConfidence(row: StockRow): 'complete' | 'partial' {
  return row.ratePerHour > 0 && row.currentStock >= 0 ? 'complete' : 'partial';
}

const RISK_COLORS: Record<string, string> = {
  stockout: 'var(--text-primary)',
  critical: C.rd,
  warning: C.yl,
  ok: C.ac,
};

export function StocksTab({ engine, mrp, skuView, blocks }: StocksTabProps) {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [machineFilter, setMachineFilter] = useState('all');
  const [sortBy, setSortBy] = useState<SortKey>('coverage');
  const [sortAsc, setSortAsc] = useState(true);

  const allRows = useMemo(
    () => computeStockRows(engine, mrp, skuView, blocks),
    [engine, mrp, skuView, blocks],
  );

  const kpis = useMemo(() => computeStockKPIs(allRows), [allRows]);

  const filtered = useMemo(() => {
    let rows = allRows;
    if (machineFilter !== 'all') rows = rows.filter((r) => r.machine === machineFilter);
    if (search) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (r) =>
          r.sku.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q) ||
          r.toolCode.toLowerCase().includes(q) ||
          r.customer.toLowerCase().includes(q),
      );
    }
    const sorted = [...rows];
    sorted.sort((a, b) => {
      let cmp = 0;
      if (sortBy === 'sku') cmp = a.sku.localeCompare(b.sku);
      else if (sortBy === 'stock') cmp = a.currentStock - b.currentStock;
      else if (sortBy === 'final') cmp = a.stockFinalToday - b.stockFinalToday;
      else if (sortBy === 'coverage') cmp = a.coverageDays - b.coverageDays;
      else if (sortBy === 'deadline')
        cmp = (a.nextOrderDeadline ?? '').localeCompare(b.nextOrderDeadline ?? '');
      return sortAsc ? cmp : -cmp;
    });
    return sorted;
  }, [allRows, machineFilter, search, sortBy, sortAsc]);

  function handleSort(key: SortKey) {
    if (sortBy === key) setSortAsc(!sortAsc);
    else {
      setSortBy(key);
      setSortAsc(true);
    }
  }

  const sortIcon = (key: SortKey) => (sortBy === key ? (sortAsc ? ' \u25B2' : ' \u25BC') : '');

  return (
    <>
      <StockKPIPanel kpis={kpis} totalSkus={allRows.length} />

      <CoverageTimeline rows={allRows} />

      <div className="mrp__filters">
        <select
          className="mrp__filter-select"
          value={machineFilter}
          onChange={(e) => setMachineFilter(e.target.value)}
        >
          <option value="all">Todas máquinas</option>
          {engine.machines.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id} ({m.area})
            </option>
          ))}
        </select>
        <input
          className="mrp__filter-input"
          type="text"
          placeholder="Procurar SKU/produto/cliente..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {filtered.length} de {allRows.length} SKUs
        </span>
      </div>

      <div className="mrp__card">
        <table className="mrp__table">
          <thead>
            <tr>
              <th />
              <th style={{ cursor: 'pointer' }} onClick={() => handleSort('sku')}>
                SKU{sortIcon('sku')}
              </th>
              <th>Designação</th>
              <th
                style={{ textAlign: 'right', cursor: 'pointer' }}
                onClick={() => handleSort('stock')}
              >
                Stock Actual{sortIcon('stock')}
              </th>
              <th style={{ textAlign: 'right' }}>Prod. Hoje</th>
              <th
                style={{ textAlign: 'right', cursor: 'pointer' }}
                onClick={() => handleSort('final')}
              >
                Stock Final{sortIcon('final')}
              </th>
              <th style={{ textAlign: 'right' }}>Próx. Enc.</th>
              <th style={{ cursor: 'pointer' }} onClick={() => handleSort('deadline')}>
                Deadline{sortIcon('deadline')}
              </th>
              <th
                style={{ textAlign: 'right', cursor: 'pointer' }}
                onClick={() => handleSort('coverage')}
              >
                Cobertura{sortIcon('coverage')}
              </th>
              <th style={{ textAlign: 'center' }}>Confiança</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => {
              const covColor = coverageColor(row.coverageDays, row.stockoutDay);
              return (
                <tr
                  key={`${row.sku}-${row.toolCode}`}
                  className={row.stockFinalToday < 0 ? 'mrp__row--stockout' : ''}
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/mrp/stock/${encodeURIComponent(row.sku)}`)}
                >
                  <td>
                    <span
                      className="mrp__enc-risk-dot"
                      style={{ background: RISK_COLORS[row.riskLevel] ?? C.t3 }}
                    />
                  </td>
                  <td style={{ ...mono, fontSize: 12, color: C.t1, fontWeight: 600 }}>{row.sku}</td>
                  <td
                    style={{
                      fontSize: 12,
                      color: C.t2,
                      maxWidth: 180,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {row.name}
                  </td>
                  <td style={{ textAlign: 'right', ...mono, fontSize: 12, color: C.t1 }}>
                    {fmtQty(row.currentStock)}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      ...mono,
                      fontSize: 12,
                      color: row.productionToday > 0 ? C.ac : C.t3,
                    }}
                  >
                    {row.productionToday > 0 ? fmtQty(row.productionToday) : '-'}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      ...mono,
                      fontSize: 12,
                      fontWeight: 600,
                      color: row.stockFinalToday < 0 ? C.rd : C.t1,
                    }}
                  >
                    {fmtQty(row.stockFinalToday)}
                  </td>
                  <td style={{ textAlign: 'right', ...mono, fontSize: 12, color: C.t2 }}>
                    {row.nextOrderQty > 0 ? fmtQty(row.nextOrderQty) : '-'}
                  </td>
                  <td style={{ ...mono, fontSize: 12, color: C.t2 }}>
                    {row.nextOrderDeadline ?? '-'}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      fontWeight: 600,
                      ...mono,
                      fontSize: 12,
                      color: covColor,
                    }}
                  >
                    {row.coverageDays}d
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    {(() => {
                      const conf = skuConfidence(row);
                      return (
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            padding: '2px 6px',
                            borderRadius: 3,
                            background: conf === 'complete' ? `${C.ac}18` : `${C.yl}18`,
                            color: conf === 'complete' ? C.ac : C.yl,
                          }}
                        >
                          {conf === 'complete' ? 'Completo' : 'Parcial'}
                        </span>
                      );
                    })()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
            Nenhum SKU encontrado
          </div>
        )}
      </div>
    </>
  );
}

import { Fragment, useMemo } from 'react';
import { Term } from '@/components/Common/Tooltip';
import type { MRPRecord } from '@/domain/mrp/mrp-types';
import { C } from '@/lib/engine';
import { mono } from '../utils/mrp-helpers';
import { MRPRow, type ToolTableTabProps } from './ToolTableTab';

export function MachineTableTab({
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
}: ToolTableTabProps) {
  const stockoutCount = allRecords.filter((r) => r.stockoutDay !== null).length;
  const backlogCount = allRecords.filter((r) => r.backlog > 0).length;

  const grouped = useMemo(() => {
    const map = new Map<string, MRPRecord[]>();
    for (const m of machines) map.set(m.id, []);
    for (const r of records) {
      const arr = map.get(r.machine);
      if (arr) arr.push(r);
    }
    return map;
  }, [records, machines]);

  return (
    <>
      <div className="mrp__filters">
        <select
          className="mrp__filter-select"
          value={filter}
          onChange={(e) => setFilter(e.target.value as 'all' | 'stockout' | 'backlog')}
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
          placeholder="Procurar tool/SKU..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {records.length} de {allRecords.length} registos
        </span>
      </div>
      <div className="mrp__card">
        <table className="mrp__table">
          <thead>
            <tr>
              <th style={{ width: 20 }} />
              <th>Tool</th>
              <th>SKU(s)</th>
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
              <th style={{ textAlign: 'right' }}>
                <Term code="POR" label="POR Total" />
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="Cob." label="Cob." />
              </th>
            </tr>
          </thead>
          <tbody>
            {machines.map((m) => {
              const machineRecs = grouped.get(m.id) || [];
              if (machineRecs.length === 0) return null;
              return (
                <Fragment key={m.id}>
                  <tr className="mrp__machine-header">
                    <td colSpan={7 + dates.length}>
                      <span style={{ ...mono, fontSize: 12, fontWeight: 600, color: C.t1 }}>
                        {m.id}
                      </span>
                      <span style={{ fontSize: 12, color: C.t3, marginLeft: 8 }}>
                        {m.area} · {machineRecs.length} tools
                      </span>
                    </td>
                  </tr>
                  {machineRecs.map((r) => (
                    <MRPRow
                      key={r.toolCode}
                      record={r}
                      isExpanded={expanded.has(r.toolCode)}
                      hasStockout={r.stockoutDay !== null}
                      numDays={dates.length}
                      onToggle={() => toggleExpand(r.toolCode)}
                    />
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {records.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
            Nenhum registo encontrado
          </div>
        )}
      </div>
    </>
  );
}

import { Term } from '@/components/Common/Tooltip';
import type { MRPRecord } from '@/domain/mrp/mrp-types';
import { C } from '@/theme/color-bridge';
import { MRPRow } from './MRPRow';

export type { MRPRowProps } from './MRPRow';
export { MRPRow } from './MRPRow';

type Filter = 'all' | 'stockout' | 'backlog';

export interface ToolTableTabProps {
  records: MRPRecord[];
  allRecords: MRPRecord[];
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
  toggleExpand: (toolCode: string) => void;
}

export function ToolTableTab({
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
              <th style={{ textAlign: 'right' }}>
                <Term code="POR" label="POR Total" />
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="Cob." label="Cob." />
              </th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <MRPRow
                key={r.toolCode}
                record={r}
                isExpanded={expanded.has(r.toolCode)}
                hasStockout={r.stockoutDay !== null}
                numDays={dates.length}
                onToggle={() => toggleExpand(r.toolCode)}
              />
            ))}
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

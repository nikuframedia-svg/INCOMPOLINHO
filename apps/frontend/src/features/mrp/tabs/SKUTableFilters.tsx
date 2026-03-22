import type { MRPSkuViewRecord } from '@/domain/mrp/mrp-types';
import { C } from '@/theme/color-bridge';

type Filter = 'all' | 'stockout' | 'backlog';

interface SKUTableFiltersProps {
  allRecords: MRPSkuViewRecord[];
  filteredCount: number;
  filter: Filter;
  setFilter: (f: Filter) => void;
  machineFilter: string;
  setMachineFilter: (m: string) => void;
  machines: Array<{ id: string; area: string }>;
  search: string;
  setSearch: (s: string) => void;
}

export function SKUTableFilters({
  allRecords,
  filteredCount,
  filter,
  setFilter,
  machineFilter,
  setMachineFilter,
  machines,
  search,
  setSearch,
}: SKUTableFiltersProps) {
  const stockoutCount = allRecords.filter((r) => r.stockoutDay !== null).length;
  const backlogCount = allRecords.filter((r) => r.backlog > 0).length;

  return (
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
        {filteredCount} de {allRecords.length} SKUs
      </span>
    </div>
  );
}

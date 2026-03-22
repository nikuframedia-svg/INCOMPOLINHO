import { C, TC } from '@/theme/color-bridge';
import { Term } from '../../components/Common/Tooltip';
import { useUIStore } from '../../stores/useUIStore';
import type { PecaRow, SortDir, SortField } from './pecas-types';

interface PecasSkuTableProps {
  rows: PecaRow[];
  sortField: SortField;
  sortDir: SortDir;
  onToggleSort: (field: SortField) => void;
}

export function PecasSkuTable({ rows, sortField, sortDir, onToggleSort }: PecasSkuTableProps) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);

  const sortArrow = (f: SortField) => (sortField === f ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  return (
    <div className="pec__table-wrap">
      <table className="pec__table">
        <thead>
          <tr>
            <th onClick={() => onToggleSort('sku')} style={{ cursor: 'pointer' }}>
              SKU{sortArrow('sku')}
            </th>
            <th>Nome</th>
            <th onClick={() => onToggleSort('tool')} style={{ cursor: 'pointer' }}>
              Ferr.{sortArrow('tool')}
            </th>
            <th onClick={() => onToggleSort('machine')} style={{ cursor: 'pointer' }}>
              Máq.{sortArrow('machine')}
            </th>
            <th>Alt.</th>
            <th
              onClick={() => onToggleSort('backlog')}
              style={{ cursor: 'pointer', textAlign: 'right' }}
            >
              <Term code="Backlog" />
              {sortArrow('backlog')}
            </th>
            <th
              onClick={() => onToggleSort('demand')}
              style={{ cursor: 'pointer', textAlign: 'right' }}
            >
              Procura{sortArrow('demand')}
            </th>
            <th
              onClick={() => onToggleSort('stock')}
              style={{ cursor: 'pointer', textAlign: 'right' }}
            >
              Stock{sortArrow('stock')}
            </th>
            <th style={{ textAlign: 'right' }}>
              <Term code="lt" label="Lote" />
            </th>
            <th
              onClick={() => onToggleSort('produced')}
              style={{ cursor: 'pointer', textAlign: 'right' }}
            >
              Prod.{sortArrow('produced')}
            </th>
            <th
              onClick={() => onToggleSort('coverage')}
              style={{ cursor: 'pointer', textAlign: 'right' }}
            >
              <Term code="Cob." label="Cob." />
              {sortArrow('coverage')}
            </th>
            <th
              onClick={() => onToggleSort('pH')}
              style={{ cursor: 'pointer', textAlign: 'right' }}
            >
              <Term code="pH" />
              {sortArrow('pH')}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <PecasTableRow
              key={r.opId}
              row={r}
              onRowClick={() => {
                openContextPanel({ type: 'tool', id: r.tool });
                setFocus({ toolId: r.tool, machine: r.machine });
              }}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface PecasTableRowProps {
  row: PecaRow;
  onRowClick: () => void;
}

function PecasTableRow({ row: r, onRowClick }: PecasTableRowProps) {
  const tColor = TC[r.toolIdx >= 0 ? r.toolIdx % TC.length : 0];
  const covBad = r.coverage < 95;
  const hasBacklog = r.backlog > 0;

  return (
    <tr
      className="pec__table-row--clickable"
      style={{ background: covBad ? C.rdS : hasBacklog ? C.ylS : undefined }}
      onClick={onRowClick}
      data-testid={`pec-row-${r.opId}`}
    >
      <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{r.sku}</td>
      <td
        style={{
          maxWidth: 140,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {r.name}
      </td>
      <td>
        <span style={{ color: tColor, fontFamily: "'JetBrains Mono',monospace" }}>{r.tool}</span>
      </td>
      <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{r.machine}</td>
      <td style={{ fontFamily: "'JetBrains Mono',monospace", color: r.alt ? C.t2 : C.t4 }}>
        {r.alt || '-'}
      </td>
      <td
        style={{
          textAlign: 'right',
          fontWeight: hasBacklog ? 600 : 400,
          color: hasBacklog ? C.yl : undefined,
        }}
      >
        {r.backlog > 0 ? r.backlog.toLocaleString() : ''}
      </td>
      <td style={{ textAlign: 'right' }}>{r.totalDemand.toLocaleString()}</td>
      <td style={{ textAlign: 'right', color: r.stock === 0 ? C.rd : undefined }}>
        {r.stock > 0 ? r.stock.toLocaleString() : '0'}
      </td>
      <td style={{ textAlign: 'right', color: C.t3 }}>
        {r.lotEco > 0 ? r.lotEco.toLocaleString() : '-'}
      </td>
      <td style={{ textAlign: 'right', fontWeight: 600 }}>{r.produced.toLocaleString()}</td>
      <td style={{ textAlign: 'right', fontWeight: 600, color: covBad ? C.rd : C.ac }}>
        {r.coverage.toFixed(0)}%
      </td>
      <td style={{ textAlign: 'right', color: C.t3 }}>{r.pH.toLocaleString()}/h</td>
    </tr>
  );
}

/**
 * OperationsTable — Sortable operation list for Gantt split-pane left panel.
 */

import { useMemo, useState } from 'react';
import type { Block } from '../../../../lib/engine';
import './OperationsTable.css';

interface OperationsTableProps {
  blocks: Block[];
  selectedOpId: string | null;
  onSelectBlock: (block: Block) => void;
  dayIdx: number;
  dates?: string[];
}

type SortKey = 'sku' | 'nm' | 'qty' | 'eddDay' | 'machineId' | 'type' | 'priority';
type SortDir = 'asc' | 'desc';

const TYPE_ORDER: Record<string, number> = { infeasible: 0, overflow: 1, ok: 2, blocked: 3 };

function priorityScore(b: Block): number {
  if (b.eddDay == null) return 999;
  return Math.max(0, b.eddDay - b.dayIdx);
}

function priorityLabel(b: Block): string {
  const slack = b.eddDay != null ? b.eddDay - b.dayIdx : null;
  if (slack == null) return '—';
  if (slack <= 0) return 'Urgente';
  if (slack <= 2) return 'Alta';
  if (slack <= 5) return 'Media';
  return 'Normal';
}

function priorityColor(b: Block): string {
  const slack = b.eddDay != null ? b.eddDay - b.dayIdx : null;
  if (slack == null) return 'var(--text-ghost)';
  if (slack <= 0) return 'var(--semantic-red)';
  if (slack <= 2) return 'var(--semantic-amber)';
  return 'var(--text-secondary)';
}

function typeBadgeClass(type: string): string {
  if (type === 'ok') return 'ops-tbl__badge ops-tbl__badge--ok';
  if (type === 'overflow') return 'ops-tbl__badge ops-tbl__badge--overflow';
  return 'ops-tbl__badge ops-tbl__badge--infeasible';
}

export function OperationsTable({
  blocks,
  selectedOpId,
  onSelectBlock,
  dayIdx,
  dates,
}: OperationsTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('priority');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const dayBlocks = useMemo(
    () => blocks.filter((b) => b.dayIdx === dayIdx && b.type !== 'blocked'),
    [blocks, dayIdx],
  );

  const sorted = useMemo(() => {
    const arr = [...dayBlocks];
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'sku':
          cmp = a.sku.localeCompare(b.sku);
          break;
        case 'nm':
          cmp = a.nm.localeCompare(b.nm);
          break;
        case 'qty':
          cmp = a.qty - b.qty;
          break;
        case 'eddDay':
          cmp = (a.eddDay ?? 999) - (b.eddDay ?? 999);
          break;
        case 'machineId':
          cmp = a.machineId.localeCompare(b.machineId);
          break;
        case 'type':
          cmp = (TYPE_ORDER[a.type] ?? 9) - (TYPE_ORDER[b.type] ?? 9);
          break;
        case 'priority':
          cmp = priorityScore(a) - priorityScore(b);
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return arr;
  }, [dayBlocks, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function sortArrow(key: SortKey): string {
    if (sortKey !== key) return '';
    return sortDir === 'asc' ? ' ▲' : ' ▼';
  }

  return (
    <div className="ops-tbl">
      <table className="ops-tbl__table">
        <thead>
          <tr>
            <th onClick={() => handleSort('sku')}>
              SKU<span className="ops-tbl__sort-arrow">{sortArrow('sku')}</span>
            </th>
            <th onClick={() => handleSort('nm')}>
              Cliente<span className="ops-tbl__sort-arrow">{sortArrow('nm')}</span>
            </th>
            <th onClick={() => handleSort('qty')}>
              Qtd<span className="ops-tbl__sort-arrow">{sortArrow('qty')}</span>
            </th>
            <th onClick={() => handleSort('eddDay')}>
              Deadline<span className="ops-tbl__sort-arrow">{sortArrow('eddDay')}</span>
            </th>
            <th onClick={() => handleSort('machineId')}>
              Maq<span className="ops-tbl__sort-arrow">{sortArrow('machineId')}</span>
            </th>
            <th onClick={() => handleSort('type')}>
              Estado<span className="ops-tbl__sort-arrow">{sortArrow('type')}</span>
            </th>
            <th onClick={() => handleSort('priority')}>
              Prior.<span className="ops-tbl__sort-arrow">{sortArrow('priority')}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((b, i) => (
            <tr
              key={`${b.opId}_${b.startMin}_${i}`}
              className={`ops-tbl__row${selectedOpId === b.opId ? ' ops-tbl__row--selected' : ''}`}
              onClick={() => onSelectBlock(b)}
            >
              <td title={b.sku}>{b.sku}</td>
              <td title={b.nm}>{b.nm}</td>
              <td>{b.qty.toLocaleString()}</td>
              <td>{b.eddDay != null && dates ? (dates[b.eddDay] ?? `d${b.eddDay}`) : '—'}</td>
              <td>{b.machineId}</td>
              <td>
                <span className={typeBadgeClass(b.type)}>{b.type}</span>
              </td>
              <td style={{ color: priorityColor(b) }}>{priorityLabel(b)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div style={{ textAlign: 'center', padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>
          Sem operações neste dia.
        </div>
      )}
    </div>
  );
}

/**
 * OrderTableRow — Expandable order row with PeggingTree for OrdersPage.
 */

import type { Block, EngineData } from '@/lib/engine';
import { C } from '@/lib/engine';
import { fmtQty, mono } from '../utils/mrp-helpers';
import type { OrderEntry } from '../utils/orders-compute';
import { PeggingTree } from './PeggingTree';

const STATUS_CFG: Record<string, { label: string; color: string; bg: string }> = {
  done: { label: 'Concluída', color: C.ac, bg: `${C.ac}18` },
  'on-time': { label: 'On-time', color: C.ac, bg: `${C.ac}18` },
  'at-risk': { label: 'At-risk', color: C.yl, bg: `${C.yl}18` },
  late: { label: 'Late', color: C.rd, bg: `${C.rd}18` },
};

export function OrderTableRow({
  entry: e,
  isSelected,
  onSelect,
  engine,
  blocks,
}: {
  entry: OrderEntry;
  isSelected: boolean;
  onSelect: () => void;
  engine: EngineData;
  blocks: Block[];
}) {
  const cfg = STATUS_CFG[e.status] ?? STATUS_CFG['on-time'];

  return (
    <>
      <tr
        style={{ cursor: 'pointer' }}
        onClick={onSelect}
        className={e.status === 'late' ? 'mrp__row--stockout' : ''}
      >
        <td>
          <span style={{ ...mono, fontSize: 12, fontWeight: 600, color: C.t1 }}>{e.sku}</span>
          {e.isTwin && <span style={{ fontSize: 12, color: C.yl, marginLeft: 4 }}>Twin</span>}
        </td>
        <td style={{ textAlign: 'right', ...mono, fontSize: 12, color: C.t1 }}>
          {fmtQty(e.orderQty)}
        </td>
        <td style={{ ...mono, fontSize: 12, color: C.t2 }}>{e.deadline ?? '-'}</td>
        <td style={{ ...mono, fontSize: 12, color: e.gapDays > 0 ? C.rd : C.t2 }}>
          {e.scheduledEndDate ?? '-'}
        </td>
        <td>
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              padding: '2px 6px',
              borderRadius: 3,
              background: cfg.bg,
              color: cfg.color,
            }}
          >
            {cfg.label}
          </span>
        </td>
        <td
          style={{
            textAlign: 'right',
            ...mono,
            fontSize: 12,
            fontWeight: 600,
            color: e.gapDays > 0 ? C.rd : e.gapDays < 0 ? C.ac : C.t3,
          }}
        >
          {e.gapDays !== 0 ? `${e.gapDays > 0 ? '+' : ''}${e.gapDays}d` : '-'}
        </td>
      </tr>
      {isSelected && (
        <tr className="mrp__detail-row">
          <td colSpan={6}>
            <PeggingTree entry={e} engine={engine} blocks={blocks} />
          </td>
        </tr>
      )}
    </>
  );
}

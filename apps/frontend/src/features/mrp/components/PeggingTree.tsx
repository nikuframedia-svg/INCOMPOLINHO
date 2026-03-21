/**
 * PeggingTree — Visual 3-level tree for order pegging.
 * Level 1: Order (customer, qty, deadline)
 * Level 2: Production runs (machine, qty, day)
 * Level 3: Tool + completion status
 */

import type { Block, EngineData } from '@/lib/engine';
import { C, getBlockQtyForOp, getBlocksForOp } from '@/lib/engine';
import { fmtQty, mono } from '../utils/mrp-helpers';
import type { OrderEntry } from '../utils/orders-compute';

interface PeggingTreeProps {
  entry: OrderEntry;
  engine: EngineData;
  blocks: Block[];
}

export function PeggingTree({ entry, engine, blocks }: PeggingTreeProps) {
  const opBlocks = getBlocksForOp(blocks, entry.opId).filter((b) => b.type !== 'blocked');
  const isLate = entry.status === 'late';

  return (
    <div style={{ padding: '12px 16px', fontSize: 12 }}>
      {/* Level 1: Order */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span style={{ fontSize: 14 }}>📦</span>
        <span style={{ fontWeight: 700, color: C.t1 }}>Encomenda {entry.sku}</span>
        <span style={{ color: C.t2 }}>{entry.customerName ?? 'Sem cliente'}</span>
        <span style={{ ...mono, color: C.t2 }}>{fmtQty(entry.orderQty)} pcs</span>
        {entry.deadline && (
          <span style={{ ...mono, color: isLate ? C.rd : C.t2 }}>deadline {entry.deadline}</span>
        )}
        {entry.isTwin && (
          <span style={{ fontSize: 12, color: C.yl, fontWeight: 600 }}>Twin: {entry.twinSku}</span>
        )}
      </div>

      {/* Level 2: Production runs */}
      {opBlocks.length === 0 ? (
        <div style={{ paddingLeft: 28, color: C.rd, fontWeight: 500 }}>Sem produção agendada</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {opBlocks.map((block, i) => {
            const qty = getBlockQtyForOp(block, entry.opId);
            const dateLabel = engine.dates[block.dayIdx] ?? `D${block.dayIdx}`;
            const blockLate = entry.deadlineDayIdx != null && block.dayIdx > entry.deadlineDayIdx;

            return (
              <div key={`${block.dayIdx}-${i}`} style={{ paddingLeft: 20 }}>
                {/* Connector line */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 6,
                    borderLeft: `2px solid ${blockLate ? C.rd : `${C.t4}44`}`,
                    paddingLeft: 12,
                    paddingBottom: 6,
                  }}
                >
                  <div style={{ flex: 1 }}>
                    {/* Level 2: Production block */}
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        marginBottom: 3,
                      }}
                    >
                      <span style={{ fontSize: 12 }}>🏭</span>
                      <span style={{ fontWeight: 600, color: blockLate ? C.rd : C.t1 }}>
                        OP {entry.opId.slice(0, 12)}
                      </span>
                      <span style={{ ...mono, color: C.t2 }}>{block.machineId}</span>
                      <span style={{ ...mono, color: C.ac }}>{fmtQty(qty)} pcs</span>
                      <span style={{ ...mono, color: blockLate ? C.rd : C.t2 }}>{dateLabel}</span>
                      {blockLate && (
                        <span style={{ fontSize: 12, color: C.rd, fontWeight: 600 }}>ATRASADO</span>
                      )}
                    </div>

                    {/* Level 3: Tool + completion */}
                    <div
                      style={{
                        display: 'flex',
                        gap: 12,
                        paddingLeft: 22,
                        color: C.t3,
                        fontSize: 12,
                      }}
                    >
                      <span>🔧 {block.toolId}</span>
                      <span>
                        📅 Conclusão: {dateLabel} {blockLate ? '❌' : '✅'}
                      </span>
                    </div>

                    {/* Twin outputs */}
                    {block.isTwinProduction && block.outputs && block.outputs.length > 1 && (
                      <div
                        style={{
                          paddingLeft: 22,
                          marginTop: 3,
                          fontSize: 12,
                          color: C.yl,
                        }}
                      >
                        Co-produção:{' '}
                        {block.outputs.map((o) => `${o.sku} (${fmtQty(o.qty)})`).join(' + ')}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Summary footer */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          marginTop: 8,
          paddingTop: 6,
          borderTop: `1px solid ${C.bd}`,
          fontSize: 12,
          color: C.t3,
        }}
      >
        <span>
          Total agendado:{' '}
          <span style={{ ...mono, color: C.t1, fontWeight: 600 }}>
            {fmtQty(entry.totalScheduledQty)}
          </span>
        </span>
        {entry.shortfallQty > 0 && (
          <span>
            Deficit:{' '}
            <span style={{ ...mono, color: C.rd, fontWeight: 600 }}>
              {fmtQty(entry.shortfallQty)}
            </span>
          </span>
        )}
        {entry.gapDays !== 0 && (
          <span>
            Gap:{' '}
            <span
              style={{
                ...mono,
                color: entry.gapDays > 0 ? C.rd : C.ac,
                fontWeight: 600,
              }}
            >
              {entry.gapDays > 0 ? '+' : ''}
              {entry.gapDays}d
            </span>
          </span>
        )}
      </div>
    </div>
  );
}

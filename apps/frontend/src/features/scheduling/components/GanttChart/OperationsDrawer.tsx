/**
 * OperationsDrawer — Ant Design Drawer wrapping OperationsTable.
 * Opens from right side, showing sortable operation list for current day.
 */

import { Drawer } from 'antd';
import { useMemo } from 'react';
import type { Block } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { OperationsTable } from './OperationsTable';

export function OperationsDrawer({
  open,
  onClose,
  blocks,
  dayIdx,
  dates,
  dnames,
  onSelectBlock,
  selectedOpId,
}: {
  open: boolean;
  onClose: () => void;
  blocks: Block[];
  dayIdx: number;
  dates: string[];
  dnames: string[];
  onSelectBlock: (block: Block) => void;
  selectedOpId: string | null;
}) {
  const dayBlocks = useMemo(
    () => blocks.filter((b) => b.dayIdx === dayIdx && b.type !== 'blocked'),
    [blocks, dayIdx],
  );
  const machineCount = useMemo(
    () => new Set(dayBlocks.map((b) => b.machineId)).size,
    [dayBlocks],
  );

  return (
    <Drawer
      title={
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>
            Operações planeadas — {dnames[dayIdx]} {dates[dayIdx]}
          </div>
          <div style={{ fontSize: 12, color: C.t3, fontWeight: 400 }}>
            {dayBlocks.length} operações · {machineCount} máquinas
          </div>
        </div>
      }
      open={open}
      onClose={onClose}
      size="large"
      placement="right"
      styles={{ body: { padding: 0 }, wrapper: { width: 540 } }}
    >
      <OperationsTable
        blocks={blocks}
        selectedOpId={selectedOpId}
        onSelectBlock={onSelectBlock}
        dayIdx={dayIdx}
        dates={dates}
      />
    </Drawer>
  );
}

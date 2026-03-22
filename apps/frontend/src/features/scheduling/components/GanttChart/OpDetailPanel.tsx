import { X } from 'lucide-react';
import type { Block, DayLoad, EMachine, EOp, ETool } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { toolColor } from '../atoms';
import { ActionsSection, MachineSection } from './OpDetailMachine';
import {
  ProductionSection,
  SetupSection,
  StockSection,
  TwinSection,
  WeeklyChartSection,
} from './OpDetailSections';

export function OpDetailPanel({
  block: b,
  tool,
  op,
  dayLoad,
  dnames,
  selDay,
  machines,
  mSt,
  tools,
  onMove,
  onUndo,
  onClose,
}: {
  block: Block;
  tool: ETool | undefined;
  op: EOp | undefined;
  dayLoad: DayLoad | undefined;
  dnames: string[];
  selDay: number;
  machines: EMachine[];
  mSt: Record<string, string>;
  tools: ETool[];
  onMove: (opId: string, toM: string) => void;
  onUndo: (opId: string) => void;
  onClose: () => void;
}) {
  const col = toolColor(tools, b.toolId);
  const mc = machines.find((m) => m.id === b.machineId);

  return (
    <div
      style={{
        width: 320,
        minWidth: 320,
        background: C.s2,
        border: `1px solid ${C.bd}`,
        borderRadius: 8,
        overflow: 'hidden',
        alignSelf: 'flex-start',
        maxHeight: 520,
        overflowY: 'auto',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 14px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
        }}
      >
        <div>
          <div style={{ fontSize: 13, fontWeight: 600, color: col }}>
            {b.toolId} <span style={{ color: C.t2, fontWeight: 500 }}>—</span>{' '}
            <span style={{ color: C.t1 }}>{b.sku}</span>
          </div>
          <div style={{ fontSize: 12, color: C.t2, marginTop: 2 }}>{b.nm}</div>
          <div style={{ fontSize: 12, color: C.t3, marginTop: 2 }}>
            <span style={{ fontWeight: 600, fontFamily: 'monospace', color: C.t1 }}>
              {b.machineId}
            </span>
            {mc && <span> · {mc.area}</span>}
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: C.t3,
            cursor: 'pointer',
            fontSize: 16,
            padding: '0 2px',
            fontFamily: 'inherit',
            lineHeight: 1,
          }}
        >
          <X size={14} strokeWidth={2} />
        </button>
      </div>

      <ProductionSection block={b} tool={tool} />
      <TwinSection block={b} col={col} />
      <SetupSection block={b} />
      <StockSection block={b} />
      {op && <WeeklyChartSection op={op} dnames={dnames} selDay={selDay} />}
      <MachineSection block={b} machines={machines} mSt={mSt} dayLoad={dayLoad} />
      <ActionsSection block={b} mSt={mSt} onMove={onMove} onUndo={onUndo} />
    </div>
  );
}

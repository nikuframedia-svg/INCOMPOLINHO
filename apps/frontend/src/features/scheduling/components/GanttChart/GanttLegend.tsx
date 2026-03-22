import { Layers, Lock } from 'lucide-react';
import type { Block, ETool } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Tag, toolColor } from '../atoms';

export function GanttLegend({
  dayB,
  dayBlkN,
  tools,
}: {
  dayB: Block[];
  dayBlkN: number;
  tools: ETool[];
}) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 6,
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 12,
        color: C.t3,
        padding: '4px 0',
      }}
    >
      {[...new Set(dayB.map((b) => b.toolId))].slice(0, 14).map((tid) => (
        <div key={tid} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
          <div
            style={{ width: 8, height: 8, borderRadius: 2, background: toolColor(tools, tid) }}
          />
          <span style={{ fontFamily: 'monospace' }}>{tid}</span>
        </div>
      ))}
      <span style={{ width: 1, height: 12, background: C.bd }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <div
          style={{
            width: 14,
            height: 8,
            borderRadius: 2,
            background: `repeating-linear-gradient(45deg,${C.t3}40,${C.t3}40 2px,${C.t3}70 2px,${C.t3}70 4px)`,
          }}
        />
        <span>Setup</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <div style={{ width: 14, height: 8, borderRadius: 2, border: `2px dashed ${C.rd}88` }} />
        <span>Congelado</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <Layers size={9} strokeWidth={1.5} style={{ color: C.t3 }} />
        <span>Co-produção</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
        <Lock size={9} strokeWidth={1.5} style={{ color: C.rd }} />
        <span>Frozen</span>
      </div>
      {dayBlkN > 0 && <Tag color={C.rd}>{dayBlkN} bloqueadas</Tag>}
    </div>
  );
}

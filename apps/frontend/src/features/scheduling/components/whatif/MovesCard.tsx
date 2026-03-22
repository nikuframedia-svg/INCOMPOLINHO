import { ArrowRight } from 'lucide-react';
import type { EOp, ETool, OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Card, Tag, toolColor } from '../atoms';

export function MovesCard({
  scenario: s,
  rc,
  ops,
  tools,
  moveable,
}: {
  scenario: OptResult;
  rc: string;
  ops: EOp[];
  tools: ETool[];
  moveable: Array<{ opId: string }>;
}) {
  return (
    <Card style={{ padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Movimentos <Tag color={rc}>{s.moves.length}</Tag>
      </div>
      {s.moves.length === 0 ? (
        <div style={{ fontSize: 12, color: C.t4, padding: 12, textAlign: 'center' }}>
          Sem movimentos — plano original
        </div>
      ) : (
        s.moves.map((mv, i) => {
          const op = ops.find((o) => o.id === mv.opId);
          return (
            <div
              key={i}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '5px 0',
                borderBottom: i < s.moves.length - 1 ? `1px solid ${C.bd}` : 'none',
              }}
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: toolColor(tools, op?.t || ''),
                  fontFamily: 'monospace',
                  minWidth: 52,
                }}
              >
                {op?.t}
              </span>
              <span
                style={{
                  fontSize: 12,
                  color: C.rd,
                  fontFamily: 'monospace',
                  textDecoration: 'line-through',
                }}
              >
                {op?.m}
              </span>
              <span
                style={{ color: rc, fontWeight: 600, display: 'inline-flex', alignItems: 'center' }}
              >
                <ArrowRight size={12} strokeWidth={1.5} />
              </span>
              <span style={{ fontSize: 12, color: rc, fontFamily: 'monospace', fontWeight: 600 }}>
                {mv.toM}
              </span>
              <span
                style={{
                  flex: 1,
                  fontSize: 12,
                  color: C.t3,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {op?.nm}
              </span>
            </div>
          );
        })
      )}
      {moveable.length > 0 && (
        <div
          style={{
            fontSize: 12,
            color: C.t4,
            marginTop: 6,
            padding: '6px 0',
            borderTop: `1px solid ${C.bd}`,
          }}
        >
          {moveable.length} operações movíveis ·{' '}
          {moveable.filter((m) => s.moves.find((mv) => mv.opId === m.opId)).length} movidas
        </div>
      )}
    </Card>
  );
}

/**
 * ResourceDownCard — Machine/tool down status management.
 */
import { Undo2, Zap } from 'lucide-react';
import type { MoveAction, ReplanProposal } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { Card, dot, Pill } from '../atoms';

export function ResourceDownCard({
  machines,
  tools,
  focusIds,
  mSt,
  tSt,
  editingDown,
  setEditingDown,
  blockCountByMachine,
  getResourceDownDays,
  clearResourceDown,
  moves,
  undoMove,
  applyMove,
  onApplyAndSave,
  isSaving,
  decs,
}: {
  machines: { id: string; area: string }[];
  tools: { id: string; m: string; alt?: string }[];
  focusIds: string[];
  mSt: Record<string, string>;
  tSt: Record<string, string>;
  editingDown: { type: 'machine' | 'tool'; id: string } | null;
  setEditingDown: React.Dispatch<
    React.SetStateAction<{ type: 'machine' | 'tool'; id: string } | null>
  >;
  blockCountByMachine: Record<string, number>;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  moves: MoveAction[];
  undoMove: (opId: string) => void;
  applyMove: (opId: string, toM: string) => void;
  onApplyAndSave?: () => void;
  isSaving?: boolean;
  decs: ReplanProposal[];
  dates: string[];
  dnames: string[];
  wdi: number[];
  downStartDay: number;
  downEndDay: number;
  setDownStartDay: React.Dispatch<React.SetStateAction<number>>;
  setDownEndDay: React.Dispatch<React.SetStateAction<number>>;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
}) {
  const rp = decs.filter((d) => d.type === 'replan');

  return (
    <Card style={{ padding: 16 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, color: C.t1 }}>
          Replaneamento{' '}
          <span style={{ fontSize: 12, color: C.t4, fontWeight: 400 }}>Remove & Repair</span>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {moves.length > 0 && (
            <Pill color={C.rd} active onClick={() => moves.forEach((m) => undoMove(m.opId))}>
              <Undo2
                size={10}
                strokeWidth={1.5}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />{' '}
              Todos ({moves.length})
            </Pill>
          )}
          {rp.length > 0 && (
            <Pill
              color={C.ac}
              active
              onClick={() => rp.forEach((d) => d.action && applyMove(d.action.opId, d.action.toM))}
            >
              <Zap
                size={10}
                strokeWidth={1.5}
                style={{ display: 'inline', verticalAlign: 'middle' }}
              />{' '}
              Auto ({rp.length})
            </Pill>
          )}
          {moves.length > 0 && onApplyAndSave && (
            <button
              onClick={onApplyAndSave}
              disabled={isSaving}
              style={{
                padding: '5px 14px',
                borderRadius: 8,
                border: 'none',
                cursor: isSaving ? 'wait' : 'pointer',
                background: C.ac,
                color: C.bg,
                fontSize: 12,
                fontWeight: 600,
                fontFamily: 'inherit',
                opacity: isSaving ? 0.6 : 1,
              }}
            >
              {isSaving ? 'A guardar...' : `Aplicar & Guardar (${moves.length})`}
            </button>
          )}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.t3, marginBottom: 6 }}>Máquinas</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {machines.map((m) => {
            const isD = mSt[m.id] === 'down';
            const n = blockCountByMachine[m.id] ?? 0;
            const mDownDays = getResourceDownDays('machine', m.id);
            return (
              <button
                key={m.id}
                onClick={() => {
                  if (mDownDays.size > 0) {
                    clearResourceDown('machine', m.id);
                    setEditingDown(null);
                  } else {
                    setEditingDown(
                      editingDown?.type === 'machine' && editingDown.id === m.id
                        ? null
                        : { type: 'machine', id: m.id },
                    );
                  }
                }}
                style={{
                  padding: '6px 10px',
                  borderRadius: 8,
                  cursor: 'pointer',
                  textAlign: 'center',
                  minWidth: 80,
                  background: isD
                    ? C.rdS
                    : editingDown?.type === 'machine' && editingDown.id === m.id
                      ? `${C.ac}12`
                      : 'transparent',
                  border: `1.5px solid ${isD ? C.rd + '44' : editingDown?.type === 'machine' && editingDown.id === m.id ? C.ac + '44' : C.bd}`,
                  fontFamily: 'inherit',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 4,
                  }}
                >
                  <span style={dot(isD ? C.rd : C.ac, isD)} />
                  <span style={{ fontSize: 12, fontWeight: 600, color: isD ? C.rd : C.ac }}>
                    {mDownDays.size > 0 ? `DOWN ${mDownDays.size}d` : 'RUN'}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: isD ? C.rd : C.t1,
                    fontFamily: 'monospace',
                    marginTop: 2,
                  }}
                >
                  {m.id}
                </div>
                <div style={{ fontSize: 12, color: C.t4 }}>
                  {m.area} · {n} ops
                </div>
              </button>
            );
          })}
        </div>
      </div>
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.t3, marginBottom: 5 }}>
          Ferramentas
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
          {tools
            .filter(
              (t) => focusIds.includes(t.m) || (t.alt && t.alt !== '-' && focusIds.includes(t.alt)),
            )
            .map((t) => {
              const tDownDays = getResourceDownDays('tool', t.id);
              return (
                <Pill
                  key={t.id}
                  active={tSt[t.id] === 'down'}
                  color={C.rd}
                  onClick={() => {
                    if (tDownDays.size > 0) {
                      clearResourceDown('tool', t.id);
                      setEditingDown(null);
                    } else {
                      setEditingDown(
                        editingDown?.type === 'tool' && editingDown.id === t.id
                          ? null
                          : { type: 'tool', id: t.id },
                      );
                    }
                  }}
                  size="sm"
                >
                  {t.id}
                  {tDownDays.size > 0 ? ` ${tDownDays.size}d` : ''}
                </Pill>
              );
            })}
        </div>
      </div>
    </Card>
  );
}

import { Sparkles, Undo2 } from 'lucide-react';
import type { Block, DayLoad, EMachine } from '@/domain/types/scheduling';
import { DAY_CAP } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { dot } from '../atoms';
import { Row, Sec } from './OpDetailAtoms';

/* ── Machine Info + Utilization Bar ── */
export function MachineSection({
  block: b,
  machines: _machines,
  mSt,
  dayLoad,
}: {
  block: Block;
  machines: EMachine[];
  mSt: Record<string, string>;
  dayLoad: DayLoad | undefined;
}) {
  const total = dayLoad ? dayLoad.prod + dayLoad.setup : 0;
  const util = total / DAY_CAP;

  return (
    <Sec label="Máquina">
      <Row k="Primária" v={b.origM} />
      {b.hasAlt && b.altM && <Row k="Alternativa" v={b.altM} />}
      <Row
        k="Estado"
        v={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span
              style={dot(mSt[b.machineId] === 'down' ? C.rd : C.ac, mSt[b.machineId] === 'down')}
            />
            {mSt[b.machineId] === 'down' ? 'DOWN' : 'RUN'}
          </span>
        }
        color={mSt[b.machineId] === 'down' ? C.rd : C.ac}
      />
      {total > 0 && (
        <>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '2px 0',
              marginTop: 2,
            }}
          >
            <span style={{ fontSize: 12, color: C.t3 }}>Utilização</span>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: util > 1 ? C.rd : util > 0.85 ? C.yl : C.ac,
                fontFamily: 'monospace',
              }}
            >
              {(util * 100).toFixed(0)}%
            </span>
          </div>
          <div
            style={{
              height: 4,
              background: C.bg,
              borderRadius: 2,
              overflow: 'hidden',
              marginTop: 2,
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${Math.min(util * 100, 100)}%`,
                background: util > 1 ? C.rd : util > 0.85 ? C.yl : C.ac,
                borderRadius: 2,
              }}
            />
          </div>
        </>
      )}
    </Sec>
  );
}

/* ── Actions (Move / Undo) ── */
export function ActionsSection({
  block: b,
  mSt,
  onMove,
  onUndo,
}: {
  block: Block;
  mSt: Record<string, string>;
  onMove: (opId: string, toM: string) => void;
  onUndo: (opId: string) => void;
}) {
  return (
    <div style={{ padding: '10px 14px' }}>
      {b.moved && (
        <div style={{ marginBottom: 8 }}>
          <div
            style={{
              fontSize: 12,
              color: C.ac,
              fontWeight: 600,
              marginBottom: 6,
              display: 'flex',
              alignItems: 'center',
              gap: 3,
            }}
          >
            <Sparkles size={10} strokeWidth={1.5} /> Replaneado de {b.origM}
          </div>
          <button
            onClick={() => onUndo(b.opId)}
            style={{
              width: '100%',
              padding: '7px 0',
              borderRadius: 6,
              border: `1px solid ${C.yl}33`,
              background: C.ylS,
              color: C.yl,
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            <Undo2
              size={10}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle' }}
            />{' '}
            Desfazer
          </button>
        </div>
      )}
      {!b.moved && b.hasAlt && b.altM && mSt[b.altM] !== 'down' && (
        <button
          onClick={() => onMove(b.opId, b.altM!)}
          style={{
            width: '100%',
            padding: '7px 0',
            borderRadius: 6,
            border: 'none',
            background: C.ac,
            color: C.bg,
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Mover para {b.altM}
        </button>
      )}
    </div>
  );
}

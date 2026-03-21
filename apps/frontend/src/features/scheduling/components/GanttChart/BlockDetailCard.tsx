/**
 * BlockDetailCard — Glass overlay card for clicked Gantt block details.
 * ISA-101: color + icon + text, never color alone.
 * Replaces OpDetailPanel with a compact positioned overlay.
 */

import { Layers, Sparkles, Undo2, X } from 'lucide-react';
import type { Block, ETool } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { fmtT, toolColor } from '../atoms';

export function BlockDetailCard({
  block: b,
  tool,
  mSt,
  tools,
  onMove,
  onUndo,
  onClose,
}: {
  block: Block;
  tool: ETool | undefined;
  mSt: Record<string, string>;
  tools: ETool[];
  onMove: (opId: string, toM: string) => void;
  onUndo: (opId: string) => void;
  onClose: () => void;
}) {
  const col = toolColor(tools, b.toolId);
  const dur = Math.round(b.endMin - b.startMin);
  const setupDur =
    b.setupS != null && b.setupE != null ? Math.round(b.setupE - b.setupS) : null;

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'absolute',
        top: 8,
        right: 8,
        width: 300,
        background: `${C.s2}F2`,
        backdropFilter: 'blur(12px)',
        border: `1px solid ${C.bd}`,
        borderRadius: 10,
        boxShadow: '0 8px 32px #00000040',
        zIndex: 50,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '10px 12px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          borderBottom: `1px solid ${C.bd}`,
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: col }}>
            {b.toolId} <span style={{ color: C.t2 }}>—</span>{' '}
            <span style={{ color: C.t1 }}>{b.sku}</span>
          </div>
          <div style={{ fontSize: 12, color: C.t2, marginTop: 2 }}>{b.nm}</div>
          <div style={{ fontSize: 12, color: C.t3, marginTop: 1 }}>
            <span style={{ fontWeight: 600, fontFamily: 'monospace', color: C.t1 }}>
              {b.machineId}
            </span>
            {' · '}
            <span style={{ color: mSt[b.machineId] === 'down' ? C.rd : C.ac }}>
              {mSt[b.machineId] === 'down' ? 'Parada' : 'A produzir'}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: C.t3,
            cursor: 'pointer',
            padding: '0 2px',
            fontFamily: 'inherit',
          }}
        >
          <X size={14} strokeWidth={2} />
        </button>
      </div>

      {/* Production details */}
      <div
        style={{
          padding: '8px 12px',
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '3px 12px',
          fontSize: 12,
        }}
      >
        <KV k="Quantidade" v={`${b.qty.toLocaleString()} pcs`} />
        {tool && <KV k="Velocidade" v={`${tool.pH.toLocaleString()} pç/h`} />}
        <KV k="Duração" v={`${dur} min`} />
        <KV k="Operadores" v={String(b.operators)} />
        <KV k="Início" v={fmtT(b.startMin)} />
        <KV k="Fim" v={fmtT(b.endMin)} />
        {setupDur != null && <KV k="Setup" v={`${setupDur} min`} />}
        <KV
          k="Turno"
          v={b.shift === 'Z' ? 'Noite' : b.shift === 'X' ? 'Manhã' : 'Tarde'}
        />
        {b.eddDay != null && (
          <KV
            k="Deadline"
            v={`Dia ${b.eddDay}`}
            color={b.eddDay <= b.dayIdx ? C.rd : undefined}
          />
        )}
      </div>

      {/* Status alerts */}
      {(b.type === 'blocked' || b.overflow) && (
        <div style={{ padding: '0 12px 6px' }}>
          {b.type === 'blocked' && (
            <div style={{ fontSize: 12, color: C.rd, fontWeight: 600 }}>
              BLOQUEADA — {b.reason === 'tool_down' ? 'ferramenta avariada' : 'máquina parada'}
            </div>
          )}
          {b.overflow && (
            <div style={{ fontSize: 12, color: C.yl, fontWeight: 600 }}>
              OVERFLOW — +{b.overflowMin?.toFixed(0)}min além do turno
            </div>
          )}
        </div>
      )}

      {/* Twin co-production */}
      {b.isTwinProduction && b.outputs && (
        <div style={{ padding: '6px 12px', borderTop: `1px solid ${C.bd}` }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: col,
              display: 'flex',
              alignItems: 'center',
              gap: 3,
              marginBottom: 4,
            }}
          >
            <Layers size={10} strokeWidth={1.5} /> Co-Produção
          </div>
          {b.outputs.map((o, i) => (
            <div key={i} style={{ fontSize: 12, color: C.t2 }}>
              {o.sku} —{' '}
              <span style={{ color: C.t1, fontWeight: 600 }}>
                {o.qty.toLocaleString()} pcs
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      <div
        style={{
          padding: '8px 12px',
          borderTop: `1px solid ${C.bd}`,
          display: 'flex',
          gap: 6,
          alignItems: 'center',
        }}
      >
        {b.moved ? (
          <>
            <div
              style={{
                fontSize: 12,
                color: C.ac,
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 3,
              }}
            >
              <Sparkles size={9} strokeWidth={1.5} /> Replaneado de {b.origM}
            </div>
            <button
              type="button"
              onClick={() => onUndo(b.opId)}
              style={{
                marginLeft: 'auto',
                padding: '4px 10px',
                borderRadius: 5,
                border: `1px solid ${C.yl}33`,
                background: C.ylS,
                color: C.yl,
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'inherit',
                display: 'flex',
                alignItems: 'center',
                gap: 3,
              }}
            >
              <Undo2 size={9} strokeWidth={1.5} /> Desfazer
            </button>
          </>
        ) : b.hasAlt && b.altM && mSt[b.altM] !== 'down' ? (
          <button
            type="button"
            onClick={() => onMove(b.opId, b.altM!)}
            style={{
              flex: 1,
              padding: '5px 0',
              borderRadius: 5,
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
        ) : null}
      </div>
    </div>
  );
}

function KV({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <div>
      <span style={{ color: C.t3 }}>{k}</span>{' '}
      <span
        style={{
          color: color || C.t1,
          fontWeight: 600,
          fontFamily: "'JetBrains Mono',monospace",
        }}
      >
        {v}
      </span>
    </div>
  );
}

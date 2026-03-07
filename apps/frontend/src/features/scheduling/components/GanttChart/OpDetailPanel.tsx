import { Layers, Sparkles, Undo2, X } from 'lucide-react';
import type React from 'react';
import type { Block, DayLoad, EMachine, EOp, ETool } from '../../../../lib/engine';
import { C, DAY_CAP } from '../../../../lib/engine';
import { dot, fmtT, toolColor } from '../atoms';

export default function OpDetailPanel({
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
  const Sec = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div style={{ borderTop: `1px solid ${C.bd}`, padding: '10px 14px' }}>
      <div
        style={{
          fontSize: 9,
          fontWeight: 600,
          color: C.t4,
          letterSpacing: '.06em',
          textTransform: 'uppercase',
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
  const Row = ({ k, v, color }: { k: string; v: React.ReactNode; color?: string }) => (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        padding: '2px 0',
      }}
    >
      <span style={{ fontSize: 10, color: C.t3 }}>{k}</span>
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: color || C.t1,
          fontFamily: "'JetBrains Mono',monospace",
        }}
      >
        {v}
      </span>
    </div>
  );
  const col = toolColor(tools, b.toolId);
  const mc = machines.find((m) => m.id === b.machineId);
  const total = dayLoad ? dayLoad.prod + dayLoad.setup : 0;
  const util = total / DAY_CAP;
  const maxQty = op ? Math.max(...op.d, 1) : 1;

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
          <div style={{ fontSize: 11, color: C.t2, marginTop: 2 }}>{b.nm}</div>
          <div style={{ fontSize: 10, color: C.t3, marginTop: 2 }}>
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

      {/* Production */}
      <Sec label="Produção">
        <Row k="Quantidade" v={`${b.qty.toLocaleString()} pcs`} />
        <Row k="Tempo" v={`${(b.endMin - b.startMin).toFixed(0)} min`} />
        <Row k="Início" v={fmtT(b.startMin)} />
        <Row k="Fim" v={fmtT(b.endMin)} />
        {tool && <Row k="pcs/H" v={tool.pH.toLocaleString()} />}
        <Row k="Operadores" v={b.operators} />
        {b.type === 'blocked' && (
          <div style={{ fontSize: 10, color: C.rd, fontWeight: 600, marginTop: 4 }}>
            BLOQUEADA — {b.reason === 'tool_down' ? 'ferramenta avariada' : 'máquina DOWN'}
          </div>
        )}
        {b.overflow && (
          <div style={{ fontSize: 10, color: C.yl, fontWeight: 600, marginTop: 4 }}>
            OVERFLOW — +{b.overflowMin?.toFixed(0)}min
          </div>
        )}
      </Sec>

      {/* Twin Co-Production */}
      {b.isTwinProduction && b.outputs && (
        <Sec label="Co-Produção">
          <div
            style={{
              fontSize: 10,
              color: C.t3,
              marginBottom: 6,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
          >
            <Layers size={11} strokeWidth={1.5} color={col} />
            <span>Produção simultânea de 2 SKUs</span>
          </div>
          {b.outputs.map((o, oi) => (
            <div
              key={oi}
              style={{
                borderTop: oi > 0 ? `1px solid ${C.bd}44` : undefined,
                paddingTop: oi > 0 ? 6 : 0,
                marginTop: oi > 0 ? 6 : 0,
              }}
            >
              <div
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: C.t1,
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                {o.sku}
              </div>
              <Row k="Quantidade" v={`${o.qty.toLocaleString()} pcs`} />
            </div>
          ))}
        </Sec>
      )}

      {/* Setup */}
      {b.setupS != null && b.setupE != null && (
        <Sec label="Setup">
          <Row k="Tempo" v={`${(b.setupE - b.setupS).toFixed(0)} min`} />
          <Row k="Início Setup" v={fmtT(b.setupS)} />
          <Row k="Fim Setup" v={fmtT(b.setupE)} />
        </Sec>
      )}

      {/* Stock & Backlog */}
      <Sec label="Stock & Backlog">
        <Row
          k="Stock"
          v={`${b.stk.toLocaleString()} pcs`}
          color={b.stk === 0 && b.lt > 0 ? C.yl : undefined}
        />
        {b.lt > 0 && <Row k="Lote Económico" v={`${b.lt.toLocaleString()} pcs`} />}
        <Row
          k="Atraso"
          v={b.atr > 0 ? `${b.atr.toLocaleString()} pcs` : '—'}
          color={b.atr > 0 ? C.rd : C.t3}
        />
      </Sec>

      {/* Weekly schedule mini barchart */}
      {op && (
        <Sec label="Programação Semanal">
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end' }}>
            {op.d.map((qty, i) => (
              <div key={i} style={{ flex: 1, textAlign: 'center' }}>
                <div
                  style={{
                    height: 40,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'flex-end',
                  }}
                >
                  {qty > 0 && (
                    <div
                      style={{
                        height: `${Math.min((qty / maxQty) * 100, 100)}%`,
                        background: i === selDay ? C.ac : C.bl + '55',
                        borderRadius: '2px 2px 0 0',
                        minHeight: 2,
                      }}
                    />
                  )}
                </div>
                {qty > 0 && (
                  <div style={{ fontSize: 7, color: C.t3, fontFamily: 'monospace', marginTop: 1 }}>
                    {(qty / 1000).toFixed(0)}K
                  </div>
                )}
                <div
                  style={{
                    fontSize: 8,
                    color: i === selDay ? C.ac : C.t4,
                    fontWeight: i === selDay ? 700 : 400,
                  }}
                >
                  {dnames[i]}
                </div>
              </div>
            ))}
          </div>
        </Sec>
      )}

      {/* Machine */}
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
              <span style={{ fontSize: 10, color: C.t3 }}>Utilização</span>
              <span
                style={{
                  fontSize: 11,
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

      {/* Actions */}
      <div style={{ padding: '10px 14px' }}>
        {b.moved && (
          <div style={{ marginBottom: 8 }}>
            <div
              style={{
                fontSize: 10,
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
                fontSize: 10,
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
              fontSize: 10,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Mover para {b.altM}
          </button>
        )}
      </div>
    </div>
  );
}

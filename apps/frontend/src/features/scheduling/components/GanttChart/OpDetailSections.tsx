import { Layers } from 'lucide-react';
import type { Block, EOp, ETool } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { fmtT } from '../atoms';
import { Row, Sec } from './OpDetailAtoms';

/* ── Production ── */
export function ProductionSection({ block: b, tool }: { block: Block; tool: ETool | undefined }) {
  return (
    <Sec label="Produção">
      <Row k="Quantidade" v={`${b.qty.toLocaleString()} pcs`} />
      <Row k="Tempo" v={`${(b.endMin - b.startMin).toFixed(0)} min`} />
      <Row k="Início" v={fmtT(b.startMin)} />
      <Row k="Fim" v={fmtT(b.endMin)} />
      {tool && <Row k="pcs/H" v={tool.pH.toLocaleString()} />}
      <Row k="Operadores" v={b.operators} />
      {b.type === 'blocked' && (
        <div style={{ fontSize: 12, color: C.rd, fontWeight: 600, marginTop: 4 }}>
          BLOQUEADA — {b.reason === 'tool_down' ? 'ferramenta avariada' : 'máquina DOWN'}
        </div>
      )}
      {b.overflow && (
        <div style={{ fontSize: 12, color: C.yl, fontWeight: 600, marginTop: 4 }}>
          OVERFLOW — +{b.overflowMin?.toFixed(0)}min
        </div>
      )}
    </Sec>
  );
}

/* ── Twin Co-Production ── */
export function TwinSection({ block: b, col }: { block: Block; col: string }) {
  if (!b.isTwinProduction || !b.outputs) return null;
  return (
    <Sec label="Co-Produção">
      <div
        style={{
          fontSize: 12,
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
              fontSize: 12,
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
  );
}

/* ── Setup ── */
export function SetupSection({ block: b }: { block: Block }) {
  if (b.setupS == null || b.setupE == null) return null;
  return (
    <Sec label="Setup">
      <Row k="Tempo" v={`${(b.setupE - b.setupS).toFixed(0)} min`} />
      <Row k="Início Setup" v={fmtT(b.setupS)} />
      <Row k="Fim Setup" v={fmtT(b.setupE)} />
    </Sec>
  );
}

/* ── Stock & Backlog ── */
export function StockSection({ block: b }: { block: Block }) {
  return (
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
  );
}

/* ── Weekly Schedule Barchart ── */
export function WeeklyChartSection({
  op,
  dnames,
  selDay,
}: {
  op: EOp;
  dnames: string[];
  selDay: number;
}) {
  const maxQty = Math.max(...op.d, 1);
  return (
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
                    background: i === selDay ? C.ac : `${C.bl}55`,
                    borderRadius: '2px 2px 0 0',
                    minHeight: 2,
                  }}
                />
              )}
            </div>
            {qty > 0 && (
              <div style={{ fontSize: 12, color: C.t3, fontFamily: 'monospace', marginTop: 1 }}>
                {(qty / 1000).toFixed(0)}K
              </div>
            )}
            <div
              style={{
                fontSize: 12,
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
  );
}

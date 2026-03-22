import { Clock, Layers, Sparkles, Zap } from 'lucide-react';
import type { Block, EngineData } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { fmtT } from '../atoms';

export interface BlockTooltipProps {
  b: Block;
  col: string;
  data: EngineData;
  classifications?: Set<string>;
}

export function BlockTooltip({ b, col, data, classifications }: BlockTooltipProps) {
  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        position: 'absolute',
        bottom: 'calc(100% + 6px)',
        left: 0,
        background: C.s3,
        border: `1px solid ${col}44`,
        borderRadius: 8,
        padding: 10,
        zIndex: 30,
        width: 240,
      }}
    >
      <div style={{ fontSize: 12, fontWeight: 600, color: col }}>{b.toolId}</div>
      <div style={{ fontSize: 12, color: C.t2, marginBottom: 6 }}>
        {b.nm} · {b.sku}
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '4px 12px',
          fontSize: 12,
        }}
      >
        {(
          [
            ['Qtd', `${b.qty.toLocaleString()}`],
            ['Tempo', `${(b.endMin - b.startMin).toFixed(0)}min`],
            ['Início', fmtT(b.startMin)],
            ['Fim', fmtT(b.endMin)],
            ['pcs/H', data.toolMap[b.toolId]?.pH],
            [
              'Setup',
              b.setupS != null && b.setupE != null ? `${b.setupE - b.setupS}min` : '\u2014',
            ],
            ['Ops', b.operators],
            ['Máq', b.machineId],
            ['Turno', b.shift === 'Z' ? 'Noite' : b.shift === 'X' ? 'Manhã' : 'Tarde'],
          ] as [string, unknown][]
        ).map(([k, v], i) => (
          <div key={i} style={{ color: C.t3 }}>
            {k} <span style={{ color: C.t1, fontWeight: 600 }}>{String(v)}</span>
          </div>
        ))}
      </div>
      {b.moved && (
        <div
          style={{
            fontSize: 12,
            color: C.ac,
            marginTop: 4,
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: 3,
          }}
        >
          <Sparkles size={9} strokeWidth={1.5} /> Replaneado de {b.origM}
        </div>
      )}
      {b.isTwinProduction && b.outputs && (
        <div
          style={{
            borderTop: `1px solid ${col}33`,
            marginTop: 6,
            paddingTop: 6,
          }}
        >
          <div
            style={{
              fontSize: 12,
              color: col,
              fontWeight: 600,
              marginBottom: 3,
              display: 'flex',
              alignItems: 'center',
              gap: 3,
            }}
          >
            <Layers size={9} strokeWidth={1.5} /> Co-Produção
          </div>
          {b.outputs.map((o, oi) => (
            <div key={oi} style={{ fontSize: 12, color: C.t3 }}>
              {o.sku}{' '}
              <span style={{ color: C.t1, fontWeight: 600 }}>{o.qty.toLocaleString()} pcs</span>
            </div>
          ))}
        </div>
      )}
      {classifications && classifications.size > 0 && (
        <div
          style={{
            borderTop: `1px solid ${col}33`,
            marginTop: 6,
            paddingTop: 6,
            display: 'flex',
            gap: 4,
            flexWrap: 'wrap',
          }}
        >
          {classifications.has('atrasado') && (
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: C.rd,
                background: `${C.rd}18`,
                padding: '1px 5px',
                borderRadius: 3,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
              }}
            >
              <Clock size={7} strokeWidth={2.5} /> Atrasado
            </span>
          )}
          {classifications.has('urgente') && (
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: C.yl,
                background: `${C.yl}18`,
                padding: '1px 5px',
                borderRadius: 3,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
              }}
            >
              <Zap size={7} strokeWidth={2.5} /> Urgente
            </span>
          )}
          {classifications.has('robusto') && (
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: C.ac,
                background: `${C.ac}18`,
                padding: '1px 5px',
                borderRadius: 3,
              }}
            >
              Robusto
            </span>
          )}
        </div>
      )}
    </div>
  );
}

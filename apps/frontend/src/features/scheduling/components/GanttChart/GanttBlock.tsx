import { AlertTriangle, Layers, Lock, Sparkles } from 'lucide-react';
import React from 'react';
import type { Block, EngineData } from '../../../../lib/engine';
import { C, S0 } from '../../../../lib/engine';
import { fmtT } from '../atoms';

export interface GanttBlockProps {
  b: Block;
  bi: number;
  ppm: number;
  col: string;
  hov: string | null;
  selOp: string | null;
  selDay: number;
  data: EngineData;
  setHov: (v: string | null) => void;
  setSelOp: (v: string | null) => void;
}

export function GanttBlock({
  b,
  bi,
  ppm,
  col,
  hov,
  selOp,
  selDay,
  data,
  setHov,
  setSelOp,
}: GanttBlockProps) {
  const isH = hov === `${b.opId}-${selDay}`;
  const isSel = selOp === b.opId;
  const y = 5 + bi * 22;

  return (
    <React.Fragment>
      {b.setupS != null && b.setupE != null && (
        <div
          style={{
            position: 'absolute',
            left: (b.setupS - S0) * ppm,
            width: Math.max((b.setupE - b.setupS) * ppm, 4),
            top: y,
            height: 17,
            background: `repeating-linear-gradient(45deg,${col}40,${col}40 3px,${col}70 3px,${col}70 6px)`,
            borderRadius: '4px 0 0 4px',
            border: `1px solid ${col}66`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <span style={{ fontSize: 8, color: col, fontWeight: 700 }}>SET</span>
        </div>
      )}
      <div
        onClick={() => setSelOp(selOp === b.opId ? null : b.opId)}
        onMouseEnter={() => setHov(`${b.opId}-${selDay}`)}
        onMouseLeave={() => setHov(null)}
        style={{
          position: 'absolute',
          left: (b.startMin - S0) * ppm,
          width: Math.max((b.endMin - b.startMin) * ppm, 12),
          top: y,
          height: 17,
          background: isSel ? col : isH ? col : `${col}CC`,
          borderRadius: b.setupS != null ? '0 4px 4px 0' : 4,
          border: isSel
            ? `2px solid ${C.ac}`
            : b.moved
              ? `2px solid ${C.ac}`
              : b.freezeStatus === 'frozen'
                ? `2px dashed ${C.rd}88`
                : b.freezeStatus === 'slushy'
                  ? `2px dotted ${C.yl}88`
                  : `1px solid ${col}44`,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          paddingLeft: 4,
          overflow: 'hidden',
          opacity: b.freezeStatus === 'frozen' ? 0.9 : 1,
          zIndex: isSel ? 25 : isH ? 20 : 1,
        }}
      >
        <span
          style={{
            fontSize: 9,
            color: C.t1,
            fontWeight: 600,
            whiteSpace: 'nowrap',
            textShadow: '0 1px 3px #0009',
          }}
        >
          {b.toolId}
        </span>
        {(b.endMin - b.startMin) * ppm > 70 && (
          <span style={{ fontSize: 8, color: C.t2, marginLeft: 5 }}>{b.qty.toLocaleString()}</span>
        )}
        {b.overflow && (
          <span
            style={{
              color: C.yl,
              marginLeft: 3,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            <AlertTriangle size={8} strokeWidth={2} />
          </span>
        )}
        {b.freezeStatus === 'frozen' && (
          <span
            style={{
              color: C.rd,
              marginLeft: 3,
              display: 'inline-flex',
              alignItems: 'center',
              opacity: 0.9,
            }}
          >
            <Lock size={8} strokeWidth={2} />
          </span>
        )}
        {b.isTwinProduction && (b.endMin - b.startMin) * ppm > 40 && (
          <span
            style={{
              color: '#fff9',
              marginLeft: 'auto',
              paddingRight: 3,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            <Layers size={9} strokeWidth={2} />
          </span>
        )}
        {isH && <BlockTooltip b={b} col={col} data={data} />}
      </div>
    </React.Fragment>
  );
}

function BlockTooltip({ b, col, data }: { b: Block; col: string; data: EngineData }) {
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
      <div style={{ fontSize: 11, fontWeight: 600, color: col }}>{b.toolId}</div>
      <div style={{ fontSize: 9, color: C.t2, marginBottom: 6 }}>
        {b.nm} · {b.sku}
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '4px 12px',
          fontSize: 9,
        }}
      >
        {(
          [
            ['Qtd', `${b.qty.toLocaleString()}`],
            ['Tempo', `${(b.endMin - b.startMin).toFixed(0)}min`],
            ['Início', fmtT(b.startMin)],
            ['Fim', fmtT(b.endMin)],
            ['pcs/H', data.toolMap[b.toolId]?.pH],
            ['Setup', b.setupS != null && b.setupE != null ? `${b.setupE - b.setupS}min` : '—'],
            ['Ops', b.operators],
            ['Máq', b.machineId],
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
            fontSize: 9,
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
              fontSize: 9,
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
            <div key={oi} style={{ fontSize: 9, color: C.t3 }}>
              {o.sku}{' '}
              <span style={{ color: C.t1, fontWeight: 600 }}>{o.qty.toLocaleString()} pcs</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

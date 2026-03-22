import { AlertTriangle, Clock, Layers, Lock, Zap } from 'lucide-react';
import React, { memo } from 'react';
import type { Block, EngineData } from '@/domain/types/scheduling';
import { S0 } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { BlockTooltip } from './BlockTooltip';

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
  onDragStart?: (block: Block, e: React.MouseEvent) => void;
  /** Map opId → 3-letter client abbreviation for block label */
  clientMap?: Record<string, string>;
  /** L4 definition IDs that match this block (from useClassifications) */
  classifications?: Set<string>;
}

export const GanttBlock = memo(function GanttBlock({
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
  onDragStart,
  clientMap,
  classifications,
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
          <span style={{ fontSize: 12, color: col, fontWeight: 700 }}>
            {(() => {
              const sw = Math.max((b.setupE! - b.setupS!) * ppm, 4);
              const sd = Math.round(b.setupE! - b.setupS!);
              if (sw >= 90) return `Setup ${b.toolId} · ${sd}min`;
              if (sw >= 60) return `Setup · ${sd}min`;
              return 'SET';
            })()}
          </span>
        </div>
      )}
      <div
        data-block-id={b.opId}
        onClick={() => setSelOp(selOp === b.opId ? null : b.opId)}
        onMouseDown={(e) => onDragStart?.(b, e)}
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
            fontSize: 12,
            color: C.t1,
            fontWeight: 600,
            whiteSpace: 'nowrap',
            textShadow: '0 1px 3px #0009',
          }}
        >
          {(() => {
            const w = Math.max((b.endMin - b.startMin) * ppm, 12);
            const sku10 = (b.sku || b.toolId).slice(0, 10);
            const client3 = (clientMap?.[b.opId] || b.nm)?.slice(0, 3)?.toUpperCase();
            const op = data.ops.find((o) => o.id === b.opId);
            const td = op ? op.d.reduce((a, v) => a + Math.max(v, 0), 0) + Math.max(op.atr, 0) : 0;
            const pct = td > 0 ? Math.min(100, Math.round((b.qty / td) * 100)) : null;
            if (w >= 140 && client3) return `${sku10} · ${client3} · ${pct ?? ''}%`;
            if (w >= 100) return pct != null ? `${sku10} · ${pct}%` : sku10;
            if (w >= 50) return b.toolId;
            if (w >= 25 && pct != null) return `${pct}%`;
            return '';
          })()}
        </span>
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
              color: 'var(--text-inverse, #fff9)',
              marginLeft: 'auto',
              paddingRight: 3,
              display: 'inline-flex',
              alignItems: 'center',
            }}
          >
            <Layers size={9} strokeWidth={2} />
          </span>
        )}
        {b.shift === 'Z' && (
          <span
            style={{
              fontSize: 12,
              fontWeight: 800,
              color: 'var(--text-inverse, #fffc)',
              marginLeft: b.isTwinProduction ? 0 : 'auto',
              paddingRight: 3,
              textShadow: '0 1px 2px #000a',
            }}
          >
            N
          </span>
        )}
        {classifications?.has('atrasado') && (b.endMin - b.startMin) * ppm > 25 && (
          <span
            style={{ color: C.rd, marginLeft: 2, display: 'inline-flex', alignItems: 'center' }}
          >
            <Clock size={8} strokeWidth={2.5} />
          </span>
        )}
        {classifications?.has('urgente') && (b.endMin - b.startMin) * ppm > 25 && (
          <span
            style={{ color: C.yl, marginLeft: 2, display: 'inline-flex', alignItems: 'center' }}
          >
            <Zap size={8} strokeWidth={2.5} />
          </span>
        )}
        {isH && <BlockTooltip b={b} col={col} data={data} classifications={classifications} />}
      </div>
    </React.Fragment>
  );
});

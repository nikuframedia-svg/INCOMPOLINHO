import { memo } from 'react';
import type { Block, DayLoad, EMachine, EngineData, ETool } from '@/domain/types/scheduling';
import { DAY_CAP, S0, S1, T1 } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { blockKey } from '../../../../domain/configurable-logic-eval';
import { dot, toolColor } from '../atoms';
import type { DiffAction } from './GanttBlock';
import { GanttBlock } from './GanttBlock';

export interface GanttMachineRowProps {
  mc: EMachine;
  mB: Block[];
  mSt: Record<string, string>;
  cap: Record<string, DayLoad[]>;
  data: EngineData;
  hours: number[];
  ppm: number;
  selDay: number;
  hov: string | null;
  selOp: string | null;
  tools: ETool[];
  thirdShift?: boolean;
  setHov: (v: string | null) => void;
  setSelOp: (v: string | null) => void;
  onDragStart?: (block: Block, e: React.MouseEvent) => void;
  isDragOver?: boolean;
  blockClassifications?: Map<string, Set<string>>;
  /** Per-block diff action for scenario comparison */
  diffMap?: Map<string, DiffAction>;
}

export const GanttMachineRow = memo(function GanttMachineRow({
  mc,
  mB,
  mSt,
  cap,
  data,
  hours,
  ppm,
  selDay,
  hov,
  selOp,
  tools,
  thirdShift,
  setHov,
  setSelOp,
  onDragStart,
  isDragOver,
  blockClassifications,
  diffMap,
}: GanttMachineRowProps) {
  const isDown = mSt[mc.id] === 'down';
  const rowH = Math.max(44, mB.length * 22 + 10);
  const mC = cap[mc.id]?.[selDay];
  const total = mC ? mC.prod + mC.setup : 0;
  const dayCap = thirdShift ? DAY_CAP + 420 : DAY_CAP;
  const u = total / dayCap;
  const stateText = isDown ? 'Parada' : mB.length === 0 ? 'Inactiva' : 'A produzir';
  const stateColor = isDown ? C.rd : mB.length === 0 ? C.t4 : C.ac;
  const avgPH = (() => {
    const pHs = [...new Set(mB.map((bl) => bl.toolId))]
      .map((tid) => data.toolMap[tid]?.pH)
      .filter((v): v is number => v != null && v > 0);
    if (pHs.length === 0) return null;
    return Math.round(pHs.reduce((a, b) => a + b, 0) / pHs.length);
  })();

  return (
    <div
      style={{
        display: 'flex',
        borderBottom: `1px solid ${C.bd}`,
        minHeight: rowH,
      }}
    >
      {/* Sidebar label */}
      <div
        style={{
          width: 100,
          minWidth: 100,
          padding: '6px 10px',
          borderRight: `1px solid ${C.bd}`,
          background: C.s1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 2,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={dot(isDown ? C.rd : C.ac, isDown)} />
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: isDown ? C.rd : C.t1,
              fontFamily: 'monospace',
            }}
          >
            {mc.id}
          </span>
        </div>
        <div style={{ fontSize: 12, color: stateColor, fontWeight: 600 }}>{stateText}</div>
        <div style={{ fontSize: 12, color: C.t3 }}>
          {mB.length} lote{mB.length !== 1 ? 's' : ''}
        </div>
        {avgPH != null && (
          <div style={{ fontSize: 12, color: C.t3, fontFamily: 'monospace' }}>
            {avgPH.toLocaleString()} pç/h
          </div>
        )}
      </div>

      {/* Timeline area */}
      <div
        data-machine-id={mc.id}
        style={{
          position: 'relative',
          flex: 1,
          height: rowH,
          background: isDragOver ? `${C.ac}15` : isDown ? C.rdS : 'transparent',
          outline: isDragOver ? `2px dashed ${C.ac}66` : undefined,
          outlineOffset: -2,
          transition: 'background 0.15s, outline 0.15s',
        }}
      >
        {hours.map((h) => (
          <div
            key={h}
            style={{
              position: 'absolute',
              left: (h * 60 - S0) * ppm,
              top: 0,
              bottom: 0,
              borderLeft: `1px solid ${C.bd}22`,
            }}
          />
        ))}
        <div
          style={{
            position: 'absolute',
            left: (T1 - S0) * ppm,
            top: 0,
            bottom: 0,
            borderLeft: `2px solid ${C.yl}33`,
          }}
        />
        {thirdShift && (
          <div
            style={{
              position: 'absolute',
              left: (S1 - S0) * ppm,
              top: 0,
              bottom: 0,
              borderLeft: `2px solid ${C.yl}33`,
            }}
          />
        )}
        {isDown && (
          <div
            style={{
              position: 'absolute',
              inset: 0,
              background: `repeating-linear-gradient(45deg,transparent,transparent 8px,${C.rd}08 8px,${C.rd}08 16px)`,
            }}
          />
        )}
        {mB.map((b, bi) => (
          <GanttBlock
            key={`${b.opId}-${bi}`}
            b={b}
            bi={bi}
            ppm={ppm}
            col={toolColor(tools, b.toolId)}
            hov={hov}
            selOp={selOp}
            selDay={selDay}
            data={data}
            setHov={setHov}
            setSelOp={setSelOp}
            onDragStart={onDragStart}
            classifications={blockClassifications?.get(blockKey(b))}
            diffAction={diffMap?.get(`${b.opId}|${b.eddDay ?? -1}`)}
          />
        ))}
        {!isDown && total > 0 && (
          <div
            style={{
              position: 'absolute',
              bottom: 0,
              left: 0,
              right: 0,
              height: 3,
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${Math.min(u * 100, 100)}%`,
                background: u > 1 ? C.rd : C.ac,
                opacity: 0.25,
                borderRadius: '0 2px 0 0',
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
});

import type { Block, DayLoad, EMachine, EngineData, ETool } from '../../../../lib/engine';
import { C, DAY_CAP, S0, T1 } from '../../../../lib/engine';
import { dot, toolColor } from '../atoms';
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
  setHov: (v: string | null) => void;
  setSelOp: (v: string | null) => void;
}

export function GanttMachineRow({
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
  setHov,
  setSelOp,
}: GanttMachineRowProps) {
  const isDown = mSt[mc.id] === 'down';
  const rowH = Math.max(44, mB.length * 22 + 10);
  const mC = cap[mc.id]?.[selDay];
  const total = mC ? mC.prod + mC.setup : 0;
  const u = total / DAY_CAP;

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
        <div style={{ fontSize: 9, color: C.t3 }}>
          {mc.area} · {mB.length} ops
        </div>
        {total > 0 && (
          <div
            style={{
              fontSize: 10,
              color: u > 1 ? C.rd : u > 0.85 ? C.yl : C.ac,
              fontWeight: 600,
            }}
          >
            {(u * 100).toFixed(0)}%
          </div>
        )}
      </div>

      {/* Timeline area */}
      <div
        style={{
          position: 'relative',
          flex: 1,
          height: rowH,
          background: isDown ? C.rdS : 'transparent',
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
}

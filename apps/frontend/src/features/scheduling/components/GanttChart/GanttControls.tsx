import { AlertTriangle } from 'lucide-react';
import type { Block } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Pill } from '../atoms';

export function GanttControls({
  wdi,
  selDay,
  selM,
  zoom,
  dnames,
  dates,
  blocks,
  machines,
  mSt,
  violationsByDay,
  onDayChange,
  onSelM,
  onZoom,
}: {
  wdi: number[];
  selDay: number;
  selM: string | null;
  zoom: number;
  dnames: string[];
  dates: string[];
  blocks: Block[];
  machines: { id: string }[];
  mSt: Record<string, string>;
  violationsByDay: Record<number, number>;
  onDayChange: (d: number) => void;
  onSelM: (m: string | null) => void;
  onZoom: (z: number) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 6,
      }}
    >
      <div
        className="ne-day-strip"
        style={{ display: 'flex', gap: 3, overflowX: 'auto', flex: '1 1 0', minWidth: 0 }}
      >
        {wdi.map((i) => {
          const has = blocks.some((b) => b.dayIdx === i && b.type !== 'blocked');
          const vc = violationsByDay[i] ?? 0;
          return (
            <Pill
              key={i}
              active={selDay === i}
              color={C.ac}
              onClick={() => onDayChange(i)}
              size="sm"
            >
              <span style={{ opacity: has ? 1 : 0.4 }}>
                {dnames[i]} {dates[i]}
              </span>
              {vc > 0 && (
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 700,
                    color: C.yl,
                    marginLeft: 4,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 2,
                  }}
                >
                  <AlertTriangle size={8} strokeWidth={2.5} />
                  {vc}
                </span>
              )}
            </Pill>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        <Pill active={!selM} color={C.ac} onClick={() => onSelM(null)}>
          Todas
        </Pill>
        {machines
          .filter(
            (m) =>
              blocks.some((b) => b.dayIdx === selDay && b.machineId === m.id) ||
              mSt[m.id] === 'down',
          )
          .map((m) => {
            const isDown = mSt[m.id] === 'down';
            return (
              <Pill
                key={m.id}
                active={selM === m.id}
                color={isDown ? C.rd : C.ac}
                onClick={() => onSelM(selM === m.id ? null : m.id)}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: isDown ? C.rd : C.ac,
                    display: 'inline-block',
                    marginRight: 4,
                  }}
                />
                {m.id}
              </Pill>
            );
          })}
        <span style={{ width: 1, height: 16, background: C.bd, margin: '0 2px' }} />
        {[0.6, 1, 1.5, 2].map((z) => (
          <Pill key={z} active={zoom === z} color={C.bl} onClick={() => onZoom(z)}>
            {z}×
          </Pill>
        ))}
      </div>
    </div>
  );
}

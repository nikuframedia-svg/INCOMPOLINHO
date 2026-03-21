/**
 * ShiftCalendarEditor — Weekly shift grid per machine (7 days × 3 shifts).
 */

import { useState } from 'react';
import './ShiftCalendarEditor.css';

export interface ShiftSlot {
  active: boolean;
  operators: number;
  isNight: boolean;
}

interface ShiftCalendarEditorProps {
  machines: string[];
  laborGroupMap: Record<string, string>;
  laborCapacities: Record<string, number[]>;
}

const DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
const SHIFTS = ['A', 'B', 'Noite'];

function buildDefaults(
  machines: string[],
  laborGroupMap: Record<string, string>,
  laborCapacities: Record<string, number[]>,
): Record<string, ShiftSlot[][]> {
  const grid: Record<string, ShiftSlot[][]> = {};
  for (const m of machines) {
    const group = laborGroupMap[m] ?? 'Grandes';
    const caps = laborCapacities[group] ?? [6, 6, 5];
    grid[m] = DAYS.map(() => [
      { active: true, operators: caps[0] ?? 6, isNight: false },
      { active: true, operators: caps[2] ?? 5, isNight: false },
      { active: false, operators: 0, isNight: true },
    ]);
  }
  return grid;
}

function applyTemplate(
  grid: Record<string, ShiftSlot[][]>,
  template: 'normal' | 'night' | 'holiday',
  laborGroupMap: Record<string, string>,
  laborCapacities: Record<string, number[]>,
): Record<string, ShiftSlot[][]> {
  const next: Record<string, ShiftSlot[][]> = {};
  for (const m of Object.keys(grid)) {
    const group = laborGroupMap[m] ?? 'Grandes';
    const caps = laborCapacities[group] ?? [6, 6, 5];
    next[m] = DAYS.map((_, di) => {
      const isWeekend = di >= 5;
      if (template === 'holiday' || (template === 'normal' && isWeekend)) {
        return [
          { active: false, operators: 0, isNight: false },
          { active: false, operators: 0, isNight: false },
          { active: false, operators: 0, isNight: true },
        ];
      }
      if (template === 'night') {
        return [
          { active: true, operators: caps[0] ?? 6, isNight: false },
          { active: true, operators: caps[2] ?? 5, isNight: false },
          { active: !isWeekend, operators: isWeekend ? 0 : 2, isNight: true },
        ];
      }
      return [
        { active: true, operators: caps[0] ?? 6, isNight: false },
        { active: true, operators: caps[2] ?? 5, isNight: false },
        { active: false, operators: 0, isNight: true },
      ];
    });
  }
  return next;
}

export function ShiftCalendarEditor({
  machines,
  laborGroupMap,
  laborCapacities,
}: ShiftCalendarEditorProps) {
  const [grid, setGrid] = useState(() => buildDefaults(machines, laborGroupMap, laborCapacities));

  const toggle = (machine: string, day: number, shift: number) => {
    setGrid((prev) => {
      const next = { ...prev };
      const mGrid = next[machine].map((d) => d.map((s) => ({ ...s })));
      mGrid[day][shift].active = !mGrid[day][shift].active;
      if (!mGrid[day][shift].active) mGrid[day][shift].operators = 0;
      else {
        const group = laborGroupMap[machine] ?? 'Grandes';
        const caps = laborCapacities[group] ?? [6, 6, 5];
        mGrid[day][shift].operators = shift === 2 ? 2 : (caps[shift === 0 ? 0 : 2] ?? 5);
      }
      next[machine] = mGrid;
      return next;
    });
  };

  const handleTemplate = (t: 'normal' | 'night' | 'holiday') => {
    setGrid((prev) => applyTemplate(prev, t, laborGroupMap, laborCapacities));
  };

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {(
          [
            ['normal', 'Semana normal'],
            ['night', 'Semana com noite'],
            ['holiday', 'Feriado'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            className="constraint-toggles__param-select"
            onClick={() => handleTemplate(key)}
            style={{ cursor: 'pointer', padding: '4px 12px', fontSize: 12 }}
          >
            {label}
          </button>
        ))}
      </div>

      {machines.map((machine) => (
        <div key={machine} style={{ marginBottom: 16 }}>
          <div
            style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6 }}
          >
            {machine}
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
              {laborGroupMap[machine] ?? 'Grandes'}
            </span>
          </div>
          <div className="shift-grid">
            <div className="shift-grid__header">
              <div className="shift-grid__corner" />
              {DAYS.map((d) => (
                <div key={d} className="shift-grid__day-label">
                  {d}
                </div>
              ))}
            </div>
            {SHIFTS.map((shift, si) => (
              <div key={shift} className="shift-grid__row">
                <div className="shift-grid__shift-label">{shift}</div>
                {DAYS.map((_, di) => {
                  const slot = grid[machine]?.[di]?.[si];
                  if (!slot) return <div key={di} className="shift-grid__cell" />;
                  const cls = slot.active
                    ? slot.isNight
                      ? 'shift-grid__cell shift-grid__cell--night'
                      : 'shift-grid__cell shift-grid__cell--active'
                    : 'shift-grid__cell';
                  return (
                    <div
                      key={di}
                      className={cls}
                      onClick={() => toggle(machine, di, si)}
                      style={{ cursor: 'pointer' }}
                    >
                      {slot.active && <span className="shift-grid__ops">{slot.operators}</span>}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      ))}

      {grid[machines[0]]?.some((d) => d[2].active) && (
        <div
          style={{
            padding: '6px 12px',
            background: 'var(--semantic-red-bg, rgba(239,68,68,0.1))',
            border: '1px solid var(--semantic-red)',
            borderRadius: 4,
            fontSize: 12,
            color: 'var(--semantic-red)',
            marginTop: 8,
          }}
        >
          Turno noite activo — só emergência. Sinalizar no plano.
        </div>
      )}
    </div>
  );
}

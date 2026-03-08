/**
 * OperatorPanel — Workforce demand per labor group x time window.
 */

import type { ZoneShiftDemand } from '@/lib/engine';
import { fmtMin } from '@/lib/engine';
import './OperatorPanel.css';

interface OperatorPanelProps {
  workforce: ZoneShiftDemand[];
  operatorsByArea: { pg1: number; pg2: number; total: number };
  operatorCapacity: { pg1: number; pg2: number };
  dayName: string;
}

const GROUPS = ['Grandes', 'Medias'] as const;

export function OperatorPanel({
  workforce,
  operatorsByArea,
  operatorCapacity,
  dayName,
}: OperatorPanelProps) {
  const totalCap = operatorCapacity.pg1 + operatorCapacity.pg2;

  return (
    <div className="opanel" data-testid="operator-panel">
      <div className="opanel__title">Operadores — {dayName}</div>

      <div className="opanel__summary">
        <span>
          PG1: {operatorsByArea.pg1}/{operatorCapacity.pg1}
        </span>
        <span>
          PG2: {operatorsByArea.pg2}/{operatorCapacity.pg2}
        </span>
        <span>
          Total: {operatorsByArea.total}/{totalCap}
        </span>
      </div>

      {workforce.length === 0 ? (
        <div className="opanel__empty">Sem dados de workforce para este dia.</div>
      ) : (
        GROUPS.map((group) => {
          const entries = workforce.filter((w) => w.laborGroup === group);
          if (entries.length === 0) return null;

          return (
            <div key={group} className="opanel__group">
              <div className="opanel__group-label">{group}</div>
              {entries.map((w, i) => {
                const pct =
                  w.capacity > 0
                    ? Math.min((w.peakNeed / w.capacity) * 100, 100)
                    : w.peakNeed > 0
                      ? 100
                      : 0;
                const excess = w.peakNeed - w.capacity;

                return (
                  <div
                    key={i}
                    className={`opanel__window${w.overloaded ? ' opanel__window--overloaded' : ''}`}
                    data-testid={`opanel-window-${group}-${w.shift}`}
                  >
                    <span className="opanel__window-label">
                      {fmtMin(w.windowStart)}–{fmtMin(w.windowEnd)} ({w.shift})
                    </span>
                    <div className="opanel__bar-bg">
                      <div className="opanel__bar-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <span className={`opanel__ratio${w.overloaded ? ' opanel__ratio--over' : ''}`}>
                      {w.peakNeed}/{w.capacity}
                      {excess > 0 && ` +${excess}`}
                    </span>
                  </div>
                );
              })}
            </div>
          );
        })
      )}
    </div>
  );
}

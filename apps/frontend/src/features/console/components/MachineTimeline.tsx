/**
 * MachineTimeline — Horizontal bar chart per machine for the selected day.
 * Blocks positioned absolutely based on startMin/endMin relative to S0-S1.
 */

import { useMemo } from 'react';
import type { MachineLoad } from '@/hooks/useDayData';
import type { Block, EngineData } from '@/lib/engine';
import { fmtMin, S0, S1, T1 } from '@/lib/engine';
import './MachineTimeline.css';

const RANGE = S1 - S0; // 1020 min

const SCALE_TICKS = ['07:00', '10:00', '13:00', '15:30', '18:00', '21:00', '24:00'];
const SHIFT_LINE_PCT = ((T1 - S0) / RANGE) * 100;

function getNowMin(): number {
  const now = new Date();
  return now.getHours() * 60 + now.getMinutes();
}

interface MachineTimelineProps {
  engine: EngineData;
  blocks: Block[];
  machineLoads: MachineLoad[];
  date: string;
  onBlockClick: (block: Block) => void;
  onMachineClick: (machineId: string) => void;
}

export function MachineTimeline({
  engine,
  blocks,
  machineLoads,
  date,
  onBlockClick,
  onMachineClick,
}: MachineTimelineProps) {
  const nowMin = useMemo(() => getNowMin(), []);
  const isToday = date === new Date().toISOString().slice(0, 10);
  const nowInRange = isToday && nowMin >= S0 && nowMin <= S1;
  const nowPct = nowInRange ? ((nowMin - S0) / RANGE) * 100 : -1;

  return (
    <div className="mtl" data-testid="machine-timeline">
      <div className="mtl__header">
        <span className="mtl__title">Máquinas — {date}</span>
        <div className="mtl__scale">
          {SCALE_TICKS.map((t) => (
            <span key={t} className="mtl__tick">
              {t}
            </span>
          ))}
        </div>
      </div>

      {engine.machines.map((m) => {
        const ml = machineLoads.find((x) => x.machineId === m.id);
        const mBlocks = ml?.blocks ?? blocks.filter((b) => b.machineId === m.id);
        const util = ml?.utilization ?? 0;

        return (
          <div key={m.id} className="mtl__row" data-testid={`mtl-row-${m.id}`}>
            <div
              className="mtl__label"
              onClick={() => onMachineClick(m.id)}
              data-testid={`mtl-label-${m.id}`}
            >
              <span className="mtl__machine-id">{m.id}</span>
              <span className="mtl__machine-util">{(util * 100).toFixed(0)}%</span>
            </div>

            <div className="mtl__bar">
              {/* Shift separator at T1 (15:30) */}
              <div className="mtl__shift-line" style={{ left: `${SHIFT_LINE_PCT}%` }} />
              {/* Now line */}
              {nowPct >= 0 && <div className="mtl__now-line" style={{ left: `${nowPct}%` }} />}

              {mBlocks.map((b, i) => {
                // Clamp to visible range
                const start = Math.max(b.startMin, S0);
                const end = Math.min(b.endMin, S1);
                if (end <= start) return null;

                const left = ((start - S0) / RANGE) * 100;
                const width = ((end - start) / RANGE) * 100;

                // Setup bar
                const hasSetup = b.setupS != null && b.setupE != null;
                let setupLeft = 0;
                let setupWidth = 0;
                if (hasSetup) {
                  const ss = Math.max(b.setupS!, S0);
                  const se = Math.min(b.setupE!, S1);
                  if (se > ss) {
                    setupLeft = ((ss - S0) / RANGE) * 100;
                    setupWidth = ((se - ss) / RANGE) * 100;
                  }
                }

                const blockType =
                  b.type === 'ok'
                    ? 'ok'
                    : b.type === 'overflow'
                      ? 'overflow'
                      : b.type === 'infeasible'
                        ? 'infeasible'
                        : 'blocked';

                return (
                  <div key={`${b.opId}-${i}`}>
                    {hasSetup && setupWidth > 0 && (
                      <div
                        className="mtl__setup"
                        style={{ left: `${setupLeft}%`, width: `${setupWidth}%` }}
                      />
                    )}
                    <div
                      className={`mtl__block mtl__block--${blockType}${nowInRange ? (b.endMin <= nowMin ? ' mtl__block--past' : b.startMin >= nowMin ? ' mtl__block--future' : '') : ''}`}
                      style={{ left: `${left}%`, width: `${Math.max(width, 0.2)}%` }}
                      title={`${b.toolId} · ${b.sku} · ${b.qty.toLocaleString()} pcs · ${fmtMin(b.startMin)}–${fmtMin(b.endMin)} · ${b.shift}`}
                      onClick={() => onBlockClick(b)}
                      data-testid={`mtl-block-${b.opId}-${i}`}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      {blocks.length === 0 && (
        <div className="mtl__empty">Sem blocos escalonados para este dia.</div>
      )}
    </div>
  );
}

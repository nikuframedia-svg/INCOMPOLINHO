/**
 * ReplanTimeline — Chronological history of all replans in the session.
 *
 * Shows timestamp, trigger, strategy, KPI delta, and undo button.
 */

import { Trash2, Undo2 } from 'lucide-react';
import type { ReplanHistoryEntry } from '../hooks/useReplanHistory';
import { Tag } from './atoms';
import './ReplanTimeline.css';
import { C } from '@/theme/color-bridge';

interface ReplanTimelineProps {
  entries: ReplanHistoryEntry[];
  onUndo: (id: string) => void;
  onClear: () => void;
}

const STRATEGY_COLORS: Record<string, string> = {
  right_shift: C.ac,
  match_up: C.bl,
  partial: C.yl,
  full_regen: C.rd,
  auto_replan: C.pp,
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

function otdDelta(entry: ReplanHistoryEntry): { text: string; color: string } {
  const diff = entry.kpiAfter.otd - entry.kpiBefore.otd;
  if (Math.abs(diff) < 0.1) return { text: '=', color: C.t3 };
  const sign = diff > 0 ? '+' : '';
  return {
    text: `${sign}${diff.toFixed(1)}%`,
    color: diff > 0 ? C.ac : C.rd,
  };
}

export function ReplanTimeline({ entries, onUndo, onClear }: ReplanTimelineProps) {
  if (entries.length === 0) return null;

  return (
    <div className="replan-timeline">
      <div className="replan-timeline__header">
        <span className="replan-timeline__title">Histórico de Replans</span>
        <button className="replan-timeline__clear" onClick={onClear}>
          <Trash2
            size={10}
            strokeWidth={1.5}
            style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }}
          />
          Limpar
        </button>
      </div>

      <div className="replan-timeline__list">
        {entries.map((entry) => {
          const delta = otdDelta(entry);
          const sc = STRATEGY_COLORS[entry.strategy] || C.t3;

          return (
            <div
              key={entry.id}
              className={`replan-timeline__entry${entry.undone ? ' replan-timeline__entry--undone' : ''}`}
            >
              <div
                className="replan-timeline__dot"
                style={{ background: entry.undone ? C.t4 : sc }}
              />
              <div className="replan-timeline__line" />

              <div className="replan-timeline__content">
                <div className="replan-timeline__row">
                  <span className="replan-timeline__time">{formatTime(entry.timestamp)}</span>
                  <span className="replan-timeline__trigger">{entry.trigger}</span>
                  <Tag color={entry.undone ? C.t4 : sc}>{entry.strategyLabel}</Tag>
                </div>
                <div className="replan-timeline__row replan-timeline__row--detail">
                  <span className="replan-timeline__detail">
                    {entry.movesCount} movimento{entry.movesCount !== 1 ? 's' : ''}
                  </span>
                  <span className="replan-timeline__detail">
                    OTD-D {entry.kpiBefore.otd.toFixed(1)}%
                    <span style={{ color: C.t4, margin: '0 3px' }}>→</span>
                    <span style={{ color: delta.color, fontWeight: 600 }}>
                      {entry.kpiAfter.otd.toFixed(1)}%
                    </span>
                  </span>
                  {!entry.undone ? (
                    <button className="replan-timeline__undo" onClick={() => onUndo(entry.id)}>
                      <Undo2 size={9} strokeWidth={1.5} /> Undo
                    </button>
                  ) : (
                    <span className="replan-timeline__undone-label">desfeito</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

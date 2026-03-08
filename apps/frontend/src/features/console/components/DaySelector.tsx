/**
 * DaySelector — Week-grouped day selector for long horizons (up to 80+ days).
 *
 * Groups days into ISO weeks. Active week is expanded, others collapsed.
 * Keyboard: Arrow L/R (day), Page Up/Down (week jump).
 * For <=14 days, renders flat strip (legacy mode).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { utilColor } from '@/utils/utilColor';
import './DaySelector.css';

interface DaySelectorProps {
  dates: string[];
  dayNames: string[];
  workdays: boolean[];
  selectedIdx: number;
  onSelect: (idx: number) => void;
  dailyUtils: number[];
}

interface WeekGroup {
  weekLabel: string;
  startIdx: number;
  endIdx: number;
  days: number[];
  avgUtil: number;
}

/** Group day indices into ISO-week-like groups (Mon-Sun blocks) */
function groupByWeek(dayNames: string[], dates: string[], dailyUtils: number[]): WeekGroup[] {
  if (dates.length === 0) return [];

  const groups: WeekGroup[] = [];
  let currentGroup: number[] = [];
  let groupStart = 0;

  for (let i = 0; i < dates.length; i++) {
    const dn = dayNames[i]?.toLowerCase() ?? '';
    // Start new week on Monday (Seg) unless it's the very first day
    const isMonday = dn === 'seg';
    if (isMonday && currentGroup.length > 0) {
      groups.push(buildGroup(currentGroup, groupStart, dates, dailyUtils));
      currentGroup = [];
      groupStart = i;
    }
    currentGroup.push(i);
  }
  if (currentGroup.length > 0) {
    groups.push(buildGroup(currentGroup, groupStart, dates, dailyUtils));
  }
  return groups;
}

function buildGroup(
  days: number[],
  startIdx: number,
  dates: string[],
  dailyUtils: number[],
): WeekGroup {
  const endIdx = days[days.length - 1];
  const utils = days.map((i) => dailyUtils[i] ?? 0).filter((u) => u > 0);
  const avgUtil = utils.length > 0 ? utils.reduce((a, b) => a + b, 0) / utils.length : 0;
  const weekLabel = `${dates[startIdx]} — ${dates[endIdx]}`;
  return { weekLabel, startIdx, endIdx, days, avgUtil };
}

export function DaySelector({
  dates,
  dayNames,
  workdays,
  selectedIdx,
  onSelect,
  dailyUtils,
}: DaySelectorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isCompact = dates.length > 14;

  // Week grouping (only used when compact)
  const weeks = useMemo(
    () => (isCompact ? groupByWeek(dayNames, dates, dailyUtils) : []),
    [isCompact, dayNames, dates, dailyUtils],
  );

  // Track which week is expanded (contains selectedIdx by default)
  const activeWeekIdx = useMemo(() => {
    return weeks.findIndex((w) => w.days.includes(selectedIdx));
  }, [weeks, selectedIdx]);

  const [expandedWeek, setExpandedWeek] = useState<number>(activeWeekIdx);

  // When selected day changes, expand its week
  useEffect(() => {
    if (activeWeekIdx >= 0) setExpandedWeek(activeWeekIdx);
  }, [activeWeekIdx]);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') {
        e.preventDefault();
        onSelect(Math.min(selectedIdx + 1, dates.length - 1));
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        onSelect(Math.max(selectedIdx - 1, 0));
      } else if (e.key === 'PageDown' && isCompact) {
        e.preventDefault();
        // Jump to first day of next week
        const curWeek = weeks.findIndex((w) => w.days.includes(selectedIdx));
        if (curWeek >= 0 && curWeek < weeks.length - 1) {
          onSelect(weeks[curWeek + 1].days[0]);
        }
      } else if (e.key === 'PageUp' && isCompact) {
        e.preventDefault();
        // Jump to first day of previous week
        const curWeek = weeks.findIndex((w) => w.days.includes(selectedIdx));
        if (curWeek > 0) {
          onSelect(weeks[curWeek - 1].days[0]);
        }
      } else if (e.key === 'Home') {
        e.preventDefault();
        onSelect(0);
      } else if (e.key === 'End') {
        e.preventDefault();
        onSelect(dates.length - 1);
      }
    },
    [selectedIdx, dates.length, onSelect, isCompact, weeks],
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.addEventListener('keydown', handleKeyDown);
    return () => el.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Scroll active pill into view
  useEffect(() => {
    const active = containerRef.current?.querySelector(
      '.day-sel__pill--active',
    ) as HTMLElement | null;
    active?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [selectedIdx]);

  // ── Flat mode (<=14 days) ──
  if (!isCompact) {
    return (
      <div
        className="day-sel day-sel--flat"
        ref={containerRef}
        tabIndex={0}
        data-testid="day-selector"
      >
        {dates.map((date, i) => {
          const isActive = i === selectedIdx;
          const isWeekend = !workdays[i];
          const cls = `day-sel__pill${isActive ? ' day-sel__pill--active' : ''}${isWeekend ? ' day-sel__pill--weekend' : ''}`;
          return (
            <button
              key={i}
              className={cls}
              onClick={() => onSelect(i)}
              data-testid={`day-pill-${i}`}
              aria-pressed={isActive}
              aria-label={`${dayNames[i]} ${date}`}
            >
              <span className="day-sel__day-name">{dayNames[i]}</span>
              <span className="day-sel__date">{date}</span>
              <span
                className="day-sel__util-dot"
                style={{ background: utilColor(dailyUtils[i] ?? 0) }}
              />
            </button>
          );
        })}
      </div>
    );
  }

  // ── Grouped mode (>14 days) ──
  return (
    <div
      className="day-sel day-sel--grouped"
      ref={containerRef}
      tabIndex={0}
      data-testid="day-selector"
    >
      <div className="day-sel__summary">
        <span className="day-sel__summary-text">
          {dates[0]} — {dates[dates.length - 1]} · {dates.length} dias · {weeks.length} semanas
        </span>
      </div>
      <div className="day-sel__weeks">
        {weeks.map((week, wi) => {
          const isExpanded = wi === expandedWeek;
          const hasSelected = week.days.includes(selectedIdx);
          const weekCls = `day-sel__week${hasSelected ? ' day-sel__week--active' : ''}${isExpanded ? ' day-sel__week--expanded' : ''}`;

          return (
            <div key={wi} className={weekCls} data-testid={`week-group-${wi}`}>
              <button
                className="day-sel__week-header"
                onClick={() => setExpandedWeek(isExpanded ? -1 : wi)}
                type="button"
              >
                <span className="day-sel__week-label">
                  S{wi + 1} · {week.weekLabel}
                </span>
                <span className="day-sel__week-days">{week.days.length}d</span>
                <span
                  className="day-sel__week-util-bar"
                  style={{ background: utilColor(week.avgUtil) }}
                  title={`Util. média: ${(week.avgUtil * 100).toFixed(0)}%`}
                />
              </button>

              {isExpanded && (
                <div className="day-sel__week-pills">
                  {week.days.map((dayIdx) => {
                    const isActive = dayIdx === selectedIdx;
                    const isWeekend = !workdays[dayIdx];
                    const cls = `day-sel__pill${isActive ? ' day-sel__pill--active' : ''}${isWeekend ? ' day-sel__pill--weekend' : ''}`;
                    return (
                      <button
                        key={dayIdx}
                        className={cls}
                        onClick={() => onSelect(dayIdx)}
                        data-testid={`day-pill-${dayIdx}`}
                        aria-pressed={isActive}
                        aria-label={`${dayNames[dayIdx]} ${dates[dayIdx]}`}
                      >
                        <span className="day-sel__day-name">{dayNames[dayIdx]}</span>
                        <span className="day-sel__date">{dates[dayIdx]}</span>
                        <span
                          className="day-sel__util-dot"
                          style={{ background: utilColor(dailyUtils[dayIdx] ?? 0) }}
                        />
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

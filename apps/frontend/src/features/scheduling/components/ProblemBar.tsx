/**
 * ProblemBar — Explicit problem descriptions for the selected day.
 * ISA-101: NEVER only color — always color + icon + text.
 * Renders NOTHING when there are no problems (no "0 problemas" noise).
 */

import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';
import { C } from '../../../lib/engine';
import type { DayProblem } from '../hooks/useDayProblems';

const MAX_VISIBLE = 5;

const SEV_COLOR: Record<string, string> = {
  critical: C.rd,
  high: C.yl,
  medium: C.bl,
};
const SEV_BG: Record<string, string> = {
  critical: C.rdS,
  high: C.ylS,
  medium: C.blS,
};

export function ProblemBar({ problems }: { problems: DayProblem[] }) {
  const [expanded, setExpanded] = useState(false);
  if (problems.length === 0) return null;

  const hasCritical = problems.some((p) => p.severity === 'critical');
  const borderColor = hasCritical ? C.rd : C.yl;
  const visible = expanded ? problems : problems.slice(0, MAX_VISIBLE);
  const hasMore = problems.length > MAX_VISIBLE && !expanded;

  return (
    <div
      style={{
        background: hasCritical ? C.rdS : C.ylS,
        border: `1px solid ${borderColor}33`,
        borderLeft: `3px solid ${borderColor}`,
        borderRadius: 6,
        padding: '10px 14px',
        marginBottom: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <AlertTriangle size={14} strokeWidth={2} style={{ color: borderColor, flexShrink: 0 }} />
        <span style={{ fontSize: 12, fontWeight: 700, color: borderColor }}>
          {problems.length} problema{problems.length !== 1 ? 's' : ''} neste dia
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {visible.map((p) => (
          <div
            key={p.id}
            style={{
              display: 'flex',
              gap: 8,
              alignItems: 'flex-start',
              padding: '6px 8px',
              borderRadius: 4,
              background: SEV_BG[p.severity] ?? 'transparent',
              borderLeft: `2px solid ${SEV_COLOR[p.severity] ?? C.t3}`,
            }}
          >
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                background: SEV_COLOR[p.severity] ?? C.t3,
                flexShrink: 0,
                marginTop: 4,
              }}
            />
            <div style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontSize: 12, color: C.t1, lineHeight: 1.4 }}>{p.text}</span>
              {p.consequence && (
                <span style={{ display: 'block', fontSize: 12, color: C.t3, marginTop: 2 }}>
                  {p.consequence}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {(hasMore || (expanded && problems.length > MAX_VISIBLE)) && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          style={{
            marginTop: 8,
            background: 'none',
            border: 'none',
            color: borderColor,
            fontSize: 12,
            fontWeight: 600,
            cursor: 'pointer',
            fontFamily: 'inherit',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: 0,
          }}
        >
          {expanded ? (
            <>
              <ChevronUp size={10} /> Mostrar menos
            </>
          ) : (
            <>
              <ChevronDown size={10} /> e mais {problems.length - MAX_VISIBLE}...
            </>
          )}
        </button>
      )}
    </div>
  );
}

import { AlertTriangle, Check, ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import type { ScheduleValidationReport, ScheduleViolation } from '../../../lib/engine';
import { C } from '../../../lib/engine';
import { Card, Tag } from './atoms';

export function ValidationPanel({
  validation,
  dnames,
  dates,
  applyMove,
}: {
  validation: ScheduleValidationReport;
  dnames: string[];
  dates: string[];
  applyMove?: (opId: string, toM: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const critC = validation.violations.filter((v) => v.severity === 'critical').length;
  const highC = validation.violations.filter((v) => v.severity === 'high').length;
  const sevOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
  const sevColor: Record<string, string> = { critical: C.rd, high: C.yl, medium: C.bl, low: C.t3 };
  const sevBg: Record<string, string> = {
    critical: C.rdS,
    high: C.ylS,
    medium: C.blS,
    low: 'transparent',
  };
  const dayLabel = (v: ScheduleViolation): string | null => {
    const days = [...new Set(v.affectedOps.map((o) => o.dayIdx))].sort((a, b) => a - b);
    if (days.length === 0) return null;
    return days.map((d) => `${dnames[d] ?? '?'} ${dates[d] ?? ''}`).join(', ');
  };

  if (validation.violations.length === 0)
    return (
      <div
        style={{
          padding: '6px 12px',
          borderRadius: 6,
          background: C.acS,
          border: `1px solid ${C.acM}`,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          marginBottom: 8,
        }}
      >
        <Check size={12} strokeWidth={2} style={{ color: C.ac }} />
        <span style={{ fontSize: 11, fontWeight: 600, color: C.ac }}>
          Schedule válido — 0 violações
        </span>
      </div>
    );

  return (
    <Card style={{ marginBottom: 8, padding: 0, overflow: 'hidden' }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          padding: '6px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          background: validation.valid ? C.acS : C.rdS,
          borderBottom: expanded ? `1px solid ${C.bd}` : undefined,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle
            size={12}
            strokeWidth={2}
            style={{ color: validation.valid ? C.yl : C.rd }}
          />
          <span style={{ fontSize: 11, fontWeight: 600, color: validation.valid ? C.yl : C.rd }}>
            {validation.violations.length} violaç{validation.violations.length === 1 ? 'ão' : 'ões'}
          </span>
          {critC > 0 && <Tag color={C.rd}>{critC} crít</Tag>}
          {highC > 0 && (
            <Tag color={C.yl}>
              {highC} alta{highC > 1 ? 's' : ''}
            </Tag>
          )}
        </div>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </div>
      {expanded && (
        <div style={{ maxHeight: 240, overflowY: 'auto', padding: '6px 8px' }}>
          {validation.violations
            .sort((a, b) => (sevOrder[a.severity] ?? 3) - (sevOrder[b.severity] ?? 3))
            .map((v) => (
              <div
                key={v.id}
                style={{
                  padding: '5px 8px',
                  marginBottom: 3,
                  borderRadius: 4,
                  background: sevBg[v.severity],
                  borderLeft: `3px solid ${sevColor[v.severity]}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      color: sevColor[v.severity],
                      textTransform: 'uppercase',
                      letterSpacing: '.04em',
                    }}
                  >
                    {v.severity}
                  </span>
                  {dayLabel(v) && (
                    <span
                      style={{
                        fontSize: 8,
                        fontWeight: 600,
                        color: C.t3,
                        background: C.s2,
                        padding: '1px 4px',
                        borderRadius: 3,
                        fontFamily: "'JetBrains Mono',monospace",
                      }}
                    >
                      {dayLabel(v)}
                    </span>
                  )}
                  <span style={{ fontSize: 10, fontWeight: 600, color: C.t1 }}>{v.title}</span>
                </div>
                <div
                  style={{
                    fontSize: 9,
                    color: C.t2,
                    marginTop: 1,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {v.detail}
                </div>
                {v.suggestedFix && (
                  <div style={{ fontSize: 9, color: C.ac, marginTop: 1 }}>{v.suggestedFix}</div>
                )}
                {v.action && applyMove && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      applyMove(v.action!.opId, v.action!.toM);
                    }}
                    style={{
                      marginTop: 2,
                      fontSize: 9,
                      fontWeight: 600,
                      color: C.bg,
                      background: C.ac,
                      border: 'none',
                      borderRadius: 3,
                      padding: '2px 8px',
                      cursor: 'pointer',
                    }}
                  >
                    Mover para {v.action.toM}
                  </button>
                )}
              </div>
            ))}
        </div>
      )}
    </Card>
  );
}

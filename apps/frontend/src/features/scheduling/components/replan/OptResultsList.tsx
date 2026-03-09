/**
 * OptResultsList — Displays ranked optimization results with apply buttons.
 */
import { Star } from 'lucide-react';
import type { OptResult } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';

export interface OptResultsListProps {
  optResults: OptResult[];
  applyOptResult: (r: OptResult) => void;
}

export function OptResultsList({ optResults, applyOptResult }: OptResultsListProps) {
  if (optResults.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {optResults.slice(0, 5).map((r, ri) => (
        <div
          key={ri}
          style={{
            padding: 10,
            borderRadius: 6,
            background: ri === 0 ? `${C.pp}08` : C.bg,
            border: `1px solid ${ri === 0 ? C.pp + '33' : C.bd}`,
            borderLeft: `3px solid ${ri === 0 ? C.pp : C.t4}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              {ri === 0 && <Star size={12} strokeWidth={1.5} style={{ color: C.pp }} />}
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: ri === 0 ? C.pp : C.t1,
                  fontFamily: "'JetBrains Mono',monospace",
                }}
              >
                #{ri + 1}
              </span>
            </div>
            <div style={{ display: 'flex', gap: 8, fontSize: 10 }}>
              <span style={{ color: C.t3 }}>
                OTD{' '}
                <span
                  style={{
                    fontWeight: 600,
                    color: r.otd >= 95 ? C.ac : C.rd,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {r.otd.toFixed(1)}%
                </span>
              </span>
              <span style={{ color: C.t3 }}>
                Setups{' '}
                <span
                  style={{
                    fontWeight: 600,
                    color: C.t1,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {r.setupCount}
                </span>
              </span>
              <span style={{ color: C.t3 }}>
                Tard.{' '}
                <span
                  style={{
                    fontWeight: 600,
                    color: r.tardinessDays > 0 ? C.yl : C.ac,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {r.tardinessDays.toFixed(1)}d
                </span>
              </span>
              <span style={{ color: C.t3 }}>
                Moves{' '}
                <span
                  style={{
                    fontWeight: 600,
                    color: C.bl,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {r.moves.length}
                </span>
              </span>
            </div>
            {r.label && <span style={{ fontSize: 9, color: C.t4 }}>{r.label}</span>}
          </div>
          <button
            onClick={() => applyOptResult(r)}
            data-testid={`apply-opt-${ri}`}
            style={{
              padding: '4px 12px',
              borderRadius: 4,
              border: 'none',
              background: ri === 0 ? C.pp : C.s3,
              color: C.t1,
              fontSize: 10,
              fontWeight: 600,
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            Aplicar
          </button>
        </div>
      ))}
    </div>
  );
}

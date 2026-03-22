/**
 * MiniGantt — Lightweight read-only Gantt chart for Scenario Lab.
 * Renders Block[] directly. 6 machine rows × 8 day columns.
 * Blocks positioned by (startMin - S0) / (S1 - S0).
 */

import type React from 'react';
import { useMemo } from 'react';
import type { Block, EMachine } from '@/domain/types/scheduling';
import { S0, S1 } from '@/domain/types/scheduling';
import { TC } from '@/theme/color-bridge';
import { gridDensityVars } from '../../utils/gridDensity';
import './MiniGantt.css';

const RANGE = S1 - S0;

interface MiniGanttProps {
  blocks: Block[];
  machines: EMachine[];
  dates: string[];
  dnames: string[];
  highlightOps?: Set<string>;
  label?: string;
}

export function MiniGantt({
  blocks,
  machines,
  dates,
  dnames,
  highlightOps,
  label,
}: MiniGanttProps) {
  // Group blocks by machine+day
  const gridData = useMemo(() => {
    const map = new Map<string, Block[]>();
    for (const b of blocks) {
      const key = `${b.machineId}-${b.dayIdx}`;
      const arr = map.get(key);
      if (arr) arr.push(b);
      else map.set(key, [b]);
    }
    return map;
  }, [blocks]);

  // Build a tool→index map for coloring
  const toolIndex = useMemo(() => {
    const m = new Map<string, number>();
    let i = 0;
    for (const b of blocks) {
      if (!m.has(b.toolId)) m.set(b.toolId, i++);
    }
    return m;
  }, [blocks]);

  return (
    <div className="mini-gantt" data-testid="mini-gantt">
      {label && <div className="mini-gantt__label">{label}</div>}
      <div
        className="mini-gantt__grid"
        style={
          {
            gridTemplateColumns: `60px repeat(${dates.length}, 1fr)`,
            gridTemplateRows: `auto repeat(${machines.length}, 28px)`,
            '--n-days': dates.length,
            ...gridDensityVars(dates.length),
          } as React.CSSProperties
        }
      >
        {/* Header row */}
        <div className="mini-gantt__corner" />
        {dnames.map((dn, i) => (
          <div key={i} className="mini-gantt__day-header">
            {dn}
            <span className="mini-gantt__day-date">{dates[i]}</span>
          </div>
        ))}

        {/* Machine rows */}
        {machines.map((m) => (
          <div key={m.id} className="mini-gantt__row" style={{ display: 'contents' }}>
            <div className="mini-gantt__machine">{m.id}</div>
            {Array.from({ length: dates.length }, (_, di) => {
              const dayBlocks = gridData.get(`${m.id}-${di}`) || [];
              return (
                <div key={di} className="mini-gantt__cell">
                  {dayBlocks.map((b, bi) => {
                    const left = ((b.startMin - S0) / RANGE) * 100;
                    const width = ((b.endMin - b.startMin) / RANGE) * 100;
                    const ti = toolIndex.get(b.toolId) ?? 0;
                    const color = TC[ti % TC.length];
                    const isHighlighted = highlightOps?.has(b.opId);
                    const isSetup = b.setupMin > 0 && b.setupS != null;

                    return (
                      <div key={`${b.opId}-${b.startMin}-${bi}`} className="mini-gantt__block-wrap">
                        {/* Setup bar */}
                        {isSetup && b.setupS != null && b.setupE != null && (
                          <div
                            className="mini-gantt__setup"
                            style={{
                              left: `${((b.setupS - S0) / RANGE) * 100}%`,
                              width: `${((b.setupE - b.setupS) / RANGE) * 100}%`,
                            }}
                            title={`Setup: ${Math.round(b.setupMin)}min`}
                          />
                        )}
                        {/* Production bar */}
                        <div
                          className={`mini-gantt__block${isHighlighted ? ' mini-gantt__block--highlight' : ''}`}
                          style={{
                            left: `${left}%`,
                            width: `${Math.max(width, 1)}%`,
                            background: color,
                          }}
                          title={`${b.toolId} · ${b.sku} · ${b.qty} pcs · ${Math.round(b.prodMin)}min`}
                        />
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

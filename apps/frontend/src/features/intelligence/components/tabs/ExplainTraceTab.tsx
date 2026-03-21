import { useCallback, useState } from 'react';
import { C } from '../../../../lib/engine';
import type { IntelData } from '../../compute';
import { StatRow } from '../intel-atoms';
import { MC, mono } from '../intel-helpers';

export function ExplainView({ data }: { data: IntelData }) {
  const { explain } = data;
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<'all' | 'issues'>('all');

  const toggle = useCallback((sku: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(sku)) next.delete(sku);
      else next.add(sku);
      return next;
    });
  }, []);

  const withIssues = explain.filter((n) => n.steps.some((s) => !s.ok));
  const shown = filter === 'issues' ? withIssues : explain;

  return (
    <div>
      <StatRow
        items={[
          { label: 'SKUs Analyzed', value: explain.length },
          {
            label: 'With Issues',
            value: withIssues.length,
            color: withIssues.length > 0 ? C.yl : C.ac,
          },
          { label: 'Steps/SKU', value: 6 },
        ]}
      />
      {/* Filter toggle */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {(['all', 'issues'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '4px 12px',
              borderRadius: 6,
              border: `1px solid ${filter === f ? C.ac : C.bd}`,
              background: filter === f ? C.acS : 'transparent',
              color: filter === f ? C.ac : C.t3,
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              textTransform: 'uppercase' as const,
              letterSpacing: '0.04em',
            }}
          >
            {f === 'all' ? `All (${explain.length})` : `Issues (${withIssues.length})`}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {shown.map((node) => {
          const isOpen = expanded.has(node.sku);
          const hasIssue = node.steps.some((s) => !s.ok);
          return (
            <div
              key={node.sku}
              style={{
                background: C.s2,
                borderRadius: 8,
                border: `1px solid ${hasIssue ? `${C.yl}44` : C.bd}`,
                overflow: 'hidden',
              }}
            >
              {/* Collapsed header */}
              <div
                onClick={() => toggle(node.sku)}
                style={{
                  padding: '9px 14px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  cursor: 'pointer',
                  userSelect: 'none' as const,
                }}
              >
                <span
                  style={{
                    color: C.t4,
                    fontSize: 12,
                    transform: isOpen ? 'rotate(90deg)' : 'none',
                    transition: 'transform 0.15s',
                    display: 'inline-block',
                  }}
                >
                  ▶
                </span>
                <span style={{ color: C.t1, fontSize: 12, ...mono, fontWeight: 600 }}>
                  {node.sku}
                </span>
                <span style={{ color: MC[node.machine] || C.t3, fontSize: 12, ...mono }}>
                  {node.machine}
                </span>
                <span style={{ color: C.t3, fontSize: 12 }}>{node.tool}</span>
                <span style={{ marginLeft: 'auto' }}>
                  {node.steps.map((s, i) => (
                    <span
                      key={i}
                      style={{
                        display: 'inline-block',
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: s.ok ? C.ac : C.yl,
                        marginLeft: 3,
                      }}
                    />
                  ))}
                </span>
              </div>
              {/* Expanded steps */}
              {isOpen && (
                <div
                  style={{
                    padding: '0 14px 12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 5,
                  }}
                >
                  {node.steps.map((step) => (
                    <div
                      key={step.step}
                      style={{
                        display: 'flex',
                        gap: 10,
                        alignItems: 'flex-start',
                        padding: '6px 8px',
                        background: step.ok ? `${C.ac}06` : `${C.yl}08`,
                        borderRadius: 6,
                      }}
                    >
                      <div
                        style={{
                          minWidth: 22,
                          height: 22,
                          borderRadius: '50%',
                          background: step.ok ? C.acS : C.ylS,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          color: step.ok ? C.ac : C.yl,
                          fontSize: 12,
                          fontWeight: 600,
                          ...mono,
                        }}
                      >
                        {step.step}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ color: C.t2, fontSize: 12, marginBottom: 2 }}>
                          {step.question}
                        </div>
                        <div style={{ color: C.t1, fontSize: 12, fontWeight: 600, ...mono }}>
                          {step.answer}
                        </div>
                        <div style={{ color: C.t4, fontSize: 12, marginTop: 2 }}>
                          {step.evidence}
                        </div>
                      </div>
                      <div
                        style={{
                          color: step.ok ? C.ac : C.yl,
                          fontSize: 12,
                          fontWeight: 600,
                          minWidth: 16,
                        }}
                      >
                        {step.ok ? '✓' : '⚠'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
//  MAIN COMPONENT
// ══════════════════════════════════════════════════════════════

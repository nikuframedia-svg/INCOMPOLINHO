import { C } from '../../../../lib/engine';
import type { IntelData } from '../../compute';
import { StatRow } from '../intel-atoms';
import { cardSt, fmtMin, fmtPct, labelSt, MC, mono } from '../intel-helpers';

export function BottleneckView({ data }: { data: IntelData }) {
  const { bottlenecks } = data;
  const overflowed = bottlenecks.filter((b) => b.peakPct > 100);
  const noAlt = bottlenecks.filter((b) => !b.hasAlternatives);

  return (
    <div>
      <StatRow
        items={[
          {
            label: 'Overloaded Machines',
            value: overflowed.length,
            color: overflowed.length > 0 ? C.rd : C.ac,
          },
          { label: 'No Alternatives', value: noAlt.length, color: noAlt.length > 0 ? C.rd : C.ac },
          {
            label: 'Total Overflow',
            value: fmtMin(bottlenecks.reduce((s, b) => s + b.totalOverflowMin, 0)),
            color: C.rd,
          },
          {
            label: 'Relief Paths',
            value: bottlenecks.reduce((s, b) => s + b.reliefPaths.length, 0),
            color: C.ac,
          },
        ]}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {bottlenecks.map((node) => {
          const isOverflow = node.peakPct > 100;
          const barColor = !node.hasAlternatives ? C.rd : isOverflow ? C.yl : C.ac;
          return (
            <div
              key={node.machine}
              style={{
                ...cardSt,
                borderColor: isOverflow ? `${C.rd}44` : !node.hasAlternatives ? `${C.rd}44` : C.bd,
              }}
            >
              {/* Machine header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <div
                  style={{
                    width: 10,
                    height: 10,
                    borderRadius: '50%',
                    background: MC[node.machine],
                  }}
                />
                <span style={{ color: C.t1, fontSize: 14, fontWeight: 600, ...mono }}>
                  {node.machine}
                </span>
                <span style={{ color: C.t3, fontSize: 12 }}>{node.area}</span>
                {!node.hasAlternatives && (
                  <span
                    style={{
                      color: C.rd,
                      fontSize: 12,
                      fontWeight: 600,
                      padding: '2px 6px',
                      background: C.rdS,
                      borderRadius: 4,
                      textTransform: 'uppercase' as const,
                    }}
                  >
                    NO ALTERNATIVES
                  </span>
                )}
                {isOverflow && (
                  <span
                    style={{
                      color: C.rd,
                      fontSize: 12,
                      fontWeight: 600,
                      padding: '2px 6px',
                      background: C.rdS,
                      borderRadius: 4,
                    }}
                  >
                    OVERFLOW {node.overflowDays}d
                  </span>
                )}
                <span
                  style={{
                    marginLeft: 'auto',
                    color: barColor,
                    fontSize: 16,
                    fontWeight: 600,
                    ...mono,
                  }}
                >
                  {fmtPct(node.peakPct)}
                </span>
              </div>
              {/* Utilization bar */}
              <div
                style={{
                  height: 8,
                  borderRadius: 4,
                  background: C.s3,
                  marginBottom: 8,
                  position: 'relative',
                }}
              >
                <div
                  style={{
                    height: '100%',
                    borderRadius: 4,
                    background: barColor,
                    width: `${Math.min(100, node.peakPct)}%`,
                    transition: 'width 0.3s ease',
                  }}
                />
                {node.peakPct > 100 && (
                  <div
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: '100%',
                      height: '100%',
                      borderLeft: `2px dashed ${C.rd}`,
                    }}
                  />
                )}
              </div>
              {/* Relief paths */}
              {node.reliefPaths.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
                  <span style={{ ...labelSt, fontSize: 12 }}>RELIEF PATHS</span>
                  {node.reliefPaths.slice(0, 4).map((rp, i) => (
                    <div
                      key={i}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '4px 8px',
                        background: `${C.ac}08`,
                        borderRadius: 4,
                      }}
                    >
                      <span style={{ color: C.t3, fontSize: 12 }}>→</span>
                      <span style={{ color: C.t1, fontSize: 12, ...mono }}>{rp.toolCode}</span>
                      <span style={{ color: C.t3, fontSize: 12 }}>to</span>
                      <span
                        style={{
                          color: MC[rp.altMachine] || C.ac,
                          fontSize: 12,
                          ...mono,
                          fontWeight: 600,
                        }}
                      >
                        {rp.altMachine}
                      </span>
                      <span style={{ color: C.t3, fontSize: 12 }}>
                        ({fmtPct(rp.altLoadPct)} load)
                      </span>
                      <span style={{ marginLeft: 'auto', color: C.ac, fontSize: 12, ...mono }}>
                        saves {fmtMin(rp.minutesSaved)}
                      </span>
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
//  VIEW 7: SETUP CREW TIMELINE — Cross-machine Gantt
// ══════════════════════════════════════════════════════════════

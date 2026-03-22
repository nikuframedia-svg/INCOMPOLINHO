import React from 'react';
import { C, TC } from '@/theme/color-bridge';
import type { IntelData } from '../../compute';
import { StatRow } from '../intel-atoms';
import { cardSt, labelSt, MC, mono, toolFamily } from '../intel-helpers';

export function ToolGroupView({ data }: { data: IntelData }) {
  const { toolGrouping } = data;

  // Family color mapping
  const familyColors: Record<string, string> = {};
  let fci = 0;
  const allFamilies = new Set(
    toolGrouping.flatMap((tg) =>
      [...tg.currentSequence, ...tg.optimalSequence].map((t) => toolFamily(t)),
    ),
  );
  allFamilies.forEach((f) => {
    familyColors[f] = TC[fci++ % TC.length];
  });

  // Compute cross-family transitions (meaningful metric)
  const countFamilyChanges = (seq: string[]): number => {
    let count = 0;
    for (let i = 1; i < seq.length; i++) {
      if (toolFamily(seq[i]) !== toolFamily(seq[i - 1])) count++;
    }
    return count;
  };

  const totalSaved = toolGrouping.reduce((s, tg) => {
    const cur = countFamilyChanges(tg.currentSequence);
    const opt = countFamilyChanges(tg.optimalSequence);
    return s + Math.max(0, cur - opt);
  }, 0);

  return (
    <div>
      <StatRow
        items={[
          { label: 'Machines Analyzed', value: toolGrouping.length },
          {
            label: 'Family Transitions Saved',
            value: totalSaved,
            color: totalSaved > 0 ? C.ac : C.t2,
          },
          {
            label: 'Total Tools',
            value: toolGrouping.reduce((s, tg) => s + tg.currentSequence.length, 0),
          },
        ]}
      />
      {/* Family legend */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        {Object.entries(familyColors).map(([fam, color]) => (
          <div key={fam} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: color }} />
            <span style={{ color: C.t2, fontSize: 12, ...mono }}>{fam}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {toolGrouping.map((tg) => {
          const curChanges = countFamilyChanges(tg.currentSequence);
          const optChanges = countFamilyChanges(tg.optimalSequence);
          const saved = Math.max(0, curChanges - optChanges);
          return (
            <div key={tg.machine} style={cardSt}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <div
                  style={{ width: 10, height: 10, borderRadius: '50%', background: MC[tg.machine] }}
                />
                <span style={{ color: C.t1, fontSize: 14, fontWeight: 600, ...mono }}>
                  {tg.machine}
                </span>
                <span style={{ color: C.t3, fontSize: 12 }}>
                  {tg.area} — {tg.currentSequence.length} tools
                </span>
                {saved > 0 && (
                  <span
                    style={{
                      marginLeft: 'auto',
                      color: C.ac,
                      fontSize: 12,
                      fontWeight: 600,
                      ...mono,
                      padding: '2px 8px',
                      background: C.acS,
                      borderRadius: 4,
                    }}
                  >
                    -{saved} family change{saved !== 1 ? 's' : ''}
                  </span>
                )}
              </div>
              {/* Current sequence */}
              <div style={{ marginBottom: 8 }}>
                <span style={{ ...labelSt, fontSize: 12, display: 'block', marginBottom: 4 }}>
                  CURRENT (DEMAND ORDER)
                </span>
                <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  {tg.currentSequence.map((t, i) => {
                    const fam = toolFamily(t);
                    const prevFam = i > 0 ? toolFamily(tg.currentSequence[i - 1]) : fam;
                    const isChange = i > 0 && fam !== prevFam;
                    return (
                      <React.Fragment key={`cur-${i}`}>
                        {isChange && (
                          <div
                            style={{
                              width: 2,
                              height: 22,
                              background: C.rd,
                              borderRadius: 1,
                              alignSelf: 'center',
                              margin: '0 1px',
                            }}
                          />
                        )}
                        <div
                          style={{
                            padding: '3px 6px',
                            borderRadius: 4,
                            fontSize: 12,
                            ...mono,
                            background: `${familyColors[fam]}22`,
                            color: familyColors[fam],
                            border: `1px solid ${familyColors[fam]}44`,
                          }}
                        >
                          {t}
                        </div>
                      </React.Fragment>
                    );
                  })}
                </div>
                <span style={{ color: C.t4, fontSize: 12, marginTop: 2, display: 'block' }}>
                  {curChanges} family transition{curChanges !== 1 ? 's' : ''}
                </span>
              </div>
              {/* Optimal sequence */}
              <div>
                <span style={{ ...labelSt, fontSize: 12, display: 'block', marginBottom: 4 }}>
                  OPTIMAL (FAMILY GROUPED)
                </span>
                <div style={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                  {tg.optimalSequence.map((t, i) => {
                    const fam = toolFamily(t);
                    const prevFam = i > 0 ? toolFamily(tg.optimalSequence[i - 1]) : fam;
                    const isChange = i > 0 && fam !== prevFam;
                    return (
                      <React.Fragment key={`opt-${i}`}>
                        {isChange && (
                          <div
                            style={{
                              width: 2,
                              height: 22,
                              background: C.ac,
                              borderRadius: 1,
                              alignSelf: 'center',
                              margin: '0 1px',
                            }}
                          />
                        )}
                        <div
                          style={{
                            padding: '3px 6px',
                            borderRadius: 4,
                            fontSize: 12,
                            ...mono,
                            background: `${familyColors[fam]}22`,
                            color: familyColors[fam],
                            border: `1px solid ${familyColors[fam]}44`,
                          }}
                        >
                          {t}
                        </div>
                      </React.Fragment>
                    );
                  })}
                </div>
                <span style={{ color: C.t4, fontSize: 12, marginTop: 2, display: 'block' }}>
                  {optChanges} family transition{optChanges !== 1 ? 's' : ''}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════
//  VIEW 9: MACHINE ALTERNATIVE NETWORK — Force-directed graph
// ══════════════════════════════════════════════════════════════

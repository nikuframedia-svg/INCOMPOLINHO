import React from 'react';
import type { OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Card } from '../atoms';

export function ComparisonTable({
  top3,
  sel,
  rankColor,
  rankLabel,
}: {
  top3: OptResult[];
  sel: number;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
}) {
  const rows = [
    {
      l: 'OTD-D',
      f: (s2: OptResult) => `${s2.otdDelivery.toFixed(1)}%`,
      best: (s2: OptResult) => s2.otdDelivery,
    },
    {
      l: 'OTD Produção',
      f: (s2: OptResult) => `${s2.otd.toFixed(1)}%`,
      best: (s2: OptResult) => s2.otd,
    },
    {
      l: 'Produção',
      f: (s2: OptResult) => `${(s2.produced / 1000).toFixed(0)}K`,
      best: (s2: OptResult) => s2.produced,
    },
    {
      l: 'Peças Perdidas',
      f: (s2: OptResult) => (s2.lostPcs > 0 ? `${(s2.lostPcs / 1000).toFixed(1)}K` : '0'),
      best: (s2: OptResult) => -s2.lostPcs,
    },
    { l: 'Setups', f: (s2: OptResult) => s2.setupCount, best: (s2: OptResult) => -s2.setupCount },
    {
      l: 'Setup Time',
      f: (s2: OptResult) => `${Math.round(s2.setupMin)}min`,
      best: (s2: OptResult) => -s2.setupMin,
    },
    {
      l: 'Movimentos',
      f: (s2: OptResult) => s2.moves.length,
      best: (s2: OptResult) => -s2.moves.length,
    },
    {
      l: 'Pico Operadores',
      f: (s2: OptResult) => s2.peakOps,
      best: (s2: OptResult) => -s2.peakOps,
    },
    {
      l: 'Over Capacity',
      f: (s2: OptResult) => s2.overflows,
      best: (s2: OptResult) => -s2.overflows,
    },
    { l: 'Score', f: (s2: OptResult) => s2.score.toFixed(1), best: (s2: OptResult) => s2.score },
  ];

  return (
    <Card style={{ padding: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
        Comparação Cenários
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '120px repeat(3,1fr)', gap: 3 }}>
        <div />
        {top3.map((_, i) => (
          <div key={i} style={{ textAlign: 'center', padding: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: rankColor(i) }}>
              {rankLabel(i)}
            </span>
          </div>
        ))}
        {rows.map((row, ri) => (
          <React.Fragment key={ri}>
            <div style={{ fontSize: 12, color: C.t3, padding: '4px 0', fontWeight: 500 }}>
              {row.l}
            </div>
            {top3.map((s2, ci) => {
              const isBest = top3.every((s3) => row.best(s2) >= row.best(s3));
              return (
                <div
                  key={ci}
                  style={{
                    textAlign: 'center',
                    fontSize: 12,
                    fontWeight: isBest ? 800 : 500,
                    color: isBest ? rankColor(ci) : C.t2,
                    fontFamily: 'monospace',
                    padding: '4px 0',
                    background: ci === sel ? C.s3 : 'transparent',
                    borderRadius: 4,
                  }}
                >
                  {String(row.f(s2))}
                </div>
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </Card>
  );
}

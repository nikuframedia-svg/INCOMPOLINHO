/**
 * MRPTrustBanner — Data confidence indicator for MRP page.
 * Reads TrustIndex from data store (computed during ISOP parsing).
 */

import { C } from '@/lib/engine';
import { useDataStore } from '@/stores/useDataStore';
import { mono } from '../utils/mrp-helpers';

function classifyGate(score: number): { label: string; color: string } {
  if (score >= 0.9) return { label: 'Full Auto', color: C.ac };
  if (score >= 0.7) return { label: 'Monitoring', color: C.ac };
  if (score >= 0.5) return { label: 'Suggestion', color: C.yl };
  return { label: 'Manual', color: C.rd };
}

export function MRPTrustBanner() {
  const trustScore = useDataStore((s) => s.meta?.trustScore);

  if (trustScore == null) return null;

  const gate = classifyGate(trustScore);
  const isLow = trustScore < 0.7;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '6px 12px',
        borderRadius: 6,
        background: isLow ? `${C.yl}12` : `${C.ac}08`,
        borderLeft: `3px solid ${gate.color}`,
        marginBottom: 12,
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: gate.color,
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize: 11, color: C.t2 }}>
        Confiança dos dados:{' '}
        <span style={{ fontWeight: 700, color: gate.color, ...mono }}>{trustScore.toFixed(2)}</span>
      </span>
      <span style={{ fontSize: 9, color: C.t3 }}>{gate.label}</span>
      {isLow && (
        <span style={{ fontSize: 9, color: C.yl, marginLeft: 'auto', fontWeight: 500 }}>
          Projecções de stock podem não ser fiáveis
        </span>
      )}
    </div>
  );
}

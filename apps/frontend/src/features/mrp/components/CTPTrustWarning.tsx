/**
 * CTPTrustWarning — shows a warning banner when TrustIndex is below threshold.
 */

import { AlertTriangle } from 'lucide-react';
import { C } from '@/theme/color-bridge';

export function CTPTrustWarning({ score }: { score: number }) {
  if (score >= 0.7) return null;
  return (
    <div
      style={{
        padding: '6px 12px',
        background: `${C.yl}14`,
        border: `1px solid ${C.yl}30`,
        borderRadius: 4,
        fontSize: 12,
        color: C.yl,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        marginBottom: 12,
      }}
    >
      <AlertTriangle size={12} />
      TrustIndex baixo ({(score * 100).toFixed(0)}%) — resultados CTP com menor fiabilidade
    </div>
  );
}

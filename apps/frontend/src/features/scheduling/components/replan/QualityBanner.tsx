import { AlertTriangle } from 'lucide-react';
import { C } from '@/theme/color-bridge';

export function QualityBanner({
  qv,
}: {
  qv: { criticalCount: number; highCount: number; warnings: string[] };
}) {
  if (qv.criticalCount === 0 && qv.highCount === 0) return null;
  const isCrit = qv.criticalCount > 0;
  const color = isCrit ? C.rd : C.yl;
  const bg = isCrit ? C.rdS : `${C.yl}18`;
  const critTxt = isCrit
    ? `${qv.criticalCount} conflito${qv.criticalCount > 1 ? 's' : ''} crítico${qv.criticalCount > 1 ? 's' : ''}`
    : '';
  const highTxt = qv.highCount > 0 ? `${qv.highCount} alerta${qv.highCount > 1 ? 's' : ''}` : '';
  const sep = critTxt && highTxt ? ' · ' : '';
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 6,
        background: bg,
        borderLeft: `3px solid ${color}`,
      }}
    >
      <AlertTriangle size={13} style={{ color, flexShrink: 0 }} />
      <span style={{ fontSize: 12, fontWeight: 600, color }}>
        {critTxt}
        {sep}
        {highTxt}
      </span>
      {qv.warnings.length > 0 && (
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>{qv.warnings[0]}</span>
      )}
    </div>
  );
}

import { X } from 'lucide-react';
import { C } from '@/theme/color-bridge';

export function SchedulingBanners({
  isopBanner,
  setIsopBanner,
  isScheduling,
}: {
  isopBanner: string | null;
  setIsopBanner: (v: string | null) => void;
  isScheduling: boolean;
}) {
  return (
    <>
      {isopBanner && (
        <div
          style={{
            padding: '8px 16px',
            borderRadius: 6,
            marginBottom: 12,
            background: C.ylS,
            border: `1px solid ${C.yl}40`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span style={{ fontSize: 12, color: C.yl, fontWeight: 500 }}>{isopBanner}</span>
          <button
            onClick={() => setIsopBanner(null)}
            aria-label="Fechar banner"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: C.t3,
              padding: 2,
            }}
          >
            <X size={14} strokeWidth={1.5} />
          </button>
        </div>
      )}
      {isScheduling && (
        <div
          style={{
            padding: '6px 12px',
            borderRadius: 6,
            background: `${C.ac}15`,
            border: `1px solid ${C.ac}33`,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginBottom: 8,
          }}
        >
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: C.ac,
              animation: 'pulse 1s infinite',
            }}
          />
          <span style={{ fontSize: 12, color: C.ac, fontWeight: 600 }}>
            A recalcular schedule...
          </span>
        </div>
      )}
    </>
  );
}

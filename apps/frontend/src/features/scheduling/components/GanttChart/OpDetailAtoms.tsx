import type React from 'react';
import { C } from '@/theme/color-bridge';

export function Sec({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ borderTop: `1px solid ${C.bd}`, padding: '10px 14px' }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.t4,
          letterSpacing: '.06em',
          textTransform: 'uppercase',
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

export function Row({ k, v, color }: { k: string; v: React.ReactNode; color?: string }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        padding: '2px 0',
      }}
    >
      <span style={{ fontSize: 12, color: C.t3 }}>{k}</span>
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: color || C.t1,
          fontFamily: "'JetBrains Mono',monospace",
        }}
      >
        {v}
      </span>
    </div>
  );
}

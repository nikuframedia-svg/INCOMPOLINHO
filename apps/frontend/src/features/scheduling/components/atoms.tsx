import type React from 'react';
import type { ETool } from '@/domain/types/scheduling';
import { C, TC, tci } from '@/theme/color-bridge';

export function Pill({
  children,
  color,
  active,
  onClick,
  size = 'sm',
  title,
  'aria-label': ariaLabel,
}: {
  children: React.ReactNode;
  color: string;
  active?: boolean;
  onClick?: () => void;
  size?: 'sm' | 'md';
  title?: string;
  'aria-label'?: string;
}) {
  const s = size === 'sm';
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: s ? '3px 8px' : '5px 12px',
        borderRadius: 20,
        fontSize: s ? 10 : 11,
        fontWeight: 600,
        background: active ? `${color}20` : 'transparent',
        border: `1.5px solid ${active ? `${color}55` : C.bd}`,
        color: active ? color : C.t2,
        cursor: onClick ? 'pointer' : 'default',
        fontFamily: 'inherit',
        transition: 'all .15s',
        letterSpacing: '.01em',
      }}
    >
      {children}
    </button>
  );
}

export function Tag({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span
      style={{
        fontSize: 12,
        fontWeight: 600,
        color,
        letterSpacing: '.04em',
        textTransform: 'uppercase',
      }}
    >
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  sub,
  color,
  large,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  color?: string;
  large?: boolean;
}) {
  return (
    <div style={{ padding: large ? '16px' : '12px 14px' }}>
      <div
        style={{
          fontSize: 12,
          color: C.t3,
          fontWeight: 500,
          marginBottom: 4,
          letterSpacing: '.02em',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: large ? 24 : 20,
          fontWeight: 600,
          color: color || C.t1,
          fontFamily: "'JetBrains Mono',monospace",
          lineHeight: 1,
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: C.t3, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

export function Card({ children, style: sx, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div style={{ background: C.s2, borderRadius: 8, border: `1px solid ${C.bd}`, ...sx }} {...p}>
      {children}
    </div>
  );
}

export const fmtT = (min: number) =>
  `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(Math.round(min % 60)).padStart(2, '0')}`;

export const dot = (c: string, _pulse?: boolean): React.CSSProperties => ({
  display: 'inline-block',
  width: 7,
  height: 7,
  borderRadius: '50%',
  background: c,
});

export function toolColor(tools: ETool[], toolId: string): string {
  return (
    TC[
      tci(
        toolId,
        tools.map((t) => t.id),
      )
    ] ?? TC[0]
  );
}

import type React from 'react';
import { C, TC } from '../../../lib/engine';

export const MC: Record<string, string> = {
  PRM019: TC[0],
  PRM020: TC[1],
  PRM031: TC[2],
  PRM039: TC[3],
  PRM042: TC[4],
  PRM043: TC[5],
};

export const AREA: Record<string, string> = {
  PRM019: 'PG1',
  PRM020: 'PG1',
  PRM031: 'PG2',
  PRM039: 'PG2',
  PRM042: 'PG2',
  PRM043: 'PG1',
};

export function heatColor(pct: number): string {
  if (pct <= 0) return C.s3;
  if (pct < 40) return '#065F46';
  if (pct < 60) return '#047857';
  if (pct < 80) return '#059669';
  if (pct < 95) return '#D97706';
  if (pct < 100) return '#EA580C';
  return '#DC2626';
}

export function fmtPct(n: number): string {
  return n.toFixed(0) + '%';
}
export function fmtMin(n: number): string {
  return n < 60 ? `${n.toFixed(0)}m` : `${(n / 60).toFixed(1)}h`;
}
export function fmtQty(n: number): string {
  if (n >= 10000) return `${(n / 1000).toFixed(0)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n));
}
export function fmtDate(d: string): string {
  return d.slice(5).replace('-', '/');
}
export function timeStr(min: number): string {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}
export function toolFamily(id: string): string {
  return id.replace(/\d+/g, '');
}

export type IntelTab =
  | 'heatmap'
  | 'horizon'
  | 'urgency'
  | 'risk'
  | 'crossclient'
  | 'bottleneck'
  | 'setup'
  | 'toolgroup'
  | 'network'
  | 'explain';

export const TABS: Array<{ key: IntelTab; label: string }> = [
  { key: 'heatmap', label: 'Demand Heatmap' },
  { key: 'horizon', label: 'Capacity Horizon' },
  { key: 'urgency', label: 'Urgency Matrix' },
  { key: 'risk', label: 'Client Risk' },
  { key: 'crossclient', label: 'Cross-Client SKU' },
  { key: 'bottleneck', label: 'Bottleneck Cascade' },
  { key: 'setup', label: 'Setup Crew' },
  { key: 'toolgroup', label: 'Tool Grouping' },
  { key: 'network', label: 'Machine Network' },
  { key: 'explain', label: 'Explain Trace' },
];

export const mono: React.CSSProperties = {
  fontFamily: 'JetBrains Mono, Fira Code, Consolas, monospace',
};
export const labelSt: React.CSSProperties = {
  color: C.t3,
  fontSize: 12,
  fontWeight: 500,
  textTransform: 'uppercase' as const,
  letterSpacing: '0.06em',
};
export const cardSt: React.CSSProperties = {
  background: C.s2,
  borderRadius: 8,
  padding: 16,
  border: `1px solid ${C.bd}`,
};

export function clientColorMap(codes: string[]): Record<string, string> {
  const map: Record<string, string> = {};
  const unique = [...new Set(codes)];
  unique.forEach((c, i) => {
    map[c] = TC[i % TC.length];
  });
  return map;
}

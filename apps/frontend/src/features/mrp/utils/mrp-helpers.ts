import { C } from '@/theme/color-bridge';
export const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

export function projColor(val: number): string {
  if (val < 0) return C.rd;
  if (val === 0) return C.yl;
  return C.t1;
}

export function fmtQty(n: number): string {
  if (n === 0) return '-';
  if (Math.abs(n) >= 10000) return `${(n / 1000).toFixed(0)}K`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(Math.round(n));
}

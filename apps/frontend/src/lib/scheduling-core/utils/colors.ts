// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Color Constants
//  Theme colors and tool color palette
// ═══════════════════════════════════════════════════════════

/** Theme color palette (dark mode) */
export const C = {
  bg: '#0D0D0D',
  s1: '#141414',
  s2: '#141414',
  s3: '#1A1A1A',
  bd: '#1F1F1F',
  bh: 'rgba(20,184,166,0.30)',
  t1: '#FFFFFF',
  t2: '#9CA3AF',
  t3: '#6B7280',
  t4: '#374151',
  ac: '#14b8a6',
  acS: 'rgba(20,184,166,0.10)',
  acM: 'rgba(20,184,166,0.25)',
  rd: '#ef4444',
  rdS: 'rgba(239,68,68,0.20)',
  rdM: 'rgba(239,68,68,0.25)',
  yl: '#f59e0b',
  ylS: 'rgba(245,158,11,0.20)',
  bl: '#3b82f6',
  blS: 'rgba(59,130,246,0.20)',
  pp: '#a78bfa',
  ppS: 'rgba(167,139,250,0.20)',
  cy: '#22d3ee',
  w: '#FFFFFF',
} as const;

/** Tool color palette (16 distinct colors for Gantt blocks) */
export const TC = [
  '#34D399',
  '#60A5FA',
  '#FBBF24',
  '#A78BFA',
  '#F87171',
  '#22D3EE',
  '#F472B6',
  '#818CF8',
  '#4ADE80',
  '#FB923C',
  '#38BDF8',
  '#E879F9',
  '#FCD34D',
  '#67E8F9',
  '#C084FC',
  '#FDA4AF',
] as const;

/** Tool color index — maps tool ID to color */
export function tci(toolId: string, allToolIds: string[]): number {
  const idx = allToolIds.indexOf(toolId);
  return idx >= 0 ? idx % TC.length : 0;
}

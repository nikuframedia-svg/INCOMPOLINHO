// ═══════════════════════════════════════════════════════════
//  Color Bridge — CSS variable-aware drop-in for engine C
//
//  Engine C has hardcoded hex values (teal accent).
//  CSS vars in index.css use indigo accent + glassmorphism.
//  This bridge intercepts C property access and resolves
//  CSS vars to hex strings, keeping C.xx + 'HH' patterns working.
// ═══════════════════════════════════════════════════════════

/** Theme color palette (dark mode fallbacks) */
const EngineC = {
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
const EngineTC = [
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

/** Resolve a CSS custom property to its computed value */
function resolveVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const val = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return val || fallback;
}

// Engine C key → [CSS variable, fallback value]
// Fallbacks match index.css :root values
const VAR_MAP: Record<string, [cssVar: string, fallback: string]> = {
  // Backgrounds
  bg: ['--bg-void', '#06080D'],
  s1: ['--bg-surface-solid', '#0E1016'],
  s2: ['--bg-base', '#0E1016'],
  s3: ['--bg-raised', 'rgba(30,34,48,0.65)'],
  // Borders
  bd: ['--border-default', 'rgba(255,255,255,0.06)'],
  bh: ['--border-hover', 'rgba(129,140,248,0.30)'],
  // Text — 4 levels
  t1: ['--text-primary', '#F0F0F2'],
  t2: ['--text-secondary', '#8E919A'],
  t3: ['--text-muted', '#505362'],
  t4: ['--text-ghost', '#2A2D3A'],
  // Accent (teal → indigo)
  ac: ['--accent', '#818CF8'],
  acS: ['--accent-bg', 'rgba(129,140,248,0.12)'],
  acM: ['--accent-border', 'rgba(129,140,248,0.25)'],
  // Red semantic
  rd: ['--semantic-red', '#F87171'],
  rdS: ['--semantic-red-bg', 'rgba(248,113,113,0.12)'],
  rdM: ['', 'rgba(248,113,113,0.25)'],
  // Amber/Yellow
  yl: ['--semantic-amber', '#FBBF24'],
  ylS: ['--semantic-amber-bg', 'rgba(251,191,36,0.10)'],
  // Blue
  bl: ['--semantic-blue', '#60A5FA'],
  blS: ['--semantic-blue-bg', 'rgba(96,165,250,0.12)'],
  // Purple → accent
  pp: ['--accent', '#818CF8'],
  ppS: ['--accent-bg', 'rgba(129,140,248,0.12)'],
  // Cyan
  cy: ['--semantic-cyan', '#22D3EE'],
  // White
  w: ['--text-primary', '#F0F0F2'],
  // Extra: green (not in engine C, but useful)
  gn: ['--semantic-green', '#34D399'],
};

let _cache: Record<string, string> | null = null;

function resolve(): Record<string, string> {
  if (_cache) return _cache;
  _cache = {};
  for (const [key, [cssVar, fallback]] of Object.entries(VAR_MAP)) {
    _cache[key] = cssVar ? resolveVar(cssVar, fallback) : fallback;
  }
  return _cache;
}

/**
 * Drop-in replacement for engine C.
 * Proxy resolves CSS vars on first property access.
 */
export const C: typeof EngineC & { gn: string } = new Proxy(EngineC as Record<string, string>, {
  get(target: Record<string, string>, key: string) {
    const resolved = resolve();
    return key in resolved ? resolved[key] : target[key];
  },
}) as typeof EngineC & { gn: string };

/** TC unchanged — tool palette colors are category-based, not theme-dependent. */
export const TC = EngineTC;

/** Tool color index — maps tool ID to color */
export function tci(toolId: string, allToolIds: string[]): number {
  const idx = allToolIds.indexOf(toolId);
  return idx >= 0 ? idx % TC.length : 0;
}

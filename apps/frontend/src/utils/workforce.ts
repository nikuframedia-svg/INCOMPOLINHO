/**
 * Workforce helper — moved from engine.ts.
 */

import type { ZoneShiftDemand } from '@/domain/types/scheduling';
import type { OpDay } from '@/domain/types/scheduling/legacy';

export function opsByDayFromWorkforce(wfd: ZoneShiftDemand[], nDays: number): OpDay[] {
  const result: OpDay[] = Array.from({ length: nDays }, () => ({ pg1: 0, pg2: 0, total: 0 }));
  for (const e of wfd) {
    if (e.dayIdx < 0 || e.dayIdx >= nDays) continue;
    if (e.laborGroup === 'Grandes') {
      result[e.dayIdx].pg1 = Math.max(result[e.dayIdx].pg1, e.peakNeed);
    } else {
      result[e.dayIdx].pg2 = Math.max(result[e.dayIdx].pg2, e.peakNeed);
    }
  }
  for (const r of result) r.total = r.pg1 + r.pg2;
  return result;
}

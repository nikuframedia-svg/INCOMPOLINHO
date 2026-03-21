// ═══════════════════════════════════════════════════════════
//  INCOMPOL PLAN — Shift-in-failure-window utility
//  Shared by failure-timeline.ts and impact-analysis.ts
// ═══════════════════════════════════════════════════════════

import type { FailureEvent, ShiftId } from '../types/failure.js';

/**
 * Check whether a given (day, shift) falls within the failure's
 * temporal window [startDay/startShift .. endDay/endShift].
 */
export function isShiftInFailureWindow(
  fe: FailureEvent,
  day: number,
  shift: ShiftId,
  activeShifts: ShiftId[],
): boolean {
  if (day < fe.startDay || day > fe.endDay) return false;

  const si = activeShifts.indexOf(shift);
  if (si < 0) return false;

  // On the start day, only shifts >= startShift are affected
  if (day === fe.startDay && fe.startShift) {
    const startIdx = activeShifts.indexOf(fe.startShift);
    if (startIdx >= 0 && si < startIdx) return false;
  }

  // On the end day, only shifts <= endShift are affected
  if (day === fe.endDay && fe.endShift) {
    const endIdx = activeShifts.indexOf(fe.endShift);
    if (endIdx >= 0 && si > endIdx) return false;
  }

  return true;
}

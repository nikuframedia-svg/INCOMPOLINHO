// ═══════════════════════════════════════════════════════════
//  Time Utilities
//  Shift boundaries, minute formatting, absolute time
// ═══════════════════════════════════════════════════════════

import {
  DEFAULT_MO_CAPACITY,
  MINUTES_PER_DAY,
  S0,
  S1,
  S2,
  T1,
} from '@/domain/types/scheduling/constants';

/** Format minutes as HH:MM */
export function fmtMin(m: number): string {
  const wrapped = ((m % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  const h = Math.floor(wrapped / 60);
  const min = Math.round(wrapped % 60);
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

/** Convert (dayIdx, minuteInDay) to absolute minutes from day 0 */
export function toAbs(day: number, min: number): number {
  return day * MINUTES_PER_DAY + min;
}

/** Convert absolute minutes back to (dayIdx, minuteInDay) */
export function fromAbs(abs: number): { day: number; min: number } {
  return { day: Math.floor(abs / MINUTES_PER_DAY), min: abs % MINUTES_PER_DAY };
}

/** Get shift for a given minute within a day */
export function getShift(min: number, thirdShift?: boolean): 'X' | 'Y' | 'Z' {
  if (min >= S0 && min < T1) return 'X';
  if (min >= T1 && min < S1) return 'Y';
  if (thirdShift) return 'Z';
  return 'X';
}

/** Get shift end minute for a given shift */
export function getShiftEnd(shift: 'X' | 'Y' | 'Z'): number {
  if (shift === 'X') return T1;
  if (shift === 'Y') return S1;
  return S2;
}

/** Get shift start minute for a given shift */
export function getShiftStart(shift: 'X' | 'Y' | 'Z'): number {
  if (shift === 'X') return S0;
  if (shift === 'Y') return T1;
  return S1;
}

/** Infer workday flags from day-of-week labels */
export function inferWorkdaysFromLabels(dnames: string[], nDays: number): boolean[] {
  const WE = new Set(['Sáb', 'Dom', 'Sab', 'SAB', 'DOM']);
  if (dnames.length >= nDays) return dnames.slice(0, nDays).map((l) => !WE.has(l));
  return Array(nDays).fill(true) as boolean[];
}

/**
 * Pad MO (operator capacity) array to target length.
 */
export function padMoArray(
  arr: number[],
  targetLen: number,
  strategy: 'cyclic' | 'nominal' | 'custom',
  nominalVal: number,
): number[] {
  if (!arr || arr.length === 0) return Array(targetLen).fill(DEFAULT_MO_CAPACITY) as number[];
  if (arr.length >= targetLen) return arr.slice(0, targetLen);
  const result = [...arr];
  const srcLen = arr.length;
  while (result.length < targetLen) {
    if (strategy === 'cyclic') {
      result.push(arr[result.length % srcLen]);
    } else {
      result.push(nominalVal);
    }
  }
  return result;
}

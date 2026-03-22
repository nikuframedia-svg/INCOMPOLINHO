// ═══════════════════════════════════════════════════════════
//  Failure Timeline Builder
//  Converts FailureEvent[] into per-resource ResourceTimeline maps.
// ═══════════════════════════════════════════════════════════

import type {
  DayShiftCapacity,
  DayShiftStatus,
  FailureEvent,
  ResourceTimeline,
  ShiftId,
} from '@/domain/types/scheduling';

// ── Shift-in-failure-window utility ──

function isShiftInFailureWindow(
  fe: FailureEvent,
  day: number,
  shift: ShiftId,
  activeShifts: ShiftId[],
): boolean {
  if (day < fe.startDay || day > fe.endDay) return false;
  const si = activeShifts.indexOf(shift);
  if (si < 0) return false;
  if (day === fe.startDay && fe.startShift) {
    const startIdx = activeShifts.indexOf(fe.startShift);
    if (startIdx >= 0 && si < startIdx) return false;
  }
  if (day === fe.endDay && fe.endShift) {
    const endIdx = activeShifts.indexOf(fe.endShift);
    if (endIdx >= 0 && si > endIdx) return false;
  }
  return true;
}

// ── Default (healthy) slot ──

function mkDefault(): DayShiftCapacity {
  return { status: 'running', capacityFactor: 1.0, failureIds: [] };
}

function statusFromFactor(cf: number): DayShiftStatus {
  if (cf <= 0) return 'down';
  if (cf < 0.7) return 'partial';
  if (cf < 1.0) return 'degraded';
  return 'running';
}

function mkEmptyTimeline(nDays: number, activeShifts: ShiftId[]): ResourceTimeline {
  const tl: ResourceTimeline = [];
  for (let d = 0; d < nDays; d++) {
    const rec: Record<ShiftId, DayShiftCapacity> = {} as Record<ShiftId, DayShiftCapacity>;
    for (const s of activeShifts) rec[s] = mkDefault();
    tl.push(rec);
  }
  return tl;
}

/**
 * Convert FailureEvent[] into per-resource ResourceTimeline maps.
 */
export function buildResourceTimelines(
  failures: FailureEvent[],
  nDays: number,
  thirdShift?: boolean,
): {
  machineTimelines: Record<string, ResourceTimeline>;
  toolTimelines: Record<string, ResourceTimeline>;
} {
  const activeShifts: ShiftId[] = thirdShift ? ['X', 'Y', 'Z'] : ['X', 'Y'];
  const machineTimelines: Record<string, ResourceTimeline> = {};
  const toolTimelines: Record<string, ResourceTimeline> = {};
  const idSets = new Map<DayShiftCapacity, Set<string>>();

  for (const fe of failures) {
    const store = fe.resourceType === 'machine' ? machineTimelines : toolTimelines;
    if (!store[fe.resourceId]) {
      store[fe.resourceId] = mkEmptyTimeline(nDays, activeShifts);
    }
    const tl = store[fe.resourceId];
    const dStart = Math.max(fe.startDay, 0);
    const dEnd = Math.min(fe.endDay, nDays - 1);

    for (let d = dStart; d <= dEnd; d++) {
      for (const sh of activeShifts) {
        if (!isShiftInFailureWindow(fe, d, sh, activeShifts)) continue;
        const slot = tl[d][sh];
        const newFactor = Math.min(slot.capacityFactor, fe.capacityFactor);
        slot.capacityFactor = newFactor;
        slot.status = statusFromFactor(newFactor);
        let ids = idSets.get(slot);
        if (!ids) {
          ids = new Set(slot.failureIds);
          idSets.set(slot, ids);
        }
        if (!ids.has(fe.id)) {
          ids.add(fe.id);
          slot.failureIds.push(fe.id);
        }
      }
    }
  }

  return { machineTimelines, toolTimelines };
}

/**
 * Derive legacy-compatible binary status maps from failure events.
 */
export function deriveLegacyStatus(
  failures: FailureEvent[],
  nDays: number,
  thirdShift?: boolean,
): {
  mSt: Record<string, 'running' | 'down'>;
  tSt: Record<string, 'running' | 'down'>;
} {
  const { machineTimelines, toolTimelines } = buildResourceTimelines(failures, nDays, thirdShift);
  const activeShifts: ShiftId[] = thirdShift ? ['X', 'Y', 'Z'] : ['X', 'Y'];

  const derive = (
    timelines: Record<string, ResourceTimeline>,
  ): Record<string, 'running' | 'down'> => {
    const st: Record<string, 'running' | 'down'> = {};
    for (const [resId, tl] of Object.entries(timelines)) {
      let allDown = true;
      for (let d = 0; d < nDays && allDown; d++) {
        for (const sh of activeShifts) {
          if (tl[d]?.[sh]?.capacityFactor > 0) {
            allDown = false;
            break;
          }
        }
      }
      st[resId] = allDown ? 'down' : 'running';
    }
    return st;
  };

  return {
    mSt: derive(machineTimelines),
    tSt: derive(toolTimelines),
  };
}

/**
 * Convert legacy binary status maps into equivalent FailureEvent[].
 */
export function legacyStatusToFailureEvents(
  mSt: Record<string, string>,
  tSt: Record<string, string>,
  nDays: number,
): FailureEvent[] {
  const events: FailureEvent[] = [];
  let seq = 0;

  for (const [id, status] of Object.entries(mSt)) {
    if (status === 'down') {
      events.push({
        id: `legacy-m-${id}-${seq++}`,
        resourceType: 'machine',
        resourceId: id,
        startDay: 0,
        startShift: null,
        endDay: nDays - 1,
        endShift: null,
        severity: 'total',
        capacityFactor: 0,
        description: 'Legacy binary down status',
      });
    }
  }

  for (const [id, status] of Object.entries(tSt)) {
    if (status === 'down') {
      events.push({
        id: `legacy-t-${id}-${seq++}`,
        resourceType: 'tool',
        resourceId: id,
        startDay: 0,
        startShift: null,
        endDay: nDays - 1,
        endShift: null,
        severity: 'total',
        capacityFactor: 0,
        description: 'Legacy binary down status',
      });
    }
  }

  return events;
}

/**
 * Returns true if the resource has zero capacity for every active shift
 * across the given day range [fromDay, toDay] inclusive.
 */
export function isFullyDown(
  timeline: ResourceTimeline | undefined,
  fromDay: number,
  toDay: number,
  thirdShift?: boolean,
): boolean {
  if (!timeline) return false;
  const activeShifts: ShiftId[] = thirdShift ? ['X', 'Y', 'Z'] : ['X', 'Y'];

  for (let d = fromDay; d <= toDay; d++) {
    if (!timeline[d]) return false;
    for (const sh of activeShifts) {
      if (!timeline[d][sh]) return false;
      if (timeline[d][sh].capacityFactor > 0) return false;
    }
  }
  return true;
}

/**
 * Get capacity factor for a specific resource/day/shift.
 * Returns 1.0 (full capacity) if no timeline data exists.
 */
export function getCapacityFactor(
  timeline: ResourceTimeline | undefined,
  dayIdx: number,
  shift: ShiftId,
): number {
  if (!timeline?.[dayIdx]?.[shift]) return 1.0;
  return timeline[dayIdx][shift].capacityFactor;
}

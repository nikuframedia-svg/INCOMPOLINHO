// compute/setup-timeline.ts — Feature 4: Setup Crew Timeline

import { S0, S1, T1 } from '@/domain/types/scheduling';
import { MACHINES } from './constants';
import type { DateContext, NkData } from './types';

export interface SetupSlot {
  machine: string;
  toolCode: string;
  dayIdx: number;
  startMin: number;
  endMin: number;
  durationMin: number;
  shift: 'X' | 'Y';
}

export function computeSetupCrewTimeline(nk: NkData, ctx?: DateContext): SetupSlot[] {
  const slots: SetupSlot[] = [];

  const wdCount = ctx ? ctx.workingDates.length : 24;
  const numDays = Math.min(8, wdCount);

  for (let di = 0; di < numDays; di++) {
    const daySetups: Array<{ start: number; end: number }> = [];

    function findNextSlot(earliest: number, duration: number, shiftEnd: number): number {
      let candidate = earliest;
      let changed = true;
      while (changed) {
        changed = false;
        for (const s of daySetups) {
          if (candidate < s.end && candidate + duration > s.start) {
            candidate = s.end;
            changed = true;
          }
        }
      }
      return candidate + duration <= shiftEnd ? candidate : -1;
    }

    for (const machineId of MACHINES) {
      const machineTools = nk.tools.filter((t) => t.m === machineId);
      if (machineTools.length === 0) continue;

      const sorted = [...machineTools].sort((a, b) => {
        if (a.stk === 0 && b.stk > 0) return -1;
        if (b.stk === 0 && a.stk > 0) return 1;
        return b.pH - a.pH;
      });

      let lastTool: string | null = null;
      let cursor = S0;

      for (const tool of sorted) {
        if (tool.id === lastTool) continue;

        const setupMin = tool.s * 60;
        if (setupMin <= 0) {
          lastTool = tool.id;
          continue;
        }

        let shiftEnd = cursor < T1 ? T1 : S1;
        let start = findNextSlot(cursor, setupMin, shiftEnd);

        if (start < 0 && cursor < T1) {
          cursor = T1;
          shiftEnd = S1;
          start = findNextSlot(cursor, setupMin, shiftEnd);
        }

        if (start >= 0) {
          const end = start + setupMin;
          daySetups.push({ start, end });
          slots.push({
            machine: machineId,
            toolCode: tool.id,
            dayIdx: di,
            startMin: start,
            endMin: end,
            durationMin: setupMin,
            shift: start < T1 ? 'X' : 'Y',
          });
          cursor = end;
        }

        lastTool = tool.id;
      }
    }
  }

  return slots;
}

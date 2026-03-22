import { useMemo, useState } from 'react';

import type { Block, EMachine, ScheduleValidationReport } from '@/domain/types/scheduling';
import { S0, S1, S2 } from '@/domain/types/scheduling';

export interface GanttInteractionState {
  hov: string | null;
  selDay: number;
  selM: string | null;
  zoom: number;
  selOp: string | null;
  selBlock: Block | null;
  dayB: Block[];
  dayBlkN: number;
  activeM: EMachine[];
  wdi: number[];
  ppm: number;
  totalW: number;
  violationsByDay: Record<number, number>;
}

export interface GanttInteractionActions {
  setHov: (v: string | null) => void;
  setSelDay: (v: number) => void;
  setSelM: (v: string | null) => void;
  setZoom: (v: number) => void;
  setSelOp: (v: string | null) => void;
}

export function useGanttInteraction(
  blocks: Block[],
  machines: EMachine[],
  mSt: Record<string, string>,
  workdays: boolean[],
  validation?: ScheduleValidationReport | null,
  thirdShift?: boolean,
): { state: GanttInteractionState; actions: GanttInteractionActions } {
  const wdi = useMemo(
    () => workdays.map((w: boolean, i: number) => (w ? i : -1)).filter((i): i is number => i >= 0),
    [workdays],
  );

  const [hov, setHov] = useState<string | null>(null);
  const [selDay, setSelDay] = useState(() => (wdi.length > 0 ? wdi[0] : 0));
  const [selM, setSelM] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [selOp, setSelOp] = useState<string | null>(null);

  const selBlock = useMemo(
    () => (selOp ? (blocks.find((b) => b.opId === selOp && b.dayIdx === selDay) ?? null) : null),
    [blocks, selOp, selDay],
  );

  const dayB = useMemo(
    () =>
      blocks.filter(
        (b) =>
          b.dayIdx === selDay &&
          b.type !== 'blocked' &&
          (b.endMin - b.startMin >= 2 || b.setupS != null),
      ),
    [blocks, selDay],
  );

  const dayBlkN = useMemo(
    () =>
      new Set(blocks.filter((b) => b.dayIdx === selDay && b.type === 'blocked').map((b) => b.opId))
        .size,
    [blocks, selDay],
  );

  const activeM = useMemo(() => {
    const ms = new Set<string>();
    blocks.filter((b) => b.dayIdx === selDay).forEach((b) => ms.add(b.machineId));
    Object.entries(mSt).forEach(([id, s]) => {
      if (s === 'down') ms.add(id);
    });
    let a = machines.filter((m) => ms.has(m.id));
    if (selM) a = a.filter((m) => m.id === selM);
    return a;
  }, [blocks, selDay, selM, mSt, machines]);

  const ppm = 1.2 * zoom;
  const totalW = (thirdShift ? S2 - S0 : S1 - S0) * ppm;

  const violationsByDay = useMemo(() => {
    if (!validation) return {} as Record<number, number>;
    const byDay: Record<number, number> = {};
    for (const v of validation.violations) {
      const daySet = new Set<number>();
      for (const op of v.affectedOps) daySet.add(op.dayIdx);
      for (const d of daySet) byDay[d] = (byDay[d] || 0) + 1;
    }
    return byDay;
  }, [validation]);

  return {
    state: {
      hov,
      selDay,
      selM,
      zoom,
      selOp,
      selBlock,
      dayB,
      dayBlkN,
      activeM,
      wdi,
      ppm,
      totalW,
      violationsByDay,
    },
    actions: { setHov, setSelDay, setSelM, setZoom, setSelOp },
  };
}

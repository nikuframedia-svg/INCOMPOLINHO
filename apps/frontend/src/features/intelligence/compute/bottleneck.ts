// compute/bottleneck.ts — Feature 3: Bottleneck Cascade

import { DAY_CAP } from '@/domain/types/scheduling';
import { MACHINE_AREA, MACHINES } from './constants';
import type { HeatmapCell } from './heatmap';
import { buildRoutingIndex } from './index-builders';
import type { NkData, SnapshotFixture } from './types';

export interface ReliefPath {
  toolCode: string;
  altMachine: string;
  minutesSaved: number;
  altLoadPct: number;
}

export interface BottleneckNode {
  machine: string;
  area: string;
  peakPct: number;
  overflowDays: number;
  totalOverflowMin: number;
  hasAlternatives: boolean;
  reliefPaths: ReliefPath[];
}

export function computeBottleneckCascade(
  heatmap: HeatmapCell[][],
  snap: SnapshotFixture,
  nk: NkData,
): BottleneckNode[] {
  const ri = buildRoutingIndex(snap);

  const nodes: BottleneckNode[] = MACHINES.map((m, mi) => {
    const row = heatmap[mi];
    const peakPct = Math.max(...row.map((c) => c.pct));
    const overflowDays = row.filter((c) => c.pct > 100).length;
    const totalOverflowMin = row.reduce((s, c) => s + Math.max(0, c.loadMin - DAY_CAP), 0);

    const toolsOnMachine = nk.tools.filter((t) => t.m === m);
    const hasAlt = toolsOnMachine.some((t) => t.alt && t.alt !== '-');

    const reliefPaths: ReliefPath[] = [];
    if (peakPct > 100) {
      for (const tool of toolsOnMachine) {
        if (!tool.alt || tool.alt === '-') continue;
        const toolMinPerDay =
          tool.skus.reduce((sum, sku) => {
            const route = ri[sku];
            if (!route) return sum;
            const lotQty = tool.lt > 0 ? tool.lt : 1000;
            const prodMin = tool.pH > 0 ? (lotQty / tool.pH) * 60 : 0;
            return sum + prodMin / 8;
          }, 0) +
          tool.s * 60;

        const altMi = MACHINES.indexOf(tool.alt as (typeof MACHINES)[number]);
        const altPeak = altMi >= 0 ? Math.max(...heatmap[altMi].map((c) => c.pct)) : 0;

        reliefPaths.push({
          toolCode: tool.id,
          altMachine: tool.alt,
          minutesSaved: toolMinPerDay,
          altLoadPct: altPeak,
        });
      }
      reliefPaths.sort((a, b) => b.minutesSaved - a.minutesSaved);
    }

    return {
      machine: m,
      area: MACHINE_AREA[m],
      peakPct,
      overflowDays,
      totalOverflowMin,
      hasAlternatives: hasAlt,
      reliefPaths,
    };
  });

  return nodes.sort((a, b) => b.peakPct - a.peakPct);
}

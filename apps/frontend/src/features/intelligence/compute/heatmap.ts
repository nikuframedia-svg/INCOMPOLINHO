// compute/heatmap.ts — Feature 1: Demand Heatmap

import { DAY_CAP } from '@/domain/types/scheduling';
import { MACHINES } from './constants';
import { buildRoutingIndex, buildSeriesBySkuDate } from './index-builders';
import type { DateContext, NkData, SnapshotFixture } from './types';

export interface HeatmapCell {
  machine: string;
  date: string;
  dayIdx: number;
  loadMin: number;
  pct: number;
  skuCount: number;
}

export function computeDemandHeatmap(
  snap: SnapshotFixture,
  _nk: NkData,
  ctx: DateContext,
): HeatmapCell[][] {
  const ri = buildRoutingIndex(snap);
  const seriesIdx = buildSeriesBySkuDate(snap);

  const grid: HeatmapCell[][] = MACHINES.map((m) =>
    ctx.workingDates.map((d, di) => ({
      machine: m,
      date: d,
      dayIdx: di,
      loadMin: 0,
      pct: 0,
      skuCount: 0,
    })),
  );

  const machineIdx = Object.fromEntries(MACHINES.map((m, i) => [m, i]));

  for (const sku of Object.keys(seriesIdx)) {
    const route = ri[sku];
    if (!route) continue;
    const mi = machineIdx[route.machine];
    if (mi === undefined) continue;
    const rate = route.rate;

    const dates = Object.keys(seriesIdx[sku]).sort();
    for (let i = 0; i < dates.length; i++) {
      const d = dates[i];
      if (!ctx.isWorking[d]) continue;
      const wi = ctx.workingDates.indexOf(d);
      if (wi < 0) continue;

      const val = seriesIdx[sku][d];
      const prevVal = i > 0 ? seriesIdx[sku][dates[i - 1]] : 0;
      let demandQty = 0;
      if (val < 0) {
        demandQty = Math.max(0, prevVal >= 0 ? -val : -(val - prevVal));
      } else if (prevVal < 0 && val >= 0) {
        demandQty = 0;
      }

      if (demandQty > 0) {
        const minutes = (demandQty / rate) * 60;
        grid[mi][wi].loadMin += minutes;
        grid[mi][wi].skuCount++;
      }
    }
  }

  for (const row of grid) {
    for (const cell of row) {
      cell.pct = (cell.loadMin / DAY_CAP) * 100;
    }
  }

  return grid;
}

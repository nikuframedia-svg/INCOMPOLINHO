/**
 * CapacityHistogram — ECharts bar chart showing machine utilization for selected day.
 */

import { BarChart } from 'echarts/charts';
import { GridComponent, MarkLineComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { useMemo } from 'react';
import type { DayLoad, EMachine } from '../../../../lib/engine';
import { DAY_CAP } from '../../../../lib/engine';
import './CapacityHistogram.css';

echarts.use([BarChart, GridComponent, MarkLineComponent, CanvasRenderer]);

interface CapacityHistogramProps {
  cap: Record<string, DayLoad[]>;
  machines: EMachine[];
  dayIdx: number;
}

function utilColor(pct: number): string {
  if (pct >= 0.95) return 'var(--semantic-red)';
  if (pct >= 0.8) return 'var(--semantic-amber)';
  return 'var(--semantic-green)';
}

export function CapacityHistogram({ cap, machines, dayIdx }: CapacityHistogramProps) {
  const option = useMemo(() => {
    const names: string[] = [];
    const values: number[] = [];
    const colors: string[] = [];

    for (const m of machines) {
      const load = cap[m.id]?.[dayIdx];
      if (!load) continue;
      const used = load.prod + load.setup;
      const pct = DAY_CAP > 0 ? used / DAY_CAP : 0;
      names.push(m.id);
      values.push(Math.round(pct * 100));
      colors.push(utilColor(pct));
    }

    return {
      grid: { top: 8, right: 16, bottom: 24, left: 60 },
      xAxis: {
        type: 'category' as const,
        data: names,
        axisLabel: { fontSize: 12, color: 'var(--text-muted)' },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value' as const,
        max: 120,
        axisLabel: { fontSize: 12, color: 'var(--text-secondary)', formatter: '{value}%' },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
      },
      series: [
        {
          type: 'bar' as const,
          data: values.map((v, i) => ({
            value: v,
            itemStyle: { color: colors[i] },
          })),
          barWidth: '60%',
          markLine: {
            silent: true,
            symbol: 'none',
            data: [{ yAxis: 100, lineStyle: { type: 'dashed' as const, color: 'var(--text-muted)', width: 1 } }],
            label: { show: false },
          },
        },
      ],
      tooltip: {
        trigger: 'axis' as const,
        formatter: (params: Array<{ name: string; value: number }>) => {
          const p = params[0];
          return p ? `${p.name}: ${p.value}%` : '';
        },
      },
    };
  }, [cap, machines, dayIdx]);

  return (
    <div className="cap-hist" data-testid="capacity-histogram">
      <div className="cap-hist__title">Utilização por Máquina</div>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: 100, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        notMerge
      />
    </div>
  );
}

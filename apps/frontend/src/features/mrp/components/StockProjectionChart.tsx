/**
 * StockProjectionChart — ECharts step-line (dente-de-serra) for stock projection.
 * Shows projected stock, safety stock mark line, and optional uncertainty bands.
 */

import { LineChart } from 'echarts/charts';
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { useMemo } from 'react';
import { C } from '@/theme/color-bridge';
import type { StockChartData } from '../utils/stock-detail-compute';
import { computeUncertaintyBands } from '../utils/stock-detail-compute';

echarts.use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

interface StockProjectionChartProps {
  chartData: StockChartData;
  trustScore?: number;
}

export function StockProjectionChart({ chartData, trustScore }: StockProjectionChartProps) {
  const option = useMemo(() => {
    const { dates, projected, safetyStock } = chartData;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const series: any[] = [
      {
        name: 'Stock Projectado',
        type: 'line',
        step: 'end',
        data: projected,
        lineStyle: { color: C.ac, width: 2 },
        itemStyle: { color: C.ac },
        symbol: 'circle',
        symbolSize: 3,
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `${C.ac}25` },
            { offset: 1, color: `${C.ac}05` },
          ]),
        },
        markLine:
          safetyStock != null
            ? {
                silent: true,
                symbol: 'none',
                label: {
                  formatter: 'Safety Stock',
                  fontSize: 12,
                  color: C.yl,
                  position: 'insideEndTop',
                },
                data: [
                  {
                    yAxis: safetyStock,
                    lineStyle: { type: 'dashed', color: C.yl, width: 1.5 },
                  },
                ],
              }
            : undefined,
      },
    ];

    if (trustScore != null && projected.length > 0) {
      const bands = computeUncertaintyBands(projected, trustScore, projected.length);
      series.push(
        {
          name: 'lower',
          type: 'line',
          data: bands.lower,
          lineStyle: { opacity: 0 },
          symbol: 'none',
          stack: 'band',
          areaStyle: { color: 'transparent' },
        },
        {
          name: 'upper',
          type: 'line',
          data: bands.upper.map((u, i) => u - bands.lower[i]),
          lineStyle: { opacity: 0 },
          symbol: 'none',
          stack: 'band',
          areaStyle: { color: `${C.yl}15` },
        },
      );
    }

    return {
      grid: { top: 40, right: 20, bottom: 50, left: 65 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: C.s3,
        borderColor: C.bd,
        textStyle: { fontSize: 12, color: C.t1 },
        formatter: (params: { name: string; value: number; seriesName: string }[]) => {
          const main = params.find((p) => p.seriesName === 'Stock Projectado');
          if (!main) return '';
          const dayIdx = dates.indexOf(main.name);
          const prod = chartData.productions.find((p) => p.dayIdx === dayIdx);
          const ship = chartData.shipments.find((s) => s.dayIdx === dayIdx);
          let html = `<b>${main.name}</b><br/>Stock: <b>${Math.round(main.value)}</b>`;
          if (prod)
            html += `<br/><span style="color:${C.ac}">Produção: +${Math.round(prod.qty)}</span>`;
          if (ship)
            html += `<br/><span style="color:${C.rd}">Expedição: -${Math.round(ship.qty)}</span>`;
          return html;
        },
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { fontSize: 12, color: C.t3, rotate: 45 },
        axisLine: { lineStyle: { color: C.bd } },
      },
      yAxis: {
        type: 'value',
        name: 'Stock (pcs)',
        nameTextStyle: { fontSize: 12, color: C.t3 },
        axisLabel: { fontSize: 12, color: C.t3 },
        splitLine: { lineStyle: { color: `${C.t4}22` } },
      },
      series,
    };
  }, [chartData, trustScore]);

  return (
    <div className="mrp__card" style={{ padding: 12 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: C.t2,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
          marginBottom: 4,
        }}
      >
        Projecção de Stock (Dente de Serra)
      </div>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: 300, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        notMerge
      />
    </div>
  );
}

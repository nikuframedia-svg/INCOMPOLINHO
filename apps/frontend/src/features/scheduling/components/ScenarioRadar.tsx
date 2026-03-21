/**
 * ScenarioRadar — ECharts radar chart comparing baseline vs selected scenario.
 *
 * 5 axes: OTD, Setup Efficiency, Tardiness (inverted), Utilization, Robustness.
 */

import { RadarChart } from 'echarts/charts';
import { RadarComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { useMemo } from 'react';
import type { OptResult } from '../../../lib/engine';
import { C } from '../../../lib/engine';

echarts.use([RadarChart, RadarComponent, TooltipComponent, CanvasRenderer]);

interface ScenarioRadarProps {
  baseline: OptResult | null;
  scenario: OptResult | null;
  fragilityScore?: number;
}

function normalize(value: number, max: number): number {
  return Math.min(100, Math.max(0, (value / max) * 100));
}

function invertNormalize(value: number, max: number): number {
  return Math.min(100, Math.max(0, (1 - value / max) * 100));
}

function metricsToRadar(m: OptResult | null, fragilityScore?: number): number[] {
  if (!m) return [0, 0, 0, 0, 0];
  return [
    m.otdDelivery,
    invertNormalize(m.setupMin, 6000),
    invertNormalize(m.tardinessDays, 100),
    normalize(m.capUtil, 1),
    (fragilityScore ?? 5) * 10,
  ];
}

export function ScenarioRadar({ baseline, scenario, fragilityScore }: ScenarioRadarProps) {
  const option = useMemo(() => {
    const baseData = metricsToRadar(baseline, fragilityScore);
    const scenData = metricsToRadar(scenario, fragilityScore);

    return {
      radar: {
        indicator: [
          { name: 'OTD-D', max: 100 },
          { name: 'Setup Eff.', max: 100 },
          { name: 'Pontualidade', max: 100 },
          { name: 'Utilização', max: 100 },
          { name: 'Robustez', max: 100 },
        ],
        shape: 'polygon' as const,
        splitNumber: 4,
        axisName: { color: C.t3, fontSize: 12 },
        splitLine: { lineStyle: { color: C.bd } },
        splitArea: { show: false },
        axisLine: { lineStyle: { color: C.bd } },
      },
      tooltip: {
        trigger: 'item' as const,
      },
      series: [
        {
          type: 'radar' as const,
          data: [
            {
              value: baseData,
              name: 'Baseline',
              areaStyle: { opacity: 0.15 },
              lineStyle: { color: C.ac, width: 2 },
              itemStyle: { color: C.ac },
            },
            ...(scenario
              ? [
                  {
                    value: scenData,
                    name: 'Cenario',
                    areaStyle: { opacity: 0.1 },
                    lineStyle: { color: C.bl, width: 2 },
                    itemStyle: { color: C.bl },
                  },
                ]
              : []),
          ],
        },
      ],
    };
  }, [baseline, scenario, fragilityScore]);

  if (!baseline) return null;

  return (
    <div data-testid="scenario-radar">
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: 220, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        notMerge
      />
    </div>
  );
}

import { LineChart } from 'echarts/charts';
import { GridComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import ReactEChartsCore from 'echarts-for-react/lib/core';
import { memo, useMemo } from 'react';
import '../../theme/base-components.css';

echarts.use([LineChart, GridComponent, CanvasRenderer]);

export type TrendDirection = 'up' | 'down' | 'flat';

export interface KPICardProps {
  label: string;
  value: string | number;
  unit?: string;
  /** Human-readable interpretation (e.g. "Dentro do objectivo") */
  subtitle?: string;
  /** Extended context line below subtitle (e.g. "de 667 entregas, 649 a tempo") */
  contextLine?: string;
  trend?: { direction: TrendDirection; label: string };
  sparkline?: number[];
  statusColor?: string;
}

export const KPICard = memo(function KPICard({ label, value, unit, subtitle, contextLine, trend, sparkline, statusColor }: KPICardProps) {
  const sparkOption = useMemo(() => {
    if (!sparkline || sparkline.length === 0) return null;
    return {
      grid: { top: 2, right: 0, bottom: 2, left: 0 },
      xAxis: { type: 'category' as const, show: false, data: sparkline.map((_, i) => i) },
      yAxis: { type: 'value' as const, show: false },
      series: [
        {
          type: 'line' as const,
          data: sparkline,
          smooth: true,
          symbol: 'none',
          lineStyle: { width: 1.5, color: statusColor ?? 'var(--accent)' },
          areaStyle: { color: `${statusColor ?? 'var(--accent)'}20` },
        },
      ],
    };
  }, [sparkline, statusColor]);

  const trendArrow =
    trend?.direction === 'up' ? '\u2191' : trend?.direction === 'down' ? '\u2193' : '';

  return (
    <div className="kpi-card" data-testid="kpi-card">
      {statusColor && <div className="kpi-card__status-bar" style={{ background: statusColor }} />}

      <div className="kpi-card__header">
        <span className="kpi-card__label">{label}</span>
        {trend && (
          <span className={`kpi-card__trend kpi-card__trend--${trend.direction}`}>
            {trendArrow} {trend.label}
          </span>
        )}
      </div>

      <span className="kpi-card__value">
        {value}
        {unit && <span style={{ fontSize: 14, fontWeight: 400, marginLeft: 4 }}>{unit}</span>}
      </span>

      {subtitle && (
        <span className="kpi-card__subtitle" style={{ color: statusColor }}>
          {subtitle}
        </span>
      )}

      {contextLine && (
        <span style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.3, display: 'block', marginTop: 2 }}>
          {contextLine}
        </span>
      )}

      {sparkOption && (
        <div className="kpi-card__sparkline">
          <ReactEChartsCore
            echarts={echarts}
            option={sparkOption}
            style={{ height: 60, width: '100%' }}
            opts={{ renderer: 'canvas' }}
            notMerge
          />
        </div>
      )}
    </div>
  );
});

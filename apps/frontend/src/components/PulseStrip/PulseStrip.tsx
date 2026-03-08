/**
 * PulseStrip — Compact horizontal KPI bar.
 *
 * Replaces the 6 KPI cards with a dense, scannable strip.
 * Each pill: label, mono value, 7-point sparkline, semantic color border.
 * Consumes data from useScheduleData().
 */

import { useMemo } from 'react';
import { useScheduleData } from '../../hooks/useScheduleData';
import { C, DAY_CAP, opsByDayFromWorkforce } from '../../lib/engine';
import './PulseStrip.css';

type PillVariant = 'green' | 'amber' | 'red' | 'teal' | 'blue';

interface PulseKPI {
  label: string;
  value: string;
  variant: PillVariant;
  sparkData?: number[];
}

// Mini sparkline SVG — 7 data points, 48x20px
function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (data.length < 2) return null;
  const w = 56,
    h = 22,
    pad = 2;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });
  return (
    <span className="pulse-strip__spark">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
        <polyline
          points={points.join(' ')}
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}

const VARIANT_COLORS: Record<PillVariant, string> = {
  green: '#22C55E',
  amber: C.yl,
  red: C.rd,
  teal: C.ac,
  blue: C.bl,
};

export function PulseStrip() {
  const { engine, cap, metrics, validation } = useScheduleData();

  // Working day indices — filter out weekends
  const wdi = useMemo(() => {
    if (!engine) return [] as number[];
    return engine.workdays
      .map((w: boolean, i: number) => (w ? i : -1))
      .filter((i): i is number => i >= 0);
  }, [engine]);

  const kpis = useMemo((): PulseKPI[] => {
    if (!engine || !metrics) return [];

    const totalViolations = validation?.summary
      ? validation.summary.toolConflicts +
        validation.summary.setupOverlaps +
        validation.summary.machineOvercapacity +
        validation.summary.deadlineMisses
      : 0;

    // Per working-day utilization averages (for sparkline)
    const dailyUtils: number[] = [];
    for (const di of wdi) {
      let dayTotal = 0;
      let machCount = 0;
      for (const m of engine.machines) {
        const mc = cap[m.id] || [];
        if (mc[di]) {
          dayTotal += (mc[di].prod + mc[di].setup) / DAY_CAP;
          machCount++;
        }
      }
      dailyUtils.push(machCount > 0 ? dayTotal / machCount : 0);
    }

    // Per working-day ops count (for sparkline)
    const opsByDay = opsByDayFromWorkforce(metrics.workforceDemand, engine.nDays);
    const dailyOps = wdi.map((i) => opsByDay[i]?.total ?? 0);

    // Per working-day pcs produced (for sparkline)
    const dailyPcs: number[] = [];
    for (const di of wdi) {
      let dayPcs = 0;
      for (const m of engine.machines) {
        const mc = cap[m.id] || [];
        if (mc[di]) dayPcs += mc[di].pcs;
      }
      dailyPcs.push(dayPcs);
    }

    return [
      {
        label: 'OTD',
        value: `${metrics.otdDelivery.toFixed(1)}%`,
        variant: metrics.otdDelivery >= 95 ? 'green' : metrics.otdDelivery >= 85 ? 'amber' : 'red',
      },
      {
        label: 'Producao',
        value:
          metrics.produced > 1000
            ? `${(metrics.produced / 1000).toFixed(1)}K`
            : String(metrics.produced),
        variant: 'teal',
        sparkData: dailyPcs,
      },
      {
        label: 'Utilizacao',
        value: `${(metrics.capUtil * 100).toFixed(0)}%`,
        variant: metrics.capUtil > 0.85 ? 'amber' : 'teal',
        sparkData: dailyUtils.map((u) => u * 100),
      },
      {
        label: 'Violacoes',
        value: String(totalViolations),
        variant: totalViolations > 3 ? 'red' : totalViolations > 0 ? 'amber' : 'green',
      },
      {
        label: 'Perdidas',
        value:
          metrics.lostPcs > 1000
            ? `${(metrics.lostPcs / 1000).toFixed(1)}K`
            : String(metrics.lostPcs),
        variant: metrics.lostPcs > 0 ? 'red' : 'green',
      },
      {
        label: 'Operadores',
        value: `${metrics.peakOps}/${metrics.overOps > 0 ? metrics.overOps + ' over' : 'OK'}`,
        variant: metrics.overOps > 0 ? 'amber' : 'teal',
        sparkData: dailyOps,
      },
      {
        label: 'Setups',
        value: `${metrics.setupCount}`,
        variant: metrics.setupCount > 20 ? 'amber' : 'teal',
      },
      {
        label: 'Atraso',
        value: metrics.tardinessDays > 0 ? `${metrics.tardinessDays.toFixed(1)}d` : '0',
        variant: metrics.tardinessDays > 1 ? 'red' : metrics.tardinessDays > 0 ? 'amber' : 'green',
      },
    ];
  }, [engine, cap, metrics, validation, wdi]);

  if (kpis.length === 0) return null;

  return (
    <div className="pulse-strip" data-testid="pulse-strip">
      {kpis.map((kpi) => (
        <div key={kpi.label} className={`pulse-strip__pill pulse-strip__pill--${kpi.variant}`}>
          <div className="pulse-strip__pill-body">
            <span className="pulse-strip__pill-label">{kpi.label}</span>
            <span className="pulse-strip__pill-value">{kpi.value}</span>
          </div>
          {kpi.sparkData && <Sparkline data={kpi.sparkData} color={VARIANT_COLORS[kpi.variant]} />}
        </div>
      ))}
    </div>
  );
}

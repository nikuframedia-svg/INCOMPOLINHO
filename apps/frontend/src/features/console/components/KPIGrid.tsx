/**
 * KPIGrid — 6 premium KPI cards with sparklines for the selected day.
 * Uses KPICard from Industrial/ for ECharts sparklines + trend + status bar.
 */

import { KPICard } from '@/components/Industrial/KPICard';
import {
  formatOTD,
  formatUtilization,
  formatSetupTime,
  formatAlerts,
} from '@/utils/explicitText';
import './KPIGrid.css';

export interface KPISparklines {
  pcs: number[];
  ops: number[];
  util: number[];
  setup: number[];
  alerts: number[];
  operators: number[];
}

interface KPIGridProps {
  totalPcs: number;
  totalOps: number;
  factoryUtil: number;
  totalSetupMin: number;
  violationCount: number;
  infeasibleCount: number;
  overflowCount: number;
  operatorsByArea: { pg1: number; pg2: number; total: number };
  operatorCapacity: { pg1: number; pg2: number };
  sparklines?: KPISparklines;
  otd?: number;
  otdSparkline?: number[];
  activeMachines?: number;
  totalMachines?: number;
  setupCount?: number;
  lateDeliveriesCount?: number;
}

const semanticColor = (s: 'good' | 'warning' | 'critical' | 'neutral'): string =>
  s === 'good' ? 'var(--semantic-green)'
    : s === 'warning' ? 'var(--semantic-amber)'
    : s === 'critical' ? 'var(--semantic-red)'
    : 'var(--accent)';

export function KPIGrid(props: KPIGridProps) {
  const {
    totalPcs,
    totalOps,
    factoryUtil,
    totalSetupMin,
    violationCount,
    infeasibleCount,
    overflowCount,
    sparklines,
    otd,
    otdSparkline,
    activeMachines = 5,
    totalMachines = 5,
    setupCount = 0,
    lateDeliveriesCount = 0,
  } = props;

  const otdE = otd != null ? formatOTD(otd) : null;
  const utilE = formatUtilization(factoryUtil, activeMachines, totalMachines);
  const setupE = formatSetupTime(totalSetupMin, setupCount);
  const alertE = formatAlerts(violationCount, infeasibleCount, overflowCount);

  return (
    <div className="kpi-grid" data-testid="kpi-grid">
      <KPICard
        label="OTD-D"
        value={otdE?.formatted ?? '—'}
        subtitle={otdE?.qualifier}
        contextLine={
          lateDeliveriesCount > 0
            ? `${lateDeliveriesCount} atraso${lateDeliveriesCount > 1 ? 's' : ''} pendente${lateDeliveriesCount > 1 ? 's' : ''}`
            : otdE?.context
        }
        sparkline={otdSparkline}
        statusColor={
          lateDeliveriesCount > 0
            ? semanticColor('critical')
            : otdE ? semanticColor(otdE.semantic) : undefined
        }
      />
      <KPICard
        label="Produção"
        value={totalPcs.toLocaleString()}
        unit="pcs"
        subtitle={`${totalOps} operações`}
        sparkline={sparklines?.pcs}
        statusColor="var(--accent)"
      />
      <KPICard
        label="Operações"
        value={totalOps}
        sparkline={sparklines?.ops}
        statusColor="var(--accent)"
      />
      <KPICard
        label="Utilização"
        value={utilE.formatted}
        subtitle={utilE.qualifier}
        contextLine={utilE.context}
        sparkline={sparklines?.util}
        statusColor={semanticColor(utilE.semantic)}
      />
      <KPICard
        label="Setup"
        value={setupE.formatted}
        subtitle={setupE.qualifier}
        contextLine={setupE.context}
        sparkline={sparklines?.setup}
        statusColor={semanticColor(setupE.semantic)}
      />
      <KPICard
        label="Alertas"
        value={alertE.formatted}
        subtitle={alertE.qualifier}
        contextLine={alertE.context}
        trend={
          overflowCount > 0
            ? { direction: 'up' as const, label: `${overflowCount} overflow` }
            : undefined
        }
        sparkline={sparklines?.alerts}
        statusColor={semanticColor(alertE.semantic)}
      />
    </div>
  );
}

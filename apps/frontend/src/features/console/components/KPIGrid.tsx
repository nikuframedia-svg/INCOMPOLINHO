/**
 * KPIGrid — 6 compact metric cards for the selected day.
 */

import './KPIGrid.css';

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
}

type Variant = 'teal' | 'green' | 'amber' | 'red';

interface KPICard {
  label: string;
  value: string;
  sub?: string;
  variant: Variant;
}

export function KPIGrid(props: KPIGridProps) {
  const {
    totalPcs,
    totalOps,
    factoryUtil,
    totalSetupMin,
    violationCount,
    infeasibleCount,
    overflowCount,
    operatorsByArea,
    operatorCapacity,
  } = props;

  const alertCount = violationCount + infeasibleCount;

  const utilPct = (factoryUtil * 100).toFixed(0);
  const utilVariant: Variant = factoryUtil < 0.6 ? 'green' : factoryUtil < 0.85 ? 'teal' : 'amber';

  const alertVariant: Variant = alertCount === 0 ? 'green' : alertCount <= 3 ? 'amber' : 'red';

  const totalCap = operatorCapacity.pg1 + operatorCapacity.pg2;
  const opVariant: Variant = operatorsByArea.total <= totalCap ? 'teal' : 'red';

  const setupH = Math.floor(totalSetupMin / 60);
  const setupM = totalSetupMin % 60;

  const cards: KPICard[] = [
    {
      label: 'Producao',
      value: `${totalProdMinToHours(props.totalPcs)}`,
      sub: `${totalPcs.toLocaleString()} pcs`,
      variant: totalPcs > 0 ? 'teal' : 'teal',
    },
    {
      label: 'Operacoes',
      value: `${totalOps}`,
      variant: 'teal',
    },
    {
      label: 'Utilizacao',
      value: `${utilPct}%`,
      variant: utilVariant,
    },
    {
      label: 'Setup',
      value: `${setupH}h${setupM > 0 ? `${setupM}m` : ''}`,
      variant: 'teal',
    },
    {
      label: 'Alertas',
      value: `${alertCount}`,
      sub: overflowCount > 0 ? `${overflowCount} overflow` : undefined,
      variant: alertVariant,
    },
    {
      label: 'Operadores',
      value: `${operatorsByArea.total}`,
      sub: `G:${operatorsByArea.pg1} M:${operatorsByArea.pg2} / cap ${totalCap}`,
      variant: opVariant,
    },
  ];

  return (
    <div className="kpi-grid" data-testid="kpi-grid">
      {cards.map((k) => (
        <div key={k.label} className={`kpi-grid__card kpi-grid__card--${k.variant}`}>
          <span className="kpi-grid__label">{k.label}</span>
          <span className="kpi-grid__value">{k.value}</span>
          {k.sub && <span className="kpi-grid__sub">{k.sub}</span>}
        </div>
      ))}
    </div>
  );
}

/** Helper — just format pcs, not minutes. The "Producao" card shows pcs. */
function totalProdMinToHours(pcs: number): string {
  return pcs.toLocaleString();
}

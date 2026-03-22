/**
 * StockKPIPanel — KPI cards for stock dashboard.
 */

import { C } from '@/theme/color-bridge';
import { KCard } from '../components/KCard';
import { fmtQty } from '../utils/mrp-helpers';
import type { StockKPIs } from '../utils/stock-compute';

interface StockKPIPanelProps {
  kpis: StockKPIs;
  totalSkus: number;
}

export function StockKPIPanel({ kpis, totalSkus }: StockKPIPanelProps) {
  return (
    <div className="mrp__kpis" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
      <KCard
        label="Stockout"
        value={String(kpis.stockoutCount)}
        sub={
          kpis.stockoutCount === 0
            ? 'Sem rupturas previstas'
            : `${kpis.stockoutCount} de ${totalSkus} SKUs em ruptura`
        }
        color={kpis.stockoutCount > 0 ? C.rd : C.ac}
      />
      <KCard
        label="Em Risco"
        value={String(kpis.riskCount)}
        sub={
          kpis.riskCount === 0
            ? 'Cobertura adequada em todos os SKUs'
            : `${kpis.riskCount} SKUs com menos de 15 dias de stock`
        }
        color={kpis.riskCount > 0 ? C.yl : C.ac}
      />
      <KCard
        label="Stock Total"
        value={fmtQty(kpis.totalStock)}
        sub={`${totalSkus} SKUs em armazem`}
        color={C.t1}
      />
      <KCard
        label="Cobertura Media"
        value={`${Math.round(kpis.avgCoverage)}d`}
        sub={
          kpis.avgCoverage >= 30
            ? 'Nivel confortavel'
            : kpis.avgCoverage >= 15
              ? 'Nivel aceitavel'
              : 'Abaixo do minimo — rever plano'
        }
        color={kpis.avgCoverage < 15 ? C.yl : C.ac}
      />
    </div>
  );
}

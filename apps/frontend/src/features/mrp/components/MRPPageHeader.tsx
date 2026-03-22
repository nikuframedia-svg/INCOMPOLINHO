import type {
  EngineData,
  LateDeliveryAnalysis,
  MRPResult,
  MRPSkuViewResult,
  OptResult,
} from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { mono } from '../utils/mrp-helpers';

interface MRPPageHeaderProps {
  metrics: OptResult | null;
  lateDeliveries: LateDeliveryAnalysis | null;
  engine: EngineData;
  skuView: MRPSkuViewResult;
  mrp: MRPResult;
}

export function MRPPageHeader({
  metrics,
  lateDeliveries,
  engine,
  skuView,
  mrp,
}: MRPPageHeaderProps) {
  return (
    <div className="mrp__header">
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
          MRP — Necessidades de Produção
        </h1>
        <p className="page-desc">
          Cálculo de necessidades: quando e quanto produzir, e onde falta capacidade.
        </p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {metrics?.otdDelivery != null && (
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color:
                metrics.otdDelivery >= 0.95
                  ? 'var(--semantic-green)'
                  : metrics.otdDelivery >= 0.8
                    ? 'var(--semantic-amber)'
                    : 'var(--semantic-red)',
              padding: '2px 8px',
              borderRadius: 4,
              background:
                metrics.otdDelivery >= 0.95
                  ? 'rgba(34,197,94,0.1)'
                  : metrics.otdDelivery >= 0.8
                    ? 'rgba(245,158,11,0.1)'
                    : 'rgba(239,68,68,0.1)',
            }}
          >
            OTD-D {(metrics.otdDelivery * 100).toFixed(0)}%
            {(lateDeliveries?.unresolvedCount ?? 0) > 0 && (
              <span style={{ fontWeight: 500 }}>
                {' '}
                · {lateDeliveries?.unresolvedCount} atraso
                {lateDeliveries?.unresolvedCount > 1 ? 's' : ''}
              </span>
            )}
          </span>
        )}
        <span style={{ fontSize: 12, color: C.t3, ...mono }}>
          {engine.dates[0]} — {engine.dates[engine.dates.length - 1]} · {skuView.summary.totalSkus}{' '}
          SKUs · {mrp.records.length} tools
        </span>
      </div>
    </div>
  );
}

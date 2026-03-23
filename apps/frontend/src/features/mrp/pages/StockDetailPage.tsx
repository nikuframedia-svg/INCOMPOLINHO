/**
 * StockDetailPage — SKU stock projection based on REAL scheduler blocks.
 * Route: /mrp/stock/:sku (or /mrp/stock without SKU for summary view)
 */

import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useDataStore } from '@/stores/useDataStore';
import { C } from '@/theme/color-bridge';
import { InlineCTPForm } from '../components/InlineCTPForm';
import { StockDayTable } from '../components/StockDayTable';
import { StockEventTable } from '../components/StockEventTable';
import { StockProjectionChart } from '../components/StockProjectionChart';
import { StockSkuSidebar } from '../components/StockSkuSidebar';
import { fmtQty, mono } from '../utils/mrp-helpers';
import {
  computeProjectionConfidence,
  computeRealStockProjection,
  computeSkuSummaries,
  computeStockChartDataReal,
  computeStockEventsReal,
} from '../utils/stock-detail-compute';

function InfoField({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span
        style={{ fontSize: 12, color: C.t3, textTransform: 'uppercase', letterSpacing: '.03em' }}
      >
        {label}
      </span>
      <span style={{ fontSize: 12, fontWeight: 600, color: color ?? C.t1, ...mono }}>{value}</span>
    </div>
  );
}

export function StockDetailPage() {
  const { sku } = useParams<{ sku: string }>();
  const navigate = useNavigate();
  const { engine, blocks, loading, error } = useScheduleData();
  const trustScore = useDataStore((s) => s.meta?.trustScore);

  const summaries = useMemo(() => {
    if (!engine || !blocks) return [];
    return computeSkuSummaries(blocks, engine);
  }, [engine, blocks]);

  const skuInfo = useMemo(() => {
    if (!sku) return null;
    return summaries.find((s) => s.sku === sku) ?? null;
  }, [summaries, sku]);

  const projection = useMemo(() => {
    if (!sku || !engine || !blocks) return [];
    return computeRealStockProjection(sku, blocks, engine);
  }, [sku, engine, blocks]);

  const chartData = useMemo(() => {
    if (projection.length === 0) return null;
    return computeStockChartDataReal(projection);
  }, [projection]);

  const events = useMemo(() => computeStockEventsReal(projection), [projection]);

  const confidence = useMemo(() => {
    if (trustScore == null || !skuInfo) return null;
    return computeProjectionConfidence(trustScore, skuInfo.coverageDays);
  }, [trustScore, skuInfo]);

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <SkeletonTable rows={6} cols={4} />
      </div>
    );
  }

  if (error || !engine) {
    return (
      <div style={{ padding: 24 }}>
        <EmptyState
          icon="error"
          title="Sem dados de scheduling"
          description="Carregue um ISOP para ver a projecção de stock."
        />
      </div>
    );
  }

  const confColor =
    confidence != null ? (confidence >= 80 ? C.ac : confidence >= 60 ? C.yl : C.rd) : C.t3;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 56px)' }}>
      <StockSkuSidebar
        summaries={summaries}
        selectedSku={sku}
        onSelect={(s) => navigate(`/mrp/stock/${s}`)}
      />

      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
        {!sku || !skuInfo ? (
          <EmptyState
            icon="search"
            title="Seleccione um SKU"
            description="Escolha um SKU na lista para ver a projecção de stock dia a dia."
          />
        ) : (
          <>
            {/* Header */}
            <div className="mrp__card" style={{ padding: 16, marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
                <span style={{ fontSize: 16, fontWeight: 700, color: C.t1, ...mono }}>
                  {skuInfo.sku}
                </span>
                <span style={{ fontSize: 12, color: C.t2 }}>{skuInfo.name}</span>
              </div>
              <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                <InfoField label="Máquina" value={skuInfo.machine} />
                <InfoField label="Ferramenta" value={skuInfo.tool} />
                {skuInfo.altMachine && <InfoField label="Alternativa" value={skuInfo.altMachine} />}
                <InfoField label="Cadência" value={`${skuInfo.pH} pcs/h`} />
                <InfoField label="Lote Eco" value={fmtQty(skuInfo.ecoLot)} />
                <InfoField label="Demanda" value={fmtQty(skuInfo.totalDemand)} />
                <InfoField label="Produzido" value={fmtQty(skuInfo.totalProduced)} />
                <InfoField
                  label="Surplus"
                  value={fmtQty(skuInfo.surplus)}
                  color={skuInfo.surplus < 0 ? C.rd : skuInfo.surplus > 0 ? C.ac : C.t2}
                />
                {skuInfo.clients.length > 0 && (
                  <InfoField label="Clientes" value={skuInfo.clients.join(', ')} />
                )}
              </div>
            </div>

            {/* Chart */}
            {chartData && (
              <StockProjectionChart chartData={chartData} trustScore={trustScore ?? undefined} />
            )}

            {/* Confidence */}
            {confidence != null && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '6px 12px',
                  fontSize: 12,
                  color: C.t2,
                  marginTop: 4,
                  marginBottom: 12,
                }}
              >
                <span
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: '50%',
                    background: confColor,
                    flexShrink: 0,
                  }}
                />
                Confiança:{' '}
                <span style={{ fontWeight: 700, color: confColor, ...mono }}>{confidence}%</span>
              </div>
            )}

            {/* CTP */}
            <div style={{ marginBottom: 12 }}>
              <InlineCTPForm sku={sku} nDays={engine.nDays} />
            </div>

            {/* Day table */}
            <div style={{ marginBottom: 12 }}>
              <StockDayTable rows={projection} ecoLot={skuInfo.ecoLot} />
            </div>

            {/* Events */}
            <StockEventTable events={events} />
          </>
        )}
      </div>
    </div>
  );
}

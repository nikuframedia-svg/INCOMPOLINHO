/**
 * StockDetailPage — Detail view for a single SKU's stock projection.
 * Route: /mrp/stock/:sku
 */

import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import { useScheduleData } from '@/hooks/useScheduleData';
import { C } from '@/lib/engine';
import { useDataStore } from '@/stores/useDataStore';
import { StockEventTable } from '../components/StockEventTable';
import { StockProjectionChart } from '../components/StockProjectionChart';
import { fmtQty, mono } from '../utils/mrp-helpers';
import {
  computeProjectionConfidence,
  computeStockChartData,
  computeStockEvents,
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
  const { engine, blocks, loading, error, mrpSkuView: skuView, mrpRopSku: ropSummary } = useScheduleData();
  const trustScore = useDataStore((s) => s.meta?.trustScore);

  const skuRec = useMemo(() => {
    if (!skuView || !sku) return null;
    return skuView.skuRecords.find((r) => r.sku === sku) ?? null;
  }, [skuView, sku]);

  const safetyStock = useMemo(() => {
    if (!ropSummary || !sku) return undefined;
    const rec = ropSummary.records.find((r) => r.sku === sku);
    return rec?.safetyStock;
  }, [ropSummary, sku]);

  const chartData = useMemo(() => {
    if (!skuRec) return null;
    return computeStockChartData(skuRec, blocks, safetyStock);
  }, [skuRec, blocks, safetyStock]);

  const events = useMemo(() => {
    if (!skuRec) return [];
    return computeStockEvents(skuRec, blocks);
  }, [skuRec, blocks]);

  const confidence = useMemo(() => {
    if (trustScore == null || !skuRec) return null;
    return computeProjectionConfidence(trustScore, skuRec.coverageDays);
  }, [trustScore, skuRec]);

  if (loading) {
    return (
      <div style={{ padding: 24 }}>
        <SkeletonTable rows={6} cols={4} />
      </div>
    );
  }

  if (error || !engine || !skuRec || !chartData) {
    return (
      <div style={{ padding: 24 }}>
        <Link to="/mrp" style={{ fontSize: 12, color: C.ac, textDecoration: 'none' }}>
          ← MRP
        </Link>
        <EmptyState
          icon="error"
          title={`SKU não encontrado: ${sku ?? '?'}`}
          description="Este SKU não existe nos dados MRP carregados."
        />
      </div>
    );
  }

  const confColor =
    confidence != null ? (confidence >= 80 ? C.ac : confidence >= 60 ? C.yl : C.rd) : C.t3;

  return (
    <div style={{ padding: '16px 24px', maxWidth: 1100 }}>
      <Link
        to="/mrp"
        style={{
          fontSize: 12,
          color: C.ac,
          textDecoration: 'none',
          marginBottom: 12,
          display: 'inline-block',
        }}
      >
        ← MRP
      </Link>

      {/* SKU Header */}
      <div className="mrp__card" style={{ padding: 16, marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: C.t1, ...mono }}>{skuRec.sku}</span>
          <span style={{ fontSize: 12, color: C.t2 }}>{skuRec.name}</span>
          {skuRec.twin && (
            <span style={{ fontSize: 12, color: C.yl, fontWeight: 600 }}>Gémea: {skuRec.twin}</span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          <InfoField label="Máquina" value={skuRec.machine} />
          <InfoField label="Ferramenta" value={skuRec.toolCode} />
          <InfoField label="Cadência" value={`${skuRec.ratePerHour} pcs/h`} />
          <InfoField label="Stock Actual" value={fmtQty(skuRec.currentStock)} />
          <InfoField
            label="Cobertura"
            value={`${skuRec.coverageDays}d`}
            color={skuRec.coverageDays < 15 ? C.rd : skuRec.coverageDays <= 30 ? C.yl : C.ac}
          />
          {skuRec.customer && <InfoField label="Cliente" value={skuRec.customer} />}
          {skuRec.altMachine && <InfoField label="Alternativa" value={skuRec.altMachine} />}
        </div>
      </div>

      {/* Chart */}
      <StockProjectionChart chartData={chartData} trustScore={trustScore ?? undefined} />

      {/* Confidence badge */}
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
          Confiança desta projecção:{' '}
          <span style={{ fontWeight: 700, color: confColor, ...mono }}>{confidence}%</span>
          <span style={{ fontSize: 12, color: C.t3 }}>(baseado em TrustIndex + horizonte)</span>
        </div>
      )}

      {/* Events Table */}
      <StockEventTable events={events} />
    </div>
  );
}

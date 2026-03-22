/**
 * OrdersPage — Orders by client with pegging tree.
 * Route: /mrp/orders
 */

import { ChevronDown, ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import type { Block, EngineData } from '@/domain/types/scheduling';
import { useScheduleData } from '@/hooks/useScheduleData';
import { C } from '@/theme/color-bridge';
import { KCard } from '../components/KCard';
import { OrderTableRow } from '../components/OrderTableRow';
import { mono } from '../utils/mrp-helpers';
import type { ClientOrderGroup } from '../utils/orders-compute';
import { computeOrderEntries, groupOrdersByClient } from '../utils/orders-compute';

function ClientAccordion({
  group,
  engine,
  blocks,
}: {
  group: ClientOrderGroup;
  engine: EngineData;
  blocks: Block[];
}) {
  const [open, setOpen] = useState(false);
  const [selectedOp, setSelectedOp] = useState<string | null>(null);
  const otdColor = group.otdPercent >= 90 ? C.ac : group.otdPercent >= 70 ? C.yl : C.rd;

  return (
    <div style={{ marginBottom: 4 }}>
      <div
        className="mrp__enc-client-row"
        onClick={() => setOpen(!open)}
        style={{ cursor: 'pointer' }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {open ? <ChevronDown size={12} color={C.t3} /> : <ChevronRight size={12} color={C.t3} />}
          <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{group.customerName}</span>
          <span style={{ fontSize: 12, color: C.t3, ...mono }}>{group.customerCode}</span>
        </span>
        <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: C.t2 }}>{group.totalOrders} encomendas</span>
          <span style={{ ...mono, fontSize: 12, fontWeight: 700, color: otdColor }}>
            {group.otdPercent}%
          </span>
          {group.lateCount > 0 && (
            <span style={{ fontSize: 12, color: C.rd, fontWeight: 600 }}>
              {group.lateCount} late
            </span>
          )}
          {group.atRiskCount > 0 && (
            <span style={{ fontSize: 12, color: C.yl }}>{group.atRiskCount} at-risk</span>
          )}
        </span>
      </div>
      {open && (
        <table className="mrp__table" style={{ marginTop: 4, marginBottom: 8 }}>
          <thead>
            <tr>
              <th>SKU</th>
              <th style={{ textAlign: 'right' }}>Qtd</th>
              <th>Data Pedida</th>
              <th>Data Prevista</th>
              <th>Estado</th>
              <th style={{ textAlign: 'right' }}>Gap</th>
            </tr>
          </thead>
          <tbody>
            {group.entries.map((e) => (
              <OrderTableRow
                key={e.opId}
                entry={e}
                isSelected={selectedOp === e.opId}
                onSelect={() => setSelectedOp(selectedOp === e.opId ? null : e.opId)}
                engine={engine}
                blocks={blocks}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function OrdersPage() {
  const { engine, blocks, loading, error, mrp, mrpSkuView: skuView } = useScheduleData();
  const [search, setSearch] = useState('');
  const allEntries = useMemo(() => {
    if (!engine || !mrp || !skuView) return [];
    return computeOrderEntries(engine, mrp, skuView, blocks);
  }, [engine, mrp, skuView, blocks]);
  const filtered = useMemo(() => {
    if (!search) return allEntries;
    const q = search.toLowerCase();
    return allEntries.filter(
      (e) =>
        e.sku.toLowerCase().includes(q) ||
        e.skuName.toLowerCase().includes(q) ||
        e.customerName?.toLowerCase().includes(q),
    );
  }, [allEntries, search]);
  const clientGroups = useMemo(() => groupOrdersByClient(filtered), [filtered]);

  if (loading)
    return (
      <div style={{ padding: 24 }}>
        <SkeletonTable rows={8} cols={6} />
      </div>
    );
  if (error || !engine || !mrp || !skuView) {
    return (
      <div style={{ padding: 24 }}>
        <Link to="/mrp" style={{ fontSize: 12, color: C.ac, textDecoration: 'none' }}>
          ← MRP
        </Link>
        <EmptyState icon="error" title="Sem dados" description={error || 'Importe ISOP.'} />
      </div>
    );
  }

  const onTimeDone = allEntries.filter((e) => e.status === 'on-time' || e.status === 'done').length;
  const totalOTD = allEntries.length > 0 ? Math.round((onTimeDone / allEntries.length) * 100) : 100;
  const lateCount = allEntries.filter((e) => e.status === 'late').length;
  const atRiskCount = allEntries.filter((e) => e.status === 'at-risk').length;

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
      <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: '0 0 4px' }}>
        Encomendas por Cliente
      </h1>

      <div className="mrp__kpis" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <KCard label="Total" value={String(allEntries.length)} sub="encomendas" color={C.t1} />
        <KCard
          label="OTD-D"
          value={`${totalOTD}%`}
          sub="on-time delivery"
          color={totalOTD >= 90 ? C.ac : totalOTD >= 70 ? C.yl : C.rd}
        />
        <KCard
          label="Late"
          value={String(lateCount)}
          sub="atrasadas"
          color={lateCount > 0 ? C.rd : C.ac}
        />
        <KCard
          label="At-Risk"
          value={String(atRiskCount)}
          sub="em risco"
          color={atRiskCount > 0 ? C.yl : C.ac}
        />
      </div>

      <div className="mrp__filters">
        <input
          className="mrp__filter-input"
          type="text"
          placeholder="Procurar SKU/produto/cliente..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {filtered.length} de {allEntries.length} encomendas · {clientGroups.length} clientes
        </span>
      </div>

      <div className="mrp__card">
        {clientGroups.map((group) => (
          <ClientAccordion key={group.customerCode} group={group} engine={engine} blocks={blocks} />
        ))}
        {clientGroups.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
            Nenhuma encomenda encontrada
          </div>
        )}
      </div>
    </div>
  );
}

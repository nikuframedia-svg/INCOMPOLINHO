import { useEffect, useMemo, useState } from 'react';
import { EmptyState } from '@/components/Common/EmptyState';
import { FeatureErrorBoundary } from '@/components/Common/FeatureErrorBoundary';
import { SkeletonTable } from '@/components/Common/SkeletonLoader';
import type { MRPRecord, MRPSkuViewRecord } from '@/domain/mrp/mrp-types';
import { useScheduleData } from '@/hooks/useScheduleData';
import { useUIActions, useUIStore } from '@/stores/useUIStore';
import { MRPPageHeader } from '../components/MRPPageHeader';
import { MRPStatusSection } from '../components/MRPStatusSection';
import { MRPTrustBanner } from '../components/MRPTrustBanner';
import { CTPTab } from '../tabs/CTPTab';
import { EncomendasTab } from '../tabs/EncomendasTab';
import { MachineTableTab, SKUTableTab, ToolTableTab } from '../tabs/MRPTableTab';
import { StocksTab } from '../tabs/StocksTab';
import './MRPPage.css';
import { C } from '@/theme/color-bridge';

type Tab = 'stocks' | 'table' | 'encomendas' | 'ctp';
type Filter = 'all' | 'stockout' | 'backlog';
type ViewMode = 'sku' | 'tool' | 'machine';

const TAB_LABELS: Record<Tab, string> = {
  stocks: 'Stocks',
  table: 'Tabela MRP',
  encomendas: 'Encomendas',
  ctp: 'CTP',
};
const TAB_TOOLTIPS: Partial<Record<Tab, string>> = {
  stocks: 'Dashboard de stocks: cobertura, projecções e alertas',
  encomendas: 'Encomendas em risco, sugestões e calendário de produção',
  ctp: 'Capable-to-Promise: verificar viabilidade de encomenda',
};
const ALL_TABS: Tab[] = ['stocks', 'table', 'encomendas', 'ctp'];
const VIEW_LABELS: Record<ViewMode, string> = {
  sku: 'SKU',
  tool: 'Ferramenta',
  machine: 'Máquina',
};

export function MRPPage() {
  const {
    engine,
    blocks,
    loading,
    error,
    metrics,
    lateDeliveries,
    mrp,
    mrpSkuView: skuView,
  } = useScheduleData();
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  const [tab, setTab] = useState<Tab>('stocks');
  const [viewMode, setViewMode] = useState<ViewMode>('sku');
  const [filter, setFilter] = useState<Filter>('all');
  const [machineFilter, setMachineFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { setMrpRiskCount } = useUIActions();
  useEffect(() => {
    if (skuView) {
      setMrpRiskCount(skuView.summary.skusWithStockout);
    }
  }, [skuView, setMrpRiskCount]);

  const filteredRecords = useMemo(() => {
    if (!mrp) return [];
    let recs: MRPRecord[] = mrp.records;
    if (filter === 'stockout') recs = recs.filter((r) => r.stockoutDay !== null);
    if (filter === 'backlog') recs = recs.filter((r) => r.backlog > 0);
    if (machineFilter !== 'all') recs = recs.filter((r) => r.machine === machineFilter);
    if (search) {
      const q = search.toLowerCase();
      recs = recs.filter(
        (r) =>
          r.toolCode.toLowerCase().includes(q) ||
          r.skus.some((s) => s.sku.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)),
      );
    }
    return recs;
  }, [mrp, filter, machineFilter, search]);

  const filteredSkuRecords = useMemo(() => {
    if (!skuView) return [];
    let recs: MRPSkuViewRecord[] = skuView.skuRecords;
    if (filter === 'stockout') recs = recs.filter((r) => r.stockoutDay !== null);
    if (filter === 'backlog') recs = recs.filter((r) => r.backlog > 0);
    if (machineFilter !== 'all') recs = recs.filter((r) => r.machine === machineFilter);
    if (search) {
      const q = search.toLowerCase();
      recs = recs.filter(
        (r) =>
          r.sku.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q) ||
          r.toolCode.toLowerCase().includes(q),
      );
    }
    return recs;
  }, [skuView, filter, machineFilter, search]);

  if (loading)
    return (
      <div className="mrp" data-testid="mrp-page">
        <div className="mrp__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            MRP — Necessidades de Produção
          </h1>
          <p className="page-desc">
            Cálculo de necessidades: quando e quanto produzir, e onde falta capacidade.
          </p>
        </div>
        <SkeletonTable rows={8} cols={10} />
      </div>
    );
  if (error || !engine || !mrp || !skuView)
    return (
      <div className="mrp" data-testid="mrp-page">
        <div className="mrp__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            MRP — Necessidades de Produção
          </h1>
          <p className="page-desc">
            Cálculo de necessidades: quando e quanto produzir, e onde falta capacidade.
          </p>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados MRP"
          description={
            error ||
            'Importe um ficheiro ISOP na página Planning para calcular as necessidades de produção.'
          }
        />
      </div>
    );

  const machines = engine.machines;

  function toggleExpand(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <FeatureErrorBoundary module="MRP">
      <div className={`mrp${panelOpen ? ' mrp--panel-open' : ''}`} data-testid="mrp-page">
        <MRPPageHeader
          metrics={metrics}
          lateDeliveries={lateDeliveries}
          engine={engine}
          skuView={skuView}
          mrp={mrp}
        />

        <MRPTrustBanner />

        <MRPStatusSection mrp={mrp} skuView={skuView} />

        {/* View Mode Selector (only for table tab) + Tabs */}
        <div className="mrp__view-bar">
          {tab === 'table' && (
            <div className="mrp__view-selector">
              {(['sku', 'tool', 'machine'] as ViewMode[]).map((vm) => (
                <button
                  key={vm}
                  className={`mrp__view-btn ${viewMode === vm ? 'mrp__view-btn--active' : ''}`}
                  onClick={() => setViewMode(vm)}
                >
                  {VIEW_LABELS[vm]}
                </button>
              ))}
            </div>
          )}
          <div className="mrp__tabs">
            {ALL_TABS.map((t) => (
              <button
                key={t}
                className={`mrp__tab ${tab === t ? 'mrp__tab--active' : ''}`}
                onClick={() => setTab(t)}
                title={TAB_TOOLTIPS[t]}
              >
                {TAB_LABELS[t]}
              </button>
            ))}
          </div>
        </div>

        {/* Stocks Tab */}
        {tab === 'stocks' && (
          <StocksTab engine={engine} mrp={mrp} skuView={skuView} blocks={blocks} />
        )}

        {/* Table Tab */}
        {tab === 'table' && viewMode === 'sku' && (
          <SKUTableTab
            records={filteredSkuRecords}
            allRecords={skuView.skuRecords}
            dates={engine.dates}
            dnames={engine.dnames}
            machines={machines}
            filter={filter}
            setFilter={setFilter}
            machineFilter={machineFilter}
            setMachineFilter={setMachineFilter}
            search={search}
            setSearch={setSearch}
            expanded={expanded}
            toggleExpand={toggleExpand}
          />
        )}
        {tab === 'table' && viewMode === 'tool' && (
          <ToolTableTab
            records={filteredRecords}
            allRecords={mrp.records}
            dates={engine.dates}
            dnames={engine.dnames}
            machines={machines}
            filter={filter}
            setFilter={setFilter}
            machineFilter={machineFilter}
            setMachineFilter={setMachineFilter}
            search={search}
            setSearch={setSearch}
            expanded={expanded}
            toggleExpand={toggleExpand}
          />
        )}
        {tab === 'table' && viewMode === 'machine' && (
          <MachineTableTab
            records={filteredRecords}
            allRecords={mrp.records}
            dates={engine.dates}
            dnames={engine.dnames}
            machines={machines}
            filter={filter}
            setFilter={setFilter}
            machineFilter={machineFilter}
            setMachineFilter={setMachineFilter}
            search={search}
            setSearch={setSearch}
            expanded={expanded}
            toggleExpand={toggleExpand}
          />
        )}

        {/* Encomendas Tab */}
        {tab === 'encomendas' && (
          <EncomendasTab engine={engine} mrp={mrp} skuView={skuView} blocks={blocks} />
        )}

        {/* CTP Tab */}
        {tab === 'ctp' && <CTPTab mrp={mrp} engine={engine} skuView={skuView} />}
      </div>
    </FeatureErrorBoundary>
  );
}

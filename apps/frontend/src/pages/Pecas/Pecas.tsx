import { useEffect, useMemo, useState } from 'react';
import { EmptyState } from '../../components/Common/EmptyState';
import { SkeletonTable } from '../../components/Common/SkeletonLoader';
import { StatusBanner } from '../../components/Common/StatusBanner';
import { useScheduleData } from '../../hooks/useScheduleData';
import { useUIStore } from '../../stores/useUIStore';
import { PecasSkuTable } from './PecasSkuTable';
import { PecasSummaryCards } from './PecasSummaryCards';
import type { PecaRow, SortDir, SortField } from './pecas-types';
import './Pecas.css';
import { C } from '@/theme/color-bridge';

export function Pecas() {
  const { engine, blocks, loading, error } = useScheduleData();
  const focus = useUIStore((s) => s.focus);
  const panelOpen = useUIStore((s) => s.contextPanelOpen);

  const [sortField, setSortField] = useState<SortField>('coverage');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [filterM, setFilterM] = useState<string>('all');
  const [onlyBacklog, setOnlyBacklog] = useState(false);
  const [userOverrodeFilter, setUserOverrodeFilter] = useState(false);

  // Focus-reactive: auto-set machine filter from FocusStrip
  useEffect(() => {
    if (focus.machine && !userOverrodeFilter) {
      setFilterM(focus.machine);
    }
  }, [focus.machine, userOverrodeFilter]);

  const rows = useMemo<PecaRow[]>(() => {
    if (!engine) return [];
    return engine.ops.map((op) => {
      const tool = engine.toolMap[op.t];
      const opBlocks = blocks.filter((b) => b.opId === op.id && b.type === 'ok');
      const produced = opBlocks.reduce((s, b) => s + b.qty, 0);
      const demand = op.d.reduce((s, v) => s + Math.max(v, 0), 0);
      const totalDemand = demand + Math.max(op.atr, 0);
      return {
        opId: op.id,
        sku: op.sku,
        name: op.nm,
        tool: op.t,
        machine: op.m,
        alt: tool?.alt && tool.alt !== '-' ? tool.alt : null,
        backlog: op.atr,
        demand,
        totalDemand,
        stock: tool?.stk ?? 0,
        lotEco: tool?.lt ?? 0,
        pH: tool?.pH ?? 0,
        setupH: tool?.sH ?? 0,
        operators: tool?.op ?? 1,
        produced,
        coverage: totalDemand > 0 ? (produced / totalDemand) * 100 : 100,
        daily: op.d,
        toolIdx: engine.tools.findIndex((t) => t.id === op.t),
      };
    });
  }, [engine, blocks]);

  const filteredRows = useMemo(() => {
    let r = [...rows];
    if (filterM !== 'all') r = r.filter((x) => x.machine === filterM);
    if (onlyBacklog) r = r.filter((x) => x.backlog > 0);

    r.sort((a, b) => {
      const va = a[sortField];
      const vb = b[sortField];
      if (typeof va === 'string' && typeof vb === 'string') {
        return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      const na = Number(va) || 0,
        nb = Number(vb) || 0;
      return sortDir === 'asc' ? na - nb : nb - na;
    });
    return r;
  }, [rows, filterM, onlyBacklog, sortField, sortDir]);

  const toggleSort = (f: SortField) => {
    if (sortField === f) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortField(f);
      setSortDir(f === 'coverage' ? 'asc' : 'desc');
    }
  };

  // Summary values
  const totalSKUs = new Set(rows.map((r) => r.sku)).size;
  const totalDemand = rows.reduce((s, r) => s + r.totalDemand, 0);
  const totalStock = useMemo(() => {
    if (!engine) return 0;
    return engine.tools.reduce((s, t) => s + t.stk, 0);
  }, [engine]);
  const totalBacklog = rows.reduce((s, r) => s + Math.max(r.backlog, 0), 0);

  if (loading)
    return (
      <div className="pec" data-testid="pecas-page">
        <div className="pec__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Peças & Stock</h1>
          <p className="page-desc">
            Todas as peças (SKUs) com stock, procura, backlog e cobertura de produção.
          </p>
        </div>
        <SkeletonTable rows={10} cols={6} />
      </div>
    );
  if (error || !engine)
    return (
      <div className="pec" data-testid="pecas-page">
        <div className="pec__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Peças & Stock</h1>
          <p className="page-desc">
            Todas as peças (SKUs) com stock, procura, backlog e cobertura de produção.
          </p>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados de peças"
          description={
            error ||
            'Importe um ficheiro ISOP na página Planning para carregar dados de peças e stock.'
          }
        />
      </div>
    );

  const avgCov = rows.length > 0 ? rows.reduce((s, r) => s + r.coverage, 0) / rows.length : 100;
  const lowCovCount = rows.filter((r) => r.coverage < 80).length;

  return (
    <div className={`pec${panelOpen ? ' pec--panel-open' : ''}`} data-testid="pecas-page">
      <div className="pec__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Peças & Stock</h1>
          <p className="page-desc">
            Todas as peças (SKUs) com stock, procura, backlog e cobertura de produção.
          </p>
        </div>
        <span style={{ fontSize: 12, color: C.t3 }}>
          {totalSKUs} SKUs · {engine.ops.length} operações
        </span>
      </div>

      {/* Status Banner */}
      {avgCov < 50 || lowCovCount > rows.length * 0.3 ? (
        <StatusBanner
          variant="critical"
          message={`Risco — cobertura média ${avgCov.toFixed(0)}%, ${lowCovCount} peças abaixo de 80%.`}
        />
      ) : avgCov < 80 || totalBacklog > 0 ? (
        <StatusBanner
          variant="warning"
          message={`Atenção — ${[
            `cobertura média ${avgCov.toFixed(0)}%`,
            ...(totalBacklog > 0 ? [`${totalBacklog.toLocaleString()} peças em backlog`] : []),
          ].join(', ')}.`}
        />
      ) : (
        <StatusBanner
          variant="ok"
          message={`Stock adequado — cobertura média ${avgCov.toFixed(0)}%, sem backlog significativo.`}
        />
      )}

      {/* Summary Cards */}
      <PecasSummaryCards
        totalSKUs={totalSKUs}
        totalDemand={totalDemand}
        totalStock={totalStock}
        totalBacklog={totalBacklog}
      />

      {/* Filters */}
      <div className="pec__filters">
        <select
          value={filterM}
          onChange={(e) => {
            setFilterM(e.target.value);
            setUserOverrodeFilter(true);
          }}
          className="pec__select"
        >
          <option value="all">Todas as máquinas</option>
          {engine.machines.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id} ({m.area})
            </option>
          ))}
        </select>
        <label className="pec__toggle">
          <input
            type="checkbox"
            checked={onlyBacklog}
            onChange={(e) => setOnlyBacklog(e.target.checked)}
          />
          <span>Só backlog</span>
        </label>
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {filteredRows.length} resultados
        </span>
      </div>

      {/* SKU Table */}
      <PecasSkuTable
        rows={filteredRows}
        sortField={sortField}
        sortDir={sortDir}
        onToggleSort={toggleSort}
      />
    </div>
  );
}

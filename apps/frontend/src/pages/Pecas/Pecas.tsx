import { useEffect, useMemo, useState } from 'react';
import { EmptyState } from '../../components/Common/EmptyState';
import { SkeletonTable } from '../../components/Common/SkeletonLoader';
import { StatusBanner } from '../../components/Common/StatusBanner';
import { Term } from '../../components/Common/Tooltip';
import { useScheduleData } from '../../hooks/useScheduleData';
import { C, TC } from '../../lib/engine';
import { useUIStore } from '../../stores/useUIStore';
import './Pecas.css';

type SortField =
  | 'sku'
  | 'tool'
  | 'machine'
  | 'backlog'
  | 'demand'
  | 'stock'
  | 'produced'
  | 'coverage'
  | 'pH';
type SortDir = 'asc' | 'desc';

export function Pecas() {
  const { engine, blocks, loading, error } = useScheduleData();
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
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

  const rows = useMemo(() => {
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

  // Summary cards
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

  const sortArrow = (f: SortField) => (sortField === f ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  return (
    <div className={`pec${panelOpen ? ' pec--panel-open' : ''}`} data-testid="pecas-page">
      <div className="pec__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Peças & Stock</h1>
          <p className="page-desc">
            Todas as peças (SKUs) com stock, procura, backlog e cobertura de produção.
          </p>
        </div>
        <span style={{ fontSize: 11, color: C.t3 }}>
          {totalSKUs} SKUs · {engine.ops.length} operações
        </span>
      </div>

      {/* Status Banner */}
      {(() => {
        const avgCov =
          rows.length > 0 ? rows.reduce((s, r) => s + r.coverage, 0) / rows.length : 100;
        const lowCovCount = rows.filter((r) => r.coverage < 80).length;
        if (avgCov < 50 || lowCovCount > rows.length * 0.3) {
          return (
            <StatusBanner
              variant="critical"
              message={`Risco — cobertura média ${avgCov.toFixed(0)}%, ${lowCovCount} peças abaixo de 80%.`}
            />
          );
        }
        if (avgCov < 80 || totalBacklog > 0) {
          const parts: string[] = [`cobertura média ${avgCov.toFixed(0)}%`];
          if (totalBacklog > 0) parts.push(`${totalBacklog.toLocaleString()} peças em backlog`);
          return <StatusBanner variant="warning" message={`Atenção — ${parts.join(', ')}.`} />;
        }
        return (
          <StatusBanner
            variant="ok"
            message={`Stock adequado — cobertura média ${avgCov.toFixed(0)}%, sem backlog significativo.`}
          />
        );
      })()}

      {/* Summary Cards */}
      <div className="pec__summary">
        <SCard label="SKUs" value={String(totalSKUs)} color={C.ac} />
        <SCard
          label="Demand 8d"
          value={totalDemand > 1000 ? `${(totalDemand / 1000).toFixed(0)}K` : String(totalDemand)}
          color={C.bl}
        />
        <SCard
          label="Stock Total"
          value={totalStock > 1000 ? `${(totalStock / 1000).toFixed(0)}K` : String(totalStock)}
          color={C.ac}
        />
        <SCard
          label="Backlog Total"
          value={
            totalBacklog > 1000 ? `${(totalBacklog / 1000).toFixed(0)}K` : String(totalBacklog)
          }
          color={totalBacklog > 0 ? C.yl : C.ac}
        />
      </div>

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
        <span style={{ fontSize: 10, color: C.t3, marginLeft: 'auto' }}>
          {filteredRows.length} resultados
        </span>
      </div>

      {/* SKU Table */}
      <div className="pec__table-wrap">
        <table className="pec__table">
          <thead>
            <tr>
              <th onClick={() => toggleSort('sku')} style={{ cursor: 'pointer' }}>
                SKU{sortArrow('sku')}
              </th>
              <th>Nome</th>
              <th onClick={() => toggleSort('tool')} style={{ cursor: 'pointer' }}>
                Ferr.{sortArrow('tool')}
              </th>
              <th onClick={() => toggleSort('machine')} style={{ cursor: 'pointer' }}>
                Máq.{sortArrow('machine')}
              </th>
              <th>Alt.</th>
              <th
                onClick={() => toggleSort('backlog')}
                style={{ cursor: 'pointer', textAlign: 'right' }}
              >
                <Term code="Backlog" />
                {sortArrow('backlog')}
              </th>
              <th
                onClick={() => toggleSort('demand')}
                style={{ cursor: 'pointer', textAlign: 'right' }}
              >
                Procura{sortArrow('demand')}
              </th>
              <th
                onClick={() => toggleSort('stock')}
                style={{ cursor: 'pointer', textAlign: 'right' }}
              >
                Stock{sortArrow('stock')}
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="lt" label="Lote" />
              </th>
              <th
                onClick={() => toggleSort('produced')}
                style={{ cursor: 'pointer', textAlign: 'right' }}
              >
                Prod.{sortArrow('produced')}
              </th>
              <th
                onClick={() => toggleSort('coverage')}
                style={{ cursor: 'pointer', textAlign: 'right' }}
              >
                <Term code="Cob." label="Cob." />
                {sortArrow('coverage')}
              </th>
              <th
                onClick={() => toggleSort('pH')}
                style={{ cursor: 'pointer', textAlign: 'right' }}
              >
                <Term code="pH" />
                {sortArrow('pH')}
              </th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((r) => {
              const tColor = TC[r.toolIdx >= 0 ? r.toolIdx % TC.length : 0];
              const covBad = r.coverage < 95;
              const hasBacklog = r.backlog > 0;
              return (
                <tr
                  key={r.opId}
                  className="pec__table-row--clickable"
                  style={{ background: covBad ? C.rdS : hasBacklog ? C.ylS : undefined }}
                  onClick={() => {
                    openContextPanel({ type: 'tool', id: r.tool });
                    setFocus({ toolId: r.tool, machine: r.machine });
                  }}
                  data-testid={`pec-row-${r.opId}`}
                >
                  <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{r.sku}</td>
                  <td
                    style={{
                      maxWidth: 140,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {r.name}
                  </td>
                  <td>
                    <span style={{ color: tColor, fontFamily: "'JetBrains Mono',monospace" }}>
                      {r.tool}
                    </span>
                  </td>
                  <td style={{ fontFamily: "'JetBrains Mono',monospace" }}>{r.machine}</td>
                  <td
                    style={{ fontFamily: "'JetBrains Mono',monospace", color: r.alt ? C.t2 : C.t4 }}
                  >
                    {r.alt || '-'}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      fontWeight: hasBacklog ? 600 : 400,
                      color: hasBacklog ? C.yl : undefined,
                    }}
                  >
                    {r.backlog > 0 ? r.backlog.toLocaleString() : ''}
                  </td>
                  <td style={{ textAlign: 'right' }}>{r.totalDemand.toLocaleString()}</td>
                  <td style={{ textAlign: 'right', color: r.stock === 0 ? C.rd : undefined }}>
                    {r.stock > 0 ? r.stock.toLocaleString() : '0'}
                  </td>
                  <td style={{ textAlign: 'right', color: C.t3 }}>
                    {r.lotEco > 0 ? r.lotEco.toLocaleString() : '-'}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 600 }}>
                    {r.produced.toLocaleString()}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 600, color: covBad ? C.rd : C.ac }}>
                    {r.coverage.toFixed(0)}%
                  </td>
                  <td style={{ textAlign: 'right', color: C.t3 }}>{r.pH.toLocaleString()}/h</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="pec__scard" style={{ borderLeft: `3px solid ${color}` }}>
      <span
        style={{
          fontSize: 8,
          fontWeight: 600,
          color: C.t3,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
        }}
      >
        {label}
      </span>
      <span
        style={{ fontSize: 20, fontWeight: 700, color, fontFamily: "'JetBrains Mono',monospace" }}
      >
        {value}
      </span>
    </div>
  );
}

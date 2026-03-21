import { useMemo, useState } from 'react';
import { EmptyState } from '../../components/Common/EmptyState';
import { StatusBanner } from '../../components/Common/StatusBanner';
import { Term } from '../../components/Common/Tooltip';
import { useScheduleData } from '../../hooks/useScheduleData';
import { C } from '../../lib/engine';
import { useUIStore } from '../../stores/useUIStore';
import { KCard } from './KCard';
import './SupplyMonitor.css';
import { SupplyTableRow } from './SupplyTableRow';
import { computeSupplyRows } from './supply-compute';

const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

export function SupplyMonitor() {
  const { engine, mrp, mrpRop: rop, mrpActions: actionData, loading, error } = useScheduleData();
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  const [search, setSearch] = useState('');
  const [machineFilter, setMachineFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const allRows = useMemo(() => {
    if (!mrp || !rop || !actionData || !engine) return [];
    return computeSupplyRows(mrp, rop, actionData.messages, engine);
  }, [mrp, rop, actionData, engine]);

  const filteredRows = useMemo(() => {
    let rows = allRows;
    if (machineFilter !== 'all') rows = rows.filter((r) => r.machine === machineFilter);
    if (riskFilter !== 'all') rows = rows.filter((r) => r.risk === riskFilter);
    if (search) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (r) =>
          r.toolCode.toLowerCase().includes(q) ||
          r.skus.some((s) => s.sku.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)),
      );
    }
    return rows;
  }, [allRows, machineFilter, riskFilter, search]);

  if (loading)
    return (
      <div className="supply" data-testid="supply-page">
        <div className="supply__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Supply Monitor — Nikufra
          </h1>
          <p className="page-desc">
            Risco de abastecimento: ferramentas em perigo de ruptura de stock.
          </p>
        </div>
        <div style={{ padding: 40, textAlign: 'center', color: C.t2 }}>
          A carregar dados de abastecimento...
        </div>
      </div>
    );
  if (error || !engine || !mrp)
    return (
      <div className="supply" data-testid="supply-page">
        <div className="supply__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Supply Monitor — Nikufra
          </h1>
          <p className="page-desc">
            Risco de abastecimento: ferramentas em perigo de ruptura de stock.
          </p>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados de abastecimento"
          description={
            error ||
            'Importe um ficheiro ISOP na página Planning para monitorizar o risco de abastecimento.'
          }
        />
      </div>
    );

  function toggleExpand(toolCode: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(toolCode)) next.delete(toolCode);
      else next.add(toolCode);
      return next;
    });
  }

  const riskCounts = { critical: 0, high: 0, medium: 0, ok: 0 };
  for (const r of allRows) riskCounts[r.risk]++;
  const atRisk = riskCounts.critical + riskCounts.high;
  const stockouts = allRows.filter((r) => r.stockoutDay !== null).length;
  const avgCov =
    allRows.length > 0 ? allRows.reduce((s, r) => s + r.coverageDays, 0) / allRows.length : 0;
  const critActions = allRows.reduce(
    (s, r) => s + r.actions.filter((a) => a.severity === 'critical').length,
    0,
  );

  return (
    <div className={`supply${panelOpen ? ' supply--panel-open' : ''}`} data-testid="supply-page">
      <div className="supply__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Supply Monitor — Nikufra
          </h1>
          <p className="page-desc">
            Risco de abastecimento: ferramentas em perigo de ruptura de stock.
          </p>
        </div>
        <span style={{ fontSize: 12, color: C.t3, ...mono }}>
          {engine.dates[0]} — {engine.dates[engine.dates.length - 1]} · {allRows.length} tools ·{' '}
          {engine.ops.length} ops
        </span>
      </div>

      {(() => {
        if (riskCounts.critical > 0)
          return (
            <StatusBanner
              variant="critical"
              message={`Risco — ${riskCounts.critical} tools em estado crítico, ${stockouts} stockouts previstos.`}
              details={critActions > 0 ? `${critActions} acções críticas pendentes.` : undefined}
            />
          );
        if (riskCounts.high > 0 || stockouts > 0)
          return (
            <StatusBanner
              variant="warning"
              message={`Atenção — ${atRisk} tools em risco, cobertura média ${avgCov.toFixed(1)} dias.`}
            />
          );
        return (
          <StatusBanner
            variant="ok"
            message={`Abastecimento estável — cobertura média ${avgCov.toFixed(1)} dias, sem riscos detectados.`}
          />
        );
      })()}

      <div className="supply__kpis">
        <KCard
          label="Em Risco"
          value={String(atRisk)}
          sub={`${riskCounts.critical} críticos · ${riskCounts.high} altos`}
          color={atRisk > 0 ? C.rd : C.ac}
        />
        <KCard
          label="Stockouts"
          value={String(stockouts)}
          sub={`de ${allRows.length} tools`}
          color={stockouts > 0 ? C.rd : C.ac}
        />
        <KCard
          label="Cobertura Média"
          value={`${avgCov.toFixed(1)}d`}
          sub={avgCov < 2 ? 'nível crítico' : avgCov < 4 ? 'atenção' : 'adequado'}
          color={avgCov < 2 ? C.rd : avgCov < 4 ? C.yl : C.ac}
        />
        <KCard
          label="Acções Críticas"
          value={String(critActions)}
          sub="precisam acção imediata"
          color={critActions > 0 ? C.rd : C.ac}
        />
      </div>

      <div className="supply__filters">
        <input
          className="supply__filter-input"
          type="text"
          placeholder="Pesquisar tool, SKU, produto..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="supply__filter-select"
          value={machineFilter}
          onChange={(e) => setMachineFilter(e.target.value)}
        >
          <option value="all">Todas máquinas</option>
          {engine.machines.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id} ({m.area})
            </option>
          ))}
        </select>
        <select
          className="supply__filter-select"
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value)}
        >
          <option value="all">Todos riscos ({allRows.length})</option>
          <option value="critical">Crítico ({riskCounts.critical})</option>
          <option value="high">Alto ({riskCounts.high})</option>
          <option value="medium">Médio ({riskCounts.medium})</option>
          <option value="ok">OK ({riskCounts.ok})</option>
        </select>
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {filteredRows.length} de {allRows.length} items
        </span>
      </div>

      <div className="supply__card">
        <table className="supply__table">
          <thead>
            <tr>
              <th style={{ width: 20 }} />
              <th>Tool</th>
              <th>Produto</th>
              <th>Máquina</th>
              <th style={{ textAlign: 'center' }}>
                <Term code="ABC" />
              </th>
              <th style={{ textAlign: 'right' }}>Stock</th>
              <th style={{ textAlign: 'right' }}>
                <Term code="Backlog" />
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="SS" />
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="ROP" />
              </th>
              <th style={{ textAlign: 'right' }}>
                <Term code="Cobertura" />
              </th>
              <th>Rotura</th>
              <th>Status</th>
              <th style={{ textAlign: 'right' }}>
                <Term code="POR" />
              </th>
              <th style={{ textAlign: 'center' }}>Acções</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => (
              <SupplyTableRow
                key={row.toolCode}
                row={row}
                isExpanded={expanded.has(row.toolCode)}
                onToggle={() => toggleExpand(row.toolCode)}
                dnames={engine.dnames}
              />
            ))}
          </tbody>
        </table>
        {filteredRows.length === 0 && (
          <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
            Nenhum item encontrado para os filtros seleccionados
          </div>
        )}
      </div>
    </div>
  );
}

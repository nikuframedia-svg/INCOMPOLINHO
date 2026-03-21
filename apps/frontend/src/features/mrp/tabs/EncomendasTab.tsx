import { useMemo, useState } from 'react';
import type { MRPResult, MRPSkuViewResult } from '@/domain/mrp/mrp-types';
import type { Block, EngineData } from '@/lib/engine';
import { C } from '@/lib/engine';
import { KCard } from '../components/KCard';
import { computeOrderRisk, groupByClient } from '../utils/encomendas-compute';
import { fmtQty } from '../utils/mrp-helpers';
import { ClientGroup } from './ClientGroup';
import { OrderRow } from './OrderRow';

type EncView = 'sku' | 'cliente';
type RiskFilter = 'all' | 'risk' | 'critical';

interface EncomendasTabProps {
  engine: EngineData;
  mrp: MRPResult;
  skuView: MRPSkuViewResult;
  blocks: Block[];
}

export function EncomendasTab({ engine, mrp, skuView, blocks }: EncomendasTabProps) {
  const [view, setView] = useState<EncView>('sku');
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [clientFilter, setClientFilter] = useState('all');
  const [machineFilter, setMachineFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const allEntries = useMemo(
    () => computeOrderRisk(engine, mrp, skuView, blocks),
    [engine, mrp, skuView, blocks],
  );

  const clients = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of allEntries) {
      if (e.customerCode) map.set(e.customerCode, e.customerName || e.customerCode);
    }
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [allEntries]);

  const filteredEntries = useMemo(() => {
    let entries = allEntries;
    if (riskFilter === 'risk') entries = entries.filter((e) => e.riskLevel !== 'ok');
    if (riskFilter === 'critical') entries = entries.filter((e) => e.riskLevel === 'critical');
    if (clientFilter !== 'all') entries = entries.filter((e) => e.customerCode === clientFilter);
    if (machineFilter !== 'all') entries = entries.filter((e) => e.machineId === machineFilter);
    if (search) {
      const q = search.toLowerCase();
      entries = entries.filter(
        (e) =>
          e.sku.toLowerCase().includes(q) ||
          e.skuName.toLowerCase().includes(q) ||
          e.toolCode.toLowerCase().includes(q) ||
          e.customerName?.toLowerCase().includes(q),
      );
    }
    return entries;
  }, [allEntries, riskFilter, clientFilter, machineFilter, search]);

  const clientGroups = useMemo(() => groupByClient(filteredEntries), [filteredEntries]);

  const totalDemand = allEntries.reduce((s, e) => s + e.orderQty, 0);
  const totalScheduled = allEntries.reduce((s, e) => s + e.totalScheduledQty, 0);
  const totalShortfall = allEntries.reduce((s, e) => s + e.shortfallQty, 0);
  const criticalCount = allEntries.filter((e) => e.riskLevel === 'critical').length;

  function toggleExpand(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const numDays = engine.dates.length;

  return (
    <>
      <div className="mrp__view-bar" style={{ marginBottom: 12 }}>
        <div className="mrp__view-selector">
          {(['sku', 'cliente'] as EncView[]).map((v) => (
            <button
              key={v}
              className={`mrp__view-btn ${view === v ? 'mrp__view-btn--active' : ''}`}
              onClick={() => setView(v)}
            >
              {v === 'sku' ? 'SKU' : 'Cliente'}
            </button>
          ))}
        </div>
      </div>

      <div className="mrp__kpis" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <KCard
          label="Procura"
          value={fmtQty(totalDemand)}
          sub={`${allEntries.length} encomendas`}
          color={C.t1}
        />
        <KCard
          label="Produção"
          value={fmtQty(totalScheduled)}
          sub="agendada"
          color={totalScheduled >= totalDemand ? C.ac : C.yl}
        />
        <KCard
          label="Deficit"
          value={totalShortfall > 0 ? fmtQty(totalShortfall) : '-'}
          sub="peças em falta"
          color={totalShortfall > 0 ? C.rd : C.ac}
        />
        <KCard
          label="Criticas"
          value={String(criticalCount)}
          sub="sem produção suficiente"
          color={criticalCount > 0 ? C.rd : C.ac}
        />
      </div>

      <div className="mrp__filters">
        <select
          className="mrp__filter-select"
          value={riskFilter}
          onChange={(e) => setRiskFilter(e.target.value as RiskFilter)}
        >
          <option value="all">Todas ({allEntries.length})</option>
          <option value="risk">
            Em Risco ({allEntries.filter((e) => e.riskLevel !== 'ok').length})
          </option>
          <option value="critical">Criticas ({criticalCount})</option>
        </select>
        <select
          className="mrp__filter-select"
          value={clientFilter}
          onChange={(e) => setClientFilter(e.target.value)}
        >
          <option value="all">Todos clientes</option>
          {clients.map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
        <select
          className="mrp__filter-select"
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
        <input
          className="mrp__filter-input"
          type="text"
          placeholder="Procurar SKU/produto/cliente..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>
          {filteredEntries.length} de {allEntries.length} encomendas
        </span>
      </div>

      {view === 'sku' && (
        <div className="mrp__card">
          <table className="mrp__table">
            <thead>
              <tr>
                <th style={{ width: 20 }} />
                <th style={{ width: 20 }} />
                <th>SKU</th>
                <th>Produto</th>
                <th>Cliente</th>
                <th style={{ textAlign: 'right' }}>Deficit</th>
                <th style={{ textAlign: 'right' }}>Cobertura</th>
                <th>Produção</th>
              </tr>
            </thead>
            <tbody>
              {filteredEntries.map((entry) => (
                <OrderRow
                  key={entry.opId}
                  entry={entry}
                  isExpanded={expanded.has(entry.opId)}
                  onToggle={() => toggleExpand(entry.opId)}
                  numDays={numDays}
                  dates={engine.dates}
                  dnames={engine.dnames}
                />
              ))}
            </tbody>
          </table>
          {filteredEntries.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
              Nenhuma encomenda encontrada
            </div>
          )}
        </div>
      )}

      {view === 'cliente' && (
        <div className="mrp__card">
          {clientGroups.map((group) => (
            <ClientGroup
              key={group.customerCode}
              group={group}
              expanded={expanded}
              onToggle={toggleExpand}
              numDays={numDays}
              dates={engine.dates}
              dnames={engine.dnames}
            />
          ))}
          {clientGroups.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center', color: C.t3, fontSize: 12 }}>
              Nenhum cliente encontrado
            </div>
          )}
        </div>
      )}
    </>
  );
}

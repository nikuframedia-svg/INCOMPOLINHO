import { AlertTriangle, ChevronDown, ChevronRight, Link2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { MRPResult, MRPSkuViewResult } from '@/domain/mrp/mrp-types';
import type { Block, EngineData } from '@/lib/engine';
import { C } from '@/lib/engine';
import { useUIStore } from '@/stores/useUIStore';
import { KCard } from '../components/KCard';
import type { ClientRiskGroup, OrderRiskEntry } from '../utils/encomendas-compute';
import { computeOrderRisk, groupByClient } from '../utils/encomendas-compute';
import { fmtQty, mono } from '../utils/mrp-helpers';

type EncView = 'sku' | 'cliente';
type RiskFilter = 'all' | 'risk' | 'critical';

interface EncomendasTabProps {
  engine: EngineData;
  mrp: MRPResult;
  skuView: MRPSkuViewResult;
  blocks: Block[];
}

const RISK_DOT: Record<string, string> = {
  critical: 'var(--semantic-red)',
  warning: 'var(--semantic-amber)',
  ok: 'var(--accent)',
};

export function EncomendasTab({ engine, mrp, skuView, blocks }: EncomendasTabProps) {
  const [view, setView] = useState<EncView>('sku');
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [clientFilter, setClientFilter] = useState('all');
  const [machineFilter, setMachineFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Compute order risk entries
  const allEntries = useMemo(
    () => computeOrderRisk(engine, mrp, skuView, blocks),
    [engine, mrp, skuView, blocks],
  );

  // Distinct clients
  const clients = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of allEntries) {
      if (e.customerCode) map.set(e.customerCode, e.customerName || e.customerCode);
    }
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [allEntries]);

  // Filter entries
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

  // Client groups (for client view)
  const clientGroups = useMemo(() => groupByClient(filteredEntries), [filteredEntries]);

  // KPIs
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
      {/* View Toggle */}
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

      {/* KPIs */}
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

      {/* Filters */}
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
        <span style={{ fontSize: 10, color: C.t3, marginLeft: 'auto' }}>
          {filteredEntries.length} de {allEntries.length} encomendas
        </span>
      </div>

      {/* SKU View */}
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

      {/* Client View */}
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

// ── Order Row ──────────────────────────────────────────────

function OrderRow({
  entry: e,
  isExpanded,
  onToggle,
  numDays,
  dates,
  dnames,
}: {
  entry: OrderRiskEntry;
  isExpanded: boolean;
  onToggle: () => void;
  numDays: number;
  dates: string[];
  dnames: string[];
}) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);

  return (
    <>
      <tr
        style={{ cursor: 'pointer' }}
        onClick={onToggle}
        className={e.riskLevel === 'critical' ? 'mrp__row--stockout' : ''}
      >
        <td style={{ width: 20 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
        </td>
        <td style={{ width: 20 }}>
          <span className="mrp__enc-risk-dot" style={{ background: RISK_DOT[e.riskLevel] }} />
        </td>
        <td>
          <span
            style={{ ...mono, fontSize: 11, fontWeight: 600, color: C.t1, cursor: 'pointer' }}
            onClick={(ev) => {
              ev.stopPropagation();
              openContextPanel({ type: 'tool', id: e.toolCode });
              setFocus({ toolId: e.toolCode });
            }}
          >
            {e.sku}
          </span>
          {e.isTwin && (
            <span className="mrp__twin-badge" title={`Peça gémea: ${e.twinSku}`}>
              <Link2 size={10} />
            </span>
          )}
        </td>
        <td>
          <span style={{ fontSize: 10, color: C.t2 }}>{e.skuName}</span>
        </td>
        <td>
          {e.customerName ? (
            <span className="mrp__enc-client-badge">{e.customerName}</span>
          ) : (
            <span style={{ fontSize: 10, color: C.t4 }}>-</span>
          )}
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: e.shortfallQty > 0 ? C.rd : C.t3 }}>
            {e.shortfallQty > 0 ? fmtQty(e.shortfallQty) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span
            style={{
              fontSize: 10,
              color: e.coverageDays < 1 ? C.rd : e.coverageDays < 3 ? C.yl : C.ac,
            }}
          >
            {e.coverageDays.toFixed(1)}d
          </span>
        </td>
        <td>
          <MiniTimeline productionDays={e.productionDays} numDays={numDays} />
        </td>
      </tr>

      {isExpanded && (
        <tr className="mrp__detail-row">
          <td colSpan={8}>
            {/* Production timeline detail */}
            <div className="mrp__enc-detail">
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontSize: 10, fontWeight: 500, color: C.t2 }}>
                  Produção agendada
                </span>
                <span style={{ fontSize: 9, color: C.t3, marginLeft: 8 }}>
                  Total: <span style={{ ...mono, color: C.t1 }}>{fmtQty(e.totalScheduledQty)}</span>{' '}
                  pcs
                </span>
              </div>
              <div className="mrp__enc-timeline-detail">
                {Array.from({ length: numDays }).map((_, i) => {
                  const dayProds = e.productionDays.filter((p) => p.dayIdx === i);
                  const dayQty = dayProds.reduce((s, p) => s + p.qty, 0);
                  return (
                    <div
                      key={i}
                      className={`mrp__enc-timeline-day-detail${dayQty > 0 ? ' mrp__enc-timeline-day-detail--active' : ''}`}
                    >
                      <span className="mrp__enc-timeline-day-label">
                        {dnames[i]} {dates[i]}
                      </span>
                      {dayQty > 0 && (
                        <span style={{ ...mono, fontSize: 10, color: C.ac }}>{fmtQty(dayQty)}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Suggestions */}
            {e.suggestions.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 500,
                    color: C.t2,
                    marginBottom: 4,
                    display: 'block',
                  }}
                >
                  Sugestões
                </span>
                <div className="mrp__enc-suggestions">
                  {e.suggestions.map((s) => (
                    <div
                      key={s.id}
                      className={`mrp__enc-suggestion mrp__enc-suggestion--${s.severity}`}
                    >
                      <AlertTriangle size={11} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 10, fontWeight: 500, color: C.t1 }}>{s.title}</div>
                        <div style={{ fontSize: 9, color: C.t2 }}>{s.suggestedAction}</div>
                      </div>
                      <span style={{ ...mono, fontSize: 9, color: C.t3 }}>
                        {fmtQty(s.impact.qtyAffected)} pcs
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Detail metadata */}
            <div style={{ marginTop: 8, fontSize: 9, color: C.t3, display: 'flex', gap: 16 }}>
              <span>
                Tool: <span style={{ ...mono, color: C.t2 }}>{e.toolCode}</span>
              </span>
              <span>
                Máq: <span style={{ ...mono, color: C.t2 }}>{e.machineId}</span>
              </span>
              {e.altMachine && (
                <span>
                  Alt: <span style={{ ...mono, color: C.t2 }}>{e.altMachine}</span>
                </span>
              )}
              {!e.altMachine && <span style={{ color: C.rd }}>Sem alternativa</span>}
              {e.isTwin && <span style={{ color: C.ac }}>Twin: {e.twinSku}</span>}
              {e.stockoutDay !== null && (
                <span style={{ color: C.rd }}>Stockout dia {e.stockoutDay}</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Client Group ──────────────────────────────────────────

function ClientGroup({
  group,
  expanded,
  onToggle,
  numDays,
  dates,
  dnames,
}: {
  group: ClientRiskGroup;
  expanded: Set<string>;
  onToggle: (key: string) => void;
  numDays: number;
  dates: string[];
  dnames: string[];
}) {
  const clientKey = `__client__${group.customerCode}`;
  const isExpanded = expanded.has(clientKey);

  return (
    <div style={{ marginBottom: 4 }}>
      <div
        className="mrp__enc-client-row"
        onClick={() => onToggle(clientKey)}
        style={{ cursor: 'pointer' }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
          <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{group.customerName}</span>
          <span style={{ fontSize: 9, color: C.t3, ...mono }}>{group.customerCode}</span>
        </span>
        <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: C.t2 }}>{group.totalOrders} encomendas</span>
          {group.criticalCount > 0 && (
            <span style={{ fontSize: 9, color: C.rd, fontWeight: 600 }}>
              {group.criticalCount} criticas
            </span>
          )}
          {group.warningCount > 0 && (
            <span style={{ fontSize: 9, color: C.yl }}>{group.warningCount} em risco</span>
          )}
          {group.totalShortfall > 0 && (
            <span style={{ ...mono, fontSize: 10, color: C.rd }}>
              Deficit: {fmtQty(group.totalShortfall)}
            </span>
          )}
        </span>
      </div>

      {isExpanded && (
        <table className="mrp__table" style={{ marginTop: 4, marginBottom: 8 }}>
          <thead>
            <tr>
              <th style={{ width: 20 }} />
              <th style={{ width: 20 }} />
              <th>SKU</th>
              <th>Produto</th>
              <th style={{ textAlign: 'right' }}>Deficit</th>
              <th style={{ textAlign: 'right' }}>Cobertura</th>
              <th>Produção</th>
            </tr>
          </thead>
          <tbody>
            {group.entries.map((entry) => (
              <OrderRow
                key={entry.opId}
                entry={entry}
                isExpanded={expanded.has(entry.opId)}
                onToggle={() => onToggle(entry.opId)}
                numDays={numDays}
                dates={dates}
                dnames={dnames}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Mini Timeline ─────────────────────────────────────────

function MiniTimeline({
  productionDays,
  numDays,
}: {
  productionDays: Array<{ dayIdx: number; qty: number }>;
  numDays: number;
}) {
  const daySet = new Set(productionDays.map((p) => p.dayIdx));
  const cellW = Math.min(10, Math.max(4, 120 / numDays));
  const w = numDays * (cellW + 1);

  return (
    <svg width={w} height={12} style={{ display: 'block' }}>
      {Array.from({ length: numDays }).map((_, i) => (
        <rect
          key={i}
          x={i * (cellW + 1)}
          y={1}
          width={cellW}
          height={10}
          rx={1}
          fill={daySet.has(i) ? C.ac : `${C.t3}20`}
          opacity={daySet.has(i) ? 0.8 : 1}
        />
      ))}
    </svg>
  );
}

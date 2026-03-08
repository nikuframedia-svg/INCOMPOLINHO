import { AlertTriangle, ChevronDown, ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';
import { EmptyState } from '../../components/Common/EmptyState';
import { StatusBanner } from '../../components/Common/StatusBanner';
import { Term } from '../../components/Common/Tooltip';
import type {
  MRPRecord,
  MRPResult,
  RCCPEntry,
  ROPResult,
  ROPSummary,
} from '../../domain/mrp/mrp-types';
import { useScheduleData } from '../../hooks/useScheduleData';
import type { ActionMessage, EngineData } from '../../lib/engine';
import { C, computeActionMessages, computeMRP, computeROP } from '../../lib/engine';
import { useUIStore } from '../../stores/useUIStore';
import './SupplyMonitor.css';

const mono: React.CSSProperties = { fontFamily: "'JetBrains Mono',monospace" };

function fmtQty(n: number): string {
  if (n === 0) return '-';
  if (Math.abs(n) >= 10000) return `${(n / 1000).toFixed(0)}K`;
  if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(Math.round(n));
}

// ── Types ──────────────────────────────────────────────────────

type Risk = 'critical' | 'high' | 'medium' | 'ok';

interface SupplyRow {
  toolCode: string;
  skus: Array<{ sku: string; name: string }>;
  machine: string;
  altMachine: string | null;
  currentStock: number;
  backlog: number;
  ratePerHour: number;
  coverageDays: number;
  stockoutDay: number | null;
  stockoutDate: string | null;
  totalDemand: number;
  totalPlannedQty: number;
  canMeetDelivery: boolean;
  safetyStock: number;
  rop: number;
  abcClass: 'A' | 'B' | 'C';
  belowROP: boolean;
  belowSS: boolean;
  risk: Risk;
  actions: ActionMessage[];
  dailyProjection: Array<{ day: number; projected: number; ropLine: number; ssLine: number }>;
}

// ── Risk classification ────────────────────────────────────────

function classifyRisk(rec: MRPRecord, ropRec: ROPResult | null, isOverloaded: boolean): Risk {
  if (rec.stockoutDay !== null && rec.stockoutDay <= 1) return 'critical';
  if (rec.stockoutDay !== null && isOverloaded) return 'critical';
  if (rec.stockoutDay !== null) return 'high';
  if (ropRec && ropRec.currentStock < ropRec.rop) return 'medium';
  if (rec.coverageDays < 3 && rec.totalGrossReq > 0) return 'medium';
  return 'ok';
}

function checkMachineOverloaded(rec: MRPRecord, rccp: RCCPEntry[]): boolean {
  for (const bucket of rec.buckets) {
    if (bucket.plannedOrderRelease > 0) {
      const entry = rccp.find((e) => e.machine === rec.machine && e.dayIndex === bucket.dayIndex);
      if (entry && entry.overloaded) return true;
    }
  }
  return false;
}

const RISK_ORDER: Record<Risk, number> = { critical: 0, high: 1, medium: 2, ok: 3 };

// ── Supply row computation ─────────────────────────────────────

function computeSupplyRows(
  mrp: MRPResult,
  rop: ROPSummary,
  actions: ActionMessage[],
  engine: EngineData,
): SupplyRow[] {
  const ropMap: Record<string, ROPResult> = {};
  for (const r of rop.records) ropMap[r.toolCode] = r;

  const actionMap: Record<string, ActionMessage[]> = {};
  for (const a of actions) {
    if (!actionMap[a.toolCode]) actionMap[a.toolCode] = [];
    actionMap[a.toolCode].push(a);
  }

  const rows: SupplyRow[] = [];

  for (const rec of mrp.records) {
    const ropRec = ropMap[rec.toolCode] ?? null;
    const isOverloaded = checkMachineOverloaded(rec, mrp.rccp);
    const risk = classifyRisk(rec, ropRec, isOverloaded);
    const canMeet = rec.stockoutDay === null || !isOverloaded;

    const stockoutDate =
      rec.stockoutDay !== null && engine.dates[rec.stockoutDay]
        ? engine.dates[rec.stockoutDay]
        : null;

    const dailyProjection = rec.buckets.map((b) => ({
      day: b.dayIndex,
      projected: b.projectedAvailable,
      ropLine: ropRec?.rop ?? 0,
      ssLine: ropRec?.safetyStock ?? 0,
    }));

    rows.push({
      toolCode: rec.toolCode,
      skus: rec.skus,
      machine: rec.machine,
      altMachine: rec.altMachine,
      currentStock: rec.currentStock,
      backlog: rec.backlog,
      ratePerHour: rec.ratePerHour,
      coverageDays: rec.coverageDays,
      stockoutDay: rec.stockoutDay,
      stockoutDate,
      totalDemand: rec.totalGrossReq,
      totalPlannedQty: rec.totalPlannedQty,
      canMeetDelivery: canMeet,
      safetyStock: ropRec?.safetyStock ?? 0,
      rop: ropRec?.rop ?? 0,
      abcClass: ropRec?.abcClass ?? 'C',
      belowROP: ropRec ? rec.currentStock < ropRec.rop : false,
      belowSS: ropRec ? rec.currentStock < ropRec.safetyStock : false,
      risk,
      actions: actionMap[rec.toolCode] ?? [],
      dailyProjection,
    });
  }

  rows.sort((a, b) => {
    const rd = RISK_ORDER[a.risk] - RISK_ORDER[b.risk];
    if (rd !== 0) return rd;
    return a.coverageDays - b.coverageDays;
  });

  return rows;
}

// ── Main Component ─────────────────────────────────────────────

export function SupplyMonitor() {
  const { engine, loading, error } = useScheduleData();
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  const [search, setSearch] = useState('');
  const [machineFilter, setMachineFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState<string>('all');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const mrp = useMemo(() => (engine ? computeMRP(engine) : null), [engine]);
  const rop = useMemo(() => (mrp && engine ? computeROP(mrp, engine, 95) : null), [mrp, engine]);
  const actionData = useMemo(
    () => (mrp && engine ? computeActionMessages(mrp, engine) : null),
    [mrp, engine],
  );

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
      {/* Header */}
      <div className="supply__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Supply Monitor — Nikufra
          </h1>
          <p className="page-desc">
            Risco de abastecimento: ferramentas em perigo de ruptura de stock.
          </p>
        </div>
        <span style={{ fontSize: 11, color: C.t3, ...mono }}>
          {engine.dates[0]} — {engine.dates[engine.dates.length - 1]} · {allRows.length} tools ·{' '}
          {engine.ops.length} ops
        </span>
      </div>

      {/* Status Banner */}
      {(() => {
        if (riskCounts.critical > 0) {
          return (
            <StatusBanner
              variant="critical"
              message={`Risco — ${riskCounts.critical} tools em estado crítico, ${stockouts} stockouts previstos.`}
              details={critActions > 0 ? `${critActions} acções críticas pendentes.` : undefined}
            />
          );
        }
        if (riskCounts.high > 0 || stockouts > 0) {
          return (
            <StatusBanner
              variant="warning"
              message={`Atenção — ${atRisk} tools em risco, cobertura média ${avgCov.toFixed(1)} dias.`}
            />
          );
        }
        return (
          <StatusBanner
            variant="ok"
            message={`Abastecimento estável — cobertura média ${avgCov.toFixed(1)} dias, sem riscos detectados.`}
          />
        );
      })()}

      {/* KPIs */}
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

      {/* Filters */}
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
        <span style={{ fontSize: 10, color: C.t3, marginLeft: 'auto' }}>
          {filteredRows.length} de {allRows.length} items
        </span>
      </div>

      {/* Supply Table */}
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

// ── Table Row ──────────────────────────────────────────────────

function SupplyTableRow({
  row,
  isExpanded,
  onToggle,
  dnames,
}: {
  row: SupplyRow;
  isExpanded: boolean;
  onToggle: () => void;
  dnames: string[];
}) {
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const skuLabel =
    row.skus.length === 1 ? row.skus[0].name : `${row.skus[0].name} +${row.skus.length - 1}`;

  const stockColor = row.belowSS ? C.rd : row.belowROP ? C.yl : row.currentStock > 0 ? C.ac : C.t3;
  const covColor = row.coverageDays < 1 ? C.rd : row.coverageDays < 3 ? C.yl : C.ac;

  // Enriched status: check SS/ROP levels + stockout
  const statusBadge = (() => {
    if (row.stockoutDay !== null && !row.canMeetDelivery)
      return { label: 'FALHA', cls: 'supply__badge--fail' };
    if (row.stockoutDay !== null) return { label: 'RISCO', cls: 'supply__badge--risk' };
    if (row.belowSS) return { label: '< SS', cls: 'supply__badge--below-ss' };
    if (row.belowROP) return { label: '< ROP', cls: 'supply__badge--below-rop' };
    return { label: 'OK', cls: 'supply__badge--ok' };
  })();

  const actionCount = row.actions.length;
  const hasCritical = row.actions.some((a) => a.severity === 'critical');

  return (
    <>
      <tr className={`supply__row supply__row--${row.risk}`} onClick={onToggle}>
        <td style={{ width: 20 }}>
          {isExpanded ? (
            <ChevronDown size={12} color={C.t3} />
          ) : (
            <ChevronRight size={12} color={C.t3} />
          )}
        </td>
        <td>
          <span
            style={{ ...mono, fontSize: 11, fontWeight: 600, color: C.t1, cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'tool', id: row.toolCode });
              setFocus({ toolId: row.toolCode });
            }}
          >
            {row.toolCode}
          </span>
        </td>
        <td>
          <span
            style={{ fontSize: 10, color: C.t2 }}
            title={row.skus.map((s) => `${s.sku}: ${s.name}`).join('\n')}
          >
            {skuLabel}
          </span>
        </td>
        <td>
          <span
            style={{ ...mono, fontSize: 10, color: C.t2, cursor: 'pointer' }}
            onClick={(e) => {
              e.stopPropagation();
              openContextPanel({ type: 'machine', id: row.machine });
              setFocus({ machine: row.machine });
            }}
          >
            {row.machine}
          </span>
          {!row.altMachine && (
            <span className="supply__no-alt" title="Sem máquina alternativa">
              !
            </span>
          )}
        </td>
        <td style={{ textAlign: 'center' }}>
          <span className={`supply__abc-badge supply__abc-badge--${row.abcClass.toLowerCase()}`}>
            {row.abcClass}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: stockColor }}>
            {fmtQty(row.currentStock)}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: row.backlog > 0 ? C.yl : C.t4 }}>
            {row.backlog > 0 ? fmtQty(row.backlog) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: row.belowSS ? C.rd : C.t3 }}>
            {row.safetyStock > 0 ? fmtQty(row.safetyStock) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: row.belowROP ? C.yl : C.t3 }}>
            {row.rop > 0 ? fmtQty(row.rop) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: covColor }}>
            {row.totalDemand > 0 ? `${row.coverageDays.toFixed(1)}d` : '-'}
          </span>
        </td>
        <td>
          {row.stockoutDay !== null ? (
            <span style={{ ...mono, fontSize: 10, color: C.rd, fontWeight: 600 }}>
              D{row.stockoutDay}
              {row.stockoutDate && (
                <span style={{ fontWeight: 400, color: C.t3 }}> ({row.stockoutDate})</span>
              )}
            </span>
          ) : (
            <span style={{ fontSize: 10, color: C.t4 }}>—</span>
          )}
        </td>
        <td>
          <span className={`supply__badge ${statusBadge.cls}`}>{statusBadge.label}</span>
        </td>
        <td style={{ textAlign: 'right' }}>
          <span style={{ ...mono, fontSize: 10, color: row.totalPlannedQty > 0 ? C.ac : C.t4 }}>
            {row.totalPlannedQty > 0 ? fmtQty(row.totalPlannedQty) : '-'}
          </span>
        </td>
        <td style={{ textAlign: 'center' }}>
          {actionCount > 0 && (
            <span
              className="supply__action-count"
              style={{
                background: hasCritical ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.12)',
                color: hasCritical ? C.rd : C.yl,
              }}
            >
              {actionCount}
            </span>
          )}
        </td>
      </tr>

      {isExpanded && (
        <tr className="supply__detail">
          <td colSpan={14}>
            <div className="supply__detail-inner">
              {/* Action Suggestions */}
              <div className="supply__detail-actions">
                {row.actions.length > 0 ? (
                  row.actions.map((a) => (
                    <div
                      key={a.id}
                      className={`supply__action-card supply__action-card--${a.severity}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'flex-start', paddingTop: 1 }}>
                        <AlertTriangle
                          size={12}
                          color={
                            a.severity === 'critical' ? C.rd : a.severity === 'high' ? C.yl : C.bl
                          }
                        />
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div className="supply__action-title">{a.title}</div>
                        <div className="supply__action-desc">{a.description}</div>
                        <div className="supply__action-suggestion">{a.suggestedAction}</div>
                      </div>
                      <div
                        style={{
                          fontSize: 9,
                          color: C.t3,
                          ...mono,
                          whiteSpace: 'nowrap',
                          textAlign: 'right',
                        }}
                      >
                        <div>{fmtQty(a.impact.qtyAffected)} pcs</div>
                        <div>{a.impact.daysAffected}d</div>
                      </div>
                    </div>
                  ))
                ) : (
                  <div style={{ fontSize: 11, color: C.t3, padding: '4px 0' }}>
                    Sem acções pendentes
                  </div>
                )}

                {/* Tool info bar */}
                <div style={{ fontSize: 9, color: C.t3, display: 'flex', gap: 14, marginTop: 4 }}>
                  <span>Rate: {row.ratePerHour} p/h</span>
                  <span>Backlog: {row.backlog > 0 ? fmtQty(row.backlog) : '-'}</span>
                  <span>Demand total: {fmtQty(row.totalDemand)}</span>
                  <span>ABC: {row.abcClass}</span>
                  {row.altMachine ? (
                    <span>Alt: {row.altMachine}</span>
                  ) : (
                    <span style={{ color: C.rd }}>Sem alternativa</span>
                  )}
                </div>
              </div>

              {/* Mini projection chart */}
              <div className="supply__detail-chart">
                <MiniChart projection={row.dailyProjection} dnames={dnames} />
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Mini Stock Projection Chart ────────────────────────────────

function MiniChart({
  projection,
  dnames,
}: {
  projection: Array<{ day: number; projected: number; ropLine: number; ssLine: number }>;
  dnames: string[];
}) {
  if (projection.length === 0) return null;

  const W = 280,
    H = 80;
  const PAD = { t: 8, r: 8, b: 16, l: 36 };
  const chartW = W - PAD.l - PAD.r;
  const chartH = H - PAD.t - PAD.b;

  const allVals = projection.flatMap((p) => [p.projected, p.ropLine, p.ssLine]);
  const maxV = Math.max(...allVals, 1);
  const minV = Math.min(...allVals, 0);
  const range = maxV - minV || 1;

  const scaleY = (v: number) => PAD.t + chartH - ((v - minV) / range) * chartH;
  const scaleX = (i: number) => PAD.l + (i / (projection.length - 1 || 1)) * chartW;

  const projLine = projection
    .map(
      (p, i) => `${i === 0 ? 'M' : 'L'}${scaleX(i).toFixed(1)},${scaleY(p.projected).toFixed(1)}`,
    )
    .join(' ');

  const ropY = scaleY(projection[0].ropLine);
  const ssY = scaleY(projection[0].ssLine);

  // Area below zero
  const zeroY = scaleY(0);
  const belowZeroPath = projection.reduce((acc, p, i) => {
    if (p.projected < 0) {
      const x = scaleX(i);
      const y = scaleY(p.projected);
      if (acc === '')
        return `M${x.toFixed(1)},${zeroY.toFixed(1)} L${x.toFixed(1)},${y.toFixed(1)}`;
      return acc + ` L${x.toFixed(1)},${y.toFixed(1)}`;
    }
    if (acc !== '' && i > 0 && projection[i - 1].projected < 0) {
      return acc + ` L${scaleX(i - 1).toFixed(1)},${zeroY.toFixed(1)} Z`;
    }
    return acc;
  }, '');

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      {/* Zero line */}
      <line
        x1={PAD.l}
        y1={zeroY}
        x2={W - PAD.r}
        y2={zeroY}
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={0.5}
      />

      {/* ROP dashed line */}
      {projection[0].ropLine > 0 && (
        <line
          x1={PAD.l}
          y1={ropY}
          x2={W - PAD.r}
          y2={ropY}
          stroke={C.yl}
          strokeWidth={0.8}
          strokeDasharray="4,2"
          opacity={0.6}
        />
      )}
      {/* SS dotted line */}
      {projection[0].ssLine > 0 && (
        <line
          x1={PAD.l}
          y1={ssY}
          x2={W - PAD.r}
          y2={ssY}
          stroke={C.rd}
          strokeWidth={0.8}
          strokeDasharray="2,2"
          opacity={0.4}
        />
      )}

      {/* Below-zero area */}
      {belowZeroPath && <path d={belowZeroPath} fill="rgba(239,68,68,0.15)" />}

      {/* Projected stock line */}
      <path d={projLine} fill="none" stroke={C.ac} strokeWidth={1.5} />

      {/* Data points */}
      {projection.map((p, i) => (
        <circle
          key={i}
          cx={scaleX(i)}
          cy={scaleY(p.projected)}
          r={2}
          fill={p.projected < 0 ? C.rd : p.projected < p.ssLine ? C.yl : C.ac}
        />
      ))}

      {/* X axis labels */}
      {projection.map((_, i) => (
        <text
          key={i}
          x={scaleX(i)}
          y={H - 2}
          textAnchor="middle"
          style={{ fontSize: 7, fill: C.t4, ...mono }}
        >
          {dnames[i] ?? ''}
        </text>
      ))}

      {/* Y axis min/max */}
      <text
        x={PAD.l - 4}
        y={PAD.t + 4}
        textAnchor="end"
        style={{ fontSize: 7, fill: C.t4, ...mono }}
      >
        {fmtQty(maxV)}
      </text>
      <text
        x={PAD.l - 4}
        y={PAD.t + chartH}
        textAnchor="end"
        style={{ fontSize: 7, fill: C.t4, ...mono }}
      >
        {fmtQty(minV)}
      </text>
    </svg>
  );
}

// ── KPI Card ───────────────────────────────────────────────────

function KCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub: string;
  color: string;
}) {
  return (
    <div className="supply__kcard" style={{ borderLeft: `3px solid ${color}` }}>
      <span
        style={{
          fontSize: 9,
          fontWeight: 500,
          color: C.t3,
          textTransform: 'uppercase',
          letterSpacing: '.04em',
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: 22, fontWeight: 700, color, ...mono, lineHeight: 1.1 }}>
        {value}
      </span>
      <span style={{ fontSize: 9, color: C.t3 }}>{sub}</span>
    </div>
  );
}

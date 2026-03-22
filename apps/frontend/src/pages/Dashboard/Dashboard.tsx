import React, { useCallback, useMemo } from 'react';
import type { DayLoad } from '@/domain/types/scheduling';
import { DAY_CAP } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { opsByDayFromWorkforce } from '@/utils/workforce';
import { EmptyState } from '../../components/Common/EmptyState';
import { HeatmapLegend } from '../../components/Common/HeatmapLegend';
import { SkeletonCard, SkeletonTable } from '../../components/Common/SkeletonLoader';
import { PulseStrip } from '../../components/PulseStrip/PulseStrip';
import { useScheduleData } from '../../hooks/useScheduleData';
import { useUIStore } from '../../stores/useUIStore';
import { gridDensityVars, showDetailedCells } from '../../utils/gridDensity';
import { utilColor } from '../../utils/utilColor';
import { DashboardBottomRow } from './DashboardBottomRow';
import './Dashboard.css';

export function Dashboard() {
  const { engine, cap, metrics, loading, error } = useScheduleData();
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const panelOpen = useUIStore((s) => s.contextPanelOpen);

  // Working day indices — filter out weekends (Sáb/Dom) from display
  const wdi = useMemo(() => {
    if (!engine) return [] as number[];
    return engine.workdays.map((w, i) => (w ? i : -1)).filter((i): i is number => i >= 0);
  }, [engine]);

  const handleCellClick = useCallback(
    (machineId: string, dayIdx: number) => {
      if (!engine) return;
      openContextPanel({ type: 'machine', id: machineId });
      setFocus({ machine: machineId, day: engine.dates[dayIdx], dayIdx });
    },
    [engine, openContextPanel, setFocus],
  );

  const opsByDay = useMemo(() => {
    if (!engine || !metrics) return [];
    return opsByDayFromWorkforce(metrics.workforceDemand, engine.nDays);
  }, [engine, metrics]);

  const backlogOps = useMemo(() => {
    if (!engine) return [];
    return engine.ops
      .filter((o) => o.atr > 0)
      .sort((a, b) => b.atr - a.atr)
      .slice(0, 10);
  }, [engine]);

  if (loading)
    return (
      <div className="dash" data-testid="dashboard-page">
        <div className="dash__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Painel de Produção
          </h1>
          <p className="page-desc">
            Visão geral do plano: KPIs, cargas por máquina, operadores e atrasos.
          </p>
        </div>
        <SkeletonCard lines={2} showIcon={false} />
        <SkeletonTable rows={6} cols={8} />
      </div>
    );
  if (error || !engine || !metrics)
    return (
      <div className="dash" data-testid="dashboard-page">
        <div className="dash__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Painel de Produção
          </h1>
          <p className="page-desc">
            Visão geral do plano: KPIs, cargas por máquina, operadores e atrasos.
          </p>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados de planeamento"
          description={
            error ||
            'O scheduling engine não tem dados carregados. Importe um ficheiro ISOP na página Planning para gerar o escalonamento.'
          }
        />
      </div>
    );

  return (
    <div className={`dash${panelOpen ? ' dash--panel-open' : ''}`} data-testid="dashboard-page">
      <div className="dash__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Painel de Produção
          </h1>
          <p className="page-desc">
            Visão geral do plano a {wdi.length} dias úteis: KPIs, cargas por máquina, operadores e
            atrasos.
          </p>
        </div>
        <span style={{ fontSize: 12, color: C.t3, fontFamily: "'JetBrains Mono',monospace" }}>
          {engine.dates[0]} — {engine.dates[engine.dates.length - 1]} · {engine.ops.length}{' '}
          operações · {engine.machines.length} máquinas
        </span>
      </div>

      {/* Deadline feasibility banner */}
      {(metrics.deadlineFeasible === false || metrics.otdDelivery < 100) && (
        <div
          className="dash__deadline-banner"
          style={{
            padding: '8px 16px',
            borderRadius: 6,
            marginBottom: 12,
            background: C.rdS,
            border: `1px solid ${C.rdM}`,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 12, fontWeight: 600, color: C.rd }}>
            {metrics.lostPcs > 0
              ? `Deadline comprometida — ${metrics.tardinessDays.toFixed(1)} dias de atraso acumulado`
              : `OTD-D ${metrics.otdDelivery.toFixed(1)}% — entregas em risco`}
          </span>
          {metrics.overflows > 0 && (
            <span style={{ fontSize: 12, color: C.yl, marginLeft: 'auto' }}>
              {metrics.overflows} overflow{metrics.overflows > 1 ? 's' : ''}
            </span>
          )}
        </div>
      )}

      {/* Zona A — Pulse Strip */}
      <PulseStrip />

      {/* Zona B — Canvas: Heatmap + ExceptionFeed */}
      <div className="dash__canvas">
        <div className="dash__heatmap-card">
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 6 }}>
            Mapa de Cargas — Máquina × Dia
          </div>
          <HeatmapLegend />
          <div
            className="dash__heatmap"
            style={
              {
                gridTemplateColumns: `72px repeat(${wdi.length}, 1fr)`,
                '--n-days': wdi.length,
                ...gridDensityVars(wdi.length),
              } as React.CSSProperties
            }
          >
            <div className="dash__hm-corner" />
            {wdi.map((i, pos) => {
              const isWeekBorder = pos > 0 && engine.dnames[i]?.toLowerCase() === 'seg';
              return (
                <div
                  key={i}
                  className={`dash__hm-header${isWeekBorder ? ' dash__hm-header--week-start' : ''}`}
                >
                  {engine.dnames[i] ?? ''}
                  <br />
                  <span style={{ color: C.t3 }}>
                    {wdi.length > 30 ? engine.dates[i]?.slice(0, 2) : (engine.dates[i] ?? '')}
                  </span>
                </div>
              );
            })}
            {engine.machines.map((m) => {
              const mc = cap[m.id] || [];
              const detailed = showDetailedCells(wdi.length);
              return (
                <React.Fragment key={m.id}>
                  <div
                    className="dash__hm-label dash__hm-label--clickable"
                    onClick={() => {
                      openContextPanel({ type: 'machine', id: m.id });
                      setFocus({ machine: m.id });
                    }}
                    data-testid={`hm-label-${m.id}`}
                  >
                    <span
                      style={{
                        fontFamily: "'JetBrains Mono',monospace",
                        fontSize: 12,
                        fontWeight: 600,
                        color: C.t1,
                      }}
                    >
                      {m.id}
                    </span>
                    <span style={{ fontSize: 12, color: C.t3 }}>{m.area}</span>
                  </div>
                  {wdi.map((i, pos) => {
                    const d: DayLoad = mc[i] || { prod: 0, setup: 0, ops: 0, pcs: 0, blk: 0 };
                    const total = d.prod + d.setup;
                    const u = total / DAY_CAP;
                    const isWeekBorder = pos > 0 && engine.dnames[i]?.toLowerCase() === 'seg';
                    return (
                      <div
                        key={i}
                        className={`dash__hm-cell dash__hm-cell--clickable${isWeekBorder ? ' dash__hm-cell--week-start' : ''}`}
                        style={{
                          background: utilColor(u),
                          ...(d.blk > 0 ? { borderLeft: '2px solid var(--semantic-red)' } : {}),
                        }}
                        title={`${m.id} ${engine.dnames[i]} ${engine.dates[i]}: ${Math.round(total)}min (${(u * 100).toFixed(0)}%) — ${d.pcs} pcs, ${d.ops} ops${d.blk > 0 ? `, ${d.blk} bloqueada(s)` : ''}`}
                        onClick={() => handleCellClick(m.id, i)}
                        data-testid={`hm-cell-${m.id}-${i}`}
                      >
                        <span className="dash__hm-val">{(u * 100).toFixed(0)}%</span>
                        {detailed && d.pcs > 0 && <span className="dash__hm-sub">{d.pcs}</span>}
                      </div>
                    );
                  })}
                </React.Fragment>
              );
            })}
          </div>
        </div>
      </div>

      {/* Bottom row: Operators + Backlogs + Setup summary */}
      <DashboardBottomRow
        wdi={wdi}
        opsByDay={opsByDay}
        backlogOps={backlogOps}
        engine={engine}
        metrics={metrics}
      />
    </div>
  );
}

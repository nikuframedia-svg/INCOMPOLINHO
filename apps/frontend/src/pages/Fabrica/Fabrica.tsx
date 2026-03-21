import React, { useCallback, useMemo } from 'react';
import { Collapsible } from '../../components/Common/Collapsible';
import { EmptyState } from '../../components/Common/EmptyState';
import { HeatmapLegend } from '../../components/Common/HeatmapLegend';
import { SkeletonCard, SkeletonTable } from '../../components/Common/SkeletonLoader';
import { StatusBanner } from '../../components/Common/StatusBanner';
import { Term } from '../../components/Common/Tooltip';
import { useScheduleData } from '../../hooks/useScheduleData';
import type { DayLoad } from '../../lib/engine';
import { C, DAY_CAP, opsByDayFromWorkforce } from '../../lib/engine';
import { useUIStore } from '../../stores/useUIStore';
import { gridDensityVars, showDetailedCells } from '../../utils/gridDensity';
import { utilColor } from '../../utils/utilColor';
import { FabricaMachineCards } from './FabricaMachineCards';
import './Fabrica.css';

export function Fabrica() {
  const { engine, cap, metrics, loading, error } = useScheduleData();
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);
  const focus = useUIStore((s) => s.focus);
  const panelOpen = useUIStore((s) => s.contextPanelOpen);

  // Working day indices — filter out weekends (Sáb/Dom) from display
  const wdi = useMemo(() => {
    if (!engine) return [] as number[];
    return engine.workdays.map((w, i) => (w ? i : -1)).filter((i): i is number => i >= 0);
  }, [engine]);

  const handleMachineClick = useCallback(
    (machineId: string) => {
      openContextPanel({ type: 'machine', id: machineId });
      setFocus({ machine: machineId });
    },
    [openContextPanel, setFocus],
  );

  const handleCellClick = useCallback(
    (machineId: string, dayIdx: number) => {
      if (!engine) return;
      openContextPanel({ type: 'machine', id: machineId });
      setFocus({ machine: machineId, day: engine.dates[dayIdx], dayIdx });
    },
    [engine, openContextPanel, setFocus],
  );

  const machineStats = useMemo(() => {
    if (!engine || !cap) return [];
    return engine.machines.map((m) => {
      const mc = cap[m.id] || [];
      const totalPcs = mc.reduce((s, d) => s + d.pcs, 0);
      const totalOps = mc.reduce((s, d) => s + d.ops, 0);
      const totalSetupMin = mc.reduce((s, d) => s + d.setup, 0);
      const setupCount = mc.reduce((s, d) => s + (d.setup > 0 ? 1 : 0), 0);
      const totalBlk = mc.reduce((s, d) => s + d.blk, 0);
      // Only compute utils for working days (no weekends)
      const utils = wdi.map((i) => {
        const d = mc[i];
        return d ? (d.prod + d.setup) / DAY_CAP : 0;
      });
      const setupUtils = wdi.map((i) => {
        const d = mc[i];
        return d ? d.setup / DAY_CAP : 0;
      });
      const avgUtil = utils.length > 0 ? utils.reduce((a, v) => a + v, 0) / utils.length : 0;
      const toolCount = engine.tools.filter((t) => t.m === m.id).length;
      return {
        ...m,
        totalPcs,
        totalOps,
        totalSetupMin,
        setupCount,
        totalBlk,
        utils,
        setupUtils,
        avgUtil,
        toolCount,
      };
    });
  }, [engine, cap, wdi]);

  const opsByDay = useMemo(() => {
    if (!engine || !metrics) return [];
    return opsByDayFromWorkforce(metrics.workforceDemand, engine.nDays);
  }, [engine, metrics]);

  // Factory totals per working day
  const dailyTotals = useMemo(() => {
    if (!engine || !cap) return [];
    return wdi.map((di) => {
      let total = 0;
      engine.machines.forEach((m) => {
        const dc = cap[m.id]?.[di];
        if (dc) total += dc.prod + dc.setup;
      });
      return total;
    });
  }, [engine, cap, wdi]);

  if (loading)
    return (
      <div className="fab" data-testid="fabrica-page">
        <div className="fab__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Fábrica Nikufra</h1>
          <p className="page-desc">
            Estado das 6 máquinas Nikufra: capacidade, utilização e operadores por dia.
          </p>
        </div>
        <div className="fab__machines">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} lines={3} />
          ))}
        </div>
        <SkeletonTable rows={6} cols={8} />
      </div>
    );
  if (error || !engine || !metrics)
    return (
      <div className="fab" data-testid="fabrica-page">
        <div className="fab__header">
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Fábrica Nikufra</h1>
          <p className="page-desc">
            Estado das 6 máquinas Nikufra: capacidade, utilização e operadores por dia.
          </p>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados da fábrica"
          description={
            error ||
            'O scheduling engine não tem dados carregados. Importe um ficheiro ISOP na página Planning para gerar o escalonamento.'
          }
        />
      </div>
    );

  const factoryCap = engine.machines.length * DAY_CAP;

  return (
    <div className={`fab${panelOpen ? ' fab--panel-open' : ''}`} data-testid="fabrica-page">
      <div className="fab__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>Fábrica Nikufra</h1>
          <p className="page-desc">
            Estado das 6 máquinas Nikufra: capacidade, utilização e operadores por dia.
          </p>
        </div>
        <span style={{ fontSize: 12, color: C.t3 }}>
          {engine.machines.length} máquinas · 1º Turno (07:00–15:30) 2º Turno (15:30–24:00) · Cap.{' '}
          {factoryCap} min/dia
        </span>
      </div>

      {/* Status Banner */}
      {(() => {
        const overloaded = machineStats.filter((m) => m.avgUtil > 1.0);
        const highUtil = machineStats.filter((m) => m.avgUtil > 0.85 && m.avgUtil <= 1.0);
        if (overloaded.length > 0) {
          return (
            <StatusBanner
              variant="critical"
              message={`Risco — ${overloaded.map((m) => m.id).join(', ')} acima de 100% de capacidade.`}
              details={
                highUtil.length > 0
                  ? `${highUtil.map((m) => m.id).join(', ')} também acima de 85%.`
                  : undefined
              }
            />
          );
        }
        if (highUtil.length > 0) {
          return (
            <StatusBanner
              variant="warning"
              message={`Atenção — ${highUtil.map((m) => m.id).join(', ')} acima de 85% utilização.`}
            />
          );
        }
        return <StatusBanner variant="ok" message="Todas as máquinas dentro da capacidade." />;
      })()}

      {/* Section 1: Machine Cards */}
      <FabricaMachineCards
        machineStats={machineStats}
        focusMachine={focus.machine ?? undefined}
        onMachineClick={handleMachineClick}
      />

      {/* Section 2: Full Load Heatmap */}
      <div className="fab__section-card">
        <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
          Mapa de Cargas
        </div>
        <HeatmapLegend />
        <div
          className="fab__heatmap-full"
          style={
            {
              gridTemplateColumns: `72px repeat(${wdi.length}, 1fr)`,
              '--n-days': wdi.length,
              ...gridDensityVars(wdi.length),
            } as React.CSSProperties
          }
        >
          <div className="fab__hf-corner" />
          {wdi.map((i, pos) => {
            const isWeekBorder = pos > 0 && engine.dnames[i]?.toLowerCase() === 'seg';
            return (
              <div
                key={i}
                className={`fab__hf-header${isWeekBorder ? ' fab__hf-header--week-start' : ''}`}
              >
                <span style={{ fontWeight: 600 }}>{engine.dnames[i]}</span>
                <span style={{ color: C.t3 }}>
                  {wdi.length > 30 ? engine.dates[i]?.slice(0, 2) : engine.dates[i]}
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
                  className="fab__hf-label fab__hf-label--clickable"
                  onClick={() => handleMachineClick(m.id)}
                  data-testid={`fab-hm-label-${m.id}`}
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
                      className={`fab__hf-cell fab__hf-cell--clickable${isWeekBorder ? ' fab__hf-cell--week-start' : ''}`}
                      style={{
                        background: utilColor(u),
                        ...(d.blk > 0 ? { borderLeft: '2px solid var(--semantic-red)' } : {}),
                      }}
                      onClick={() => handleCellClick(m.id, i)}
                      title={`${m.id} ${engine.dnames[i]} ${engine.dates[i]}: ${Math.round(total)}min (${(u * 100).toFixed(0)}%) — ${d.pcs} pcs${d.blk > 0 ? `, ${d.blk} bloqueada(s)` : ''}`}
                      data-testid={`fab-hm-cell-${m.id}-${i}`}
                    >
                      <span className="fab__hf-val">
                        {detailed ? Math.round(total) : `${(u * 100).toFixed(0)}%`}
                      </span>
                      {detailed && (
                        <span className="fab__hf-sub">
                          {(u * 100).toFixed(0)}% · {d.pcs} pcs
                        </span>
                      )}
                      {detailed && d.setup > 0 && (
                        <span style={{ fontSize: 7, color: C.pp }}>{Math.round(d.setup)}m</span>
                      )}
                    </div>
                  );
                })}
              </React.Fragment>
            );
          })}
          {/* Total row */}
          <div className="fab__hf-label" style={{ borderTop: `1px solid ${C.bd}` }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: C.t2 }}>TOTAL</span>
          </div>
          {dailyTotals.map((t, idx) => (
            <div key={idx} className="fab__hf-cell" style={{ borderTop: `1px solid ${C.bd}` }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{Math.round(t)}</span>
              <span style={{ fontSize: 12, color: C.t3 }}>
                {((t / factoryCap) * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Section 3: Operator Demand */}
      <div className="fab__section-card">
        <Collapsible title="Operadores por Dia" defaultOpen={true}>
          <table className="fab__op-table">
            <thead>
              <tr>
                <th>Dia</th>
                <th>Data</th>
                <th style={{ textAlign: 'right' }}>
                  <Term code="PG1" />
                </th>
                <th style={{ textAlign: 'right' }}>
                  Cap <Term code="PG1" />
                </th>
                <th style={{ textAlign: 'right' }}>
                  <Term code="PG2" />
                </th>
                <th style={{ textAlign: 'right' }}>
                  Cap <Term code="PG2" />
                </th>
                <th style={{ textAlign: 'right' }}>Total</th>
                <th style={{ textAlign: 'right' }}>Cap</th>
                <th style={{ textAlign: 'center' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {wdi.map((di) => {
                const od = opsByDay[di];
                if (!od) return null;
                const cp1 = engine.mo?.PG1[di] ?? 4;
                const cp2 = engine.mo?.PG2[di] ?? 4;
                const totalCap = cp1 + cp2;
                const over = od.total > totalCap;
                return (
                  <tr key={di} style={{ color: over ? C.rd : undefined }}>
                    <td style={{ fontWeight: 600 }}>{engine.dnames[di]}</td>
                    <td>{engine.dates[di]}</td>
                    <td style={{ textAlign: 'right' }}>{od.pg1}</td>
                    <td style={{ textAlign: 'right', color: C.t3 }}>{cp1.toFixed(1)}</td>
                    <td style={{ textAlign: 'right' }}>{od.pg2}</td>
                    <td style={{ textAlign: 'right', color: C.t3 }}>{cp2.toFixed(1)}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>{od.total}</td>
                    <td style={{ textAlign: 'right', color: C.t3 }}>{totalCap.toFixed(1)}</td>
                    <td style={{ textAlign: 'center' }}>
                      {over ? (
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            color: C.rd,
                            background: C.rdS,
                            padding: '1px 4px',
                            borderRadius: 3,
                          }}
                        >
                          OVER
                        </span>
                      ) : (
                        <span style={{ fontSize: 12, color: C.ac }}>OK</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Collapsible>
      </div>
    </div>
  );
}

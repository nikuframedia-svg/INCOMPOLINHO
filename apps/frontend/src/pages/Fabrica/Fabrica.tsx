import { useCallback, useMemo } from 'react';
import { DAY_CAP } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { opsByDayFromWorkforce } from '@/utils/workforce';
import { EmptyState } from '../../components/Common/EmptyState';
import { SkeletonCard, SkeletonTable } from '../../components/Common/SkeletonLoader';
import { StatusBanner } from '../../components/Common/StatusBanner';
import { useScheduleData } from '../../hooks/useScheduleData';
import { useUIStore } from '../../stores/useUIStore';
import { FabricaLoadHeatmap } from './FabricaLoadHeatmap';
import { FabricaMachineCards } from './FabricaMachineCards';
import { FabricaOperatorTable } from './FabricaOperatorTable';
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
      <FabricaLoadHeatmap
        machines={engine.machines}
        cap={cap}
        wdi={wdi}
        dnames={engine.dnames}
        dates={engine.dates}
        dailyTotals={dailyTotals}
        factoryCap={factoryCap}
        onMachineClick={handleMachineClick}
        onCellClick={handleCellClick}
      />

      {/* Section 3: Operator Demand */}
      <FabricaOperatorTable
        wdi={wdi}
        dnames={engine.dnames}
        dates={engine.dates}
        opsByDay={opsByDay}
        mo={engine.mo}
      />
    </div>
  );
}

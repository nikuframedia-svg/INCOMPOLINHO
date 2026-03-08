/**
 * ConsolePage — Centro de Comando Diario
 *
 * Main landing page. Select a day from the planning horizon and see
 * KPIs, machines, operations, operators, alerts, decisions, D+1, transparency.
 */

import { useCallback, useMemo } from 'react';
import { EmptyState } from '@/components/Common/EmptyState';
import { SkeletonCard, SkeletonTable } from '@/components/Common/SkeletonLoader';
import { StatusBanner } from '@/components/Common/StatusBanner';
import { useDayData } from '@/hooks/useDayData';
import { useScheduleData } from '@/hooks/useScheduleData';
import type { Block } from '@/lib/engine';
import { C, DAY_CAP } from '@/lib/engine';
import { useUIStore } from '@/stores/useUIStore';
import { AlertsPanel } from '../components/AlertsPanel';
import { D1Preparation } from '../components/D1Preparation';
import { DayOrders } from '../components/DayOrders';
import { DaySelector } from '../components/DaySelector';
import { KPIGrid } from '../components/KPIGrid';
import { MachineTimeline } from '../components/MachineTimeline';
import { OperatorPanel } from '../components/OperatorPanel';
import { SystemDecisions } from '../components/SystemDecisions';
import { TransparencyPanel } from '../components/TransparencyPanel';
import './ConsolePage.css';

export function ConsolePage() {
  const { dayData, loading, error } = useDayData();
  const { engine, cap, blocks: allBlocks } = useScheduleData();
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  const setSelectedDayIdx = useUIStore((s) => s.actions.setSelectedDayIdx);
  const openContextPanel = useUIStore((s) => s.actions.openContextPanel);
  const setFocus = useUIStore((s) => s.actions.setFocus);

  // Daily factory utilization for all days (DaySelector dots)
  const dailyUtils = useMemo(() => {
    if (!engine || !cap) return [];
    return engine.dates.map((_, i) => {
      let totalUsed = 0;
      let totalCap = 0;
      engine.machines.forEach((m) => {
        const d = cap[m.id]?.[i];
        if (d) {
          totalUsed += d.prod + d.setup;
          totalCap += DAY_CAP;
        }
      });
      return totalCap > 0 ? totalUsed / totalCap : 0;
    });
  }, [engine, cap]);

  // Feasibility score for this day (ok blocks / total blocks)
  const dayFeasibilityScore = useMemo(() => {
    if (!dayData || dayData.blocks.length === 0) return 1;
    const okCount = dayData.okBlocks.length;
    const total = dayData.blocks.length;
    return total > 0 ? okCount / total : 1;
  }, [dayData]);

  // StatusBanner derivation
  const bannerVariant = useMemo((): 'ok' | 'warning' | 'critical' => {
    if (!dayData) return 'ok';
    if (dayData.infeasibilities.length > 0) return 'critical';
    if (dayData.violations.length > 0 || dayData.overflowBlocks.length > 0) return 'warning';
    return 'ok';
  }, [dayData]);

  const bannerMessage = useMemo(() => {
    if (!dayData) return '';
    const alertCount = dayData.violations.length + dayData.infeasibilities.length;
    if (alertCount === 0) {
      return `Dia ${dayData.dayName} ${dayData.date} — ${dayData.okBlocks.length} operacoes escalonadas sem problemas.`;
    }
    return `Dia ${dayData.dayName} ${dayData.date} — ${alertCount} alerta(s): ${dayData.infeasibilities.length} infeasivel(eis), ${dayData.violations.length} violacao(oes).`;
  }, [dayData]);

  // Interactions
  const handleDaySelect = useCallback(
    (idx: number) => {
      if (!engine) return;
      setSelectedDayIdx(idx);
      setFocus({ dayIdx: idx, day: engine.dates[idx] });
    },
    [engine, setSelectedDayIdx, setFocus],
  );

  const handleBlockClick = useCallback(
    (block: Block) => {
      openContextPanel({ type: 'tool', id: block.toolId });
      setFocus({ machine: block.machineId, toolId: block.toolId, dayIdx: block.dayIdx });
    },
    [openContextPanel, setFocus],
  );

  const handleMachineClick = useCallback(
    (machineId: string) => {
      openContextPanel({ type: 'machine', id: machineId });
      setFocus({ machine: machineId });
    },
    [openContextPanel, setFocus],
  );

  // Loading state
  if (loading) {
    return (
      <div className="cmd" data-testid="comando-diario-page">
        <div className="cmd__header">
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
              Centro de Comando Diario
            </h1>
            <p className="page-desc">
              Visao completa por dia: maquinas, operacoes, operadores, alertas e decisoes.
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          {Array.from({ length: 12 }).map((_, i) => (
            <SkeletonCard key={i} lines={1} />
          ))}
        </div>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(6, 1fr)',
            gap: 8,
            marginBottom: 16,
          }}
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonCard key={i} lines={2} />
          ))}
        </div>
        <SkeletonTable rows={6} cols={5} />
      </div>
    );
  }

  // Error / no data
  if (error || !engine || !dayData) {
    return (
      <div className="cmd" data-testid="comando-diario-page">
        <div className="cmd__header">
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
              Centro de Comando Diario
            </h1>
            <p className="page-desc">
              Visao completa por dia: maquinas, operacoes, operadores, alertas e decisoes.
            </p>
          </div>
        </div>
        <EmptyState
          icon="error"
          title="Sem dados de scheduling"
          description={
            error ?? 'O engine nao tem dados carregados. Carregue um ISOP ou verifique a fixture.'
          }
        />
      </div>
    );
  }

  return (
    <div className={`cmd${panelOpen ? ' cmd--panel-open' : ''}`} data-testid="comando-diario-page">
      {/* Header */}
      <div className="cmd__header">
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>
            Centro de Comando Diario
          </h1>
          <p className="page-desc">
            Visao completa por dia: maquinas, operacoes, operadores, alertas e decisoes.
          </p>
        </div>
        <span style={{ fontSize: 11, color: C.t3, fontFamily: 'var(--font-mono)' }}>
          {dayData.nDays} dias · {allBlocks.length} blocos · {engine.machines.length} maquinas
        </span>
      </div>

      {/* Top sections — full width */}
      <div className="cmd__top">
        <DaySelector
          dates={dayData.allDates}
          dayNames={engine.dnames}
          workdays={dayData.workdays}
          selectedIdx={dayData.dayIdx}
          onSelect={handleDaySelect}
          dailyUtils={dailyUtils}
        />

        <StatusBanner variant={bannerVariant} message={bannerMessage} />

        <KPIGrid
          totalPcs={dayData.totalPcs}
          totalOps={dayData.totalOps}
          factoryUtil={dayData.factoryUtil}
          totalSetupMin={dayData.totalSetupMin}
          violationCount={dayData.violations.length}
          infeasibleCount={dayData.infeasibilities.length}
          overflowCount={dayData.overflowBlocks.length}
          operatorsByArea={dayData.operatorsByArea}
          operatorCapacity={dayData.operatorCapacity}
        />
      </div>

      {/* Two-column body */}
      <div className="cmd__body">
        {/* Primary column (3fr) */}
        <div className="cmd__primary">
          <MachineTimeline
            engine={dayData.engine}
            blocks={dayData.blocks}
            machineLoads={dayData.machineLoads}
            date={dayData.date}
            onBlockClick={handleBlockClick}
            onMachineClick={handleMachineClick}
          />

          <DayOrders blocks={dayData.blocks} onBlockClick={handleBlockClick} />

          <TransparencyPanel
            orderJustifications={dayData.orderJustifications}
            failureJustifications={dayData.failureJustifications}
            engine={dayData.engine}
          />
        </div>

        {/* Secondary column (2fr) */}
        <div className="cmd__secondary">
          <OperatorPanel
            workforce={dayData.workforce}
            operatorsByArea={dayData.operatorsByArea}
            operatorCapacity={dayData.operatorCapacity}
            dayName={dayData.dayName}
          />

          <AlertsPanel
            violations={dayData.violations}
            infeasibilities={dayData.infeasibilities}
            feasibilityScore={dayFeasibilityScore}
          />

          <SystemDecisions decisions={dayData.systemDecisions} />

          <D1Preparation
            forecast={dayData.d1Forecast}
            blocks={allBlocks}
            workforceConfig={engine.workforceConfig}
            workdays={engine.workdays}
          />
        </div>
      </div>
    </div>
  );
}

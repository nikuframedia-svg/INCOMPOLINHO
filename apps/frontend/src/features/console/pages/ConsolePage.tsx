/**
 * ConsolePage — Centro de Comando Diário
 *
 * Main landing page. Select a day from the planning horizon and see
 * KPIs, machines, operations, operators, alerts, decisions, D+1, transparency.
 */

import { Link } from 'react-router-dom';
import { EmptyState } from '@/components/Common/EmptyState';
import { FeatureErrorBoundary } from '@/components/Common/FeatureErrorBoundary';
import { SkeletonCard, SkeletonTable } from '@/components/Common/SkeletonLoader';
import { StatusBanner } from '@/components/Common/StatusBanner';
import { ActiveDecisions } from '../components/ActiveDecisions';
import { AlertsFeed } from '../components/AlertsFeed';
import { AlertsPanel } from '../components/AlertsPanel';
import { AndonDrawer } from '../components/AndonDrawer';
import { D1Preparation } from '../components/D1Preparation';
import { DayOrders } from '../components/DayOrders';
import { DaySelector } from '../components/DaySelector';
import { DeliveryRiskPanel } from '../components/DeliveryRiskPanel';
import { KPIGrid } from '../components/KPIGrid';
import { MachineStatusGrid } from '../components/MachineStatusGrid';
import { MachineTimeline } from '../components/MachineTimeline';
import { OperatorPanel } from '../components/OperatorPanel';
import { TransparencyPanel } from '../components/TransparencyPanel';
import { WorkforceNeeds } from '../components/WorkforceNeeds';
import { useConsolePageData } from '../hooks/useConsolePageData';
import './ConsolePage.css';
import { C } from '@/theme/color-bridge';

const PAGE_TITLE = 'Centro de Comando Diário';
const PAGE_DESC = 'Visão completa por dia: máquinas, operações, operadores, alertas e decisões.';

function ConsolePageHeader() {
  return (
    <div className="cmd__header">
      <div>
        <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>{PAGE_TITLE}</h1>
        <p className="page-desc">{PAGE_DESC}</p>
      </div>
    </div>
  );
}

function ConsoleLoadingSkeleton() {
  return (
    <div className="cmd" data-testid="comando-diario-page">
      <ConsolePageHeader />
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

function ConsoleEmptyState({ errorMessage }: { errorMessage: string | null }) {
  return (
    <div className="cmd" data-testid="comando-diario-page">
      <ConsolePageHeader />
      <EmptyState
        icon="error"
        title="Ainda nao ha dados carregados"
        description={
          errorMessage ??
          'Para comecar, carrega o ficheiro ISOP do ERP. O PP1 analisa os dados e cria o plano automaticamente.'
        }
      />
    </div>
  );
}

export function ConsolePage() {
  const {
    dayData,
    loading,
    error,
    engine,
    allBlocks,
    lateDeliveries,
    panelOpen,
    downtimes,
    dailyUtils,
    sparklines,
    otd,
    clientMap,
    dayFeasibilityScore,
    bannerVariant,
    bannerMessage,
    handleDaySelect,
    handleBlockClick,
    handleMachineClick,
    handleNavigateToBlock,
  } = useConsolePageData();

  if (loading) {
    return <ConsoleLoadingSkeleton />;
  }

  if (error || !engine || !dayData) {
    return <ConsoleEmptyState errorMessage={error} />;
  }

  return (
    <FeatureErrorBoundary module="Console">
      <div
        className={`cmd${panelOpen ? ' cmd--panel-open' : ''}`}
        data-testid="comando-diario-page"
      >
        {/* Header */}
        <div className="cmd__header">
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 600, color: C.t1, margin: 0 }}>{PAGE_TITLE}</h1>
            <p className="page-desc">{PAGE_DESC}</p>
          </div>
          <span style={{ fontSize: 12, color: C.t3, fontFamily: 'var(--font-mono)' }}>
            {dayData.nDays} dias · {allBlocks.length} blocos · {engine.machines.length} máquinas
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

          <Link
            to={`/console/day/${dayData.date.split('/').join('_')}`}
            style={{ fontSize: 12, color: C.ac, textDecoration: 'none', alignSelf: 'flex-end' }}
          >
            Ver dia completo →
          </Link>

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
            sparklines={sparklines}
            otd={otd}
            activeMachines={engine.machines.length - Object.keys(downtimes).length}
            totalMachines={engine.machines.length}
            setupCount={dayData.blocks.filter((b) => b.setupS != null).length}
            lateDeliveriesCount={lateDeliveries?.unresolvedCount ?? 0}
          />
        </div>

        {/* Machine status cards */}
        <MachineStatusGrid
          engine={dayData.engine}
          blocks={dayData.blocks}
          machineLoads={dayData.machineLoads}
          clientMap={clientMap}
        />

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

            <AlertsFeed />

            {lateDeliveries && lateDeliveries.entries.length > 0 && (
              <DeliveryRiskPanel
                lateDeliveries={lateDeliveries}
                onNavigateToBlock={handleNavigateToBlock}
              />
            )}

            <AlertsPanel
              violations={dayData.violations}
              infeasibilities={dayData.infeasibilities}
              feasibilityScore={dayFeasibilityScore}
            />

            <ActiveDecisions
              decisions={dayData.systemDecisions}
              onNavigateToBlock={handleNavigateToBlock}
            />

            <WorkforceNeeds
              forecast={dayData.d1Forecast}
              operatorCapacity={dayData.operatorCapacity}
            />

            <D1Preparation forecast={dayData.d1Forecast} />
          </div>
        </div>

        <AndonDrawer />
      </div>
    </FeatureErrorBoundary>
  );
}

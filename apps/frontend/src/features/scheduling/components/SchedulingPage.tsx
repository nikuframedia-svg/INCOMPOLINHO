import { List } from 'lucide-react';
import { useCallback, useState } from 'react';
import { FeatureErrorBoundary } from '../../../components/Common/FeatureErrorBoundary';
import { useClassifications } from '../../../hooks/useClassifications';
import { useScheduleData } from '../../../hooks/useScheduleData';
import { C } from '../../../lib/engine';
import { useDayProblems } from '../hooks/useDayProblems';
import { useScheduleEngine } from '../hooks/useScheduleEngine';
import { GanttView } from './GanttChart/GanttChart';
import { OperationsDrawer } from './GanttChart/OperationsDrawer';
import { ProblemBar } from './ProblemBar';
import { ReplanView } from './ReplanPanel';
import { SchedulingBanners } from './SchedulingBanners';
import { SchedulingHeader } from './SchedulingHeader';
import { WhatIfView } from './WhatIfPanel';

export function SchedulingPage({ initialView = 'plan' }: { initialView?: string }) {
  const eng = useScheduleEngine(initialView);
  const { metrics, lateDeliveries } = useScheduleData();
  const classifications = useClassifications();
  const [selDay, setSelDay] = useState(0);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const problems = useDayProblems(
    eng.validation ?? null,
    eng.blocks,
    selDay,
    eng.mSt,
    eng.engineData?.dnames ?? [],
    eng.engineData?.dates ?? [],
  );

  const handleDayChange = useCallback((d: number) => setSelDay(d), []);

  if (eng.loading)
    return (
      <div className="ne-shell ne-loading">
        <div className="ne-loading__spinner" />
        <div className="ne-loading__text">A carregar planning engine...</div>
      </div>
    );
  if (eng.error || !eng.engineData)
    return (
      <div className="ne-shell ne-error">
        <div className="ne-error__icon" style={{ color: C.rd }}>
          ERROR
        </div>
        <div className="ne-error__msg">
          {eng.error || 'Ainda nao ha dados carregados. Carrega o ficheiro ISOP para comecar.'}
        </div>
        <button className="ne-error__retry" onClick={eng.loadData}>
          Tentar novamente
        </button>
      </div>
    );

  const dayBlocks = eng.blocks.filter((b) => b.dayIdx === selDay && b.type !== 'blocked');
  const machineCount = new Set(dayBlocks.map((b) => b.machineId)).size;

  return (
    <FeatureErrorBoundary module="Scheduling">
      <div style={{ fontFamily: "'Plus Jakarta Sans','Inter',system-ui,sans-serif", color: C.t1 }}>
        <SchedulingHeader
          view={eng.view}
          setView={eng.setView}
          downC={eng.downC}
          movesCount={eng.moves.length}
          autoMovesCount={eng.autoMoves.length}
          blkOps={eng.blkOps}
          opsCount={eng.allOps.length}
          machineCount={eng.engineData.machines.length}
          validation={eng.validation}
          otd={metrics?.otdDelivery}
          lateDeliveriesCount={lateDeliveries?.unresolvedCount ?? 0}
        />
        <div style={{ padding: '16px 20px', maxWidth: 1320, margin: '0 auto' }}>
          <SchedulingBanners
            isopBanner={eng.isopBanner}
            setIsopBanner={eng.setIsopBanner}
            isScheduling={eng.isScheduling}
          />
          {(lateDeliveries?.unresolvedCount ?? 0) > 0 && (
            <div
              style={{
                padding: '6px 12px',
                borderRadius: 6,
                background: `${C.rd}12`,
                border: `1px solid ${C.rd}33`,
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 8,
                fontSize: 11,
                color: C.rd,
                fontWeight: 500,
              }}
            >
              {lateDeliveries!.unresolvedCount} entrega
              {lateDeliveries!.unresolvedCount > 1 ? 's' : ''} em atraso
              {' · '}
              {lateDeliveries!.totalShortfallPcs.toLocaleString()} pcs em falta
              {lateDeliveries!.worstTierAffected <= 2 && (
                <span style={{ fontWeight: 700 }}>
                  {' · '}Cliente Tier {lateDeliveries!.worstTierAffected} afectado
                </span>
              )}
            </div>
          )}
          {eng.view === 'plan' && (
            <>
              {/* Headline */}
              <div style={{ marginBottom: 12 }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 2px', color: C.t1 }}>
                  Plano de produção — {eng.engineData.dnames[selDay]} {eng.engineData.dates[selDay]}
                </h2>
                <p style={{ fontSize: 11, color: C.t3, margin: 0 }}>
                  {machineCount} prensas · {dayBlocks.length} lotes
                  {problems.length > 0 &&
                    ` · ${problems.length} problema${problems.length !== 1 ? 's' : ''}`}
                </p>
              </div>
              <ProblemBar problems={problems} />
              <GanttView
                blocks={eng.blocks}
                mSt={eng.mSt}
                cap={eng.cap}
                data={eng.engineData}
                applyMove={eng.applyMove}
                undoMove={eng.undoMove}
                validation={eng.validation}
                currentMetrics={eng.neMetrics}
                onDayChange={handleDayChange}
                blockClassifications={classifications.blockDefinitions}
              />
              {/* FAB — open operations drawer */}
              <button
                type="button"
                onClick={() => setDrawerOpen(true)}
                title="Lista de operações"
                style={{
                  position: 'fixed',
                  bottom: 24,
                  right: 24,
                  zIndex: 40,
                  width: 48,
                  height: 48,
                  borderRadius: '50%',
                  background: C.ac,
                  border: 'none',
                  color: C.bg,
                  cursor: 'pointer',
                  boxShadow: '0 4px 16px #00000040',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <List size={20} strokeWidth={2} />
              </button>
              <OperationsDrawer
                open={drawerOpen}
                onClose={() => setDrawerOpen(false)}
                blocks={eng.blocks}
                dayIdx={selDay}
                dates={eng.engineData.dates}
                dnames={eng.engineData.dnames}
                onSelectBlock={() => {}}
                selectedOpId={null}
              />
            </>
          )}
          {eng.view === 'replan' && (
            <ReplanView
              mSt={eng.mSt}
              tSt={eng.tSt}
              toggleM={eng.toggleM}
              toggleT={eng.toggleT}
              moves={eng.moves}
              applyMove={eng.applyMove}
              undoMove={eng.undoMove}
              blocks={eng.blocks}
              cap={eng.cap}
              data={eng.engineData}
              onApplyAndSave={() => eng.handleApplyAndSave()}
              isSaving={eng.isSaving}
              setResourceDown={eng.setResourceDown}
              clearResourceDown={eng.clearResourceDown}
              getResourceDownDays={eng.getResourceDownDays}
              replanTimelines={eng.replanTimelines}
              rushOrders={eng.rushOrders}
              setRushOrders={eng.setRushOrders}
              allOps={eng.allOps}
              neMetrics={eng.neMetrics}
              setAppliedReplan={eng.setAppliedReplan}
            />
          )}
          {eng.view === 'whatif' && (
            <WhatIfView
              data={eng.engineData}
              onApplyMoves={(mvs, sc) => eng.handleApplyAndSave(mvs, sc)}
              isSaving={eng.isSaving}
              setResourceDown={eng.setResourceDown}
              clearResourceDown={eng.clearResourceDown}
              getResourceDownDays={eng.getResourceDownDays}
              replanTimelines={eng.replanTimelines}
              blocks={eng.blocks}
              allOps={eng.allOps}
              neMetrics={eng.neMetrics}
            />
          )}
        </div>
      </div>
    </FeatureErrorBoundary>
  );
}

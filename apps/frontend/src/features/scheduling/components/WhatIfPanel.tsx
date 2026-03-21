import { useState } from 'react';
import { ChevronLeft } from 'lucide-react';
import type {
  Block,
  buildResourceTimelines,
  EngineData,
  EOp,
  MoveAction,
  OptResult,
} from '../../../lib/engine';
import { C } from '../../../lib/engine';
import { usePlanVersionStore } from '../../../stores/usePlanVersionStore';
import { useWhatIf } from '../hooks/useWhatIf';
import { Card } from './atoms';
import { OBJECTIVE_PROFILES } from './constants';
import { PlanComparePanel } from './PlanComparePanel';
import { ScenarioRadar } from './ScenarioRadar';
import { StressTestPanel } from './StressTestPanel';
import {
  ApplyPlanButton,
  QualityWarnings,
  ScenarioBuilder,
  ScenarioDetails,
  ScenarioResultCards,
  SimpleWhatIfView,
  VersionActionBar,
  VersionHistoryPanel,
} from './whatif';

export function WhatIfView({
  data,
  onApplyMoves,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  replanTimelines,
  blocks: baselineBlocks,
  allOps: baselineOps,
  neMetrics,
}: {
  data: EngineData;
  onApplyMoves?: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  replanTimelines: ReturnType<typeof buildResourceTimelines> | null;
  blocks?: Block[];
  allOps?: EOp[];
  neMetrics?: OptResult | null;
}) {
  const [advancedMode, setAdvancedMode] = useState(false);
  const { machines, tools, ops, focusIds, toolMap: TM } = data;
  const { state: wi, actions: wiActions } = useWhatIf(
    data,
    OBJECTIVE_PROFILES,
    getResourceDownDays,
    replanTimelines,
  );
  const {
    sc,
    N,
    dispatchRule,
    objProfile,
    res,
    run,
    prog,
    editingDown,
    wdi: wdiWI,
    wiDownStartDay,
    wiDownEndDay,
    sel,
    showHistory,
    showCompare,
    diffPair,
    focusT,
    areaCaps,
    qv: qvWI,
  } = wi;
  const {
    setSc,
    setN,
    setDispatchRule,
    setObjProfile,
    setEditingDown,
    setWiDownStartDay,
    setWiDownEndDay,
    setSel,
    setShowHistory,
    setShowCompare,
    setDiffPair,
    setRes,
    optimize,
  } = wiActions;
  const versions = usePlanVersionStore((s) => s.versions);
  const currentId = usePlanVersionStore((s) => s.currentId);

  const rankColor = (i: number) => (i === 0 ? C.ac : i === 1 ? C.bl : C.pp);
  const rankLabel = (i: number) =>
    i === 0 ? '#1 MELHOR' : i === 1 ? '#2' : i === 2 ? '#3' : `#${i + 1}`;

  // Simple mode: show simplified view + results (if any)
  if (!advancedMode) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <SimpleWhatIfView
          run={run}
          prog={prog}
          res={res}
          onOptimize={optimize}
          onSelectProfile={(_id: string) => {
            setObjProfile(_id);
            setRes(null);
          }}
          onSwitchAdvanced={() => setAdvancedMode(true)}
          setResourceDown={setResourceDown}
          setRes={setRes}
          focusIds={focusIds}
        />

        {/* Show results in simple mode too */}
        {res != null && (
          <>
            <ScenarioResultCards
              top3={res.top3}
              sel={sel}
              setSel={setSel}
              rankColor={rankColor}
              rankLabel={rankLabel}
            />

            <QualityWarnings qv={qvWI} />

            {onApplyMoves && res.top3[sel]?.moves.length > 0 && (
              <ApplyPlanButton
                onApplyMoves={onApplyMoves}
                isSaving={isSaving}
                moves={res.top3[sel].moves}
                machines={machines}
                focusT={focusT}
                getResourceDownDays={getResourceDownDays}
              />
            )}

            {res.top3[sel] && (
              <ScenarioDetails
                scenario={res.top3[sel]}
                sel={sel}
                rankColor={rankColor}
                rankLabel={rankLabel}
                ops={ops}
                tools={tools}
                data={data}
                getResourceDownDays={getResourceDownDays}
                moveable={res.moveable}
                top3={res.top3}
              />
            )}
          </>
        )}
      </div>
    );
  }

  // Advanced mode: full existing UI
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <button
        onClick={() => setAdvancedMode(false)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '8px 14px',
          borderRadius: 8,
          border: `1px solid ${C.bd}`,
          background: 'transparent',
          color: C.t2,
          fontSize: 12,
          cursor: 'pointer',
          fontFamily: 'inherit',
          width: 'fit-content',
        }}
      >
        <ChevronLeft size={14} />
        Modo Simples
      </button>

      <ScenarioBuilder
        data={data}
        sc={sc}
        setSc={setSc}
        N={N}
        setN={setN}
        dispatchRule={dispatchRule}
        setDispatchRule={setDispatchRule}
        objProfile={objProfile}
        setObjProfile={setObjProfile}
        objectiveProfiles={OBJECTIVE_PROFILES}
        editingDown={editingDown}
        setEditingDown={setEditingDown}
        wdi={wdiWI}
        wiDownStartDay={wiDownStartDay}
        setWiDownStartDay={setWiDownStartDay}
        wiDownEndDay={wiDownEndDay}
        setWiDownEndDay={setWiDownEndDay}
        getResourceDownDays={getResourceDownDays}
        setResourceDown={setResourceDown}
        clearResourceDown={clearResourceDown}
        setRes={setRes}
        focusT={focusT}
        run={run}
        prog={prog}
        optimize={optimize}
      />

      {!res && !run && (
        <Card style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 15, marginBottom: 6, color: C.ac }}>OPTIMIZE</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t2 }}>
            Otimização de Planeamento
          </div>
          <div
            style={{
              fontSize: 12,
              color: C.t4,
              marginTop: 4,
              maxWidth: 400,
              margin: '4px auto 0',
              lineHeight: 1.6,
            }}
          >
            Explora {N} configurações diferentes, redistribuindo operações entre prensas. Apresenta os 3 melhores planos com comparação lado a lado de OTD-D, setups e utilização.
          </div>
        </Card>
      )}

      {res && (
        <>
          <ScenarioResultCards
            top3={res.top3}
            sel={sel}
            setSel={setSel}
            rankColor={rankColor}
            rankLabel={rankLabel}
          />

          <QualityWarnings qv={qvWI} />

          {onApplyMoves && res.top3[sel]?.moves.length > 0 && (
            <ApplyPlanButton
              onApplyMoves={onApplyMoves}
              isSaving={isSaving}
              moves={res.top3[sel].moves}
              machines={machines}
              focusT={focusT}
              getResourceDownDays={getResourceDownDays}
            />
          )}

          <VersionActionBar
            scenario={res.top3[sel]}
            sc={sc}
            areaCaps={areaCaps}
            machines={machines}
            focusT={focusT}
            ops={ops}
            tools={tools}
            focusIds={focusIds}
            getResourceDownDays={getResourceDownDays}
            showHistory={showHistory}
            setShowHistory={setShowHistory}
            showCompare={showCompare}
            setShowCompare={setShowCompare}
            versions={versions}
            toolMap={TM}
          />

          {showHistory && (
            <VersionHistoryPanel
              versions={versions}
              currentId={currentId}
              diffPair={diffPair}
              setDiffPair={setDiffPair}
            />
          )}

          {showCompare && <PlanComparePanel data={data} />}

          {res.top3[sel] && (
            <ScenarioDetails
              scenario={res.top3[sel]}
              sel={sel}
              rankColor={rankColor}
              rankLabel={rankLabel}
              ops={ops}
              tools={tools}
              data={data}
              getResourceDownDays={getResourceDownDays}
              moveable={res.moveable}
              top3={res.top3}
            />
          )}
        </>
      )}

      {res && neMetrics && (
        <Card style={{ padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 8 }}>
            Radar — Baseline vs Cenario
          </div>
          <ScenarioRadar baseline={neMetrics} scenario={res.top3[sel] ?? null} />
        </Card>
      )}

      {baselineBlocks && baselineOps && (
        <StressTestPanel
          data={data}
          blocks={baselineBlocks}
          allOps={baselineOps}
          baselineMetrics={neMetrics ?? null}
        />
      )}
    </div>
  );
}

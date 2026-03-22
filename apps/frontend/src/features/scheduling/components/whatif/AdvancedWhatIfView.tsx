import { ChevronLeft } from 'lucide-react';
import type {
  Block,
  EngineData,
  EOp,
  MoveAction,
  ObjectiveProfile,
  OptResult,
} from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import type { PlanVersion } from '../../../../stores/usePlanVersionStore';
import type { WhatIfActions, WhatIfState } from '../../hooks/useWhatIf';
import { Card } from '../atoms';
import { PlanComparePanel } from '../PlanComparePanel';
import { ScenarioRadar } from '../ScenarioRadar';
import { StressTestPanel } from '../StressTestPanel';
import { ScenarioBuilder } from './ScenarioBuilder';
import { VersionActionBar, VersionHistoryPanel } from './VersionHistory';
import { WhatIfResultsSection } from './WhatIfResultsSection';

export type AdvancedWhatIfViewProps = {
  data: EngineData;
  wi: WhatIfState;
  wiActions: WhatIfActions;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
  onApplyMoves?: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  setResourceDown: (type: 'machine' | 'tool', id: string, days: number[]) => void;
  clearResourceDown: (type: 'machine' | 'tool', id: string) => void;
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  versions: PlanVersion[];
  currentId: string | null;
  neMetrics?: OptResult | null;
  baselineBlocks?: Block[];
  baselineOps?: EOp[];
  objectiveProfiles: ObjectiveProfile[];
  onSwitchSimple: () => void;
};

export function AdvancedWhatIfView({
  data,
  wi,
  wiActions,
  rankColor,
  rankLabel,
  onApplyMoves,
  isSaving,
  setResourceDown,
  clearResourceDown,
  getResourceDownDays,
  versions,
  currentId,
  neMetrics,
  baselineBlocks,
  baselineOps,
  objectiveProfiles,
  onSwitchSimple,
}: AdvancedWhatIfViewProps) {
  const { machines, tools, ops, focusIds, toolMap: TM } = data;
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <button
        onClick={onSwitchSimple}
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
        objectiveProfiles={objectiveProfiles}
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
            Explora {N} configurações diferentes, redistribuindo operações entre prensas. Apresenta
            os 3 melhores planos com comparação lado a lado de OTD-D, setups e utilização.
          </div>
        </Card>
      )}

      {res && (
        <>
          <WhatIfResultsSection
            res={res}
            sel={sel}
            setSel={setSel}
            rankColor={rankColor}
            rankLabel={rankLabel}
            qv={qvWI}
            onApplyMoves={onApplyMoves}
            isSaving={isSaving}
            machines={machines}
            focusT={focusT}
            getResourceDownDays={getResourceDownDays}
            ops={ops}
            tools={tools}
            data={data}
          />

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

import { useState } from 'react';
import type { Block, EngineData, EOp, MoveAction, OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import type { buildResourceTimelines } from '@/utils/failure-timeline';
import { usePlanVersionStore } from '../../../stores/usePlanVersionStore';
import { useWhatIf } from '../hooks/useWhatIf';
import { OBJECTIVE_PROFILES } from './constants';
import { AdvancedWhatIfView, SimpleWhatIfView, WhatIfResultsSection } from './whatif';

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
  const { machines, tools, ops, focusIds } = data;
  const { state: wi, actions: wiActions } = useWhatIf(
    data,
    OBJECTIVE_PROFILES,
    getResourceDownDays,
    replanTimelines,
  );
  const { res, run, prog, sel, focusT, qv: qvWI } = wi;
  const { setObjProfile, setSel, setRes, optimize } = wiActions;
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
        )}
      </div>
    );
  }

  // Advanced mode: full existing UI
  return (
    <AdvancedWhatIfView
      data={data}
      wi={wi}
      wiActions={wiActions}
      rankColor={rankColor}
      rankLabel={rankLabel}
      onApplyMoves={onApplyMoves}
      isSaving={isSaving}
      setResourceDown={setResourceDown}
      clearResourceDown={clearResourceDown}
      getResourceDownDays={getResourceDownDays}
      versions={versions}
      currentId={currentId}
      neMetrics={neMetrics}
      baselineBlocks={baselineBlocks}
      baselineOps={baselineOps}
      objectiveProfiles={OBJECTIVE_PROFILES}
      onSwitchSimple={() => setAdvancedMode(false)}
    />
  );
}

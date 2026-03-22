import type {
  EMachine,
  EngineData,
  EOp,
  ETool,
  MoveAction,
  MoveableOp,
  OptResult,
  QuickValidateResult,
} from '@/domain/types/scheduling';
import { ApplyPlanButton, QualityWarnings, ScenarioResultCards } from './ScenarioComparison';
import { ScenarioDetails } from './ScenarioDetails';

export type WhatIfResultsSectionProps = {
  res: { top3: OptResult[]; moveable: MoveableOp[] };
  sel: number;
  setSel: React.Dispatch<React.SetStateAction<number>>;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
  qv: QuickValidateResult;
  onApplyMoves?: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  machines: EMachine[];
  focusT: ETool[];
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
  ops: EOp[];
  tools: ETool[];
  data: EngineData;
};

export function WhatIfResultsSection({
  res,
  sel,
  setSel,
  rankColor,
  rankLabel,
  qv,
  onApplyMoves,
  isSaving,
  machines,
  focusT,
  getResourceDownDays,
  ops,
  tools,
  data,
}: WhatIfResultsSectionProps) {
  return (
    <>
      <ScenarioResultCards
        top3={res.top3}
        sel={sel}
        setSel={setSel}
        rankColor={rankColor}
        rankLabel={rankLabel}
      />

      <QualityWarnings qv={qv} />

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
  );
}

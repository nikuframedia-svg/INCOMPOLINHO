import { AlertTriangle } from 'lucide-react';
import type { EngineData, ETool, MoveAction, OptResult } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import type { QualityViolations } from './whatif-types';

export function ScenarioResultCards({
  top3,
  sel,
  setSel,
  rankColor,
  rankLabel,
}: {
  top3: OptResult[];
  sel: number;
  setSel: (i: number) => void;
  rankColor: (i: number) => string;
  rankLabel: (i: number) => string;
}) {
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {top3.map((s, i) => (
        <button
          key={i}
          onClick={() => setSel(i)}
          style={{
            flex: 1,
            padding: 12,
            borderRadius: 8,
            cursor: 'pointer',
            textAlign: 'left',
            fontFamily: 'inherit',
            background: sel === i ? C.s3 : C.s2,
            border: `2px solid ${sel === i ? rankColor(i) : C.bd}`,
            transition: 'all .15s',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: rankColor(i) }}>
              {rankLabel(i)}
            </span>
            <span style={{ fontSize: 12, color: C.t4 }}>{s.label}</span>
          </div>
          <div
            style={{
              fontSize: 24,
              fontWeight: 600,
              color: s.otd < 95 ? C.rd : rankColor(i),
              fontFamily: 'monospace',
              lineHeight: 1,
              marginTop: 4,
            }}
          >
            {s.otd.toFixed(1)}%
          </div>
          <div
            style={{
              fontSize: 12,
              color: s.otdDelivery < 90 ? C.rd : C.t3,
              marginTop: 2,
              fontFamily: 'monospace',
            }}
          >
            OTD-D {s.otdDelivery.toFixed(1)}%
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 12, color: C.t3 }}>
            <span>{s.setupCount} setups</span>
            <span>{s.moves.length} moves</span>
            <span style={{ color: C.yl }}>{s.tardinessDays.toFixed(1)}d tard.</span>
          </div>
        </button>
      ))}
    </div>
  );
}

export function QualityWarnings({ qv }: { qv: QualityViolations }) {
  if (qv.criticalCount === 0 && qv.highCount === 0) return null;
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 12px',
        borderRadius: 6,
        background: qv.criticalCount > 0 ? C.rdS : `${C.yl}18`,
        borderLeft: `3px solid ${qv.criticalCount > 0 ? C.rd : C.yl}`,
      }}
    >
      <AlertTriangle
        size={13}
        style={{ color: qv.criticalCount > 0 ? C.rd : C.yl, flexShrink: 0 }}
      />
      <span style={{ fontSize: 12, fontWeight: 600, color: qv.criticalCount > 0 ? C.rd : C.yl }}>
        {qv.criticalCount > 0
          ? `${qv.criticalCount} conflito${qv.criticalCount > 1 ? 's' : ''} crítico${qv.criticalCount > 1 ? 's' : ''}`
          : ''}
        {qv.criticalCount > 0 && qv.highCount > 0 ? ' · ' : ''}
        {qv.highCount > 0 ? `${qv.highCount} alerta${qv.highCount > 1 ? 's' : ''}` : ''}
      </span>
      {qv.warnings.length > 0 && (
        <span style={{ fontSize: 12, color: C.t3, marginLeft: 'auto' }}>{qv.warnings[0]}</span>
      )}
    </div>
  );
}

export function ApplyPlanButton({
  onApplyMoves,
  isSaving,
  moves,
  machines,
  focusT,
  getResourceDownDays,
}: {
  onApplyMoves: (
    moves: MoveAction[],
    scenarioState: { mSt: Record<string, string>; tSt: Record<string, string> },
  ) => void;
  isSaving?: boolean;
  moves: MoveAction[];
  machines: EngineData['machines'];
  focusT: ETool[];
  getResourceDownDays: (type: 'machine' | 'tool', id: string) => Set<number>;
}) {
  if (moves.length === 0) return null;
  return (
    <button
      onClick={() => {
        const mSt = Object.fromEntries(
          machines.map((m) => [
            m.id,
            getResourceDownDays('machine', m.id).size > 0 ? 'down' : 'running',
          ]),
        );
        const tSt = Object.fromEntries(
          focusT
            .filter((t) => getResourceDownDays('tool', t.id).size > 0)
            .map((t) => [t.id, 'down']),
        );
        onApplyMoves(moves, { mSt, tSt });
      }}
      disabled={isSaving}
      style={{
        width: '100%',
        padding: 12,
        borderRadius: 8,
        border: 'none',
        cursor: isSaving ? 'wait' : 'pointer',
        background: isSaving ? C.s3 : C.ac,
        color: isSaving ? C.t3 : C.bg,
        fontSize: 13,
        fontWeight: 600,
        fontFamily: 'inherit',
        opacity: isSaving ? 0.6 : 1,
      }}
    >
      {isSaving ? 'A guardar plano...' : `Aplicar Plano Selecionado (${moves.length} movimentos)`}
    </button>
  );
}

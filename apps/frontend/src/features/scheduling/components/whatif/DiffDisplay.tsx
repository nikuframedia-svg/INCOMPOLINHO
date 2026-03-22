import { X } from 'lucide-react';
import { C } from '@/theme/color-bridge';
import { usePlanVersionStore } from '../../../../stores/usePlanVersionStore';
import { computePlanDiff } from '../../../../utils/planDiff';

export function DiffDisplay({
  diffPair,
  setDiffPair,
}: {
  diffPair: [string, string];
  setDiffPair: (pair: [string, string] | null) => void;
}) {
  const vA = usePlanVersionStore.getState().actions.getVersion(diffPair[0]);
  const vB = usePlanVersionStore.getState().actions.getVersion(diffPair[1]);
  if (!vA || !vB) return null;
  const diff = computePlanDiff(vA, vB);

  return (
    <div
      style={{
        marginTop: 12,
        padding: 12,
        background: C.bg,
        borderRadius: 6,
        border: `1px solid ${C.bd}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>
          {vA.label} → {vB.label}
        </span>
        <button
          onClick={() => setDiffPair(null)}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: C.t3, padding: 2 }}
        >
          <X size={12} strokeWidth={1.5} />
        </button>
      </div>
      <div style={{ fontSize: 12, color: C.t2, marginBottom: 8 }}>{diff.summary}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 6 }}>
        {[
          {
            l: 'OTD-D',
            v: `${diff.kpiDelta.otd > 0 ? '+' : ''}${diff.kpiDelta.otd.toFixed(1)}%`,
            c: diff.kpiDelta.otd >= 0 ? C.ac : C.rd,
          },
          {
            l: 'Setups',
            v: `${diff.kpiDelta.setupCount > 0 ? '+' : ''}${diff.kpiDelta.setupCount}`,
            c: diff.kpiDelta.setupCount <= 0 ? C.ac : C.rd,
          },
          {
            l: 'Tardiness',
            v: `${diff.kpiDelta.tardinessDays > 0 ? '+' : ''}${diff.kpiDelta.tardinessDays.toFixed(1)}d`,
            c: diff.kpiDelta.tardinessDays <= 0 ? C.ac : C.rd,
          },
        ].map((k, i) => (
          <div key={i} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: C.t4 }}>{k.l}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: k.c, fontFamily: 'monospace' }}>
              {k.v}
            </div>
          </div>
        ))}
      </div>
      {diff.moved.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 12, color: C.t3 }}>
          {diff.moved.length} ops movidas · Churn: {diff.churn.toFixed(0)} min
        </div>
      )}
    </div>
  );
}

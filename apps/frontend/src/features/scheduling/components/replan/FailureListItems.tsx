/**
 * FailureListItems — Renders active failures with impact summaries and the replan button.
 */
import { X } from 'lucide-react';
import type { FailureEvent, ImpactReport } from '../../../../lib/engine';
import { C } from '../../../../lib/engine';
import { Tag } from '../atoms';

export interface FailureListItemsProps {
  failures: FailureEvent[];
  failureImpacts: ImpactReport[];
  dnames: string[];
  dates: string[];
  removeFailure: (id: string) => void;
  cascRunning: boolean;
  runCascadingReplan: () => void;
  showFailureForm: boolean;
}

export function FailureListItems({
  failures,
  failureImpacts,
  dnames,
  dates,
  removeFailure,
  cascRunning,
  runCascadingReplan,
  showFailureForm,
}: FailureListItemsProps) {
  return (
    <>
      {failures.map((f, fi) => {
        const imp = failureImpacts[fi];
        return (
          <div
            key={f.id}
            style={{
              padding: 10,
              background: C.rdS,
              borderRadius: 6,
              border: `1px solid ${C.rd}22`,
              marginBottom: 6,
              borderLeft: `3px solid ${C.rd}`,
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 4,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span
                  style={{
                    fontSize: 12,
                    fontWeight: 600,
                    color: C.t1,
                    fontFamily: "'JetBrains Mono',monospace",
                  }}
                >
                  {f.resourceId}
                </span>
                <Tag color={f.severity === 'total' ? C.rd : f.severity === 'partial' ? C.yl : C.bl}>
                  {f.severity === 'total'
                    ? 'TOTAL'
                    : f.severity === 'partial'
                      ? `PARCIAL ${Math.round(f.capacityFactor * 100)}%`
                      : `DEGRADADA ${Math.round(f.capacityFactor * 100)}%`}
                </Tag>
                <span style={{ fontSize: 10, color: C.t3 }}>
                  {dnames[f.startDay]} {dates[f.startDay]}
                  {f.startDay !== f.endDay ? ` — ${dnames[f.endDay]} ${dates[f.endDay]}` : ''}
                </span>
              </div>
              <button
                onClick={() => removeFailure(f.id)}
                style={{
                  background: 'none',
                  border: 'none',
                  color: C.t3,
                  cursor: 'pointer',
                  padding: '0 2px',
                }}
              >
                <X size={12} strokeWidth={2} />
              </button>
            </div>
            {f.description && (
              <div style={{ fontSize: 10, color: C.t3, marginBottom: 4 }}>{f.description}</div>
            )}
            {imp && imp.summary.totalBlocksAffected > 0 && (
              <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.t2 }}>
                <span>
                  <span style={{ fontWeight: 600, color: C.rd }}>
                    {imp.summary.totalBlocksAffected}
                  </span>{' '}
                  blocos afectados
                </span>
                <span>
                  <span style={{ fontWeight: 600, color: C.rd }}>
                    {imp.summary.totalQtyAtRisk.toLocaleString()}
                  </span>{' '}
                  pcs em risco
                </span>
                <span>{imp.summary.blocksWithAlternative} c/ alternativa</span>
                <span style={{ color: C.rd, fontWeight: 600 }}>
                  {imp.summary.blocksWithoutAlternative} s/ alternativa
                </span>
              </div>
            )}
            {imp && imp.summary.totalBlocksAffected === 0 && (
              <div style={{ fontSize: 10, color: C.ac }}>Sem impacto no schedule actual</div>
            )}
          </div>
        );
      })}

      {failures.length > 0 && (
        <button
          onClick={runCascadingReplan}
          disabled={cascRunning}
          data-testid="cascading-replan"
          style={{
            width: '100%',
            padding: 8,
            borderRadius: 6,
            border: 'none',
            background: cascRunning ? C.s3 : C.rd,
            color: cascRunning ? C.t3 : C.t1,
            fontSize: 11,
            fontWeight: 600,
            cursor: cascRunning ? 'wait' : 'pointer',
            fontFamily: 'inherit',
            marginTop: 6,
          }}
        >
          {cascRunning ? 'A replanificar...' : `Replanificar com Avarias (${failures.length})`}
        </button>
      )}

      {failures.length === 0 && !showFailureForm && (
        <div style={{ fontSize: 10, color: C.t4, textAlign: 'center', padding: 8 }}>
          Sem avarias registadas
        </div>
      )}
    </>
  );
}

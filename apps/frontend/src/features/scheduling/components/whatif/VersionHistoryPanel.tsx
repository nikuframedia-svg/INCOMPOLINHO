/**
 * VersionHistoryPanel — Timeline of saved plan versions with commit/diff/branch controls.
 */
import { Star } from 'lucide-react';
import { C } from '../../../../lib/engine';
import { usePlanVersionStore } from '../../../../stores/usePlanVersionStore';
import { Card, Tag } from '../atoms';
import { DiffDisplay } from './DiffDisplay';

export function VersionHistoryPanel({
  versions,
  currentId,
  diffPair,
  setDiffPair,
}: {
  versions: ReturnType<typeof usePlanVersionStore.getState>['versions'];
  currentId: string | null;
  diffPair: [string, string] | null;
  setDiffPair: (pair: [string, string] | null) => void;
}) {
  if (versions.length === 0) return null;

  return (
    <Card style={{ padding: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: C.t1, marginBottom: 12 }}>
        Histórico de Versões <Tag color={C.pp}>{versions.length}</Tag>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0, paddingLeft: 12 }}>
        {[...versions].reverse().map((v, i) => {
          const isCurrent = v.id === currentId;
          const isFirst = i === versions.length - 1;
          return (
            <div key={v.id} style={{ position: 'relative', paddingLeft: 20, paddingBottom: 16 }}>
              {i < versions.length - 1 && (
                <div
                  style={{
                    position: 'absolute',
                    left: 3,
                    top: 10,
                    bottom: 0,
                    width: 1,
                    background: 'rgba(255,255,255,0.06)',
                  }}
                />
              )}
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 2,
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: isCurrent ? C.ac : isFirst ? C.t4 : C.t3,
                }}
              />
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <button
                    onClick={() =>
                      usePlanVersionStore.getState().actions.setFavorite(v.id, !v.isFavorite)
                    }
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      padding: 0,
                      display: 'flex',
                      alignItems: 'center',
                    }}
                  >
                    <Star
                      size={12}
                      strokeWidth={1.5}
                      fill={v.isFavorite ? C.yl : 'none'}
                      style={{ color: v.isFavorite ? C.yl : C.t4 }}
                    />
                  </button>
                  <span style={{ fontSize: 13, fontWeight: 500, color: C.t1 }}>{v.label}</span>
                  {v.branchLabel && (
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 600,
                        color: C.pp,
                        background: C.ppS,
                        padding: '1px 6px',
                        borderRadius: 3,
                      }}
                    >
                      {v.branchLabel}
                    </span>
                  )}
                  {isCurrent && (
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        fontWeight: 600,
                        background: C.acS,
                        color: C.ac,
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                      }}
                    >
                      COMMITTED
                    </span>
                  )}
                </div>
                <span style={{ fontSize: 12, color: C.t3, fontFamily: 'var(--font-mono)' }}>
                  {v.id.slice(0, 8)}
                </span>
              </div>
              <div style={{ fontSize: 12, color: C.t3, marginTop: 2 }}>
                {new Date(v.timestamp).toLocaleTimeString('pt-PT', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
                {' · '}OTD-D {v.kpis.otdDelivery.toFixed(1)}% · OTD {v.kpis.otd.toFixed(1)}% ·{' '}
                {v.kpis.setupCount} setups · tard {v.kpis.tardinessDays.toFixed(1)}d
              </div>
              <div style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
                {!isCurrent && (
                  <button
                    onClick={() => usePlanVersionStore.getState().actions.commitPlan(v.id)}
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      cursor: 'pointer',
                      background: 'transparent',
                      color: C.t2,
                      fontSize: 12,
                      fontFamily: 'inherit',
                    }}
                  >
                    Commit
                  </button>
                )}
                {i < versions.length - 1 && (
                  <button
                    onClick={() => {
                      const prev = [...versions].reverse()[i + 1];
                      if (prev) setDiffPair([prev.id, v.id]);
                    }}
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      border: `1px solid ${C.bd}`,
                      cursor: 'pointer',
                      background: 'transparent',
                      color: C.t2,
                      fontSize: 12,
                      fontFamily: 'inherit',
                    }}
                  >
                    Diff
                  </button>
                )}
                <input
                  placeholder="branch..."
                  defaultValue={v.branchLabel ?? ''}
                  onBlur={(e) =>
                    usePlanVersionStore
                      .getState()
                      .actions.setBranchLabel(v.id, e.target.value.trim())
                  }
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                  }}
                  style={{
                    marginLeft: 'auto',
                    width: 80,
                    padding: '2px 6px',
                    borderRadius: 4,
                    border: `1px solid ${C.bd}`,
                    background: 'transparent',
                    color: C.t3,
                    fontSize: 12,
                    fontFamily: 'inherit',
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
      {diffPair && <DiffDisplay diffPair={diffPair} setDiffPair={setDiffPair} />}
    </Card>
  );
}

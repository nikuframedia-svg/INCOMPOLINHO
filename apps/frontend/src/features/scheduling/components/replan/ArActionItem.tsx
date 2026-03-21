/**
 * ArActionItem — Single auto-replan action card with alternatives and simulation.
 */
import { ChevronDown, ChevronRight, Eye, Undo2 } from 'lucide-react';
import { C } from '../../../../lib/engine';
import { Tag } from '../atoms';
import type { AutoReplanCardProps } from './types';

export interface ArActionItemProps {
  act: AutoReplanCardProps['arActions'][number];
  isExp: boolean;
  isSim: boolean;
  arSim: AutoReplanCardProps['arSim'];
  setArExpanded: AutoReplanCardProps['setArExpanded'];
  handleArUndo: AutoReplanCardProps['handleArUndo'];
  handleArAlt: AutoReplanCardProps['handleArAlt'];
  handleArSimulate: AutoReplanCardProps['handleArSimulate'];
}

const STRAT_COLOR: Record<string, string> = {
  ADVANCE_PRODUCTION: C.ac,
  MOVE_ALT_MACHINE: C.bl,
  SPLIT_OPERATION: C.pp,
  OVERTIME: C.yl,
  THIRD_SHIFT: C.cy,
};

export function ArActionItem({
  act,
  isExp,
  isSim,
  arSim,
  setArExpanded,
  handleArUndo,
  handleArAlt,
  handleArSimulate,
}: ArActionItemProps) {
  const sc2 = STRAT_COLOR[act.strategy] || C.t3;
  const btnBase = {
    borderRadius: 4,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    display: 'inline-flex',
    alignItems: 'center',
    gap: 3,
  } as const;

  return (
    <div
      style={{
        padding: 12,
        borderRadius: 6,
        background: isSim ? `${C.bl}08` : C.bg,
        border: `1px solid ${isSim ? C.bl + '33' : C.bd}`,
        borderLeft: `3px solid ${sc2}`,
      }}
    >
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, flexWrap: 'wrap' }}
      >
        <Tag color={sc2}>{act.strategy.replace(/_/g, ' ')}</Tag>
        <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>{act.summary}</span>
        {act.reversible && (
          <span
            style={{
              fontSize: 12,
              color: C.ac,
              fontWeight: 600,
              background: C.acS,
              padding: '1px 4px',
              borderRadius: 3,
            }}
          >
            REVERSÍVEL
          </span>
        )}
        <span style={{ fontSize: 12, color: C.t4, fontFamily: "'JetBrains Mono',monospace" }}>
          {act.opId}
        </span>
      </div>
      <div style={{ fontSize: 12, color: C.t3, marginBottom: 8 }}>{act.detail}</div>

      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {act.alternatives.length > 0 && (
          <button
            onClick={() => setArExpanded(isExp ? null : act.decisionId)}
            style={{
              ...btnBase,
              padding: '3px 8px',
              border: `1px solid ${C.pp}33`,
              background: isExp ? C.ppS : 'transparent',
              color: C.pp,
            }}
          >
            {isExp ? (
              <ChevronDown size={9} strokeWidth={1.5} />
            ) : (
              <ChevronRight size={9} strokeWidth={1.5} />
            )}
            {act.alternatives.length} alt.
          </button>
        )}
        <button
          onClick={() => handleArUndo(act.decisionId)}
          style={{
            ...btnBase,
            padding: '3px 8px',
            border: `1px solid ${C.rd}33`,
            background: 'transparent',
            color: C.rd,
          }}
        >
          <Undo2 size={9} strokeWidth={1.5} /> Desfazer
        </button>
        <button
          onClick={() => handleArSimulate(act.decisionId)}
          style={{
            ...btnBase,
            padding: '3px 8px',
            border: `1px solid ${C.bl}33`,
            background: isSim ? C.blS : 'transparent',
            color: C.bl,
          }}
        >
          <Eye size={9} strokeWidth={1.5} /> Simular
        </button>
      </div>

      {isExp && act.alternatives.length > 0 && (
        <div style={{ marginTop: 8, padding: 8, background: C.s2, borderRadius: 4 }}>
          {act.alternatives.map((alt, ai) => (
            <div
              key={ai}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '4px 0',
                borderBottom: ai < act.alternatives.length - 1 ? `1px solid ${C.bd}` : 'none',
              }}
            >
              <div>
                <div style={{ fontSize: 12, color: C.t1 }}>{alt.description}</div>
                <div style={{ fontSize: 12, color: C.t4 }}>{alt.actionType.replace(/_/g, ' ')}</div>
              </div>
              <button
                onClick={() => handleArAlt(act.decisionId, alt)}
                style={{
                  padding: '3px 8px',
                  borderRadius: 4,
                  border: 'none',
                  background: C.ac,
                  color: C.bg,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                Aplicar
              </button>
            </div>
          ))}
        </div>
      )}

      {isSim && arSim && (
        <div
          style={{
            marginTop: 8,
            padding: 8,
            background: `${C.bl}08`,
            borderRadius: 4,
            border: `1px solid ${C.bl}22`,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 600, color: C.bl, marginBottom: 4 }}>
            <Eye
              size={10}
              strokeWidth={1.5}
              style={{ display: 'inline', verticalAlign: 'middle', marginRight: 3 }}
            />
            Simulação: sem esta acção
          </div>
          <div style={{ display: 'flex', gap: 12, fontSize: 12, color: C.t2 }}>
            <span>
              Overflow: {arSim.overflowBefore} → {arSim.overflowAfter}{' '}
              <span
                style={{
                  color: arSim.overflowDelta > 0 ? C.rd : arSim.overflowDelta < 0 ? C.ac : C.t3,
                  fontWeight: 600,
                }}
              >
                ({arSim.overflowDelta > 0 ? '+' : ''}
                {arSim.overflowDelta})
              </span>
            </span>
          </div>
          {arSim.unresolved.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <div style={{ fontSize: 12, color: C.rd, fontWeight: 600 }}>
                {arSim.unresolved.length} não resolvido{arSim.unresolved.length > 1 ? 's' : ''}
              </div>
              {arSim.unresolved.slice(0, 5).map((u, i) => (
                <div
                  key={i}
                  style={{ fontSize: 12, color: C.t3, fontFamily: "'JetBrains Mono',monospace" }}
                >
                  {u.opId}: {u.reason} (deficit: {u.deficit})
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

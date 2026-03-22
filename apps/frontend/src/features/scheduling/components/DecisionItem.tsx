import { ChevronDown, ChevronRight } from 'lucide-react';
import type { AlternativeAction, DecisionEntry, EngineData, EOp } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import {
  DECISION_CATEGORIES,
  DECISION_CATEGORY_COLORS,
  DECISION_TYPE_LABELS,
} from './decision-constants';

export function DecisionItem({
  d,
  i,
  isExpanded,
  onToggle,
  opById,
  getEDD,
  data,
}: {
  d: DecisionEntry;
  i: number;
  isExpanded: boolean;
  onToggle: () => void;
  opById: Record<string, EOp>;
  getEDD: (op: EOp) => number | null;
  data: EngineData;
}) {
  const { dates, dnames } = data;
  const catEntry = Object.entries(DECISION_CATEGORIES).find(([, cat]) =>
    cat.types.includes(d.type),
  );
  const catKey = catEntry?.[0] ?? 'scheduling';
  const catColor = DECISION_CATEGORY_COLORS[catKey] || C.t3;

  return (
    <div
      key={d.id || i}
      style={{
        padding: '6px 10px',
        borderRadius: 4,
        background: C.s1,
        borderLeft: `3px solid ${catColor}`,
      }}
    >
      <div
        style={{ display: 'flex', alignItems: 'flex-start', gap: 6, cursor: 'pointer' }}
        onClick={onToggle}
      >
        {isExpanded ? (
          <ChevronDown size={10} color={C.t3} style={{ marginTop: 2, flexShrink: 0 }} />
        ) : (
          <ChevronRight size={10} color={C.t3} style={{ marginTop: 2, flexShrink: 0 }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: catColor,
                fontFamily: 'monospace',
                minWidth: 110,
              }}
            >
              {DECISION_TYPE_LABELS[d.type] || d.type}
            </span>
            {d.opId &&
              (() => {
                const op = opById[d.opId];
                return (
                  <>
                    <span style={{ fontSize: 12, color: C.t2, fontFamily: 'monospace' }}>
                      {d.opId}
                    </span>
                    {op?.sku && (
                      <span
                        style={{ fontSize: 12, color: C.t3, fontFamily: 'monospace', opacity: 0.8 }}
                      >
                        {op.sku}
                      </span>
                    )}
                  </>
                );
              })()}
            {d.toolId && (
              <span style={{ fontSize: 12, color: C.t3, fontFamily: 'monospace' }}>{d.toolId}</span>
            )}
            {d.machineId && (
              <span style={{ fontSize: 12, color: C.t3, fontFamily: 'monospace' }}>
                {'\u2192'} {d.machineId}
              </span>
            )}
            {d.dayIdx != null && (
              <span style={{ fontSize: 12, color: C.t4, fontFamily: 'monospace' }}>
                {dates[d.dayIdx] ?? `d${d.dayIdx}`}
                {dnames[d.dayIdx] ? ` ${dnames[d.dayIdx]}` : ''}
              </span>
            )}
            {d.reversible && (
              <span
                style={{
                  fontSize: 12,
                  padding: '1px 4px',
                  borderRadius: 3,
                  background: C.acS,
                  color: C.ac,
                  fontWeight: 600,
                  marginLeft: 'auto',
                  flexShrink: 0,
                }}
              >
                reversível
              </span>
            )}
          </div>
          {d.opId &&
            (() => {
              const op = opById[d.opId];
              if (!op) return null;
              const edd = getEDD(op);
              const tool = data.toolMap[op.t];
              return (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 2 }}>
                  <span
                    style={{
                      fontSize: 12,
                      color: C.t3,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      maxWidth: 220,
                    }}
                  >
                    {op.nm}
                  </span>
                  {edd != null && (
                    <span style={{ fontSize: 12, color: C.yl, fontWeight: 500 }}>
                      EDD: {dates[edd] ?? `d${edd}`}
                    </span>
                  )}
                  {tool && (
                    <span style={{ fontSize: 12, color: C.t4, fontFamily: 'monospace' }}>
                      {tool.pH.toLocaleString()} pcs/h
                    </span>
                  )}
                </div>
              );
            })()}
        </div>
      </div>
      {isExpanded && (
        <div style={{ marginTop: 6, paddingLeft: 16, fontSize: 12 }}>
          {d.detail && <div style={{ color: C.t2, marginBottom: 3 }}>{d.detail}</div>}
          {d.shift && <div style={{ color: C.t3 }}>Turno: {d.shift}</div>}
          {d.alternatives && d.alternatives.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: C.t3,
                  textTransform: 'uppercase',
                  letterSpacing: '.04em',
                  marginBottom: 3,
                }}
              >
                Alternativas ({d.alternatives.length})
              </div>
              {d.alternatives.map((alt: AlternativeAction, ai: number) => (
                <div
                  key={ai}
                  style={{
                    padding: '3px 8px',
                    borderRadius: 3,
                    background: C.s2,
                    marginBottom: 2,
                    display: 'flex',
                    gap: 6,
                    alignItems: 'center',
                  }}
                >
                  <span style={{ fontFamily: 'monospace', color: C.bl, fontSize: 12 }}>
                    {alt.actionType}
                  </span>
                  <span style={{ color: C.t2, flex: 1 }}>{alt.description}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

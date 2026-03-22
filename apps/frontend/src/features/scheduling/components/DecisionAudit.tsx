import { useCallback, useMemo, useState } from 'react';
import type { DecisionEntry, EngineData, EOp } from '@/domain/types/scheduling';
import { C } from '@/theme/color-bridge';
import { Card } from './atoms';
import { DecisionItem } from './DecisionItem';
import { DECISION_CATEGORIES, DECISION_CATEGORY_COLORS } from './decision-constants';

export function DecisionAudit({
  decisions,
  data,
}: {
  decisions: DecisionEntry[];
  data: EngineData;
}) {
  const [showDecisions, setShowDecisions] = useState(false);
  const [decFilter, setDecFilter] = useState<string>('all');
  const [decExpanded, setDecExpanded] = useState<string | null>(null);

  const opById = useMemo(() => {
    const map: Record<string, EOp> = {};
    for (const op of data.ops) map[op.id] = op;
    return map;
  }, [data.ops]);

  const getEDD = useCallback((op: EOp): number | null => {
    for (let i = 0; i < op.d.length; i++) {
      if (op.d[i] > 0) return i;
    }
    return null;
  }, []);

  if (decisions.length === 0) return null;

  return (
    <Card style={{ padding: 14 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: showDecisions ? 10 : 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: C.t1 }}>Decisões do Engine</span>
          <span style={{ fontSize: 12, color: C.t3, fontFamily: 'monospace' }}>
            {decisions.length} total
          </span>
          {Object.entries(DECISION_CATEGORIES).map(([catKey, cat]) => {
            const count = decisions.filter((d) => cat.types.includes(d.type)).length;
            if (count === 0) return null;
            return (
              <span
                key={catKey}
                style={{
                  padding: '1px 6px',
                  borderRadius: 4,
                  fontSize: 12,
                  fontWeight: 600,
                  background: `${DECISION_CATEGORY_COLORS[catKey]}15`,
                  color: DECISION_CATEGORY_COLORS[catKey],
                }}
              >
                {cat.label} {count}
              </span>
            );
          })}
        </div>
        <button
          onClick={() => setShowDecisions(!showDecisions)}
          style={{
            padding: '3px 10px',
            borderRadius: 4,
            border: `1px solid ${C.bd}`,
            background: 'transparent',
            color: C.t3,
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          {showDecisions ? 'Esconder' : 'Expandir'}
        </button>
      </div>

      {showDecisions && (
        <>
          {/* Filter by category */}
          <div style={{ display: 'flex', gap: 3, marginBottom: 10, flexWrap: 'wrap' }}>
            <button
              onClick={() => setDecFilter('all')}
              style={{
                padding: '3px 10px',
                borderRadius: 4,
                border: 'none',
                cursor: 'pointer',
                fontFamily: 'inherit',
                fontSize: 12,
                fontWeight: 600,
                background: decFilter === 'all' ? `${C.ac}25` : C.s1,
                color: decFilter === 'all' ? C.ac : C.t3,
              }}
            >
              Todas ({decisions.length})
            </button>
            {Object.entries(DECISION_CATEGORIES).map(([catKey, cat]) => {
              const count = decisions.filter((d) => cat.types.includes(d.type)).length;
              if (count === 0) return null;
              return (
                <button
                  key={catKey}
                  onClick={() => setDecFilter(catKey)}
                  style={{
                    padding: '3px 10px',
                    borderRadius: 4,
                    border: 'none',
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                    fontSize: 12,
                    fontWeight: 600,
                    background:
                      decFilter === catKey ? `${DECISION_CATEGORY_COLORS[catKey]}25` : C.s1,
                    color: decFilter === catKey ? DECISION_CATEGORY_COLORS[catKey] : C.t3,
                  }}
                >
                  {cat.label} ({count})
                </button>
              );
            })}
          </div>

          {/* Decision list */}
          <div
            style={{
              maxHeight: 400,
              overflow: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: 3,
            }}
          >
            {decisions
              .filter(
                (d) =>
                  decFilter === 'all' || DECISION_CATEGORIES[decFilter]?.types.includes(d.type),
              )
              .slice(0, 100)
              .map((d, i) => (
                <DecisionItem
                  key={d.id || i}
                  d={d}
                  i={i}
                  isExpanded={decExpanded === d.id}
                  onToggle={() => setDecExpanded(decExpanded === d.id ? null : d.id)}
                  opById={opById}
                  getEDD={getEDD}
                  data={data}
                />
              ))}
          </div>
        </>
      )}
    </Card>
  );
}

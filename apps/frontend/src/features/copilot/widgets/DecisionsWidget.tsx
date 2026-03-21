/**
 * DecisionsWidget — compact decision audit trail.
 */

interface DecisionEntry {
  tipo?: string;
  detalhe?: string;
  máquina?: string;
  dia?: number;
  turno?: string;
  op_id?: string;
}

export function DecisionsWidget({ data }: { data: Record<string, unknown> }) {
  const decisions = (data.decisões ?? []) as DecisionEntry[];
  const total = (data.total ?? decisions.length) as number;
  if (decisions.length === 0) return null;

  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          marginBottom: 4,
        }}
      >
        Decisões ({total})
      </div>
      {decisions.slice(0, 6).map((d, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            gap: 6,
            fontSize: 10,
            padding: '2px 0',
            borderBottom: '1px solid var(--border-default, rgba(255,255,255,0.06))',
          }}
        >
          <span
            style={{
              fontFamily: "'JetBrains Mono',monospace",
              color: 'var(--accent)',
              minWidth: 50,
            }}
          >
            {d.op_id}
          </span>
          <span style={{ color: 'var(--text-muted)', minWidth: 50 }}>{d.máquina}</span>
          <span style={{ color: 'var(--text-muted)' }}>{d.tipo}</span>
          <span
            style={{
              color: 'var(--text-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              flex: 1,
            }}
          >
            {d.detalhe}
          </span>
        </div>
      ))}
    </div>
  );
}

/**
 * ProductionWidget — compact table of day's production by machine.
 */

interface ProdEntry {
  op_id?: string;
  tool?: string;
  qty?: number;
  start?: number;
  end?: number;
  turno?: string;
}

export function ProductionWidget({ data }: { data: Record<string, unknown> }) {
  const machines = (data.máquinas ?? {}) as Record<string, ProdEntry[]>;
  const dayIdx = (data.day_idx ?? 0) as number;
  const totalPcs = (data.total_peças ?? 0) as number;
  const entries = Object.entries(machines);
  if (entries.length === 0) return null;

  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          marginBottom: 6,
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <span>Produção Dia {dayIdx}</span>
        <span style={{ color: 'var(--accent)' }}>{totalPcs.toLocaleString('pt-PT')} pcs</span>
      </div>
      {entries.map(([machineId, ops]) => (
        <div key={machineId} style={{ marginBottom: 6 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--text-primary)',
              fontFamily: "'JetBrains Mono',monospace",
              marginBottom: 2,
            }}
          >
            {machineId}
          </div>
          {ops.slice(0, 5).map((op, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 8,
                fontSize: 10,
                color: 'var(--text-muted)',
                paddingLeft: 8,
              }}
            >
              <span style={{ fontFamily: "'JetBrains Mono',monospace", minWidth: 50 }}>
                {op.op_id}
              </span>
              <span style={{ minWidth: 30 }}>{op.turno}</span>
              <span>{(op.qty ?? 0).toLocaleString('pt-PT')} pcs</span>
            </div>
          ))}
          {ops.length > 5 && (
            <div style={{ fontSize: 10, color: 'var(--text-ghost)', paddingLeft: 8 }}>
              +{ops.length - 5} mais
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

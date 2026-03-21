/**
 * MachineLoadWidget — compact bar chart of machine utilisation.
 */

const BAR_STYLE: React.CSSProperties = {
  height: 14,
  borderRadius: 3,
  background: 'var(--accent, #818CF8)',
  transition: 'width 0.3s ease',
};

export function MachineLoadWidget({ data }: { data: Record<string, unknown> }) {
  const machines = (data.máquinas ?? data.machines ?? {}) as Record<
    string,
    { jobs?: number; minutos_producao?: number; pecas_total?: number }
  >;
  const entries = Object.entries(machines);
  if (entries.length === 0) return null;

  const maxMin = Math.max(...entries.map(([, v]) => v.minutos_producao ?? 0), 1);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)' }}>
        Carga por Máquina
      </div>
      {entries.map(([id, v]) => {
        const pct = ((v.minutos_producao ?? 0) / maxMin) * 100;
        return (
          <div key={id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                fontSize: 11,
                fontFamily: "'JetBrains Mono',monospace",
                minWidth: 56,
                color: 'var(--text-primary)',
              }}
            >
              {id}
            </span>
            <div
              style={{
                flex: 1,
                height: 14,
                borderRadius: 3,
                background: 'var(--bg-raised, rgba(30,34,48,0.65))',
              }}
            >
              <div style={{ ...BAR_STYLE, width: `${pct}%` }} />
            </div>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', minWidth: 40 }}>
              {v.jobs ?? 0}j
            </span>
          </div>
        );
      })}
    </div>
  );
}

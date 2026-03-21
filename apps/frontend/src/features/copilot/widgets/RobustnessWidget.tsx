/**
 * RobustnessWidget — Monte Carlo robustness summary with vulnerable jobs.
 */

export function RobustnessWidget({ data }: { data: Record<string, unknown> }) {
  const robustez = (data.robustez ?? {}) as Record<string, string>;
  const vulnerable = (data.jobs_vulneráveis ?? []) as Array<{
    job?: string;
    atrasado_em?: string;
    atraso_médio?: string;
  }>;

  const kpis = Object.entries(robustez);
  if (kpis.length === 0) return null;

  return (
    <div style={{ marginTop: 8 }}>
      <div
        style={{
          fontSize: 11,
          fontWeight: 600,
          color: 'var(--text-secondary)',
          marginBottom: 6,
        }}
      >
        Robustez Monte Carlo
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
        {kpis.map(([k, v]) => (
          <div
            key={k}
            style={{
              padding: '4px 8px',
              borderRadius: 4,
              background: 'var(--bg-raised, rgba(30,34,48,0.65))',
              fontSize: 10,
            }}
          >
            <div style={{ color: 'var(--text-muted)', marginBottom: 1 }}>{k}</div>
            <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{v}</div>
          </div>
        ))}
      </div>
      {vulnerable.length > 0 && (
        <>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>
            Jobs vulneráveis:
          </div>
          {vulnerable.slice(0, 5).map((v, i) => (
            <div key={i} style={{ fontSize: 10, display: 'flex', gap: 6, paddingLeft: 8 }}>
              <span
                style={{
                  fontFamily: "'JetBrains Mono',monospace",
                  color: 'var(--semantic-amber)',
                  minWidth: 50,
                }}
              >
                {v.job}
              </span>
              <span style={{ color: 'var(--text-muted)' }}>
                {v.atrasado_em} — atraso {v.atraso_médio}
              </span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

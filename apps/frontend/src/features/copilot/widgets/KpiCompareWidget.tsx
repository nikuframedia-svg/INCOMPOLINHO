/**
 * KpiCompareWidget — before/after KPI comparison from recalcular_plano.
 */

export function KpiCompareWidget({ data }: { data: Record<string, unknown> }) {
  const kpis = (data.kpis ?? {}) as Record<string, number>;
  const prev = (data.kpis_anteriores ?? {}) as Record<string, number>;
  const solveTime = (data.solve_time_s ?? 0) as number;
  const message = (data.message ?? '') as string;

  const entries: [string, number, number | undefined][] = [
    ['OTD %', kpis.otd_pct ?? 0, prev.otd_pct],
    ['Blocos', kpis.total_blocks ?? 0, prev.total_blocks],
    ['Infeasible', kpis.infeasible_blocks ?? 0, prev.infeasible_blocks],
    ['Peças', kpis.total_qty ?? 0, prev.total_qty],
  ];

  return (
    <div style={{ marginTop: 8 }}>
      {message && (
        <div style={{ fontSize: 11, color: 'var(--text-primary)', marginBottom: 6 }}>
          {message}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {entries.map(([label, val, prevVal]) => {
          const delta = prevVal != null ? val - prevVal : 0;
          const deltaColor =
            delta > 0
              ? 'var(--semantic-green, #34D399)'
              : delta < 0
                ? 'var(--semantic-red, #F87171)'
                : 'var(--text-ghost)';
          return (
            <div
              key={label}
              style={{
                padding: '4px 8px',
                borderRadius: 4,
                background: 'var(--bg-raised, rgba(30,34,48,0.65))',
                minWidth: 60,
              }}
            >
              <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{label}</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                {typeof val === 'number' ? val.toLocaleString('pt-PT') : val}
              </div>
              {prevVal != null && delta !== 0 && (
                <div style={{ fontSize: 9, color: deltaColor }}>
                  {delta > 0 ? '+' : ''}
                  {delta.toLocaleString('pt-PT')}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {solveTime > 0 && (
        <div style={{ fontSize: 9, color: 'var(--text-ghost)', marginTop: 4 }}>
          Calculado em {solveTime.toFixed(1)}s
        </div>
      )}
    </div>
  );
}

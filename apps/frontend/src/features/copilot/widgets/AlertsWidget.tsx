/**
 * AlertsWidget — compact alert list with severity indicators.
 */

const SEVERITY_COLORS: Record<string, string> = {
  atraso: 'var(--semantic-red, #F87171)',
  red: 'var(--semantic-red, #F87171)',
  yellow: 'var(--semantic-amber, #FBBF24)',
  green: 'var(--semantic-green, #34D399)',
};

interface Alert {
  severity?: string;
  sku?: string;
  message?: string;
}

export function AlertsWidget({ data }: { data: Record<string, unknown> }) {
  const alerts = (data.alertas ?? []) as Alert[];
  const total = (data.total ?? alerts.length) as number;
  const info = data.info as string | undefined;

  if (info) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, fontStyle: 'italic' }}>
        {info}
      </div>
    );
  }

  if (alerts.length === 0) return null;

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
        Alertas ({total})
      </div>
      {alerts.slice(0, 8).map((a, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 10,
            padding: '2px 0',
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: SEVERITY_COLORS[a.severity ?? 'yellow'] ?? 'var(--text-ghost)',
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontFamily: "'JetBrains Mono',monospace",
              color: 'var(--text-primary)',
              minWidth: 50,
            }}
          >
            {a.sku}
          </span>
          <span style={{ color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {a.message}
          </span>
        </div>
      ))}
      {alerts.length > 8 && (
        <div style={{ fontSize: 10, color: 'var(--text-ghost)', marginTop: 2 }}>
          +{alerts.length - 8} mais
        </div>
      )}
    </div>
  );
}

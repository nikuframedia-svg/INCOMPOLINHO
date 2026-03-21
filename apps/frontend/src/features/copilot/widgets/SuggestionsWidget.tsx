/**
 * SuggestionsWidget — compact list of improvement suggestions.
 */

export function SuggestionsWidget({ data }: { data: Record<string, unknown> }) {
  const suggestions = (data.sugestões ?? []) as string[];
  if (suggestions.length === 0) return null;

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
        Sugestões
      </div>
      {suggestions.map((s, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            gap: 6,
            fontSize: 10,
            color: 'var(--text-primary)',
            padding: '3px 0',
          }}
        >
          <span style={{ color: 'var(--accent)', flexShrink: 0 }}>{'→'}</span>
          <span>{s}</span>
        </div>
      ))}
    </div>
  );
}

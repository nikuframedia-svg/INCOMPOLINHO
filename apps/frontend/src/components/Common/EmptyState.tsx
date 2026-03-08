interface EmptyStateProps {
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: 'search' | 'data' | 'error' | 'empty';
}

const ICONS: Record<string, JSX.Element> = {
  search: (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--text-muted)"
      strokeWidth="1.5"
    >
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
    </svg>
  ),
  data: (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--text-muted)"
      strokeWidth="1.5"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M9 21V9" />
    </svg>
  ),
  error: (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--semantic-red)"
      strokeWidth="1.5"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  ),
  empty: (
    <svg
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--text-muted)"
      strokeWidth="1.5"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  ),
};

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  icon = 'empty',
}: EmptyStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '3rem',
        gap: '1rem',
        textAlign: 'center',
      }}
    >
      {ICONS[icon]}
      <h3
        style={{
          fontSize: '1.125rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
          margin: 0,
        }}
      >
        {title}
      </h3>
      {description && (
        <p
          style={{
            fontSize: '0.875rem',
            color: 'var(--text-muted)',
            margin: 0,
            maxWidth: '360px',
          }}
        >
          {description}
        </p>
      )}
      {actionLabel && onAction && (
        <button
          onClick={onAction}
          style={{
            marginTop: '0.5rem',
            padding: '0.5rem 1.5rem',
            background: 'var(--accent)',
            color: 'white',
            border: 'none',
            borderRadius: 'var(--radius-lg)',
            fontSize: '0.875rem',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}

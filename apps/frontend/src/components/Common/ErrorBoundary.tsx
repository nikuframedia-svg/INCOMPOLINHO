import React from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ErrorWithCorrelation extends Error {
  correlation_id?: string;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  /** Optional custom fallback component. Receives error and resetErrorBoundary. */
  fallback?: React.ComponentType<{
    error: Error;
    resetErrorBoundary: () => void;
  }>;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  container: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '300px',
    padding: 'var(--space-24)',
  } as React.CSSProperties,

  card: {
    background: 'var(--bg-card)',
    borderRadius: 'var(--radius-lg)',
    border: '1px solid var(--semantic-red)',
    padding: 'var(--space-24)',
    maxWidth: '560px',
    width: '100%',
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    gap: 'var(--space-16)',
    textAlign: 'center' as const,
  } as React.CSSProperties,

  icon: {
    width: 48,
    height: 48,
    borderRadius: '50%',
    background: 'rgba(239, 68, 68, 0.1)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  } as React.CSSProperties,

  title: {
    fontSize: 'var(--text-lg)',
    fontWeight: 600,
    color: 'var(--text-primary)',
    margin: 0,
  } as React.CSSProperties,

  message: {
    fontSize: 'var(--text-base)',
    color: 'var(--text-secondary)',
    margin: 0,
    lineHeight: 1.6,
    wordBreak: 'break-word' as const,
  } as React.CSSProperties,

  correlationId: {
    fontSize: 'var(--text-sm)',
    color: 'var(--text-muted)',
    fontFamily: 'var(--font-mono)',
    background: 'var(--bg-base)',
    padding: '0.25rem 0.75rem',
    borderRadius: 'var(--radius-sm)',
    margin: 0,
  } as React.CSSProperties,

  buttonRow: {
    display: 'flex',
    gap: 'var(--space-8)',
    marginTop: 'var(--space-8)',
  } as React.CSSProperties,

  buttonPrimary: {
    padding: '0.5rem 1.5rem',
    background: 'var(--accent)',
    color: 'white',
    border: 'none',
    borderRadius: 'var(--radius-md)',
    fontSize: 'var(--text-base)',
    fontWeight: 600,
    cursor: 'pointer',
    transition: '0.15s ease',
  } as React.CSSProperties,

  buttonSecondary: {
    padding: '0.5rem 1.5rem',
    background: 'var(--bg-base)',
    color: 'var(--text-secondary)',
    border: '1px solid var(--bg-raised)',
    borderRadius: 'var(--radius-md)',
    fontSize: 'var(--text-base)',
    fontWeight: 500,
    cursor: 'pointer',
    transition: '0.15s ease',
  } as React.CSSProperties,
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught error:', error, errorInfo);
  }

  resetErrorBoundary = () => {
    this.setState({ hasError: false, error: null });
  };

  handleCopyError = async () => {
    const { error } = this.state;
    if (!error) return;

    const correlationId = (error as ErrorWithCorrelation).correlation_id;
    const parts = [
      `Error: ${error.message}`,
      correlationId ? `Correlation ID: ${correlationId}` : null,
      error.stack ? `\nStack trace:\n${error.stack}` : null,
    ].filter(Boolean);

    try {
      await navigator.clipboard.writeText(parts.join('\n'));
    } catch {
      // Fallback for environments without clipboard API
      const textarea = document.createElement('textarea');
      textarea.value = parts.join('\n');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
  };

  render() {
    const { hasError, error } = this.state;
    const { children, fallback: FallbackComponent } = this.props;

    if (!hasError || !error) {
      return children;
    }

    // Use custom fallback if provided
    if (FallbackComponent) {
      return <FallbackComponent error={error} resetErrorBoundary={this.resetErrorBoundary} />;
    }

    const correlationId = (error as ErrorWithCorrelation).correlation_id;

    return (
      <div style={styles.container}>
        <div style={styles.card}>
          {/* Error icon */}
          <div style={styles.icon}>
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--semantic-red)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>

          <h3 style={styles.title}>Something went wrong</h3>

          <p style={styles.message}>{error.message || 'An unexpected error occurred.'}</p>

          {correlationId && <p style={styles.correlationId}>Correlation ID: {correlationId}</p>}

          <div style={styles.buttonRow}>
            <button
              onClick={this.resetErrorBoundary}
              style={styles.buttonPrimary}
              onMouseEnter={(e) => {
                e.currentTarget.style.opacity = '0.9';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = '1';
              }}
            >
              Try Again
            </button>
            <button
              onClick={this.handleCopyError}
              style={styles.buttonSecondary}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--bg-raised)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'var(--bg-base)';
              }}
            >
              Copy Error
            </button>
          </div>
        </div>
      </div>
    );
  }
}

export { ErrorBoundary };

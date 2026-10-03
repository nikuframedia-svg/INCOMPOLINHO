import { Component, type ErrorInfo, type ReactNode } from "react";
import { T } from "../theme/tokens";

interface PageErrorBoundaryProps {
  children: ReactNode;
}

interface PageErrorBoundaryState {
  hasError: boolean;
}

export class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): PageErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Page rendering failed", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        role="alert"
        style={{
          margin: 24,
          padding: 20,
          maxWidth: 560,
          border: `1px solid ${T.red}55`,
          borderRadius: T.radius,
          background: T.card,
        }}
      >
        <div style={{ color: T.primary, fontSize: 15, fontWeight: 600 }}>
          Não foi possível mostrar esta página
        </div>
        <p style={{ color: T.secondary, fontSize: 12, lineHeight: 1.6, margin: "8px 0 14px" }}>
          O plano não foi alterado. Tenta abrir novamente esta página; se o problema continuar, recarrega a aplicação.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false })}
            style={{
              background: T.blue,
              border: 0,
              borderRadius: 8,
              color: "white",
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: 12,
              fontWeight: 600,
              padding: "7px 12px",
            }}
          >
            Tentar novamente
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              background: T.elevated,
              border: `1px solid ${T.border}`,
              borderRadius: 8,
              color: T.secondary,
              cursor: "pointer",
              fontFamily: "inherit",
              fontSize: 12,
              padding: "7px 12px",
            }}
          >
            Recarregar aplicação
          </button>
        </div>
      </div>
    );
  }
}

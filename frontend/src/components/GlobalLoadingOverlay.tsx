import type { CSSProperties } from "react";
import { T } from "../theme/tokens";
import { useAppStore } from "../stores/useAppStore";

const overlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 9999,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "rgba(26, 23, 20, 0.46)",
  backdropFilter: "brightness(0.72) blur(1.5px)",
  WebkitBackdropFilter: "brightness(0.72) blur(1.5px)",
  pointerEvents: "all",
};

const panelStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 14,
  minWidth: 220,
  padding: "18px 22px",
  borderRadius: T.radiusSm,
  background: T.card,
  border: `1px solid ${T.border}`,
  boxShadow: "0 18px 48px rgba(26, 23, 20, 0.24)",
  color: T.primary,
  fontFamily: T.sans,
  fontSize: 15,
  fontWeight: 700,
};

const spinnerStyle: CSSProperties = {
  width: 26,
  height: 26,
  borderRadius: "50%",
  border: `3px solid ${T.border}`,
  borderTopColor: T.blue,
  animation: "global-loading-spin 0.8s linear infinite",
  flexShrink: 0,
};

export function GlobalLoadingOverlay() {
  const blockingRequests = useAppStore((s) => s.blockingRequests);
  const blockingMessage = useAppStore((s) => s.blockingMessage);
  if (blockingRequests <= 0) return null;

  return (
    <div
      aria-busy="true"
      aria-live="polite"
      role="alert"
      style={overlayStyle}
    >
      <style>
        {"@keyframes global-loading-spin { to { transform: rotate(360deg); } }"}
      </style>
      <div style={panelStyle}>
        <div style={spinnerStyle} />
        <span>{blockingMessage || "A carregar…"}</span>
      </div>
    </div>
  );
}

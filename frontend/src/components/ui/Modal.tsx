import { T } from "../../theme/tokens";

interface Props {
  children: React.ReactNode;
  onClose: () => void;
  title: string;
}

export function Modal({ children, onClose, title }: Props) {
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: T.card,
          borderRadius: 16,
          padding: 28,
          width: 400,
          maxHeight: "80vh",
          overflowY: "auto",
          border: `1px solid ${T.border}`,
          boxShadow: "0 24px 80px rgba(0,0,0,0.15)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <span style={{ fontSize: 17, fontWeight: 600, color: T.primary }}>{title}</span>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", color: T.tertiary, cursor: "pointer", fontSize: 18, fontFamily: "inherit" }}
          >
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

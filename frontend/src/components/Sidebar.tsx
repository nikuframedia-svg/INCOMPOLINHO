import { T } from "../theme/tokens";
import { useAppStore } from "../stores/useAppStore";
import { Label } from "./ui/Label";

const NAV = [
  { id: "console", label: "Hoje" },
  { id: "gantt", label: "Plano" },
  { id: "capacity", label: "Carga e capacidade" },
  { id: "deliveries", label: "Entregas" },
  { id: "risk", label: "Risco" },
  { id: "config", label: "Configuração" },
];

export function Sidebar() {
  const page = useAppStore((s) => s.activePage);
  const setPage = useAppStore((s) => s.setPage);
  const dataset = useAppStore((s) => s.dataset);
  const hasData = useAppStore((s) => s.hasData);
  const accessMode = useAppStore((s) => s.accessMode);
  const setAccessMode = useAppStore((s) => s.setAccessMode);

  return (
    <nav
      className="app-sidebar"
      style={{
        width: 200,
        flexShrink: 0,
        background: T.sidebar,
        borderRight: `1px solid ${T.border}`,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div className="app-sidebar-brand" style={{ padding: "20px 20px 24px" }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: T.primary, letterSpacing: 0 }}>
          ProdPlan ONE
        </div>
        <div style={{ fontSize: 11, color: T.tertiary, marginTop: 2 }}>Incompol</div>
      </div>

      <div className="app-sidebar-menu" style={{ flex: 1, padding: "0 8px", display: "flex", flexDirection: "column", gap: 1 }}>
        {NAV.map((n) => {
          const active = page === n.id;
          return (
            <button
              key={n.id}
              onClick={() => setPage(n.id)}
              style={{
                background: active ? "#E8E2D8" : "transparent",
                border: "none",
                borderRadius: 8,
                padding: "8px 12px",
                color: active ? T.primary : T.secondary,
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                cursor: "pointer",
                textAlign: "left",
                transition: "all 0.15s",
                width: "100%",
                fontFamily: "inherit",
              }}
            >
              {n.label}
            </button>
          );
        })}
      </div>

      {hasData && dataset && (
        <div className="app-sidebar-dataset" style={{ padding: 16, borderTop: `1px solid ${T.border}` }}>
          <Label>ISOP ativo</Label>
          <div
            title={dataset.filename}
            style={{
              marginTop: 6,
              fontSize: 12,
              fontWeight: 600,
              color: T.primary,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {dataset.filename}
          </div>
          <div style={{ marginTop: 8, fontSize: 11, color: T.secondary }}>
            {dataset.n_ops} operações
          </div>
        </div>
      )}

      <div className="app-sidebar-profile" style={{ padding: 16, borderTop: `1px solid ${T.border}` }}>
        <Label>Perfil</Label>
        <div
          role="group"
          aria-label="Perfil de utilização"
          style={{
            marginTop: 8,
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 4,
            background: T.elevated,
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            padding: 3,
          }}
        >
          {([
            ["edit", "Editar"],
            ["view", "Consulta"],
          ] as const).map(([mode, label]) => {
            const active = accessMode === mode;
            return (
              <button
                key={mode}
                type="button"
                onClick={() => setAccessMode(mode)}
                title={mode === "edit" ? "Permite guardar e recalcular" : "Bloqueia alterações ao plano e à configuração"}
                style={{
                  border: 0,
                  borderRadius: 6,
                  background: active ? T.card : "transparent",
                  color: active ? T.primary : T.secondary,
                  cursor: "pointer",
                  fontSize: 11,
                  fontWeight: active ? 700 : 500,
                  padding: "5px 6px",
                  fontFamily: "inherit",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
}

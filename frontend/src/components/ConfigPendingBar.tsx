import { T } from "../theme/tokens";
import { Card } from "./ui/Card";

/**
 * «N alterações por aplicar» (decisão de 16/10/2026): every pending
 * Configuração change in one list, removed one by one with «×», applied
 * together with one «Aplicar» or dropped with «Descartar».
 */
export function ConfigPendingBar({
  lines,
  orphanCount = 0,
  busy,
  disabled,
  onRemove,
  onApply,
  onDiscard,
}: {
  lines: { id: string; text: string }[];
  /** References the pending changes leave with no active machine. */
  orphanCount?: number;
  /** A replan with these changes is running: nothing can be removed or applied. */
  busy: boolean;
  /** Read-only profile or another candidate waiting: the list cannot be applied. */
  disabled: boolean;
  onRemove: (id: string) => void;
  onApply: () => void;
  onDiscard: () => void;
}) {
  if (lines.length === 0) return null;
  const locked = busy || disabled;
  const title = `${lines.length} ${lines.length === 1 ? "alteração por aplicar" : "alterações por aplicar"}`;
  return (
    <Card style={{ borderColor: T.blue, padding: "12px 16px" }}>
      <section aria-label="Alterações por aplicar" style={{ display: "grid", gap: 8 }}>
        {orphanCount > 0 && (
          <div role="alert" style={{ color: T.red, fontSize: 12, fontWeight: 600 }}>
            {`Atenção: ${orphanCount} ${orphanCount === 1 ? "referência fica" : "referências ficam"} sem máquina ativa e passa${orphanCount === 1 ? "" : "m"} a atrasada${orphanCount === 1 ? "" : "s"}.`}
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ color: T.primary, fontSize: 13, fontWeight: 700 }}>{title}</span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button
              type="button"
              disabled={locked}
              onClick={onApply}
              style={{
                background: locked ? T.elevated : T.blue,
                border: "none",
                borderRadius: 8,
                padding: "6px 18px",
                color: locked ? T.tertiary : "#fff",
                cursor: locked ? "default" : "pointer",
                fontFamily: "inherit",
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              {busy ? "A aplicar…" : "Aplicar"}
            </button>
            <button
              type="button"
              disabled={locked}
              onClick={onDiscard}
              style={{
                background: T.elevated,
                border: `1px solid ${T.border}`,
                borderRadius: 8,
                padding: "6px 14px",
                color: T.secondary,
                cursor: locked ? "default" : "pointer",
                fontFamily: "inherit",
                fontSize: 12,
              }}
            >
              Descartar
            </button>
          </span>
        </div>
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 2 }}>
          {lines.map((line) => (
            <li key={line.id} style={{ display: "flex", alignItems: "center", gap: 6, color: T.primary, fontSize: 12 }}>
              <span style={{ flex: 1 }}>{line.text}</span>
              <button
                type="button"
                disabled={locked}
                aria-label={`Retirar: ${line.text}`}
                title="Retirar da lista"
                onClick={() => onRemove(line.id)}
                style={{
                  background: "none",
                  border: "none",
                  color: locked ? T.tertiary : T.red,
                  cursor: locked ? "default" : "pointer",
                  fontSize: 15,
                  minWidth: 28,
                  minHeight: 28,
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      </section>
    </Card>
  );
}

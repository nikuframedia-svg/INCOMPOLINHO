import { T } from "../theme/tokens";

/**
 * The concrete causes of a refused change, under its message (decisão de
 * 15/10/2026). Renders nothing when there are none.
 */
export function RefusalDetails({ causes }: { causes: readonly string[] }) {
  if (!causes.length) return null;
  return (
    <div style={{ marginTop: 6, fontSize: 11, color: T.secondary, fontWeight: 400 }}>
      <div style={{ fontWeight: 700, color: T.primary }}>Porquê:</div>
      <ul style={{ margin: "4px 0 0", paddingLeft: 18, display: "grid", gap: 3 }}>
        {causes.map((cause) => (
          <li key={cause}>{cause}</li>
        ))}
      </ul>
    </div>
  );
}

import { T } from "../theme/tokens";
import { getJournal } from "../api/endpoints";
import { usePlanQuery } from "../hooks/usePlanQuery";
import { Card } from "../components/ui/Card";
import { Pill } from "../components/ui/Pill";

const severityColor = (s: string) => {
  if (s === "error") return T.red;
  if (s === "warn" || s === "warning") return T.orange;
  return T.green;
};

export function JournalPage() {
  const { data: entries, error } = usePlanQuery("journal", getJournal);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!entries) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;
  if (entries.length === 0) return <div style={{ color: T.secondary, padding: 24 }}>Sem entradas no journal.</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map((e, i) => (
        <Card key={i} style={{ padding: "10px 16px" }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Pill color={severityColor(e.severity)}>{e.severity}</Pill>
            <span style={{ fontSize: 12, fontWeight: 600, color: T.primary }}>{e.step}</span>
            <span style={{ fontSize: 12, color: T.secondary, flex: 1 }}>{e.message}</span>
            <span style={{ fontSize: 11, color: T.tertiary, fontFamily: T.mono, flexShrink: 0 }}>
              {e.elapsed_ms.toFixed(1)}ms
            </span>
          </div>
        </Card>
      ))}
    </div>
  );
}

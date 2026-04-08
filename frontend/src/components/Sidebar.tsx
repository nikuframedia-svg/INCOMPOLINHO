import { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { useAppStore } from "../stores/useAppStore";
import { getTrust } from "../api/endpoints";
import type { TrustIndex } from "../api/types";
import { ProgressBar } from "./ui/ProgressBar";
import { Label } from "./ui/Label";

const NAV = [
  { id: "console", label: "Consola" },
  { id: "gantt", label: "Produção" },
  { id: "stock", label: "Stock" },
  { id: "risk", label: "Risco" },
  { id: "expedition", label: "Expedição" },
  { id: "sim", label: "Simulador" },
  { id: "config", label: "Configuração" },
  { id: "journal", label: "Journal" },
  { id: "rules", label: "Regras" },
];

export function Sidebar() {
  const page = useAppStore((s) => s.activePage);
  const setPage = useAppStore((s) => s.setPage);
  const trustScore = useAppStore((s) => s.trustScore);
  const hasData = useAppStore((s) => s.hasData);
  const [trust, setTrust] = useState<TrustIndex | null>(null);

  useEffect(() => {
    if (!hasData) return;
    getTrust().then(setTrust).catch(() => {});
  }, [hasData]);

  return (
    <nav
      style={{
        width: 200,
        flexShrink: 0,
        background: T.sidebar,
        borderRight: `1px solid ${T.border}`,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ padding: "20px 20px 24px" }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: T.primary, letterSpacing: "-0.02em" }}>
          ProdPlan ONE
        </div>
        <div style={{ fontSize: 11, color: T.tertiary, marginTop: 2 }}>Incompol</div>
      </div>

      <div style={{ flex: 1, padding: "0 8px", display: "flex", flexDirection: "column", gap: 1 }}>
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

      {trustScore !== null && (
        <div style={{ padding: 16, borderTop: `1px solid ${T.border}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <Label>Trust Index</Label>
            <span
              style={{
                fontSize: 18,
                fontWeight: 600,
                color: trustScore >= 80 ? T.green : T.orange,
                fontFamily: T.mono,
              }}
            >
              {trustScore}
            </span>
          </div>
          <div style={{ marginTop: 6 }}>
            <ProgressBar
              value={trustScore}
              color={trustScore >= 80 ? T.green : T.orange}
              height={3}
              bg="#EFEBE3"
            />
          </div>
          {trust?.dimensions && trust.dimensions.length > 0 && (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
              {trust.dimensions.map((d) => {
                const c = d.score >= 80 ? T.green : d.score >= 50 ? T.orange : T.red;
                return (
                  <div key={d.name}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                      <span style={{ fontSize: 10, color: T.tertiary }}>{d.name}</span>
                      <span style={{ fontSize: 10, color: c, fontFamily: T.mono }}>{d.score}</span>
                    </div>
                    <ProgressBar value={d.score} color={c} height={2} bg="#EFEBE3" />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </nav>
  );
}

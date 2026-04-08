import { useState } from "react";
import { T } from "../theme/tokens";
import { useAppStore } from "../stores/useAppStore";
import { useDataStore } from "../stores/useDataStore";
import { recalculate } from "../api/endpoints";
import { TH } from "../constants/thresholds";
import { Sidebar } from "./Sidebar";
import { ChatPanel } from "./ChatPanel";
import { UploadZone } from "./ui/UploadZone";
import { ConsolePage } from "../pages/ConsolePage";
import { GanttPage } from "../pages/GanttPage";
import { StockPage } from "../pages/StockPage";
import { RiskPage } from "../pages/RiskPage";
import { SimulatorPage } from "../pages/SimulatorPage";
import { ConfigPage } from "../pages/ConfigPage";
import { ExpeditionPage } from "../pages/ExpeditionPage";
import { JournalPage } from "../pages/JournalPage";
import { RulesPage } from "../pages/RulesPage";

const NAV_LABELS: Record<string, string> = {
  console: "Consola",
  gantt: "Produção",
  stock: "Stock",
  risk: "Risco",
  expedition: "Expedição",
  sim: "Simulador",
  config: "Configuração",
  journal: "Journal",
  rules: "Regras",
};

function PageContent() {
  const page = useAppStore((s) => s.activePage);
  switch (page) {
    case "console": return <ConsolePage />;
    case "gantt": return <GanttPage />;
    case "stock": return <StockPage />;
    case "risk": return <RiskPage />;
    case "expedition": return <ExpeditionPage />;
    case "sim": return <SimulatorPage />;
    case "config": return <ConfigPage />;
    case "journal": return <JournalPage />;
    case "rules": return <RulesPage />;
    default: return <ConsolePage />;
  }
}

export function Shell() {
  const hasData = useAppStore((s) => s.hasData);
  const chatOpen = useAppStore((s) => s.chatOpen);
  const toggleChat = useAppStore((s) => s.toggleChat);
  const page = useAppStore((s) => s.activePage);
  const score = useDataStore((s) => s.score);
  const refreshAll = useDataStore((s) => s.refreshAll);
  const isSimulated = useDataStore((s) => s.isSimulated);
  const simulationSummary = useDataStore((s) => s.simulationSummary);
  const revert = useDataStore((s) => s.revert);
  const [recalcing, setRecalcing] = useState(false);
  const [reverting, setReverting] = useState(false);

  const handleRevert = async () => {
    setReverting(true);
    try { await revert(); } catch (err) { console.error("Revert failed:", err); }
    setReverting(false);
  };

  const handleRecalc = async () => {
    setRecalcing(true);
    try {
      await recalculate();
      await refreshAll();
    } catch (err) { console.error("Recalculate failed:", err); }
    setRecalcing(false);
  };

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        background: T.bg,
        color: T.primary,
        fontFamily: T.sans,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      <Sidebar />

      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header
          style={{
            height: 48,
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            borderBottom: `1px solid ${T.border}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 600, color: T.primary }}>{NAV_LABELS[page] || page}</span>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {hasData && score && (
              <div style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: (score.otd ?? 0) >= TH.OTD_GREEN ? T.green : T.orange, fontFamily: T.mono, fontWeight: 500 }}>
                  OTD {score.otd?.toFixed(1)}%
                </span>
                <span style={{ fontSize: 11, color: (score.otd_d ?? 0) >= TH.OTD_D_GREEN ? T.green : T.orange, fontFamily: T.mono, fontWeight: 500 }}>
                  OTD-D {score.otd_d?.toFixed(1)}%
                </span>
              </div>
            )}
            {hasData && (
              <>
                <button
                  onClick={() => refreshAll()}
                  title="Actualizar dados"
                  style={{
                    background: "transparent",
                    border: `1px solid ${T.border}`,
                    color: T.secondary,
                    borderRadius: 8,
                    padding: "5px 10px",
                    cursor: "pointer",
                    fontSize: 12,
                    fontFamily: "inherit",
                  }}
                >
                  ↻
                </button>
                <button
                  onClick={handleRecalc}
                  disabled={recalcing || isSimulated}
                  title={isSimulated ? "Reverta o cenario simulado primeiro" : "Recalcular schedule"}
                  style={{
                    background: "transparent",
                    border: `1px solid ${T.border}`,
                    color: (recalcing || isSimulated) ? T.tertiary : T.secondary,
                    borderRadius: 8,
                    padding: "5px 10px",
                    cursor: (recalcing || isSimulated) ? "default" : "pointer",
                    fontSize: 11,
                    fontFamily: "inherit",
                  }}
                >
                  {recalcing ? "..." : "Recalcular"}
                </button>
              </>
            )}
            <button
              onClick={toggleChat}
              style={{
                background: chatOpen ? `${T.blue}18` : "transparent",
                border: `1px solid ${chatOpen ? `${T.blue}44` : T.border}`,
                color: chatOpen ? T.blue : T.secondary,
                borderRadius: 8,
                padding: "5px 12px",
                cursor: "pointer",
                fontSize: 12,
                fontWeight: 500,
                fontFamily: "inherit",
              }}
            >
              Copilot
            </button>
          </div>
        </header>

        {isSimulated && (
          <div style={{
            padding: "8px 24px",
            background: `${T.orange}15`,
            borderBottom: `1px solid ${T.orange}44`,
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexShrink: 0,
          }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: T.orange }}>Cenario simulado</span>
            {simulationSummary.length > 0 && (
              <span style={{ fontSize: 11, color: T.secondary, flex: 1 }}>
                {simulationSummary[0]}
              </span>
            )}
            <button
              onClick={handleRevert}
              disabled={reverting}
              style={{
                background: "transparent",
                border: `1px solid ${T.orange}`,
                color: T.orange,
                borderRadius: 6,
                padding: "4px 12px",
                cursor: reverting ? "default" : "pointer",
                fontSize: 11,
                fontWeight: 600,
                fontFamily: "inherit",
              }}
            >
              {reverting ? "A reverter..." : "Reverter"}
            </button>
          </div>
        )}

        <div style={{ flex: 1, overflow: "auto", padding: 24 }}>
          {hasData ? <PageContent /> : <UploadZone />}
        </div>
      </main>

      {chatOpen && <ChatPanel />}
    </div>
  );
}

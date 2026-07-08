import { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { ACTIVE_DATASET_KEY, useAppStore } from "../stores/useAppStore";
import { useDataStore } from "../stores/useDataStore";
import { getHealth, getTrust, recalculate } from "../api/endpoints";
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
import type { MutationInput } from "../api/types";

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

function mutationLabel(mutation: MutationInput): string {
  const p = mutation.params;
  switch (mutation.type) {
    case "machine_down":
      return `${p.machine_id ?? p.machine ?? "Máquina"} parada d${p.start ?? p.from_day ?? "?"}–${p.end ?? p.to_day ?? "?"}`;
    case "tool_down":
      return `${p.tool_id ?? p.tool ?? "Ferramenta"} parada d${p.start ?? p.from_day ?? "?"}–${p.end ?? p.to_day ?? "?"}`;
    case "rush_order":
      return `Urgente ${p.sku ?? ""} ${p.qty ?? ""} pç até d${p.deadline_day ?? p.deadline ?? "?"}`;
    case "oee_change":
      return `OEE ${p.tool_id ?? p.machine_id ?? ""} → ${p.new_oee ?? p.oee ?? "?"}`;
    default:
      return mutation.type.replaceAll("_", " ");
  }
}

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
  const setHasData = useAppStore((s) => s.setHasData);
  const setTrust = useAppStore((s) => s.setTrust);
  const clearTrust = useAppStore((s) => s.clearTrust);
  const dataset = useAppStore((s) => s.dataset);
  const setDataset = useAppStore((s) => s.setDataset);
  const chatOpen = useAppStore((s) => s.chatOpen);
  const toggleChat = useAppStore((s) => s.toggleChat);
  const page = useAppStore((s) => s.activePage);
  const setPage = useAppStore((s) => s.setPage);
  const score = useDataStore((s) => s.score);
  const refreshAll = useDataStore((s) => s.refreshAll);
  const isSimulated = useDataStore((s) => s.isSimulated);
  const activeMutations = useDataStore((s) => s.activeMutations);
  const simulationSummary = useDataStore((s) => s.simulationSummary);
  const revert = useDataStore((s) => s.revert);
  const clearData = useDataStore((s) => s.clear);
  const [checkingData, setCheckingData] = useState(true);
  const [recalcing, setRecalcing] = useState(false);
  const [reverting, setReverting] = useState(false);

  useEffect(() => {
    let alive = true;

    async function hydrateFromBackend() {
      try {
        const health = await getHealth();
        if (!alive) return;
        const activeDatasetId = sessionStorage.getItem(ACTIVE_DATASET_KEY);
        if (health.has_data && health.dataset && activeDatasetId === health.dataset.id) {
          setDataset(health.dataset);
          await refreshAll();
          try {
            const trust = await getTrust();
            if (alive) setTrust(trust.score, trust.gate);
          } catch {
            // Trust is helpful for the sidebar, but the dashboard can load without it.
          }
          if (alive) setHasData(true);
        } else {
          clearData();
          clearTrust();
          setDataset(null);
          setHasData(false);
          if (!health.has_data) sessionStorage.removeItem(ACTIVE_DATASET_KEY);
        }
      } catch {
        clearData();
        clearTrust();
        setDataset(null);
        setHasData(false);
        sessionStorage.removeItem(ACTIVE_DATASET_KEY);
      } finally {
        if (alive) setCheckingData(false);
      }
    }

    hydrateFromBackend();
    return () => {
      alive = false;
    };
  }, [clearData, clearTrust, refreshAll, setDataset, setHasData, setTrust]);

  const handleChangeIsop = () => {
    sessionStorage.removeItem(ACTIVE_DATASET_KEY);
    clearData();
    clearTrust();
    setDataset(null);
    setHasData(false);
    setPage("console");
  };

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
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: T.primary }}>
              {NAV_LABELS[page] || page}
            </div>
            {hasData && dataset && (
              <div
                title={dataset.filename}
                style={{
                  fontSize: 11,
                  color: T.tertiary,
                  marginTop: 2,
                  maxWidth: 440,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                ISOP {dataset.filename} · {dataset.n_ops} ops · {dataset.n_segments} segmentos
              </div>
            )}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {hasData && score && (
              <div style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: (score.otd ?? 0) >= TH.OTD_GREEN ? T.green : T.orange, fontFamily: T.mono, fontWeight: 500 }}>
                  OTD {score.otd?.toFixed(1)}%
                </span>
                <span style={{ fontSize: 11, color: (score.otd_d ?? 0) >= TH.OTD_D_GREEN ? T.green : T.orange, fontFamily: T.mono, fontWeight: 500 }}>
                  OTD-D {score.otd_d?.toFixed(1)}%
                </span>
                {dataset && (
                  <>
                    <span style={{ fontSize: 11, color: T.green, fontFamily: T.mono, fontWeight: 500 }}>
                      Trust {dataset.trust_score}
                    </span>
                    <span style={{ fontSize: 11, color: dataset.tardy_count ? T.orange : T.green, fontFamily: T.mono, fontWeight: 500 }}>
                      {dataset.tardy_count ?? 0} atrasos
                    </span>
                  </>
                )}
              </div>
            )}
            {hasData && (
              <>
                <button
                  onClick={handleChangeIsop}
                  title="Escolher outro ficheiro ISOP"
                  style={{
                    background: "transparent",
                    border: `1px solid ${T.border}`,
                    color: T.secondary,
                    borderRadius: 8,
                    padding: "5px 10px",
                    cursor: "pointer",
                    fontSize: 11,
                    fontFamily: "inherit",
                  }}
                >
                  Trocar ISOP
                </button>
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
            <span style={{ fontSize: 11, color: T.secondary, flex: 1 }}>
              {activeMutations.length > 0
                ? activeMutations.map(mutationLabel).join(" · ")
                : simulationSummary[0] ?? "Mutacoes aplicadas no plano activo"}
            </span>
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
          {checkingData ? (
            <div style={{ color: T.secondary, padding: 24 }}>A verificar dados...</div>
          ) : hasData ? (
            <PageContent />
          ) : (
            <UploadZone />
          )}
        </div>
      </main>

      {chatOpen && <ChatPanel />}
    </div>
  );
}

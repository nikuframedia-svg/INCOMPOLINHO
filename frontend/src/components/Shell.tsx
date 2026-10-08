import { useEffect, useState, type CSSProperties } from "react";
import { T } from "../theme/tokens";
import { ACTIVE_DATASET_KEY, useAppStore } from "../stores/useAppStore";
import { loadWarnings, stopLoadPolling, useLoadStore } from "../stores/useLoadStore";
import { useDataStore } from "../stores/useDataStore";
import { assertRefreshed, RefreshError, refreshAfterCommit } from "../lib/refreshOutcome";
import { getHealth, getToday, recalculate } from "../api/endpoints";
import { staleIsopWarning } from "../lib/recalcGuard";
import { TH } from "../constants/thresholds";
import { approvalGateFromError, approvalImpactMessage, approvalReasonLabel, decisionReasons } from "../lib/gateApproval";
import { Sidebar } from "./Sidebar";
import { ChatPanel } from "./ChatPanel";
import { PageErrorBoundary } from "./PageErrorBoundary";
import { GlobalLoadingOverlay } from "./GlobalLoadingOverlay";
import { UploadZone } from "./ui/UploadZone";
import { ConsolePage } from "../pages/ConsolePage";
import { GanttPage } from "../pages/GanttPage";
import { RiskPage } from "../pages/RiskPage";
import { ConfigPage } from "../pages/ConfigPage";
import { DeliveriesPage } from "../pages/DeliveriesPage";
import { JournalPage } from "../pages/JournalPage";
import { RulesPage } from "../pages/RulesPage";
import { CapacityPage } from "../pages/CapacityPage";
import { useConfirm } from "./ui/confirmContext";
import type { MutationInput } from "../api/types";

type OperationStatus = {
  phase: "idle" | "pending" | "success" | "error";
  message: string;
  detail: string;
};

const NAV_LABELS: Record<string, string> = {
  console: "Hoje",
  gantt: "Plano",
  capacity: "Carga e capacidade",
  deliveries: "Entregas",
  risk: "Risco",
  config: "Configuração",
  journal: "Journal",
  rules: "Regras",
};

const DELIVERIES_FOCUS_KEY = "pp1DeliveriesFocus";

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
    case "capacity": return <CapacityPage />;
    case "deliveries": return <DeliveriesPage />;
    case "risk": return <RiskPage />;
    case "config": return <ConfigPage />;
    case "journal": return <JournalPage />;
    case "rules": return <RulesPage />;
    default: return <ConsolePage />;
  }
}

export function Shell() {
  const { confirm } = useConfirm();
  const hasData = useAppStore((s) => s.hasData);
  const loadJobId = useLoadStore((s) => s.jobId);
  const loadOpen = useLoadStore((s) => s.isOpen);
  const loadJob = useLoadStore((s) => s.job);
  const loadCompletion = useLoadStore((s) => s.completion);

  useEffect(() => {
    useLoadStore.getState().resume();
    return stopLoadPolling;
  }, []);
  const setHasData = useAppStore((s) => s.setHasData);
  const clearTrust = useAppStore((s) => s.clearTrust);
  const dataset = useAppStore((s) => s.dataset);
  const setDataset = useAppStore((s) => s.setDataset);
  const chatOpen = useAppStore((s) => s.chatOpen);
  const toggleChat = useAppStore((s) => s.toggleChat);
  const page = useAppStore((s) => s.activePage);
  const setPage = useAppStore((s) => s.setPage);
  const score = useDataStore((s) => s.score);
  const gateReport = useDataStore((s) => s.gateReport);
  const refreshAll = useDataStore((s) => s.refreshAll);
  const isSimulated = useDataStore((s) => s.isSimulated);
  const activeMutations = useDataStore((s) => s.activeMutations);
  const simulationSummary = useDataStore((s) => s.simulationSummary);
  const manualEdits = useDataStore((s) => s.manualEdits);
  const canRevert = useDataStore((s) => s.canRevert);
  const revert = useDataStore((s) => s.revert);
  const clearData = useDataStore((s) => s.clear);
  const [checkingData, setCheckingData] = useState(true);
  const [backendUnavailable, setBackendUnavailable] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [recalcing, setRecalcing] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [copilotAvailable, setCopilotAvailable] = useState(false);
  const [copilotReason, setCopilotReason] = useState("A verificar a disponibilidade do Copilot…");
  const [operationStatus, setOperationStatus] = useState<OperationStatus>({
    phase: "idle",
    message: "",
    detail: "",
  });
  const operationPending = refreshing || recalcing || reverting;

  useEffect(() => {
    if (operationStatus.phase !== "success") return;
    const timeout = window.setTimeout(() => {
      setOperationStatus({ phase: "idle", message: "", detail: "" });
    }, 4000);
    return () => window.clearTimeout(timeout);
  }, [operationStatus.phase]);

  useEffect(() => {
    let alive = true;
    let retryTimer: number | undefined;

    async function hydrateFromBackend() {
      // The loading workflow recovers and refreshes its own result. Do not race
      // an older health response against its application of the new dataset.
      if (useLoadStore.getState().jobId) {
        setCheckingData(false);
        return;
      }
      try {
        const health = await getHealth();
        if (!alive || useLoadStore.getState().jobId) return;
        setBackendUnavailable(false);
        setCopilotAvailable(health.copilot?.available ?? false);
        setCopilotReason(
          health.copilot?.reason
          || (health.copilot?.available ? "" : "O Copilot não está configurado."),
        );
        if (health.has_data && health.dataset) {
          assertRefreshed(await refreshAll());
          const currentDataset = useAppStore.getState().dataset;
          if (currentDataset) sessionStorage.setItem(ACTIVE_DATASET_KEY, currentDataset.id);
          if (alive) setHasData(true);
        } else {
          clearData();
          clearTrust();
          setDataset(null);
          setHasData(false);
          if (!health.has_data) sessionStorage.removeItem(ACTIVE_DATASET_KEY);
        }
      } catch {
        if (!alive) return;
        // A falha do servidor não significa que o ISOP deixou de existir.
        // Preserva a seleção local e tenta novamente enquanto o serviço reinicia.
        setBackendUnavailable(true);
        retryTimer = window.setTimeout(hydrateFromBackend, 2000);
      } finally {
        if (alive) setCheckingData(false);
      }
    }

    hydrateFromBackend();
    return () => {
      alive = false;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [clearData, clearTrust, refreshAll, setDataset, setHasData, loadJobId]);

  useEffect(() => {
    let inFlight = false;
    let lastCheck = 0;
    const reconcileVisiblePlan = async () => {
      if (document.hidden || inFlight || operationPending || useLoadStore.getState().jobId) return;
      if (Date.now() - lastCheck < 5000) return;
      lastCheck = Date.now();
      inFlight = true;
      try {
        const health = await getHealth();
        if (!health.has_data || useLoadStore.getState().jobId) return;
        const current = useDataStore.getState();
        if (health.dataset?.id !== current.datasetId || health.plan_revision !== current.planRevision) {
          await refreshAll();
        }
      } catch {
        // Keep the last coherent snapshot until the service is reachable again.
      } finally {
        inFlight = false;
      }
    };
    const onVisible = () => { if (!document.hidden) void reconcileVisiblePlan(); };
    window.addEventListener("focus", onVisible);
    document.addEventListener("visibilitychange", onVisible);
    const interval = window.setInterval(onVisible, 60_000);
    return () => {
      window.removeEventListener("focus", onVisible);
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(interval);
    };
  }, [operationPending, refreshAll]);

  const handleChangeIsop = () => {
    useLoadStore.getState().open();
  };

  const handleRevert = async () => {
    setReverting(true);
    setOperationStatus({
      phase: "pending",
      message: "A desfazer a alteração…",
      detail: "O plano real continua protegido até a operação terminar.",
    });
    try {
      await revert();
      setOperationStatus({
        phase: "success",
        message: "Alteração desfeita",
        detail: "O plano anterior voltou a estar ativo.",
      });
    } catch (err) {
      setOperationStatus({
        phase: "error",
        message: err instanceof RefreshError && err.applied ? "Alteração desfeita; ecrã por atualizar" : "Não foi possível desfazer",
        detail: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setReverting(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setOperationStatus({
      phase: "pending",
      message: "A atualizar dados…",
      detail: "A obter o estado mais recente sem recalcular o plano.",
    });
    try {
      assertRefreshed(await refreshAll());
      setOperationStatus({
        phase: "success",
        message: "Dados atualizados",
        detail: "O plano não foi recalculado.",
      });
    } catch (err) {
      setOperationStatus({
        phase: "error",
        message: "Não foi possível atualizar",
        detail: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRefreshing(false);
    }
  };

  const handleRecalc = async () => {
    const today = await getToday().catch(() => null);
    const warning = staleIsopWarning(today, useDataStore.getState().workdays[0]);
    if (warning && !(await confirm({
      title: "ISOP anterior a hoje",
      message: warning,
      confirmLabel: "Recalcular mesmo assim",
      variant: "danger",
    }))) return;
    setRecalcing(true);
    setOperationStatus({
      phase: "pending",
      message: "A recalcular o plano…",
      detail: "A reorganizar produções, setups e recursos.",
    });
    try {
      await recalculate();
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
      setOperationStatus({
        phase: "success",
        message: "Plano recalculado",
        detail: "Os novos resultados já estão visíveis.",
      });
    } catch (err) {
      const gate = approvalGateFromError(err);
      if (gate) {
        const approved = await confirm({
          title: "Aplicar plano com exceções?",
          // Plain yes/no dialog: it has no text field, so the text must not ask for a justification.
          message: approvalImpactMessage(gate, "confirm"),
          confirmLabel: "Aplicar plano",
          variant: "danger",
        });
        if (!approved) {
          setOperationStatus({
            phase: "idle",
            message: "",
            detail: "",
          });
          return;
        }
        try {
          await recalculate({
            reason: `Recálculo confirmado com exceções: ${decisionReasons(gate).map(approvalReasonLabel).join(", ") || "exceções operacionais"}`,
            author: "planeador",
          });
          assertRefreshed(await refreshAfterCommit(refreshAll), true);
          setOperationStatus({
            phase: "success",
            message: "Plano recalculado com exceções",
            detail: "O plano foi aplicado após confirmação do planeador.",
          });
        } catch (approvalError) {
          setOperationStatus({
            phase: "error",
            message: approvalError instanceof RefreshError && approvalError.applied ? "Plano aplicado; ecrã por atualizar" : "Não foi possível aplicar o plano",
            detail: approvalError instanceof Error ? approvalError.message : String(approvalError),
          });
        }
        return;
      }
      setOperationStatus({
        phase: "error",
        message: err instanceof RefreshError && err.applied ? "Plano recalculado; ecrã por atualizar" : "Não foi possível recalcular",
        detail: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setRecalcing(false);
    }
  };

  const handleDeliveriesFocus = (metric: "otd" | "otd_d") => {
    sessionStorage.setItem(
      DELIVERIES_FOCUS_KEY,
      JSON.stringify({
        page: "deliveries",
        view: "order",
        metric,
        source: "shell-kpi",
      }),
    );
    setPage("deliveries");
  };

  return (
    <div
      className="app-shell"
      style={{
        display: "flex",
        height: "100vh",
        background: T.bg,
        color: T.primary,
        fontFamily: T.sans,
        WebkitFontSmoothing: "antialiased",
      }}
    >
      <GlobalLoadingOverlay />
      <Sidebar />

      <main className="app-main" style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header
          className="app-header"
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
          <div className="app-header-title" style={{ minWidth: 0 }}>
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
          <div className="app-header-actions" style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {hasData && score && (
              <div style={{ display: "flex", gap: 12 }}>
                {(() => {
                  // Order-level service (same criterion as "no order gets worse"); older plans lack it.
                  const orderOtd = Number(gateReport?.metrics?.order_otd);
                  const hasOrderOtd = gateReport?.metrics?.order_otd != null && Number.isFinite(orderOtd);
                  const ordersLate = Number(gateReport?.metrics?.orders_late);
                  const ordersTotal = Number(gateReport?.metrics?.orders_total);
                  // The contract target is 100%: green only when no order is late.
                  const allOrdersOnTime = Number.isFinite(ordersLate) ? ordersLate === 0 : orderOtd >= 100;
                  const orderTitle = hasOrderOtd && Number.isFinite(ordersLate) && Number.isFinite(ordersTotal)
                    ? `Encomendas a tempo: ${ordersTotal - ordersLate} de ${ordersTotal}`
                    : "Abrir entregas";
                  return (
                    <button
                      type="button"
                      onClick={() => handleDeliveriesFocus("otd")}
                      title={orderTitle}
                      style={{
                        ...kpiButtonStyle,
                        fontSize: 12,
                        color: !hasOrderOtd ? T.secondary : allOrdersOnTime ? T.green : T.orange,
                      }}
                    >
                      Encomendas a tempo <b style={{ fontFamily: T.mono }}>{hasOrderOtd ? `${orderOtd.toFixed(1)}%` : "—"}</b>
                    </button>
                  );
                })()}
                <button
                  type="button"
                  onClick={() => handleDeliveriesFocus("otd")}
                  title="Um lote pode acabar depois do prazo de produção e a encomenda ainda sair a tempo."
                  style={{ ...kpiButtonStyle, color: T.secondary, fontWeight: 500 }}
                >
                  Lotes no prazo <b style={{ fontFamily: T.mono }}>{score.otd != null ? `${score.otd.toFixed(1)}%` : "—"}</b>
                </button>
                <button
                  type="button"
                  onClick={() => handleDeliveriesFocus("otd_d")}
                  title="Abrir cumprimento diário"
                  style={{ ...kpiButtonStyle, color: (score.otd_d ?? 0) >= TH.OTD_D_GREEN ? T.green : T.orange }}
                >
                  Cumprimento diário <b style={{ fontFamily: T.mono }}>{score.otd_d?.toFixed(1)}%</b>
                </button>
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
                  onClick={() => void handleRefresh()}
                  disabled={operationPending}
                  title="Obtém os dados mais recentes sem voltar a calcular o plano"
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
                  {refreshing ? "A atualizar…" : "Atualizar dados"}
                </button>
                <button
                  onClick={handleRecalc}
                  disabled={operationPending || isSimulated}
                  title={isSimulated ? "Desfaz primeiro o cenário simulado" : "Volta a organizar todas as produções e setups"}
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
                  {recalcing ? "A recalcular…" : "Recalcular plano"}
                </button>
              </>
            )}
            <button
              onClick={toggleChat}
              disabled={!copilotAvailable}
              title={copilotAvailable ? "Abrir o assistente de planeamento" : copilotReason}
              style={{
                background: chatOpen ? `${T.blue}18` : "transparent",
                border: `1px solid ${chatOpen ? `${T.blue}44` : T.border}`,
                color: chatOpen ? T.blue : T.secondary,
                borderRadius: 8,
                padding: "5px 12px",
                cursor: copilotAvailable ? "pointer" : "not-allowed",
                fontSize: 12,
                fontWeight: 500,
                fontFamily: "inherit",
              }}
            >
              {copilotAvailable ? "Copilot" : "Copilot indisponível"}
            </button>
          </div>
        </header>
        {hasData && operationStatus.phase !== "idle" && (() => {
          const color = operationStatus.phase === "error"
            ? T.red
            : operationStatus.phase === "success"
              ? T.green
              : T.blue;
          return (
            <div
              role={operationStatus.phase === "error" ? "alert" : "status"}
              aria-live="polite"
              style={{
                padding: "7px 24px",
                background: `${color}10`,
                borderBottom: `1px solid ${color}35`,
                display: "flex",
                alignItems: "center",
                gap: 10,
                flexShrink: 0,
                fontSize: 11,
              }}
            >
              <span style={{ color, fontWeight: 600 }}>{operationStatus.message}</span>
              <span style={{ color: T.secondary }}>{operationStatus.detail}</span>
            </div>
          );
        })()}

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
            <span style={{ fontSize: 12, fontWeight: 600, color: T.orange }}>Cenário simulado</span>
            <span style={{ fontSize: 11, color: T.secondary, flex: 1 }}>
              {activeMutations.length > 0
                ? activeMutations.map(mutationLabel).join(" · ")
                : simulationSummary[0] ?? "Alterações aplicadas ao plano ativo"}
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

        {manualEdits.length > 0 && (
          <div style={{
            padding: "8px 24px",
            background: `${T.blue}12`,
            borderBottom: `1px solid ${T.blue}35`,
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexShrink: 0,
          }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: T.blue }}>Edição manual ativa</span>
            <span style={{ fontSize: 11, color: T.secondary, flex: 1 }}>
              {manualEdits.map((edit) => `${edit.lot_id} → dia ${edit.target_day} (${edit.target_machine})`).join(" · ")}
            </span>
            {canRevert ? (
              <button
                onClick={handleRevert}
                disabled={reverting}
                style={{
                  background: "transparent",
                  border: `1px solid ${T.blue}`,
                  color: T.blue,
                  borderRadius: 6,
                  padding: "4px 12px",
                  cursor: reverting ? "default" : "pointer",
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: "inherit",
                }}
              >
                {reverting ? "A desfazer…" : "Desfazer"}
              </button>
            ) : (
              <span style={{ color: T.tertiary, fontSize: 10 }}>Versão anterior disponível em Planos</span>
            )}
          </div>
        )}

        {loadCompletion && (
          <div role="status" style={{ padding: "12px 24px", background: `${T.green}10`, color: T.secondary, fontSize: 13 }}>
            <strong>Plano atualizado.</strong> {loadCompletion.filename}
            {loadWarnings(loadCompletion).length > 0 && <ul style={{ margin: "8px 0", paddingLeft: 18 }}>
              {loadWarnings(loadCompletion).map((warning, index) => <li key={index}>{warning}</li>)}
            </ul>}
            <button onClick={() => useLoadStore.setState({ completion: null })}
              style={{ marginLeft: 12, cursor: "pointer", background: "transparent", border: "none", color: T.blue }}>Fechar aviso</button>
          </div>
        )}
        {loadJobId && !loadOpen && (
          <div role="status" style={{ padding: "10px 24px", background: `${T.blue}10`, color: T.secondary, fontSize: 12 }}>
            {loadJob && ["prepared", "awaiting_approval"].includes(loadJob.status)
              ? "O ficheiro está pronto para atualizar o plano."
              : loadJob && ["applied", "blocked", "failed", "cancelled", "stale"].includes(loadJob.status)
                ? loadJob.message : "A atualizar o plano…"}
            <button style={{ marginLeft: 12, cursor: "pointer", color: T.blue, background: "transparent", border: "none", fontFamily: "inherit" }}
              onClick={() => useLoadStore.getState().open()}>Acompanhar carregamento</button>
          </div>
        )}
        <div className="app-content" style={{ flex: 1, overflow: "auto", padding: page === "console" ? 0 : 24 }}>
          {loadOpen ? (
            <UploadZone />
          ) : checkingData ? (
            <div style={{ color: T.secondary, padding: 24 }}>A verificar dados...</div>
          ) : backendUnavailable ? (
            <div
              role="status"
              style={{
                minHeight: "100%",
                display: "grid",
                placeItems: "center",
                color: T.secondary,
                fontSize: 13,
              }}
            >
              A restabelecer ligação ao servidor…
            </div>
          ) : hasData ? (
              <PageErrorBoundary key={page}>
                <PageContent />
              </PageErrorBoundary>
          ) : (
            <UploadZone />
          )}
        </div>
      </main>

      {chatOpen && <ChatPanel />}
    </div>
  );
}

const kpiButtonStyle: CSSProperties = {
  appearance: "none",
  background: "transparent",
  border: "none",
  padding: 0,
  cursor: "pointer",
  fontSize: 10,
  fontWeight: 600,
  fontFamily: "inherit",
};

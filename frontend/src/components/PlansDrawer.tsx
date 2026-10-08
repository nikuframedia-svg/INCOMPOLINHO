import { useEffect, useState } from "react";
import { deletePlan, getPlans, restorePlan, savePlan } from "../api/endpoints";
import type { PlanSummary } from "../api/types";
import { useDataStore } from "../stores/useDataStore";
import { T } from "../theme/tokens";
import { useConfirm } from "./ui/confirmContext";

interface Props {
  onClose: () => void;
}

const actionStyle: React.CSSProperties = {
  background: T.elevated,
  border: `1px solid ${T.border}`,
  borderRadius: 7,
  color: T.secondary,
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 11,
  padding: "5px 9px",
};

function sourceLabel(source: string) {
  return {
    load: "ISOP carregado",
    auto: "Replaneamento",
    simulation_apply: "Cenário aplicado",
    manual_edit: "Edição manual",
    restore: "Reposição",
    user: "Guardado pelo planeador",
  }[source] ?? source;
}

function formatCreatedAt(value: string) {
  const parsed = new Date(value.includes("T") ? value : `${value.replace(" ", "T")}Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" });
}

export function PlansDrawer({ onClose }: Props) {
  const { confirm, prompt } = useConfirm();
  const refreshAll = useDataStore((s) => s.refreshAll);
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>("load");
  const [message, setMessage] = useState<string | null>(null);

  const reload = async () => {
    const response = await getPlans();
    setPlans(response.plans);
  };

  useEffect(() => {
    let alive = true;
    getPlans()
      .then((response) => { if (alive) setPlans(response.plans); })
      .catch((error) => { if (alive) setMessage(`Não foi possível carregar os planos: ${error}`); })
      .finally(() => { if (alive) setBusy(null); });
    return () => { alive = false; };
  }, []);

  const handleSave = async () => {
    if (!name.trim()) return;
    setBusy("save");
    setMessage(null);
    try {
      await savePlan(name.trim(), note.trim());
      setName("");
      setNote("");
      setMessage("Plano guardado.");
      await reload();
    } catch (error) {
      setMessage(`Erro ao guardar: ${error}`);
    } finally {
      setBusy(null);
    }
  };

  const handleRestore = async (plan: PlanSummary) => {
    const approved = await confirm({
      title: "Repor plano guardado",
      message: `Repor “${plan.name}”? O plano atualmente visível será substituído.`,
      confirmLabel: "Repor plano",
    });
    if (!approved) return;
    const reason = await prompt({
      title: "Motivo da aprovação",
      message: "Indica o motivo para aprovar as exceções deste plano.",
      defaultValue: `Reposição confirmada do plano ${plan.name}`,
      inputLabel: "Motivo",
      confirmLabel: "Continuar",
    });
    if (!reason) return;
    setBusy(plan.id);
    setMessage(null);
    try {
      const response = await restorePlan(plan.id, {
        reason,
        author: "planeador",
      });
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
      await reload();
      setMessage(
        response.gate_report.status === "applicable"
          ? `Plano “${plan.name}” reposto.`
          : `Plano reposto com aviso: ${response.gate_report.status}.`,
      );
    } catch (error) {
      setMessage(error instanceof RefreshError && error.applied ? error.message : `Erro ao repor: ${error}`);
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async (plan: PlanSummary) => {
    const approved = await confirm({
      title: "Apagar plano guardado",
      message: `Apagar definitivamente o snapshot “${plan.name}”? Esta ação não pode ser revertida.`,
      confirmLabel: "Apagar",
      variant: "danger",
    });
    if (!approved) return;
    setBusy(plan.id);
    setMessage(null);
    try {
      await deletePlan(plan.id);
      await reload();
    } catch (error) {
      setMessage(`Erro ao apagar: ${error}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      role="presentation"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, zIndex: 1000, background: "rgba(18, 16, 13, 0.28)" }}
    >
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Planos guardados"
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          bottom: 0,
          width: "min(440px, 94vw)",
          background: T.bg,
          borderLeft: `1px solid ${T.border}`,
          boxShadow: "-18px 0 50px rgba(32, 27, 20, 0.14)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ padding: "18px 20px", borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ color: T.primary, fontSize: 15, fontWeight: 700 }}>Planos</div>
            <div style={{ color: T.tertiary, fontSize: 11, marginTop: 3 }}>Versões que sobrevivem ao reinício</div>
          </div>
          <button onClick={onClose} aria-label="Fechar planos" style={{ ...actionStyle, fontSize: 16, padding: "2px 8px" }}>×</button>
        </div>

        <div style={{ padding: 16, borderBottom: `1px solid ${T.border}`, display: "grid", gap: 8 }}>
          <div style={{ color: T.secondary, fontSize: 11, fontWeight: 600 }}>Guardar plano atual</div>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Nome do plano"
            maxLength={120}
            style={{ ...actionStyle, cursor: "text", color: T.primary, width: "100%", boxSizing: "border-box", padding: "8px 10px" }}
          />
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Nota para a equipa (opcional)"
            maxLength={1000}
            rows={2}
            style={{ ...actionStyle, cursor: "text", color: T.primary, width: "100%", boxSizing: "border-box", padding: "8px 10px", resize: "vertical" }}
          />
          <button
            onClick={handleSave}
            disabled={!name.trim() || busy !== null}
            style={{ ...actionStyle, justifySelf: "start", color: T.blue, borderColor: `${T.blue}55`, opacity: !name.trim() || busy !== null ? 0.5 : 1 }}
          >
            {busy === "save" ? "A guardar…" : "Guardar plano"}
          </button>
          {message && <div style={{ color: message.startsWith("Erro") || message.startsWith("Não") ? T.red : T.secondary, fontSize: 11 }}>{message}</div>}
        </div>

        <div style={{ overflowY: "auto", padding: 12, display: "grid", gap: 8 }}>
          {busy === "load" && <div style={{ padding: 16, color: T.secondary, fontSize: 12 }}>A carregar…</div>}
          {busy !== "load" && plans.length === 0 && (
            <div style={{ padding: 16, color: T.secondary, fontSize: 12 }}>Ainda não há planos guardados.</div>
          )}
          {plans.map((plan) => {
            const valid = plan.gate_status === "applicable";
            const isBusy = busy === plan.id;
            return (
              <article key={plan.id} style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, padding: 13 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: T.primary, fontSize: 12, fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{plan.name}</div>
                    <div style={{ color: T.tertiary, fontSize: 10, marginTop: 3 }}>
                      {formatCreatedAt(plan.created_at)} · {sourceLabel(plan.source)}
                    </div>
                  </div>
                  <span style={{ color: valid ? T.green : T.orange, background: `${valid ? T.green : T.orange}15`, borderRadius: 5, padding: "3px 6px", fontSize: 9, height: "fit-content", whiteSpace: "nowrap" }}>
                    {valid ? "Válido" : "Rever gates"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10, color: T.secondary, fontFamily: T.mono, fontSize: 10 }}>
                  <span>Lotes no prazo {plan.otd?.toFixed(1) ?? "—"}%</span>
                  <span>Cumprimento diário {plan.otd_d?.toFixed(1) ?? "—"}%</span>
                  <span>{plan.tardy_count == null ? "—" : plan.tardy_count === 1 ? "1 lote atrasado" : `${plan.tardy_count} lotes atrasados`}</span>
                  <span>{plan.setups ?? "—"} setups</span>
                </div>
                {plan.origin && <div title={plan.origin} style={{ color: T.tertiary, fontSize: 10, marginTop: 8, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>Origem: {plan.origin}</div>}
                {plan.note && <div style={{ color: T.secondary, fontSize: 11, marginTop: 7, lineHeight: 1.4 }}>{plan.note}</div>}
                <div style={{ display: "flex", gap: 6, marginTop: 11 }}>
                  <button disabled={busy !== null} onClick={() => handleRestore(plan)} style={{ ...actionStyle, color: T.blue, borderColor: `${T.blue}44`, opacity: busy !== null ? 0.5 : 1 }}>
                    {isBusy ? "A repor…" : "Repor"}
                  </button>
                  <button disabled={busy !== null} onClick={() => handleDelete(plan)} style={{ ...actionStyle, color: T.red, marginLeft: "auto", opacity: busy !== null ? 0.5 : 1 }}>
                    Apagar
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
import { assertRefreshed, RefreshError, refreshAfterCommit } from "../lib/refreshOutcome";

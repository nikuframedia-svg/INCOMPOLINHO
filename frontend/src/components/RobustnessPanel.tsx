import { useCallback, useEffect, useRef, useState } from "react";
import {
  cancelRobustnessRun,
  getLatestRobustnessRun,
  getRobustnessRun,
  startRobustnessRun,
} from "../api/endpoints";
import type { RobustnessJob } from "../api/types";
import { T } from "../theme/tokens";
import { ProgressBar } from "./ui/ProgressBar";
import { usePlanKey } from "../hooks/usePlanQuery";
import { useDataStore } from "../stores/useDataStore";
import { useAppStore } from "../stores/useAppStore";

type Profile = "quick" | "standard" | "intensive";

const PROFILE_LABELS: Record<Profile, string> = {
  quick: "Rápido · 100 cenários",
  standard: "Normal · 500 cenários",
  intensive: "Intensivo · 2.000 cenários",
};

const LATEST_RETRIES = 3;
const LATEST_RETRY_MS = 2000;

const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);

const STATUS_LABELS: Record<RobustnessJob["status"], string> = {
  queued: "em espera",
  running: "a calcular",
  cancelling: "a cancelar",
  cancelled: "cancelado",
  completed: "concluído",
  failed: "falhou",
  interrupted: "interrompido",
};

/** A job computed for another revision does not describe the plan on screen. */
function belongsToRevision(job: RobustnessJob, revision: number | null | undefined): boolean {
  return typeof job.plan_revision !== "number" || typeof revision !== "number" || job.plan_revision === revision;
}

function originText(job: RobustnessJob): string {
  const revision = typeof job.plan_revision === "number" ? ` da revisão ${job.plan_revision}` : "";
  if (job.trigger === "auto") return `Cálculo automático${revision}, feito depois de gravar o plano.`;
  if (job.trigger === "manual") return `Cálculo pedido manualmente${revision}.`;
  return "Cálculo deste plano.";
}

/** "2026-10-08" -> "08/10"; parsed by hand so the timezone never shifts the day. */
function shortDate(iso: string | null | undefined): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  return match ? `${match[3]}/${match[2]}` : null;
}

function horizonWorkdays(job: RobustnessJob): number | null {
  const workdays = job.horizon_workdays ?? job.result?.horizon_workdays;
  return typeof workdays === "number" && workdays > 0 ? workdays : null;
}

function horizonText(job: RobustnessJob): string {
  const workdays = horizonWorkdays(job);
  if (workdays === null) return "Olha para o plano inteiro (modelo anterior).";
  const from = shortDate(job.result?.horizon_start_date);
  const to = shortDate(job.result?.horizon_end_date);
  const window = from && to
    ? `Olha para os dias de ${from} a ${to} (${workdays} dias úteis).`
    : `Olha para os próximos ${workdays} dias úteis.`;
  const count = job.result?.horizon_lot_count;
  if (typeof count !== "number" || count <= 0) return window;
  return `${window} ${count} ${count === 1 ? "entrega" : "entregas"} nestes dias.`;
}

/** A v5 window without deliveries has nothing to measure: never show it as 100%. */
function nothingToMeasure(job: RobustnessJob): boolean {
  const result = job.result;
  return Boolean(result && (result.no_deliveries_in_window || result.horizon_lot_count === 0));
}

function pct(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : "—";
}

function num(value: number | null | undefined, suffix = ""): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}${suffix}` : "—";
}

/** Null, stale or another revision: the automatic job may still be on its way. */
function usableLatest(job: RobustnessJob | null): boolean {
  return Boolean(job && !job.stale && belongsToRevision(job, useDataStore.getState().planRevision));
}

export function RobustnessPanel() {
  const [profile, setProfile] = useState<Profile>("standard");
  const plan = usePlanKey();
  const readOnly = useAppStore((state) => state.accessMode === "view");
  const [saved, setSaved] = useState<{ plan: string; job: RobustnessJob | null } | null>(null);
  const job = saved?.plan === plan ? saved.job : null;
  const [failure, setFailure] = useState<{ plan: string; message: string | null } | null>(null);
  const error = failure?.plan === plan ? failure.message : null;
  const setError = useCallback((message: string | null) => setFailure({ plan, message }), [plan]);
  const [pendingPlan, setPendingPlan] = useState<string | null>(null);
  const pending = pendingPlan === plan;
  const busy = useRef(false);
  const generation = useRef(0);
  const current = useCallback((token: number) => {
    const live = useDataStore.getState();
    return token === generation.current && plan === JSON.stringify([live.datasetId, live.planRevision]);
  }, [plan]);
  const setJob = useCallback((next: RobustnessJob | null) => {
    setSaved((previous) => {
      if (previous?.plan === plan && previous.job?.id === next?.id
        && previous.job && terminal.has(previous.job.status) && next && !terminal.has(next.status)) return previous;
      const revision = useDataStore.getState().planRevision;
      return { plan, job: next?.stale || (next && !belongsToRevision(next, revision)) ? null : next };
    });
  }, [plan]);
  const jobId = job?.id;
  const jobStatus = job?.status;

  useEffect(() => {
    const counter = generation;
    const token = ++counter.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    // The automatic job is queued right after the commit; give it a few
    // short chances to appear (or replace a stale one) before showing
    // "sem resultado". Queued/running jobs are then followed by id below.
    const load = () => {
      getLatestRobustnessRun("auto").then((response) => {
        if (!current(token)) return;
        setError(null);
        setJob(response.job);
        // A new day moves the 10-day window: the server re-runs the analysis
        // and says so with `refreshing`; keep asking until the new job shows.
        const waiting = response.refreshing === true || !usableLatest(response.job);
        if (waiting && ++attempts < LATEST_RETRIES) timer = setTimeout(load, LATEST_RETRY_MS);
      }).catch((reason) => { if (current(token)) setError(String(reason)); });
    };
    load();
    return () => { ++counter.current; busy.current = false; clearTimeout(timer); };
  }, [plan, current, setJob, setError]);

  useEffect(() => {
    if (pending || !jobId || !jobStatus || terminal.has(jobStatus)) return;
    let active = true;
    const token = generation.current;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await getRobustnessRun(jobId);
        if (!active || !current(token)) return;
        setJob(response.job);
        setError(null);
        if (terminal.has(response.job.status)) return;
      } catch (reason) {
        if (!active || !current(token)) return;
        setError(String(reason));
      }
      if (active && current(token)) timer = setTimeout(poll, 750);
    };
    timer = setTimeout(poll, 750);
    return () => { active = false; clearTimeout(timer); };
  }, [jobId, jobStatus, plan, pending, current, setJob, setError]);

  const running = Boolean(job && !terminal.has(job.status));
  const result = job?.result;
  const relativeResult = result?.success_definition === "no_additional_tardy_lots";
  const emptyWindow = job ? nothingToMeasure(job) : false;

  const start = async () => {
    if (busy.current || running || readOnly) return;
    busy.current = true;
    const token = ++generation.current;
    setPendingPlan(plan);
    setError(null);
    try {
      const response = await startRobustnessRun({ profile, seed: 42 });
      if (current(token)) setJob(response.job);
    } catch (reason) {
      if (current(token)) setError(String(reason));
    } finally {
      if (current(token)) { busy.current = false; setPendingPlan(null); }
    }
  };

  const cancel = async () => {
    if (!job || busy.current || readOnly) return;
    busy.current = true;
    const token = ++generation.current;
    setPendingPlan(plan);
    setError(null);
    try {
      const response = await cancelRobustnessRun(job.id);
      if (current(token)) setJob(response.job);
    } catch (reason) {
      if (current(token)) setError(`Não foi possível confirmar o cancelamento: ${String(reason)}`);
      try {
        const response = await getRobustnessRun(job.id);
        if (current(token)) setJob(response.job);
      } catch { /* Sequential polling resumes after the finite timeout. */ }
    } finally {
      if (current(token)) { busy.current = false; setPendingPlan(null); }
    }
  };

  return (
    <div style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusSm, background: T.bg, padding: 14 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 220px" }}>
          <div style={{ color: T.primary, fontSize: 13, fontWeight: 700 }}>
            Robustez (informativo): não altera o plano nem pede aprovação
          </div>
          <div style={{ color: T.secondary, fontSize: 10, marginTop: 2 }}>
            Simula imprevistos sobre o plano gravado e conta se aparecem novos atrasos. É calculada sozinha depois de cada gravação; podes repetir com mais cenários.
          </div>
        </div>
        <select
          value={profile}
          onChange={(event) => setProfile(event.target.value as Profile)}
          disabled={running || pending || readOnly}
          aria-label="Número de cenários"
          style={{ background: T.card, border: `1px solid ${T.border}`, color: T.primary, borderRadius: 7, padding: "7px 9px" }}
        >
          {(Object.keys(PROFILE_LABELS) as Profile[]).map((value) => (
            <option key={value} value={value}>{PROFILE_LABELS[value]}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={running ? cancel : start}
          disabled={pending || readOnly}
          style={{ background: running ? T.elevated : T.blue, color: running ? T.secondary : "#fff", border: `1px solid ${running ? T.border : T.blue}`, borderRadius: 7, padding: "7px 13px", cursor: "pointer", fontWeight: 650 }}
        >
          {pending ? "A aguardar…" : running ? "Cancelar" : "Executar"}
        </button>
      </div>

      {job && (
        <div style={{ marginTop: 8, color: T.tertiary, fontSize: 10 }}>
          {originText(job)} {horizonText(job)}
        </div>
      )}
      {!job && !error && !pending && (
        <div style={{ marginTop: 8, color: T.tertiary, fontSize: 10 }}>
          Ainda sem resultado para esta revisão do plano.
        </div>
      )}

      {running && (
        <div style={{ marginTop: 12 }}>
          <ProgressBar value={job?.progress ?? 0} />
          <div style={{ marginTop: 5, color: T.secondary, fontSize: 10 }}>
            {job?.progress ?? 0}% · {job ? STATUS_LABELS[job.status] ?? job.status : ""}
          </div>
        </div>
      )}

      {error && <div style={{ color: T.red, fontSize: 11, marginTop: 10 }}>{error}</div>}
      {job?.error && <div style={{ color: T.red, fontSize: 11, marginTop: 10 }}>{job.error}</div>}

      {job?.status === "completed" && result && emptyWindow && (
        <div style={{ marginTop: 12, color: T.secondary, fontSize: 12 }}>
          Sem entregas nos próximos {horizonWorkdays(job) ?? 10} dias úteis — nada a medir.
        </div>
      )}

      {job?.status === "completed" && result && !emptyWindow && (
        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(125px, 1fr))", gap: 8 }}>
            {[
              [relativeResult ? "Cenários sem novos atrasos" : "Cenários a cumprir (anterior)", pct(result.success_probability_pct)],
              ["Lotes no prazo num cenário mau", pct(result.otd_p95)],
              [relativeResult ? "Novos atrasos num cenário mau" : "Atrasos num cenário mau", num(result.additional_tardy_p95 ?? result.tardy_p95)],
              ["Dias de atraso nos piores cenários", num(result.total_tardiness_cvar95, "d")],
            ].map(([label, value]) => (
              <div key={label} style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: 10 }}>
                <div style={{ color: T.tertiary, fontSize: 9, textTransform: "uppercase" }}>{label}</div>
                <div style={{ color: T.primary, fontFamily: T.mono, fontSize: 18, marginTop: 4 }}>{value}</div>
              </div>
            ))}
          </div>
          {relativeResult ? (
            <div style={{ color: T.secondary, fontSize: 11 }}>
              O plano já tem {result.baseline_tardy_count ?? 0} lote(s) atrasado(s). A percentagem diz em quantos cenários não aparece nenhum atraso novo. "Cenário mau" é o 1 em cada 20 que corre pior.
            </div>
          ) : (
            <div style={{ color: T.orange, fontSize: 11 }}>
              Resultado calculado pelo modelo anterior. Executa novamente para comparar com os atrasos já existentes no plano.
            </div>
          )}
          {result.worst_scenarios[0] && (
            <div style={{ color: T.secondary, fontSize: 11 }}>
              Pior cenário: {result.worst_scenarios[0].tardy_count} lotes atrasados · {result.worst_scenarios[0].affected_lots.slice(0, 3).join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

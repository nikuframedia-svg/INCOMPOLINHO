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
  quick: "Rápido · 100",
  standard: "Normal · 500",
  intensive: "Intensivo · 2.000",
};

const terminal = new Set(["completed", "failed", "cancelled", "interrupted"]);

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
      return { plan, job: next?.stale ? null : next };
    });
  }, [plan]);
  const jobId = job?.id;
  const jobStatus = job?.status;

  useEffect(() => {
    const counter = generation;
    const token = ++counter.current;
    getLatestRobustnessRun().then((response) => {
      if (current(token)) { setError(null); setJob(response.job); }
    }).catch((reason) => { if (current(token)) setError(String(reason)); });
    return () => { ++counter.current; busy.current = false; };
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
          <div style={{ color: T.primary, fontSize: 13, fontWeight: 700 }}>Testar robustez</div>
          <div style={{ color: T.secondary, fontSize: 10, marginTop: 2 }}>
            Reproduz o plano sem o alterar, usando os mesmos cenários e seed.
          </div>
        </div>
        <select
          value={profile}
          onChange={(event) => setProfile(event.target.value as Profile)}
          disabled={running || pending || readOnly}
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

      {running && (
        <div style={{ marginTop: 12 }}>
          <ProgressBar value={job?.progress ?? 0} />
          <div style={{ marginTop: 5, color: T.secondary, fontSize: 10 }}>{job?.progress ?? 0}% · {job?.status}</div>
        </div>
      )}

      {error && <div style={{ color: T.red, fontSize: 11, marginTop: 10 }}>{error}</div>}
      {job?.error && <div style={{ color: T.red, fontSize: 11, marginTop: 10 }}>{job.error}</div>}

      {job?.status === "completed" && result && (
        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          {job.stale && <div style={{ color: T.orange, fontSize: 11 }}>Resultado de uma revisão anterior do plano.</div>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(125px, 1fr))", gap: 8 }}>
            {[
              [relativeResult ? "Sem novos atrasos" : "Cumprimento (anterior)", `${result.success_probability_pct.toFixed(1)}%`],
              ["OTD P95", `${result.otd_p95.toFixed(1)}%`],
              [relativeResult ? "Atrasos adicionais P95" : "Atrasos P95", (result.additional_tardy_p95 ?? result.tardy_p95).toFixed(1)],
              ["CVaR95", `${result.total_tardiness_cvar95.toFixed(1)}d`],
            ].map(([label, value]) => (
              <div key={label} style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 8, padding: 10 }}>
                <div style={{ color: T.tertiary, fontSize: 9, textTransform: "uppercase" }}>{label}</div>
                <div style={{ color: T.primary, fontFamily: T.mono, fontSize: 18, marginTop: 4 }}>{value}</div>
              </div>
            ))}
          </div>
          {relativeResult ? (
            <div style={{ color: T.secondary, fontSize: 11 }}>
              Referência do plano: {result.baseline_tardy_count ?? 0} lote(s) já atrasado(s). A percentagem mede quantos cenários não criam novos lotes em atraso.
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

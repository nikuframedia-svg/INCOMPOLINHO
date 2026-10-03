import { useEffect, useRef, useState } from "react";
import { T } from "../../theme/tokens";
import { useAppStore } from "../../stores/useAppStore";
import { loadWarnings, TERMINAL_LOAD_STATES, useLoadStore } from "../../stores/useLoadStore";
import { GateReportCard } from "../GateReportCard";

const fieldStyle: React.CSSProperties = {
  background: T.elevated, border: `1px solid ${T.border}`, borderRadius: 6,
  color: T.primary, fontFamily: "inherit", fontSize: 12, padding: "8px 12px",
};

export function UploadZone() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const load = useLoadStore();
  const hasData = useAppStore((s) => s.hasData);
  const readOnly = useAppStore((s) => s.accessMode === "view");
  const job = load.job;
  const status = job?.status;
  const calculating = status === "queued" || status === "running" || status === "preparing";
  const terminal = Boolean(status && TERMINAL_LOAD_STATES.has(status));
  const disabled = load.actionPending || readOnly;

  useEffect(() => {
    useLoadStore.getState().resume();
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);

  const upload = (file?: File) => {
    if (file && !disabled) void load.start(file);
  };
  const button = (primary = false): React.CSSProperties => ({
    ...fieldStyle, cursor: disabled ? "not-allowed" : "pointer",
    ...(primary ? { background: T.blue, color: "white", fontWeight: 700 } : {}),
    opacity: disabled ? .6 : 1,
  });
  let title = "Carregar ISOP";
  if (job) title = job.message;
  if (calculating || load.actionPending) title = "A atualizar o plano…";
  if (status === "prepared" || status === "awaiting_approval") title = "O ficheiro está pronto para atualizar o plano.";
  if (status === "applied") title = "O novo plano foi carregado.";
  if (status === "stale") title = "O plano mudou durante o carregamento.";
  if (!job && load.jobId) title = "A atualizar o plano…";
  const seconds = Math.max(0, Math.floor(((job?.elapsed_ms ?? 0)
    + (calculating ? Math.max(0, now - load.receivedAt) : 0)) / 1000));

  return (
    <div style={{ minHeight: "100%", overflow: "auto", padding: "28px 34px" }}>
      <div style={{ maxWidth: 980, margin: "0 auto", display: "grid", gap: 18 }}>
        <div>
          <div style={{ color: T.primary, fontSize: 18, fontWeight: 700 }}>{title}</div>
          {job && <div style={{ color: T.secondary, fontSize: 12, marginTop: 6 }}>{job.filename}</div>}
        </div>
        {(!load.jobId || (!job && load.missing && !load.existingJobId)) && <div>
          {load.missing && <p style={{ color: T.secondary, fontSize: 12 }}>
            Ainda não foi possível confirmar o envio. Seleciona o mesmo ficheiro para repetir o envio com o mesmo identificador.
          </p>}
          <button type="button" disabled={disabled} onClick={() => fileRef.current?.click()}
            onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); upload(event.dataTransfer.files[0]); }}
            style={{ ...fieldStyle, width: "min(100%, 440px)", padding: "38px 24px",
              border: `2px dashed ${dragging ? T.blue : T.border}`, cursor: disabled ? "default" : "pointer" }}>
            Escolher ficheiro ISOP (.xlsx)
            <span style={{ display: "block", color: T.secondary, fontSize: 12, marginTop: 8 }}>
              Também podes arrastar o ficheiro para aqui. Máximo: 25 MB.
            </span>
          </button>
          <input ref={fileRef} type="file" aria-label="Ficheiro ISOP" accept=".xlsx" disabled={disabled}
            style={{ display: "none" }} onChange={(event) => { upload(event.target.files?.[0]); event.target.value = ""; }} />
        </div>}
        {calculating && <div role="status" style={{ color: T.secondary, fontSize: 13, lineHeight: 1.7 }}>
          Tempo decorrido: {Math.floor(seconds / 60)} min {seconds % 60} s.
          <div>Podes atualizar a página ou consultar o plano atual. O carregamento continua em segundo plano.</div>
        </div>}
        {load.connectionLost && <div role="status" style={{ color: T.orange, fontSize: 13 }}>
          A restabelecer ligação… O processamento pode continuar no servidor.
        </div>}
        {load.error && <div role="alert" style={{ color: T.red, fontSize: 13 }}>{load.error}</div>}
        {job?.error && <div role="alert" style={{ color: T.red, fontSize: 13 }}>{job.error.message}</div>}
        {load.existingJobId && <button style={button()} disabled={disabled} onClick={load.followExisting}>
          Acompanhar carregamento existente
        </button>}
        {status === "applied" && loadWarnings(job!).length > 0 && <ul style={{ color: T.orange, fontSize: 13 }}>
          {loadWarnings(job!).map((warning, index) => <li key={index}>{warning}</li>)}
        </ul>}
        {status === "blocked" && job?.gate_report && <details style={{ color: T.secondary, fontSize: 12 }}>
          <summary style={{ cursor: "pointer", marginBottom: 12 }}>Ver detalhes das validações</summary>
          <GateReportCard gate={job.gate_report} />
        </details>}
        {status === "applied" && <div role="status" style={{ color: load.refreshError ? T.orange : T.secondary, fontSize: 13 }}>
          {load.refreshError ?? "A atualizar os dados do ecrã…"}
          {load.refreshError && <div style={{ marginTop: 12 }}><button disabled={load.refreshing} style={button(true)}
            onClick={() => void load.refreshApplied()}>{load.refreshing ? "A atualizar…" : "Atualizar dados do ecrã"}</button></div>}
        </div>}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {(status === "prepared" || status === "awaiting_approval") && <button disabled={disabled}
            onClick={() => void (status === "prepared" ? load.confirm() : load.approve())} style={button(true)}>
            {load.actionPending ? "A atualizar o plano…" : "Atualizar plano"}
          </button>}
          {job && !terminal && <button disabled={disabled} onClick={() => void load.cancel()} style={button()}>Cancelar carregamento</button>}
          {terminal && status !== "applied" && <button disabled={load.actionPending} style={button(true)} onClick={() => load.reset(true)}>Escolher outro ISOP</button>}
          {hasData && <button style={button()} onClick={() => { if (terminal) load.reset(); else load.hide(); }}>Ver plano atual</button>}
        </div>
        {readOnly && <div style={{ color: T.secondary, fontSize: 12 }}>Muda para Editar para atualizar o plano.</div>}
        {load.jobId && <div style={{ color: T.tertiary, fontSize: 11, overflowWrap: "anywhere" }}>Referência do carregamento: {load.jobId}</div>}
      </div>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import {
  applyManualMove,
  cancelManualMovePreview,
  getManualMovePreview,
  startManualMovePreview,
} from "../api/endpoints";
import type { GateReport, Lot, ManualMoveResponse, Segment } from "../api/types";
import { getManualMoveApplyError } from "../lib/manualMoveContract";
import { useDataStore } from "../stores/useDataStore";
import { useAppStore } from "../stores/useAppStore";
import { ApiError } from "../api/client";
import { T } from "../theme/tokens";
import { GateReportCard } from "./GateReportCard";
import { PlanDeltaCards } from "./PlanDeltaCards";
import { Modal } from "./ui/Modal";

interface Props {
  segment: Segment;
  lot: Lot;
  workdays: string[];
  initialTargetDay: number;
  initialTargetStartMin?: number;
  initialTargetMachine?: string;
  onClose: () => void;
  onApplied: () => void;
}

const fieldStyle: React.CSSProperties = {
  background: T.elevated,
  border: `1px solid ${T.border}`,
  borderRadius: 7,
  color: T.primary,
  fontFamily: T.mono,
  fontSize: 12,
  padding: "7px 9px",
};

function dayLabel(day: number, workdays: string[]) {
  const iso = workdays[day];
  if (!iso) return `Dia ${day}`;
  return `Dia ${day} · ${new Intl.DateTimeFormat("pt-PT", { weekday: "short", day: "2-digit", month: "2-digit" }).format(new Date(`${iso}T12:00:00`))}`;
}

const POLL_INTERVAL_MS = 300;

function elapsedLabel(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0
    ? `${minutes} min ${String(seconds).padStart(2, "0")} s`
    : `${seconds} s`;
}

function cancelJob(jobId: string) {
  void cancelManualMovePreview(jobId).catch(() => {
    // The server may already have completed or discarded the job.
  });
}

export function MoveLotModal({ segment, lot, workdays, initialTargetDay, initialTargetStartMin, initialTargetMachine, onClose, onApplied }: Props) {
  const refreshAll = useDataStore((state) => state.refreshAll);
  const readOnly = useAppStore((state) => state.accessMode === "view");
  const planRevision = useDataStore((state) => state.planRevision);
  const datasetId = useDataStore((state) => state.datasetId);
  const segments = useDataStore((state) => state.segments);
  const machines = [lot.machine_id, lot.alt_machine_id].filter((id): id is string => Boolean(id));
  const dayCount = Math.max(workdays.length, lot.edd + 1, initialTargetDay + 1, 1);
  const dayOptions = Array.from({ length: dayCount }, (_, day) => day);
  const firstProduction = segments?.reduce<Segment | undefined>((first, item) => {
    if (item.lot_id !== lot.id || item.prod_min <= 0) return first;
    return !first || item.day_idx < first.day_idx
      || (item.day_idx === first.day_idx && item.start_min < first.start_min)
      ? item : first;
  }, undefined) ?? segment;
  const initialProductionStart = Math.round(
    initialTargetStartMin ?? firstProduction.start_min + firstProduction.setup_min,
  );
  const [targetDay, setTargetDay] = useState(Math.min(Math.max(0, initialTargetDay), dayCount - 1));
  const [targetMachine, setTargetMachine] = useState(
    initialTargetMachine && machines.includes(initialTargetMachine)
      ? initialTargetMachine
      : machines.includes(segment.machine_id)
        ? segment.machine_id
        : machines[0],
  );
  const [targetTime, setTargetTime] = useState(
    `${String(Math.floor(initialProductionStart / 60)).padStart(2, "0")}:${String(initialProductionStart % 60).padStart(2, "0")}`,
  );
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<ManualMoveResponse | null>(null);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [previewBase, setPreviewBase] = useState<{ revision: number; datasetId: string } | null>(null);
  const [previewProgress, setPreviewProgress] = useState(0);
  const [previewMessage, setPreviewMessage] = useState("");
  const [previewElapsedSeconds, setPreviewElapsedSeconds] = useState(0);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorGate, setErrorGate] = useState<GateReport | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const requestGenerationRef = useRef(0);
  const activeJobIdRef = useRef<string | null>(null);
  const reasonInputRef = useRef<HTMLInputElement | null>(null);
  const confirmationInputRef = useRef<HTMLInputElement | null>(null);
  const blocked = preview?.gate_report?.apply_decision === "blocked";
  const stale = previewBase !== null && (previewBase.revision !== planRevision || previewBase.datasetId !== datasetId);
  const deliveryWorsened = preview !== null && (
    preview.delta.otd_after < preview.delta.otd_before - 0.001
    || preview.delta.otd_d_after < preview.delta.otd_d_before - 0.001
    || preview.delta.tardy_after > preview.delta.tardy_before
    || (preview.delta.subcontract_dispatch_after ?? 0) > (preview.delta.subcontract_dispatch_before ?? 0)
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGenerationRef.current += 1;
      const jobId = activeJobIdRef.current;
      activeJobIdRef.current = null;
      if (jobId) cancelJob(jobId);
    };
  }, []);

  const request = {
    lot_id: lot.id,
    target_day: targetDay,
    target_machine: targetMachine,
    target_start_min: Number(targetTime.split(":")[0]) * 60 + Number(targetTime.split(":")[1]),
    reason,
  };

  const invalidatePreview = () => {
    requestGenerationRef.current += 1;
    const jobId = activeJobIdRef.current;
    activeJobIdRef.current = null;
    if (jobId) cancelJob(jobId);
    setPreview(null);
    setPreviewJobId(null);
    setPreviewBase(null);
    setPreviewProgress(0);
    setPreviewMessage("");
    setPreviewElapsedSeconds(0);
    setConfirmed(false);
    setApplyError(null);
    setError(null);
    setErrorGate(null);
  };

  const handleClose = () => {
    requestGenerationRef.current += 1;
    const jobId = activeJobIdRef.current;
    activeJobIdRef.current = null;
    if (jobId) cancelJob(jobId);
    onClose();
  };

  const runPreview = async () => {
    const previousJobId = activeJobIdRef.current;
    activeJobIdRef.current = null;
    if (previousJobId) cancelJob(previousJobId);
    const generation = requestGenerationRef.current + 1;
    requestGenerationRef.current = generation;
    const requestSnapshot = { ...request };
    setBusy("preview");
    setError(null);
    setErrorGate(null);
    setPreview(null);
    setPreviewJobId(null);
    setPreviewProgress(0);
    setPreviewMessage("A preparar a verificação");
    setPreviewElapsedSeconds(0);
    setConfirmed(false);
    setApplyError(null);
    try {
      const started = await startManualMovePreview(requestSnapshot);
      let job = started.job;
      if (!mountedRef.current || requestGenerationRef.current !== generation) {
        cancelJob(job.id);
        return;
      }
      activeJobIdRef.current = job.id;
      const startedAt = Date.now();
      let failures = 0;
      while (job.status === "queued" || job.status === "running") {
        setPreviewProgress(job.progress);
        setPreviewMessage(job.message);
        setPreviewElapsedSeconds(Math.floor((Date.now() - startedAt) / 1_000));
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
        if (!mountedRef.current || requestGenerationRef.current !== generation) {
          cancelJob(job.id);
          return;
        }
        try {
          job = (await getManualMovePreview(job.id)).job;
          failures = 0;
        } catch (failure) {
          if (!mountedRef.current || requestGenerationRef.current !== generation) return;
          if (failure instanceof ApiError && failure.status > 0 && failure.status < 500) throw failure;
          failures += 1;
          setPreviewMessage("Ligação interrompida. A retomar a verificação...");
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(6000, POLL_INTERVAL_MS * 2 ** failures)));
        }
        if (!mountedRef.current || requestGenerationRef.current !== generation) return;
      }
      if (!mountedRef.current || requestGenerationRef.current !== generation) return;
      activeJobIdRef.current = null;
      if (job.status === "failed") {
        setErrorGate(job.gate_report ?? null);
        throw new Error(job.error ?? "A verificação do movimento falhou.");
      }
      if (job.status === "cancelled") {
        throw new Error("A verificação foi cancelada.");
      }
      if (job.status !== "ready" || !job.result) {
        throw new Error("A verificação não devolveu um resultado utilizável.");
      }
      setPreviewJobId(job.id);
      setPreviewBase({ revision: job.base_revision, datasetId: job.dataset_id });
      setPreview(job.result);
      setPreviewProgress(100);
      setPreviewMessage(job.message);
    } catch (failure) {
      if (!mountedRef.current || requestGenerationRef.current !== generation) return;
      const jobId = activeJobIdRef.current;
      activeJobIdRef.current = null;
      if (jobId) cancelJob(jobId);
      if (!mountedRef.current || requestGenerationRef.current !== generation) return;
      const message = failure instanceof Error ? failure.message : String(failure);
      setError(`Não foi possível verificar o movimento: ${message}`);
    } finally {
      if (mountedRef.current && requestGenerationRef.current === generation) {
        setBusy(null);
      }
    }
  };

  const apply = async () => {
    if (busy || readOnly || !preview || !previewJobId || !previewBase || blocked || stale) return;
    const validationError = preview
      ? getManualMoveApplyError({
          requiresConfirmation: preview.requires_confirmation,
          confirmed,
          reason,
        })
      : null;
    if (validationError) {
      setError(null);
      setApplyError(validationError);
      window.requestAnimationFrame(() => {
        const input = confirmed ? reasonInputRef.current : confirmationInputRef.current;
        input?.focus();
        input?.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      return;
    }

    const generation = requestGenerationRef.current;
    setBusy("apply");
    setError(null);
    setApplyError(null);
    try {
      await applyManualMove({
        ...request,
        preview_job_id: previewJobId ?? undefined,
        expected_revision: previewBase.revision,
        approve_exceptions: confirmed,
        approval_reason: reason,
        approval_author: "planeador",
        confirm_delivery_risk: confirmed,
      });
      setPreview(null);
      setPreviewJobId(null);
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
      if (!mountedRef.current || requestGenerationRef.current !== generation) return;
      onApplied();
    } catch (failure) {
      if (!mountedRef.current || requestGenerationRef.current !== generation) return;
      const message = failure instanceof Error ? failure.message : String(failure);
      setApplyError(failure instanceof RefreshError && failure.applied ? message : `Não foi possível aplicar o movimento: ${message}`);
      const detail = failure instanceof ApiError && failure.detail !== null && typeof failure.detail === "object"
        ? failure.detail as { code?: string; current_revision?: number } : null;
      const originConflict = failure instanceof ApiError && failure.status === 409 && detail !== null && (
        ["stale_preview", "preview_required", "stale_revision"].includes(detail.code ?? "")
        || typeof detail.current_revision === "number"
      );
      if (originConflict) {
        setError(`Não foi possível aplicar o movimento: ${message}`);
        setApplyError(null);
        setPreview(null);
        setPreviewJobId(null);
        setPreviewBase(null);
        setConfirmed(false);
        const outcome = await refreshAll();
        if (!mountedRef.current || requestGenerationRef.current !== generation) return;
        if (outcome !== "updated") {
          setError(`Não foi possível aplicar o movimento: ${message} ${new RefreshError(false, outcome).message}`);
        }
      }
    } finally {
      if (mountedRef.current && requestGenerationRef.current === generation) {
        setBusy(null);
      }
    }
  };

  return (
    <Modal title={`Mover lote ${lot.id}`} onClose={handleClose} width={760}>
      <div style={{ display: "grid", gap: 14 }}>
        <div style={{ padding: "10px 12px", borderRadius: 8, background: T.elevated, color: T.secondary, fontSize: 11, lineHeight: 1.5 }}>
          O lote só é guardado se o horário pedido for fisicamente válido. O motor tenta reorganizar o restante plano e mostra o impacto antes de guardar.
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "end", flexWrap: "wrap" }}>
          <label style={{ display: "grid", gap: 4, flex: "1 1 220px" }}>
            <span style={{ color: T.tertiary, fontSize: 10 }}>Dia exato</span>
            <select
              value={targetDay}
              disabled={busy !== null}
              onChange={(event) => {
                invalidatePreview();
                setTargetDay(Number(event.target.value));
              }}
              style={fieldStyle}
            >
              {dayOptions.map((day) => <option key={day} value={day}>{dayLabel(day, workdays)}</option>)}
            </select>
          </label>
          <label style={{ display: "grid", gap: 4, minWidth: 110 }}>
            <span style={{ color: T.tertiary, fontSize: 10 }}>Início exato da produção</span>
            <input
              type="time"
              min="07:00"
              max="23:59"
              value={targetTime}
              disabled={busy !== null}
              onChange={(event) => {
                invalidatePreview();
                setTargetTime(event.target.value);
              }}
              style={fieldStyle}
            />
          </label>
          <label style={{ display: "grid", gap: 4, minWidth: 170 }}>
            <span style={{ color: T.tertiary, fontSize: 10 }}>Máquina</span>
            <select
              value={targetMachine}
              disabled={busy !== null}
              onChange={(event) => {
                invalidatePreview();
                setTargetMachine(event.target.value);
              }}
              style={fieldStyle}
            >
              {machines.map((machine) => <option key={machine} value={machine}>{machine}</option>)}
            </select>
          </label>
          <button
            onClick={runPreview}
            disabled={busy !== null || !targetMachine}
            style={{ ...fieldStyle, cursor: "pointer", color: T.blue, borderColor: `${T.blue}55`, fontFamily: "inherit", fontWeight: 600 }}
          >
            {busy === "preview" ? `A verificar… ${previewProgress}%` : "Verificar riscos"}
          </button>
        </div>
        {busy === "preview" && (
          <div style={{ color: T.secondary, fontSize: 10 }}>
            {previewMessage || "A verificar"} · {elapsedLabel(previewElapsedSeconds)} decorridos. Em planos completos pode demorar vários minutos.
          </div>
        )}
        {error && <div style={{ color: T.red, background: `${T.red}10`, border: `1px solid ${T.red}35`, borderRadius: 8, padding: 10, fontSize: 11 }}>{error}</div>}
        {errorGate && <GateReportCard gate={errorGate} />}

        {preview && (
          <>
            <PlanDeltaCards delta={preview.delta} />
            <GateReportCard gate={preview.gate_report} />
            {blocked || stale ? (
              <div role="alert" style={{ color: T.red, fontSize: 12 }}>
                {stale ? "O plano mudou. Verifica novamente o movimento." : "Movimento bloqueado pelas regras do plano. Não pode ser aplicado."}
              </div>
            ) : preview.requires_confirmation ? (
              <div style={{ background: `${T.red}10`, border: `1px solid ${T.red}45`, borderRadius: 9, padding: 12 }}>
                <div style={{ color: T.red, fontSize: 12, fontWeight: 700 }}>
                  {deliveryWorsened ? "Este movimento agrava entregas" : "Este movimento precisa de aprovação"}
                </div>
                {preview.delivery_warnings.map((warning) => (
                  <div key={warning} style={{ color: T.secondary, fontSize: 11, marginTop: 5 }}>{warning}</div>
                ))}
                <label style={{ display: "grid", gap: 4, marginTop: 12 }}>
                  <span style={{ color: T.red, fontSize: 10, fontWeight: 700 }}>
                    Motivo da alteração (obrigatório)
                  </span>
                  <input
                    ref={reasonInputRef}
                    value={reason}
                    disabled={busy !== null}
                    aria-invalid={Boolean(applyError && !reason.trim())}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setApplyError(null);
                    }}
                    placeholder="Ex.: prioridade do cliente, teste pedido, falta de material…"
                    style={fieldStyle}
                  />
                </label>
                <label style={{ display: "flex", gap: 8, alignItems: "flex-start", marginTop: 10, color: T.primary, fontSize: 11, cursor: "pointer" }}>
                  <input
                    ref={confirmationInputRef}
                    type="checkbox"
                    checked={confirmed}
                    onChange={(event) => {
                      setConfirmed(event.target.checked);
                      setApplyError(null);
                    }}
                  />
                  Confirmo que aceito estas exceções do plano.
                </label>
              </div>
            ) : (
              <>
                <div style={{ color: T.green, background: `${T.green}10`, border: `1px solid ${T.green}35`, borderRadius: 8, padding: 10, fontSize: 11 }}>
                  Movimento fisicamente válido, sem novos riscos de entrega.
                </div>
                <label style={{ display: "grid", gap: 4 }}>
                  <span style={{ color: T.tertiary, fontSize: 10 }}>Motivo da alteração (opcional)</span>
                  <input
                    ref={reasonInputRef}
                    value={reason}
                    disabled={busy !== null}
                    onChange={(event) => {
                      setReason(event.target.value);
                      setApplyError(null);
                    }}
                    placeholder="Ex.: prioridade do cliente, teste pedido, falta de material…"
                    style={fieldStyle}
                  />
                </label>
              </>
            )}
            {applyError && (
              <div
                role="alert"
                style={{
                  color: T.red,
                  background: `${T.red}10`,
                  border: `1px solid ${T.red}45`,
                  borderRadius: 8,
                  padding: 10,
                  fontSize: 11,
                  fontWeight: 600,
                }}
              >
                {applyError}
              </div>
            )}
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <button
                onClick={apply}
                disabled={readOnly || blocked || stale || busy !== null || !previewJobId}
                style={{
                  ...fieldStyle,
                  cursor: readOnly || blocked || stale || busy !== null || !previewJobId ? "not-allowed" : "pointer",
                  fontFamily: "inherit",
                  fontWeight: 700,
                  background: preview.requires_confirmation ? T.red : T.blue,
                  borderColor: "transparent",
                  color: "#fff",
                  opacity: readOnly || blocked || stale || busy !== null || !previewJobId ? 0.5 : 1,
                }}
              >
                {busy === "apply" ? "A aplicar…" : "Aplicar movimento"}
              </button>
              <span style={{ color: T.tertiary, fontSize: 10 }}>
                Pode desfazer no aviso que aparecerá no topo.
              </span>
            </div>
          </>
        )}

        <div style={{ color: T.tertiary, fontSize: 10, borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
          A alteração guarda autor técnico, momento, motivo e versão anterior. Podes repor a versão anterior em Planos.
        </div>
      </div>
    </Modal>
  );
}
import { assertRefreshed, RefreshError, refreshAfterCommit } from "../lib/refreshOutcome";

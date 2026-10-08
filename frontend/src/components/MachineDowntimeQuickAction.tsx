import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { simulate } from "../api/endpoints";
import type { MutationInput, SimulateResponse } from "../api/types";
import { useDataStore } from "../stores/useDataStore";
import { useAppStore } from "../stores/useAppStore";
import { candidateMatchesPlan } from "../lib/previewCandidate";
import { T } from "../theme/tokens";
import { useConfirm } from "./ui/confirmContext";
import { approvalGateFromError, approvalImpactMessage } from "../lib/gateApproval";

interface MachineDowntimeQuickActionProps {
  currentDay: number;
  workdays: string[];
  onApplied: (range: [number, number]) => void;
}

const fieldStyle: React.CSSProperties = {
  minWidth: 170,
  minHeight: 36,
  padding: "7px 10px",
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  background: T.card,
  color: T.primary,
  cursor: "pointer",
  fontFamily: T.mono,
  fontSize: 12,
};

function formatDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("pt-PT", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

export function MachineDowntimeQuickAction({
  currentDay,
  workdays,
  onApplied,
}: MachineDowntimeQuickActionProps) {
  const { prompt } = useConfirm();
  const config = useDataStore((state) => state.config);
  const activeMutations = useDataStore((state) => state.activeMutations);
  const applySimulation = useDataStore((state) => state.applySimulation);
  const readOnly = useAppStore((state) => state.accessMode === "view");
  const candidateRef = useRef<{ key: string; result: SimulateResponse } | null>(null);
  const mounted = useRef(false);
  const [machineId, setMachineId] = useState("");
  const [startDay, setStartDay] = useState("");
  const [endDay, setEndDay] = useState("");
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const machines = useMemo(
    () => Object.entries(config?.machines ?? {})
      .filter(([, machine]) => machine.active !== false)
      .map(([id]) => id)
      .sort(),
    [config],
  );

  useEffect(() => {
    if (workdays.length === 0) {
      setStartDay("");
      setEndDay("");
      return;
    }
    const initialDay = Math.min(Math.max(currentDay, 0), workdays.length - 1);
    setStartDay(String(initialDay));
    setEndDay(String(initialDay));
  }, [currentDay, workdays.length]);

  const start = Number(startDay);
  const end = Number(endDay);
  const validRange = startDay !== ""
    && endDay !== ""
    && start >= 0
    && end >= start
    && end < workdays.length;
  const isDuplicate = validRange && machineId !== "" && activeMutations.some((mutation) => (
    mutation.type === "machine_down"
      && String(mutation.params.machine_id ?? "") === machineId
      && Number(mutation.params.start) === start
      && Number(mutation.params.end) === end
  ));

  const handleStartChange = (value: string) => {
    setStartDay(value);
    if (endDay === "" || Number(endDay) < Number(value)) setEndDay(value);
    setError(null);
  };

  const handleApply = async () => {
    if (readOnly || applying || !machineId || !validRange || isDuplicate) return;
    setApplying(true);
    setError(null);
    let applied = false;
    const mutations: MutationInput[] = [{ type: "machine_down", params: { machine_id: machineId, start, end } }];
    const key = JSON.stringify(mutations);
    try {
      const data = useDataStore.getState();
      if (candidateRef.current?.key !== key || !candidateMatchesPlan(candidateRef.current.result, data.datasetId, data.planRevision)) {
        candidateRef.current = { key, result: await simulate(mutations) };
      }
      if (!mounted.current) return;
      await applySimulation(mutations, undefined, candidateRef.current.result);
      applied = true;
    } catch (caught) {
      const gate = approvalGateFromError(caught);
      if (gate && mounted.current) {
        const reason = await prompt({
          title: "Aprovar impacto da paragem",
          message: approvalImpactMessage(gate),
          inputLabel: "Justificação",
          placeholder: "Explica por que motivo a paragem deve ser aplicada",
          confirmLabel: "Aprovar e aplicar",
          variant: "danger",
        });
        if (reason && mounted.current && candidateRef.current?.key === key) {
          try {
            await applySimulation(mutations, { reason, author: "planeador" }, candidateRef.current.result);
            applied = true;
          } catch {
            if (mounted.current) setError("Não foi possível confirmar a paragem aprovada. Atualiza o plano antes de tentar novamente.");
          }
        }
      } else if (mounted.current) {
        setError(
          caught instanceof ApiError && caught.status === 409
            ? "O plano mudou ou a paragem está bloqueada. Atualiza o plano e verifica novamente."
            : "Não foi possível aplicar a paragem. Confirma os dados e tenta novamente.",
        );
      }
    } finally {
      if (mounted.current) setApplying(false);
    }
    if (applied) candidateRef.current = null;
    if (applied && mounted.current) onApplied([start, end]);
  };

  return (
    <div
      style={{
        padding: 18,
        border: `1px solid ${T.border}`,
        borderLeft: `4px solid ${T.orange}`,
        borderRadius: T.radius,
        background: T.card,
      }}
    >
      <div style={{ marginBottom: 14 }}>
        <div style={{ color: T.primary, fontSize: 14, fontWeight: 700 }}>Parar máquina</div>
        <div style={{ color: T.secondary, fontSize: 11, lineHeight: 1.5, marginTop: 3 }}>
          Escolhe o recurso e o intervalo. O plano será recalculado e poderá ser revertido.
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "flex-end", gap: 10, flexWrap: "wrap" }}>
        <label style={{ display: "grid", gap: 5 }}>
          <span style={{ color: T.tertiary, fontSize: 10, fontWeight: 600 }}>Máquina</span>
          <select
            aria-label="Máquina a parar"
            value={machineId}
            onChange={(event) => { setMachineId(event.target.value); setError(null); }}
            disabled={applying || machines.length === 0}
            style={fieldStyle}
          >
            <option value="">Escolher máquina</option>
            {machines.map((machine) => <option key={machine} value={machine}>{machine}</option>)}
          </select>
        </label>

        <label style={{ display: "grid", gap: 5 }}>
          <span style={{ color: T.tertiary, fontSize: 10, fontWeight: 600 }}>Data inicial</span>
          <select
            aria-label="Data inicial da paragem"
            value={startDay}
            onChange={(event) => handleStartChange(event.target.value)}
            disabled={applying || workdays.length === 0}
            style={fieldStyle}
          >
            {workdays.length === 0 && <option value="">Sem datas disponíveis</option>}
            {workdays.map((date, day) => <option key={date} value={day}>{formatDate(date)}</option>)}
          </select>
        </label>

        <label style={{ display: "grid", gap: 5 }}>
          <span style={{ color: T.tertiary, fontSize: 10, fontWeight: 600 }}>Data final</span>
          <select
            aria-label="Data final da paragem"
            value={endDay}
            onChange={(event) => { setEndDay(event.target.value); setError(null); }}
            disabled={applying || startDay === ""}
            style={fieldStyle}
          >
            {workdays.map((date, day) => (
              day >= start ? <option key={date} value={day}>{formatDate(date)}</option> : null
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={handleApply}
          disabled={readOnly || applying || !machineId || !validRange || isDuplicate}
          style={{
            minHeight: 36,
            padding: "7px 16px",
            border: 0,
            borderRadius: 8,
            background: T.orange,
            color: "white",
            cursor: applying || !machineId || !validRange || isDuplicate ? "default" : "pointer",
            fontFamily: "inherit",
            fontSize: 12,
            fontWeight: 700,
            opacity: applying || !machineId || !validRange || isDuplicate ? 0.5 : 1,
          }}
        >
          {applying ? "A aplicar…" : "Aplicar paragem"}
        </button>
      </div>

      {isDuplicate && (
        <div style={{ color: T.orange, fontSize: 11, marginTop: 10 }}>
          Esta paragem já faz parte do cenário ativo.
        </div>
      )}
      {machines.length === 0 && (
        <div style={{ color: T.red, fontSize: 11, marginTop: 10 }}>
          Não existem máquinas ativas disponíveis para simulação.
        </div>
      )}
      {workdays.length === 0 && (
        <div style={{ color: T.red, fontSize: 11, marginTop: 10 }}>
          Não foi possível carregar as datas do plano. Atualiza os dados e tenta novamente.
        </div>
      )}
      {error && <div role="alert" style={{ color: T.red, fontSize: 11, marginTop: 10 }}>{error}</div>}
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { T } from "../theme/tokens";
import {
  applyCTP,
  applySavedScenario,
  checkCTP,
  getOps,
  getScenarios,
  getWorkdays,
  saveScenario,
  simulate,
} from "../api/endpoints";
import { useDataStore } from "../stores/useDataStore";
import { useSimulatorStore } from "../stores/useSimulatorStore";
import { useAppStore } from "../stores/useAppStore";
import { candidateMatchesPlan } from "../lib/previewCandidate";
import type { EOp, MutationInput, PlanSummary, Segment } from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Pill } from "../components/ui/Pill";
import { Divider } from "../components/ui/Divider";
import { PlanDeltaCards } from "../components/PlanDeltaCards";
import { GateReportCard } from "../components/GateReportCard";
import { useConfirm } from "../components/ui/confirmContext";
import { approvalGateFromError, approvalImpactMessage, gateStatusLabel } from "../lib/gateApproval";

// ── Mutation schema ──────────────────────────────────────────

interface ParamField {
  key: string;
  label: string;
  type: "text" | "number";
  source?: "machines" | "tools" | "skus" | "days" | "groups" | "shifts";
}

const MUTATION_TYPES: { value: string; label: string; fields: ParamField[] }[] = [
  // EDD shifts
  { value: "advance_edd", label: "Antecipar EDD", fields: [
    { key: "sku", label: "SKU", type: "text", source: "skus" },
    { key: "days", label: "Dias", type: "number" },
  ]},
  { value: "delay_edd", label: "Atrasar EDD", fields: [
    { key: "sku", label: "SKU", type: "text", source: "skus" },
    { key: "days", label: "Dias", type: "number" },
  ]},
  // Capacity
  { value: "machine_down", label: "Máquina parada", fields: [
    { key: "machine_id", label: "Máquina", type: "text", source: "machines" },
    { key: "start", label: "De Dia", type: "number", source: "days" },
    { key: "end", label: "Até Dia", type: "number", source: "days" },
    { key: "reason", label: "Motivo", type: "text" },
  ]},
  { value: "tool_down", label: "Ferramenta Indisponivel", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text", source: "tools" },
    { key: "start", label: "De Dia", type: "number", source: "days" },
    { key: "end", label: "Ate Dia", type: "number", source: "days" },
    { key: "reason", label: "Motivo", type: "text" },
  ]},
  { value: "overtime", label: "Horas Extra", fields: [
    { key: "extra_min", label: "Minutos Extra", type: "number" },
  ]},
  // Demand
  { value: "rush_order", label: "Encomenda Urgente", fields: [
    { key: "sku", label: "SKU", type: "text", source: "skus" },
    { key: "qty", label: "Quantidade", type: "number" },
    { key: "deadline_day", label: "Dia Limite", type: "number", source: "days" },
  ]},
  { value: "demand_change", label: "Alterar Procura", fields: [
    { key: "sku", label: "SKU", type: "text", source: "skus" },
    { key: "factor", label: "Factor (1.0=igual)", type: "number" },
  ]},
  { value: "cancel_order", label: "Cancelar Encomenda", fields: [
    { key: "sku", label: "SKU", type: "text", source: "skus" },
    { key: "from_day", label: "De Dia", type: "number", source: "days" },
    { key: "to_day", label: "Ate Dia", type: "number", source: "days" },
  ]},
  // Config
  { value: "force_machine", label: "Forcar Maquina", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text", source: "tools" },
    { key: "to_machine", label: "Para Maquina", type: "text", source: "machines" },
  ]},
  { value: "oee_change", label: "Alterar OEE", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text", source: "tools" },
    { key: "new_oee", label: "Novo OEE (0-1)", type: "number" },
  ]},
  { value: "change_eco_lot", label: "Alterar Eco Lot", fields: [
    { key: "sku", label: "SKU", type: "text", source: "skus" },
    { key: "new_eco_lot", label: "Novo Eco Lot", type: "number" },
  ]},
  // Holidays
  { value: "add_holiday", label: "Adicionar Feriado", fields: [
    { key: "day_idx", label: "Dia", type: "number", source: "days" },
  ]},
  { value: "remove_holiday", label: "Remover Feriado", fields: [
    { key: "day_idx", label: "Dia", type: "number", source: "days" },
  ]},
  { value: "operator_shortage", label: "Falta Operadores", fields: [
    { key: "group", label: "Grupo", type: "text", source: "groups" },
    { key: "shift", label: "Turno", type: "text", source: "shifts" },
    { key: "count", label: "Pessoas em falta", type: "number" },
    { key: "start", label: "De Dia", type: "number", source: "days" },
    { key: "end", label: "Até Dia", type: "number", source: "days" },
    { key: "reason", label: "Motivo", type: "text" },
  ]},
];

const MUTATION_GROUPS = [
  { label: "Datas de entrega", values: ["advance_edd", "delay_edd"] },
  { label: "Capacidade e recursos", values: ["machine_down", "tool_down", "operator_shortage", "overtime"] },
  { label: "Procura", values: ["rush_order", "demand_change", "cancel_order"] },
  { label: "Regras de produção", values: ["force_machine", "oee_change", "change_eco_lot"] },
  { label: "Calendário", values: ["add_holiday", "remove_holiday"] },
];

const inputStyle: React.CSSProperties = {
  background: T.elevated,
  border: `1px solid ${T.border}`,
  borderRadius: 6,
  padding: "4px 8px",
  fontSize: 12,
  color: T.primary,
  fontFamily: T.mono,
  outline: "none",
  width: 100,
};

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  width: 160,
  cursor: "pointer",
};

const btnStyle: React.CSSProperties = {
  background: T.blue,
  border: "none",
  borderRadius: 8,
  padding: "6px 16px",
  color: "#fff",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  fontFamily: "inherit",
};

function MiniGanttPreview({ segments }: { segments: Segment[] }) {
  const previewSegs = [...segments]
    .sort((a, b) => a.day_idx - b.day_idx || a.machine_id.localeCompare(b.machine_id) || a.start_min - b.start_min)
    .slice(0, 36);

  if (!previewSegs.length) return null;

  return (
    <Card style={{ padding: 0, overflow: "hidden" }}>
      <div style={{ padding: "10px 14px", borderBottom: `1px solid ${T.border}` }}>
        <Label>Preview Gantt do cenário</Label>
      </div>
      <div style={{ overflow: "auto", maxHeight: 260 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 720 }}>
          <thead>
            <tr>
              {["Dia", "Máquina", "Ferramenta", "SKU", "Início", "Fim", "Setup", "Qtd"].map((h) => (
                <th key={h} style={{ fontSize: 11, color: T.tertiary, textAlign: "left", padding: "7px 10px", borderBottom: `1px solid ${T.border}` }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {previewSegs.map((s, i) => (
              <tr key={`${s.lot_id}-${s.day_idx}-${s.start_min}-${i}`}>
                <td style={{ fontSize: 12, color: T.primary, padding: "6px 10px", fontFamily: T.mono }}>D{s.day_idx}</td>
                <td style={{ fontSize: 12, color: T.primary, padding: "6px 10px", fontFamily: T.mono }}>{s.machine_id}</td>
                <td style={{ fontSize: 12, color: T.primary, padding: "6px 10px", fontFamily: T.mono }}>{s.tool_id}</td>
                <td style={{ fontSize: 12, color: T.primary, padding: "6px 10px", fontFamily: T.mono }}>{s.sku}</td>
                <td style={{ fontSize: 12, color: T.secondary, padding: "6px 10px", fontFamily: T.mono }}>{s.start_min}</td>
                <td style={{ fontSize: 12, color: T.secondary, padding: "6px 10px", fontFamily: T.mono }}>{s.end_min}</td>
                <td style={{ fontSize: 12, color: s.setup_min > 0 ? T.orange : T.tertiary, padding: "6px 10px", fontFamily: T.mono }}>{s.setup_min.toFixed(0)}</td>
                <td style={{ fontSize: 12, color: T.primary, padding: "6px 10px", fontFamily: T.mono }}>{s.qty.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, val]) => [key, stableValue(val)]),
    );
  }
  return value;
}

function mutationKey(mutation: MutationInput): string {
  return JSON.stringify({ type: mutation.type, params: stableValue(mutation.params ?? {}) });
}

function uniquePendingMutations(mutations: MutationInput[], activeMutations: MutationInput[]) {
  const seen = new Set(activeMutations.map(mutationKey));
  const unique: MutationInput[] = [];
  for (const mutation of mutations) {
    const key = mutationKey(mutation);
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(mutation);
  }
  return unique;
}

function formatDayLabel(day: number, workdays: string[]) {
  if (day < 0) return `D${day} · Buffer`;
  const iso = workdays[day];
  if (!iso) return `D${day}`;
  const date = new Date(`${iso}T00:00:00`);
  const label = new Intl.DateTimeFormat("pt-PT", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(date);
  return `D${day} · ${label}`;
}

function formatCtpMilestone(day: number | null | undefined, date: string | null | undefined) {
  if (day == null) return "-";
  return date ? `${date} · D${day}` : `D${day}`;
}

// ── Main Component ───────────────────────────────────────────

export function SimulatorPanel({ onApplied }: { onApplied?: () => void }) {
  const { prompt } = useConfirm();
  const {
    mutations, result, resultMutations, ctpResult, ctpRequest, ctpInput,
    addMutation, removeMutation, updateMutationType, updateMutationParam,
    setMutations, setResult, setCtpResult, setCtpInput,
    beginSimulation, acceptSimulation, beginCtp, acceptCtp,
  } = useSimulatorStore();
  const refreshAll = useDataStore((s) => s.refreshAll);
  const applySimulation = useDataStore((s) => s.applySimulation);
  const isSimulated = useDataStore((s) => s.isSimulated);
  const activeMutations = useDataStore((s) => s.activeMutations);
  const config = useDataStore((s) => s.config);
  const datasetId = useDataStore((s) => s.datasetId);
  const planRevision = useDataStore((s) => s.planRevision);
  const readOnly = useAppStore((s) => s.accessMode === "view");
  const mounted = useRef(false);
  const [ops, setOps] = useState<EOp[]>([]);
  const [workdays, setWorkdays] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scenarioName, setScenarioName] = useState("");
  const [scenarioMessage, setScenarioMessage] = useState<string | null>(null);
  const [savedScenarios, setSavedScenarios] = useState<PlanSummary[]>([]);
  const [savedScenarioBusy, setSavedScenarioBusy] = useState<string | null>(null);

  // CTP
  const { sku: ctpSku, qty: ctpQty, deadline: ctpDeadline } = ctpInput;
  const [ctpLoading, setCtpLoading] = useState(false);
  const [ctpApplying, setCtpApplying] = useState(false);
  const [ctpApplied, setCtpApplied] = useState(false);
  const [ctpError, setCtpError] = useState<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      useSimulatorStore.getState().cancelRequests();
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    getOps().then((value) => { if (!disposed) setOps(value); }).catch(() => { if (!disposed) setOps([]); });
    getWorkdays().then((value) => { if (!disposed) setWorkdays(value); }).catch(() => { if (!disposed) setWorkdays([]); });
    getScenarios().then((response) => { if (!disposed) setSavedScenarios(response.scenarios); }).catch(() => { if (!disposed) setSavedScenarios([]); });
    return () => { disposed = true; };
  }, [datasetId, planRevision]);

  const currentCandidate = (candidate: typeof result | typeof ctpResult, ctp = false) => {
    const data = useDataStore.getState();
    const simulator = useSimulatorStore.getState();
    return mounted.current && useAppStore.getState().accessMode !== "view" && candidate !== null
      && (ctp ? simulator.ctpResult : simulator.result) === candidate
      && candidateMatchesPlan(candidate, data.datasetId, data.planRevision);
  };

  const fieldOptions = useMemo(() => {
    const machines = config?.machines
      ? Object.entries(config.machines)
          .filter(([, m]) => m.active !== false)
          .map(([id]) => id)
          .sort()
      : [];
    const tools = config?.tools ? Object.keys(config.tools).filter((t) => t !== "_default").sort() : [];
    const groups = config?.machines
      ? [...new Set(Object.values(config.machines).map((machine) => machine.group).filter(Boolean))].sort()
      : [];
    const shifts = config?.shifts?.length ? config.shifts.map((shift) => shift.id) : ["A", "B"];
    const skus = [...new Set(ops.map((op) => op.sku))].sort();
    const maxDemandDay = Math.max(0, ...ops.map((op) => (op.demand?.length ?? 1) - 1));
    const lastDay = Math.max(workdays.length - 1, maxDemandDay);
    const days = Array.from({ length: lastDay + 1 }, (_, i) => String(i));
    return { machines, tools, skus, days, groups, shifts };
  }, [config, ops, workdays]);

  const availableMutationTypes = useMemo(() => {
    const finalShiftEnd = Math.max(...(config?.shifts?.map((shift) => shift.end_min) ?? [1440]));
    return MUTATION_TYPES.filter((type) => type.value !== "overtime" || finalShiftEnd < 1440);
  }, [config]);

  const optionsFor = (source?: ParamField["source"]) => {
    if (!source) return [];
    return fieldOptions[source];
  };

  const validMutations = useMemo(
    () => mutations.filter((m) => m.type).map(({ type, params }) => ({ type, params })),
    [mutations],
  );
  const pendingMutations = useMemo(
    () => uniquePendingMutations(validMutations, activeMutations),
    [validMutations, activeMutations],
  );
  const pendingHasDuplicates = validMutations.length > pendingMutations.length;

  const runSimulation = async () => {
    if (loading || applying) return;
    if (pendingMutations.length === 0) {
      setError(pendingHasDuplicates ? "Alteração repetida: já está no cenário ativo ou na lista." : null);
      return;
    }
    setLoading(true);
    setError(null);
    setApplied(false);
    const generation = beginSimulation();
    const submitted = structuredClone(pendingMutations);
    try {
      const res = await simulate(submitted);
      if (!mounted.current || generation !== useSimulatorStore.getState().generation) return;
      const data = useDataStore.getState();
      if (!candidateMatchesPlan(res, data.datasetId, data.planRevision)) {
        throw new Error("O plano mudou desde a simulação. Simula novamente.");
      }
      acceptSimulation(generation, res, submitted);
    } catch (e) {
      if (mounted.current && generation === useSimulatorStore.getState().generation) setError(String(e));
    } finally {
      if (mounted.current) setLoading(false);
    }
  };

  const handleApply = async () => {
    if (applying || !result || !resultMutations || !currentCandidate(result)
      || result.gate_report?.apply_decision === "blocked") return;
    const submittedDraft = mutations;
    let approval: { reason: string; author: string } | undefined;
    if (result?.gate_report?.requires_approval) {
      const reason = await prompt({
        title: "Aprovar exceções do cenário",
        message: approvalImpactMessage(result.gate_report),
        inputLabel: "Justificação",
        placeholder: "Explica por que motivo este impacto é aceitável",
        confirmLabel: "Aprovar e aplicar",
        variant: "danger",
      });
      if (!reason) return;
      approval = { reason, author: "planeador" };
    }
    if (!currentCandidate(result)) return;
    setApplying(true);
    let appliedNow = false;
    try {
      try {
        await applySimulation(resultMutations, approval, result);
      } catch (exception) {
        const gate = approval ? null : approvalGateFromError(exception);
        if (!gate) throw exception;
        const reason = await prompt({
          title: "Aprovar exceções do cenário",
          message: approvalImpactMessage(gate),
          inputLabel: "Justificação",
          placeholder: "Explica por que motivo este impacto é aceitável",
          confirmLabel: "Aprovar e aplicar",
          variant: "danger",
        });
        if (!reason || !currentCandidate(result)) return;
        await applySimulation(resultMutations, { reason, author: "planeador" }, result);
      }
      if (useSimulatorStore.getState().mutations === submittedDraft) setMutations([]);
      if (useSimulatorStore.getState().result === result) setResult(null);
      if (mounted.current) setApplied(true);
      appliedNow = true;
    } catch (e) {
      if (mounted.current) setError(String(e));
    } finally {
      if (mounted.current) setApplying(false);
    }
    if (appliedNow && mounted.current) onApplied?.();
  };

  const gate = result?.gate_report;
  const canApplyScenario = Boolean(
    result
    && !readOnly && candidateMatchesPlan(result, datasetId, planRevision)
    && resultMutations?.length
    && gate?.apply_decision !== "blocked"
    && (gate?.status === "applicable" || gate?.status === "best_effort")
    && gate?.physical_gate_passed !== false
    && pendingMutations.length > 0,
  );

  const handleSaveScenario = async () => {
    const name = scenarioName.trim();
    if (readOnly || !name || !result || !resultMutations?.length
      || !candidateMatchesPlan(result, datasetId, planRevision)) return;
    const submittedName = scenarioName;
    setSavedScenarioBusy("save");
    setScenarioMessage(null);
    try {
      const response = await saveScenario(name, "", resultMutations, result);
      if (!mounted.current) return;
      setSavedScenarios((current) => [
        response.scenario,
        ...current.filter((item) => item.id !== response.scenario.id),
      ]);
      setScenarioName((current) => current === submittedName ? "" : current);
      setScenarioMessage("Cenário guardado. O plano verdadeiro não foi alterado.");
    } catch (exception) {
      if (mounted.current) setScenarioMessage(String(exception));
    } finally {
      if (mounted.current) setSavedScenarioBusy(null);
    }
  };

  const handleApplySavedScenario = async (scenario: PlanSummary) => {
    if (readOnly || savedScenarioBusy) return;
    const submittedDraft = mutations;
    const reason = await prompt({
      title: "Aplicar cenário guardado",
      message: "Indica o motivo para aprovar as exceções deste cenário.",
      defaultValue: `Aplicação confirmada do cenário ${scenario.name}`,
      inputLabel: "Motivo",
      confirmLabel: "Aplicar cenário",
      variant: "danger",
    });
    if (!reason || !mounted.current) return;
    setSavedScenarioBusy(scenario.id);
    setScenarioMessage(null);
    try {
      await applySavedScenario(scenario.id, {
        reason,
        author: "planeador",
      });
      if (useSimulatorStore.getState().mutations === submittedDraft) setMutations([]);
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
      if (!mounted.current) return;
      setScenarioMessage(`Cenário “${scenario.name}” aplicado como realidade.`);
      onApplied?.();
    } catch (exception) {
      if (mounted.current) setScenarioMessage(String(exception));
    } finally {
      if (mounted.current) setSavedScenarioBusy(null);
    }
  };

  const runCTP = async () => {
    if (ctpLoading || ctpApplying || !ctpSku || !ctpQty || !ctpDeadline) return;
    setCtpLoading(true);
    setCtpError(null);
    setCtpApplied(false);
    const generation = beginCtp();
    const submitted = { sku: ctpSku, qty: Number(ctpQty), deadline: Number(ctpDeadline) };
    try {
      const res = await checkCTP(submitted.sku, submitted.qty, submitted.deadline);
      if (!mounted.current || generation !== useSimulatorStore.getState().ctpGeneration) return;
      const data = useDataStore.getState();
      if (!candidateMatchesPlan(res, data.datasetId, data.planRevision)) {
        throw new Error("O plano mudou desde a verificação. Verifica novamente.");
      }
      acceptCtp(generation, res, submitted);
    } catch (e: unknown) {
      if (mounted.current && generation === useSimulatorStore.getState().ctpGeneration) setCtpError(String(e));
    } finally {
      if (mounted.current) setCtpLoading(false);
    }
  };

  const handleApplyCTP = async () => {
    if (ctpApplying || !ctpResult?.feasible || !ctpRequest || !currentCandidate(ctpResult, true)) return;
    setCtpApplying(true);
    setCtpError(null);
    try {
      try {
        await applyCTP(ctpRequest.sku, ctpRequest.qty, ctpRequest.deadline, undefined, ctpResult);
      } catch (exception) {
        const gate = approvalGateFromError(exception);
        if (!gate) throw exception;
        const reason = await prompt({
          title: "Aprovar exceções da promessa",
          message: approvalImpactMessage(gate),
          inputLabel: "Justificação",
          placeholder: "Explica por que motivo esta promessa deve ser aceite",
          confirmLabel: "Aprovar e aplicar",
          variant: "danger",
        });
        if (!reason || !currentCandidate(ctpResult, true)) return;
        await applyCTP(
          ctpRequest.sku,
          ctpRequest.qty,
          ctpRequest.deadline,
          { reason, author: "planeador" },
          ctpResult,
        );
      }
      // A committed promise cannot become applicable again after remounting.
      if (useSimulatorStore.getState().ctpResult === ctpResult) setCtpResult(null);
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
      if (mounted.current) setCtpApplied(true);
    } catch (e: unknown) {
      if (mounted.current) setCtpError(String(e));
    } finally {
      if (mounted.current) setCtpApplying(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Mutation Builder ── */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Alterações adicionais</span>
          <button onClick={addMutation} style={{ ...btnStyle, background: T.elevated, color: T.blue, border: `1px solid ${T.border}` }}>
            + Adicionar alteração
          </button>
        </div>

        {mutations.length === 0 ? (
          <Card>
            <div style={{ textAlign: "center", padding: 24, color: T.secondary, fontSize: 13 }}>
              Adiciona uma alteração para testar o seu impacto no plano.
            </div>
          </Card>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {mutations.map((m) => {
              const schema = availableMutationTypes.find((t) => t.value === m.type);
              return (
                <Card key={m._key} style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <select
                      value={m.type}
                      onChange={(e) => updateMutationType(m._key, e.target.value)}
                      style={selectStyle}
                    >
                      <option value="">Tipo...</option>
                      {MUTATION_GROUPS.map((group) => (
                        <optgroup key={group.label} label={group.label}>
                          {availableMutationTypes.filter((type) => group.values.includes(type.value)).map((type) => (
                            <option key={type.value} value={type.value}>{type.label}</option>
                          ))}
                        </optgroup>
                      ))}
                    </select>

                    {schema?.fields.map((f) => {
                      const opts = optionsFor(f.source);
                      if (opts.length > 0) {
                        return (
                          <select
                            key={f.key}
                            value={(m.params[f.key] as string) ?? ""}
                            onChange={(e) => updateMutationParam(m._key, f.key, e.target.value)}
                            style={{ ...selectStyle, width: f.source === "skus" || f.source === "days" ? 190 : 150 }}
                          >
                            <option value="">{f.label}</option>
                            {opts.map((opt) => (
                              <option key={opt} value={opt}>
                                {f.source === "days" ? formatDayLabel(Number(opt), workdays) : opt}
                              </option>
                            ))}
                          </select>
                        );
                      }
                      return (
                        <input
                          key={f.key}
                          type={f.type}
                          placeholder={f.label}
                          value={(m.params[f.key] as string) ?? ""}
                          onChange={(e) => updateMutationParam(m._key, f.key, e.target.value)}
                          style={inputStyle}
                        />
                      );
                    })}

                    <button
                      onClick={() => removeMutation(m._key)}
                      style={{ background: "transparent", border: "none", color: T.red, cursor: "pointer", fontSize: 14, padding: "2px 6px" }}
                    >
                      ×
                    </button>
                  </div>
                </Card>
              );
            })}
          </div>
        )}

        <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={runSimulation}
            disabled={loading || pendingMutations.length === 0}
            style={{
              ...btnStyle,
              opacity: loading || pendingMutations.length === 0 ? 0.5 : 1,
            }}
          >
            {loading ? "A simular..." : "Simular"}
          </button>
          {pendingHasDuplicates && (
            <span style={{ fontSize: 12, color: T.orange }}>Repetidas ignoradas</span>
          )}
          {error && <span style={{ fontSize: 12, color: T.red }}>{error}</span>}
        </div>
      </div>

      {/* ── Delta Results ── */}
      {result && (
        <>
          <PlanDeltaCards delta={result.delta} />

          {result.summary.length > 0 && (
            <Card>
              <Label style={{ marginBottom: 8 }}>Resumo</Label>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {result.summary.map((s, i) => (
                  <li key={i} style={{ fontSize: 12, color: T.secondary, lineHeight: 1.8 }}>{s}</li>
                ))}
              </ul>
            </Card>
          )}

          {gate && <GateReportCard gate={gate} />}

          {(result.segments?.length ?? 0) > 0 && (
            <details style={{ border: `1px solid ${T.border}`, borderRadius: T.radiusSm, overflow: "hidden" }}>
              <summary style={{ padding: "10px 14px", color: T.secondary, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
                Ver pré-visualização detalhada
              </summary>
              <div style={{ borderTop: `1px solid ${T.border}` }}>
                <MiniGanttPreview segments={result.segments ?? []} />
              </div>
            </details>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button
              onClick={handleApply}
              disabled={applying || applied || !canApplyScenario}
              style={{
                ...btnStyle,
                background: applied ? T.green : isSimulated ? T.orange : T.blue,
                opacity: applying || applied || !canApplyScenario ? 0.6 : 1,
              }}
            >
              {applying
                ? "A aplicar..."
                : applied
                  ? "Adicionado"
                  : gate?.status === "jit_window_blocked"
                    ? "Resultado não aplicável · JIT"
                  : gate?.status === "invalid_physics"
                    ? "Resultado não aplicável · conflito físico"
                    : gate?.apply_decision === "blocked"
                      ? "Resultado não aplicável ao plano"
                    : isSimulated
                      ? "Adicionar ao cenário"
                      : gate?.status === "best_effort"
                        ? "Aplicar como realidade (com avisos)"
                        : "Aplicar no Gantt"}
            </button>
            <input
              value={scenarioName}
              onChange={(event) => setScenarioName(event.target.value)}
              placeholder="Nome do cenário"
              aria-label="Nome para guardar o cenário"
              style={{ ...inputStyle, width: 190 }}
            />
            <button
              onClick={() => void handleSaveScenario()}
              disabled={readOnly || !scenarioName.trim() || savedScenarioBusy === "save" || !result
                || !candidateMatchesPlan(result, datasetId, planRevision)}
              style={{
                ...btnStyle,
                background: T.elevated,
                color: T.blue,
                border: `1px solid ${T.border}`,
                opacity: !scenarioName.trim() || savedScenarioBusy === "save" ? 0.6 : 1,
              }}
            >
              {savedScenarioBusy === "save" ? "A guardar…" : "Guardar cenário"}
            </button>
          </div>
        </>
      )}

      {scenarioMessage && (
        <div style={{ color: scenarioMessage.startsWith("Erro") ? T.red : T.secondary, fontSize: 12 }}>
          {scenarioMessage}
        </div>
      )}

      {savedScenarios.length > 0 && (
        <Card>
          <Label style={{ marginBottom: 10 }}>Cenários guardados</Label>
          <div style={{ display: "grid", gap: 8 }}>
            {savedScenarios.map((scenario) => (
              <div
                key={scenario.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 0",
                  borderTop: `1px solid ${T.border}`,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: T.primary, fontSize: 12, fontWeight: 650 }}>
                    {scenario.name}
                  </div>
                  <div style={{ color: T.tertiary, fontSize: 10, marginTop: 2 }}>
                    Lotes no prazo {scenario.otd ?? "—"}% · lotes atrasados {scenario.tardy_count ?? "—"} · {gateStatusLabel(scenario.gate_status)}
                  </div>
                </div>
                <button
                  onClick={() => void handleApplySavedScenario(scenario)}
                  disabled={readOnly || savedScenarioBusy !== null}
                  style={{ ...btnStyle, background: scenario.gate_status === "best_effort" ? T.orange : T.blue }}
                >
                  {savedScenarioBusy === scenario.id ? "A aplicar…" : "Aplicar como realidade"}
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Divider />

      {/* ── CTP ── */}
      <div>
        <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Posso prometer? <span style={{ color: T.tertiary, fontWeight: 400 }}>(CTP)</span></span>
        <div className="ctp-controls" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 12 }}>
          <select
            value={ctpSku}
            aria-label="SKU da promessa"
            onChange={(e) => setCtpInput("sku", e.target.value)}
            style={{ ...selectStyle, width: 190, maxWidth: "100%" }}
          >
            <option value="">SKU</option>
            {fieldOptions.skus.map((sku) => (
              <option key={sku} value={sku}>{sku}</option>
            ))}
          </select>
          <input
            type="number"
            placeholder="Quantidade"
            value={ctpQty}
            onChange={(e) => setCtpInput("qty", e.target.value)}
            style={inputStyle}
          />
          <input
            type="number"
            placeholder="Entrega cliente (dia)"
            value={ctpDeadline}
            onChange={(e) => setCtpInput("deadline", e.target.value)}
            style={inputStyle}
          />
          <button
            onClick={runCTP}
            disabled={ctpLoading || !ctpSku || !ctpQty || !ctpDeadline}
            style={{ ...btnStyle, opacity: ctpLoading || !ctpSku ? 0.5 : 1 }}
          >
            {ctpLoading ? "A verificar..." : "Verificar"}
          </button>
        </div>
        {ctpError && <div style={{ fontSize: 12, color: T.red, marginTop: 8 }}>{ctpError}</div>}
      </div>

      {ctpResult && (
        <Card>
          <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 12 }}>
            <Pill color={ctpResult.feasible ? T.green : T.red}>
              {ctpResult.feasible ? "Viável" : "Inviável"}
            </Pill>
            <span style={{ fontSize: 13, fontFamily: T.mono, color: T.primary }}>{ctpResult.sku}</span>
            <span style={{ fontSize: 12, color: T.secondary }}>{ctpResult.qty_requested.toLocaleString()} peças</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 12 }}>
            <div>
              <Label>Libertação material</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {formatCtpMilestone(ctpResult.material_release_day, ctpResult.material_release_date)}
              </div>
            </div>
            <div>
              <Label>Produção</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {ctpResult.latest_day !== null
                  ? ctpResult.date_start
                    ? `${ctpResult.date_start}${ctpResult.date_end && ctpResult.date_end !== ctpResult.date_start ? ` → ${ctpResult.date_end}` : ""}`
                    : `D${ctpResult.latest_day}${ctpResult.earliest_end_day !== null && ctpResult.earliest_end_day !== ctpResult.latest_day ? ` → D${ctpResult.earliest_end_day}` : ""}`
                  : "-"}
              </div>
              {ctpResult.prod_days > 0 && (
                <div style={{ fontSize: 11, color: T.tertiary, marginTop: 2 }}>
                  {ctpResult.prod_days} dia{ctpResult.prod_days > 1 ? "s" : ""} · {ctpResult.required_min.toFixed(0)} min
                </div>
              )}
            </div>
            <div>
              <Label>Prazo produção</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {formatCtpMilestone(ctpResult.production_due_day, ctpResult.production_due_date)}
              </div>
            </div>
            {ctpResult.subcontract_dispatch_day != null && (
              <div>
                <Label>Envio planeado sub.</Label>
                <div style={{ fontSize: 14, fontFamily: T.mono, color: T.orange, marginTop: 4 }}>
                  {formatCtpMilestone(ctpResult.subcontract_dispatch_day, ctpResult.subcontract_dispatch_date)}
                </div>
              </div>
            )}
            {ctpResult.latest_subcontract_dispatch_day != null
              && ctpResult.latest_subcontract_dispatch_day !== ctpResult.subcontract_dispatch_day && (
              <div>
                <Label>Último envio possível</Label>
                <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                  {formatCtpMilestone(
                    ctpResult.latest_subcontract_dispatch_day,
                    ctpResult.latest_subcontract_dispatch_date,
                  )}
                </div>
              </div>
            )}
            {ctpResult.internal_target_day != null
              && ctpResult.internal_target_day !== ctpResult.production_due_day && (
              <div>
                <Label>Alvo interno</Label>
                <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                  {formatCtpMilestone(ctpResult.internal_target_day, ctpResult.internal_target_date)}
                </div>
              </div>
            )}
            <div>
              <Label>Referência material</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {formatCtpMilestone(ctpResult.material_reference_day, ctpResult.material_reference_date)}
              </div>
            </div>
            <div>
              <Label>Entrega cliente</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {formatCtpMilestone(ctpResult.customer_delivery_day, ctpResult.customer_delivery_date)}
              </div>
            </div>
            <div>
              <Label>Máquina</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {ctpResult.machine ?? "-"}
              </div>
            </div>
            <div>
              <Label>Confiança</Label>
              <div style={{ marginTop: 4 }}>
                <Pill color={ctpResult.confidence === "high" ? T.green : ctpResult.confidence === "medium" ? T.orange : T.red}>
                  {ctpResult.confidence}
                </Pill>
              </div>
            </div>
            <div>
              <Label>Slack (min)</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {ctpResult.slack_min.toFixed(0)}
              </div>
            </div>
          </div>
          {ctpResult.reason && (
            <div style={{ marginTop: 12, fontSize: 12, color: T.secondary, lineHeight: 1.5 }}>{ctpResult.reason}</div>
          )}
          {ctpResult.feasible && (
            <div style={{ marginTop: 12 }}>
              <button
                onClick={handleApplyCTP}
                disabled={readOnly || ctpApplying || ctpApplied || !ctpRequest || !candidateMatchesPlan(ctpResult, datasetId, planRevision)}
                style={{
                  ...btnStyle,
                  background: ctpApplied ? T.green : T.blue,
                  opacity: ctpApplying || ctpApplied ? 0.6 : 1,
                }}
              >
                {ctpApplying ? "A aplicar..." : ctpApplied ? "Aplicado ao Gantt" : "Aplicar ao Gantt"}
              </button>
              {ctpApplied && (
                <span style={{ fontSize: 11, color: T.green, marginLeft: 8 }}>
                  Encomenda adicionada e plano recalculado
                </span>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
import { assertRefreshed, refreshAfterCommit } from "../lib/refreshOutcome";

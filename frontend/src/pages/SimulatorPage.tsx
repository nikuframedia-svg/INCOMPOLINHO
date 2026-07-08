import { useEffect, useMemo, useState } from "react";
import { T } from "../theme/tokens";
import { simulate, checkCTP, applyCTP, getOps, getWorkdays } from "../api/endpoints";
import { useDataStore } from "../stores/useDataStore";
import { useSimulatorStore } from "../stores/useSimulatorStore";
import type { EOp, GateProposal, MutationInput, Segment } from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Num } from "../components/ui/Num";
import { Pill } from "../components/ui/Pill";
import { Divider } from "../components/ui/Divider";

// ── Mutation schema ──────────────────────────────────────────

interface ParamField {
  key: string;
  label: string;
  type: "text" | "number";
  source?: "machines" | "tools" | "skus" | "days";
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
  { value: "machine_down", label: "Maquina Parada", fields: [
    { key: "machine_id", label: "Maquina", type: "text", source: "machines" },
    { key: "start", label: "De Dia", type: "number", source: "days" },
    { key: "end", label: "Ate Dia", type: "number", source: "days" },
  ]},
  { value: "tool_down", label: "Ferramenta Indisponivel", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text", source: "tools" },
    { key: "start", label: "De Dia", type: "number", source: "days" },
    { key: "end", label: "Ate Dia", type: "number", source: "days" },
  ]},
  { value: "overtime", label: "Horas Extra", fields: [
    { key: "machine_id", label: "Maquina", type: "text", source: "machines" },
    { key: "extra_min", label: "Minutos Extra", type: "number" },
  ]},
  { value: "third_shift", label: "3o Turno", fields: [
    { key: "machine_id", label: "Maquina", type: "text", source: "machines" },
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
  // Advisory
  { value: "operator_shortage", label: "Falta Operadores", fields: [
    { key: "note", label: "Nota", type: "text" },
  ]},
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

// ── Delta Card helper ────────────────────────────────────────

function DeltaCard({ label, before, after, suffix = "", higher = false }: {
  label: string;
  before: number;
  after: number;
  suffix?: string;
  higher?: boolean;
}) {
  const improved = higher ? after > before : after < before;
  const worsened = higher ? after < before : after > before;
  const color = improved ? T.green : worsened ? T.red : T.secondary;

  return (
    <Card style={{ textAlign: "center" }}>
      <Label>{label}</Label>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "center", gap: 4, marginTop: 4 }}>
        <span style={{ fontSize: 12, color: T.tertiary, fontFamily: T.mono }}>
          {typeof before === "number" && before % 1 !== 0 ? before.toFixed(1) : before}{suffix}
        </span>
        <span style={{ fontSize: 12, color }}>{" \u2192 "}</span>
        <Num size={20} color={color}>
          {typeof after === "number" && after % 1 !== 0 ? after.toFixed(1) : after}{suffix}
        </Num>
      </div>
    </Card>
  );
}

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

function proposalMetricLine(proposal: GateProposal) {
  const before = proposal.before as Record<string, unknown> | undefined;
  const after = proposal.after_target as Record<string, unknown> | undefined;
  if (!before || !after) return null;
  const keys = [
    "tardy_count",
    "otd",
    "otd_d",
    "setups",
    "setup_time_min",
    "earliness_avg_days",
    "setup_crew_overlaps",
  ];
  const parts = keys
    .filter((key) => key in before || key in after)
    .map((key) => `${key}: ${String(before[key] ?? "-")} -> ${String(after[key] ?? "-")}`);
  return parts.length ? parts.join(" · ") : null;
}

function affectedLine(proposal: GateProposal) {
  const machines = proposal.affected_machines as string[] | undefined;
  const skus = proposal.affected_skus as string[] | undefined;
  const chunks = [];
  if (machines?.length) chunks.push(`maquinas ${machines.slice(0, 3).join(", ")}`);
  if (skus?.length) chunks.push(`SKUs ${skus.slice(0, 3).join(", ")}`);
  return chunks.join(" · ");
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

// ── Main Component ───────────────────────────────────────────

export function SimulatorPage() {
  const {
    mutations, result, ctpResult,
    addMutation, removeMutation, updateMutationType, updateMutationParam,
    setMutations, setResult, setCtpResult,
  } = useSimulatorStore();
  const refreshAll = useDataStore((s) => s.refreshAll);
  const applySimulation = useDataStore((s) => s.applySimulation);
  const isSimulated = useDataStore((s) => s.isSimulated);
  const activeMutations = useDataStore((s) => s.activeMutations);
  const config = useDataStore((s) => s.config);
  const score = useDataStore((s) => s.score);
  const [ops, setOps] = useState<EOp[]>([]);
  const [workdays, setWorkdays] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // CTP
  const [ctpSku, setCtpSku] = useState("");
  const [ctpQty, setCtpQty] = useState("");
  const [ctpDeadline, setCtpDeadline] = useState("");
  const [ctpLoading, setCtpLoading] = useState(false);
  const [ctpApplying, setCtpApplying] = useState(false);
  const [ctpApplied, setCtpApplied] = useState(false);
  const [ctpError, setCtpError] = useState<string | null>(null);

  useEffect(() => {
    getOps().then(setOps).catch(() => setOps([]));
    getWorkdays().then(setWorkdays).catch(() => setWorkdays([]));
  }, []);

  const fieldOptions = useMemo(() => {
    const machines = config?.machines
      ? Object.entries(config.machines)
          .filter(([, m]) => m.active !== false)
          .map(([id]) => id)
          .sort()
      : [];
    const tools = config?.tools ? Object.keys(config.tools).filter((t) => t !== "_default").sort() : [];
    const skus = [...new Set(ops.map((op) => op.sku))].sort();
    const bufferDays = Math.max(0, Number(score?.buffer_days) || 0);
    const maxDemandDay = Math.max(0, ...ops.map((op) => (op.demand?.length ?? 1) - 1));
    const lastDay = Math.max(workdays.length - 1, maxDemandDay);
    const days = Array.from(
      { length: bufferDays + lastDay + 1 },
      (_, i) => String(i - bufferDays),
    );
    return { machines, tools, skus, days };
  }, [config, ops, score, workdays]);

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
    if (pendingMutations.length === 0) {
      setError(pendingHasDuplicates ? "Mutação repetida: já está no cenário ativo ou na lista." : null);
      return;
    }
    setLoading(true);
    setError(null);
    setApplied(false);
    try {
      const res = await simulate(pendingMutations);
      setResult(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async () => {
    if (pendingMutations.length === 0) {
      setError(pendingHasDuplicates ? "Mutação repetida: já está no cenário ativo ou na lista." : null);
      return;
    }
    setApplying(true);
    try {
      await applySimulation(pendingMutations);
      setMutations([]);
      setResult(null);
      setApplied(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setApplying(false);
    }
  };

  const gate = result?.gate_report;
  const canApplyScenario = Boolean(result && gate?.status === "applicable" && pendingMutations.length > 0);

  const runCTP = async () => {
    if (!ctpSku || !ctpQty || !ctpDeadline) return;
    setCtpLoading(true);
    setCtpError(null);
    setCtpApplied(false);
    try {
      const res = await checkCTP(ctpSku, parseInt(ctpQty), parseInt(ctpDeadline));
      setCtpResult(res);
    } catch (e: unknown) {
      setCtpError(String(e));
    } finally {
      setCtpLoading(false);
    }
  };

  const handleApplyCTP = async () => {
    if (!ctpSku || !ctpQty || !ctpDeadline) return;
    setCtpApplying(true);
    setCtpError(null);
    try {
      await applyCTP(ctpSku, parseInt(ctpQty), parseInt(ctpDeadline));
      await refreshAll();
      setCtpApplied(true);
    } catch (e: unknown) {
      setCtpError(String(e));
    } finally {
      setCtpApplying(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {activeMutations.length > 0 && (
        <Card style={{ padding: "12px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <Pill color={T.orange}>Cenário ativo</Pill>
            {activeMutations.map((m, i) => (
              <span
                key={`${mutationKey(m)}-${i}`}
                style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}
              >
                {m.type.replaceAll("_", " ")}
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* ── Mutation Builder ── */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Mutações pendentes</span>
          <button onClick={addMutation} style={{ ...btnStyle, background: T.elevated, color: T.blue, border: `1px solid ${T.border}` }}>
            + Adicionar Mutacao
          </button>
        </div>

        {mutations.length === 0 ? (
          <Card>
            <div style={{ textAlign: "center", padding: 24, color: T.secondary, fontSize: 13 }}>
              Adiciona mutações para simular ou somar ao cenário ativo.
            </div>
          </Card>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {mutations.map((m) => {
              const schema = MUTATION_TYPES.find((t) => t.value === m.type);
              return (
                <Card key={m._key} style={{ padding: "10px 16px" }}>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <select
                      value={m.type}
                      onChange={(e) => updateMutationType(m._key, e.target.value)}
                      style={selectStyle}
                    >
                      <option value="">Tipo...</option>
                      {MUTATION_TYPES.map((t) => (
                        <option key={t.value} value={t.value}>{t.label}</option>
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
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
            <DeltaCard label="OTD" before={result.delta.otd_before} after={result.delta.otd_after} suffix="%" higher />
            <DeltaCard label="OTD-D" before={result.delta.otd_d_before} after={result.delta.otd_d_after} suffix="%" higher />
            <DeltaCard label="Setups" before={result.delta.setups_before} after={result.delta.setups_after} />
            <DeltaCard label="Atrasos" before={result.delta.tardy_before} after={result.delta.tardy_after} />
            <DeltaCard label="Antecipacao" before={result.delta.earliness_before} after={result.delta.earliness_after} suffix="d" />
          </div>

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

          {gate && (
            <Card>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <Pill color={gate.status === "applicable" ? T.green : gate.hard_gate_passed ? T.orange : T.red}>
                  {gate.status === "applicable" ? "Aplicável" : gate.hard_gate_passed ? "Inviável" : "Física falha"}
                </Pill>
                <span style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}>
                  setup overlaps {gate.metrics.setup_crew_overlaps ?? 0} · conflitos ferramenta {gate.metrics.tool_conflicts ?? 0} · atrasos {gate.metrics.tardy_count ?? 0}
                </span>
              </div>
              {gate.setup_overlap_detail.length > 0 && (
                <div style={{ fontSize: 12, color: T.red, lineHeight: 1.6 }}>
                  {gate.setup_overlap_detail.slice(0, 3).map((v, i) => (
                    <div key={i}>
                      D{String(v.day_idx)} · {String(v.machine_a)} / {String(v.machine_b)} · {String(v.tool_a)} / {String(v.tool_b)}
                    </div>
                  ))}
                </div>
              )}
              {gate.proposals.length > 0 && (
                <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
                  {gate.proposals.slice(0, 4).map((p) => (
                    <div key={p.id} style={{ fontSize: 12, color: T.secondary, lineHeight: 1.5 }}>
                      <div style={{ color: T.primary }}>{p.description}</div>
                      <div>{p.expected_impact}</div>
                      {proposalMetricLine(p) && (
                        <div style={{ fontFamily: T.mono, color: T.tertiary }}>
                          {proposalMetricLine(p)}
                        </div>
                      )}
                      {affectedLine(p) && (
                        <div style={{ color: T.tertiary }}>{affectedLine(p)}</div>
                      )}
                      {Array.isArray(p.rejection_reasons) && p.rejection_reasons.length > 0 && (
                        <div style={{ color: T.orange }}>
                          Rejeitar se: {(p.rejection_reasons as string[]).slice(0, 3).join(", ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          <MiniGanttPreview segments={result.segments ?? []} />

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
              {applying ? "A aplicar..." : applied ? "Adicionado" : gate?.status !== "applicable" ? "Gate falhou" : isSimulated ? "Adicionar ao cenário" : "Aplicar no Gantt"}
            </button>
            <span style={{ fontSize: 11, color: T.tertiary }}>Tempo: {result.time_ms.toFixed(0)}ms</span>
          </div>
        </>
      )}

      <Divider />

      {/* ── CTP ── */}
      <div>
        <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Capable-To-Promise (CTP)</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
          <select
            value={ctpSku}
            onChange={(e) => setCtpSku(e.target.value)}
            style={{ ...selectStyle, width: 190 }}
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
            onChange={(e) => setCtpQty(e.target.value)}
            style={inputStyle}
          />
          <input
            type="number"
            placeholder="Deadline (dia)"
            value={ctpDeadline}
            onChange={(e) => setCtpDeadline(e.target.value)}
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
              {ctpResult.feasible ? "Viavel" : "Inviavel"}
            </Pill>
            <span style={{ fontSize: 13, fontFamily: T.mono, color: T.primary }}>{ctpResult.sku}</span>
            <span style={{ fontSize: 12, color: T.secondary }}>{ctpResult.qty_requested.toLocaleString()} pcs</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
            <div>
              <Label>Producao</Label>
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
              <Label>Maquina</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                {ctpResult.machine ?? "-"}
              </div>
            </div>
            <div>
              <Label>Confianca</Label>
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
            <div>
              <Label>Deadline</Label>
              <div style={{ fontSize: 14, fontFamily: T.mono, color: T.primary, marginTop: 4 }}>
                D{ctpDeadline}
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
                disabled={ctpApplying || ctpApplied}
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
                  Encomenda adicionada e schedule recalculado
                </span>
              )}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

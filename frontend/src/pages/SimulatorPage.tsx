import { useState } from "react";
import { T } from "../theme/tokens";
import { simulate, checkCTP, applyCTP } from "../api/endpoints";
import { useDataStore } from "../stores/useDataStore";
import { useSimulatorStore } from "../stores/useSimulatorStore";
import type { MutationInput, SimulateResponse, CTPResult } from "../api/types";
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
}

const MUTATION_TYPES: { value: string; label: string; fields: ParamField[] }[] = [
  // EDD shifts
  { value: "advance_edd", label: "Antecipar EDD", fields: [
    { key: "sku", label: "SKU", type: "text" },
    { key: "days", label: "Dias", type: "number" },
  ]},
  { value: "delay_edd", label: "Atrasar EDD", fields: [
    { key: "sku", label: "SKU", type: "text" },
    { key: "days", label: "Dias", type: "number" },
  ]},
  // Capacity
  { value: "machine_down", label: "Maquina Parada", fields: [
    { key: "machine_id", label: "Maquina", type: "text" },
    { key: "start", label: "De Dia", type: "number" },
    { key: "end", label: "Ate Dia", type: "number" },
  ]},
  { value: "tool_down", label: "Ferramenta Indisponivel", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text" },
    { key: "start", label: "De Dia", type: "number" },
    { key: "end", label: "Ate Dia", type: "number" },
  ]},
  { value: "overtime", label: "Horas Extra", fields: [
    { key: "machine_id", label: "Maquina", type: "text" },
    { key: "extra_min", label: "Minutos Extra", type: "number" },
  ]},
  { value: "third_shift", label: "3o Turno", fields: [
    { key: "machine_id", label: "Maquina", type: "text" },
  ]},
  // Demand
  { value: "rush_order", label: "Encomenda Urgente", fields: [
    { key: "sku", label: "SKU", type: "text" },
    { key: "qty", label: "Quantidade", type: "number" },
    { key: "deadline_day", label: "Dia Limite", type: "number" },
  ]},
  { value: "demand_change", label: "Alterar Procura", fields: [
    { key: "sku", label: "SKU", type: "text" },
    { key: "factor", label: "Factor (1.0=igual)", type: "number" },
  ]},
  { value: "cancel_order", label: "Cancelar Encomenda", fields: [
    { key: "sku", label: "SKU", type: "text" },
    { key: "from_day", label: "De Dia", type: "number" },
    { key: "to_day", label: "Ate Dia", type: "number" },
  ]},
  // Config
  { value: "force_machine", label: "Forcar Maquina", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text" },
    { key: "to_machine", label: "Para Maquina", type: "text" },
  ]},
  { value: "oee_change", label: "Alterar OEE", fields: [
    { key: "tool_id", label: "Ferramenta", type: "text" },
    { key: "new_oee", label: "Novo OEE (0-1)", type: "number" },
  ]},
  { value: "change_eco_lot", label: "Alterar Eco Lot", fields: [
    { key: "sku", label: "SKU", type: "text" },
    { key: "new_eco_lot", label: "Novo Eco Lot", type: "number" },
  ]},
  // Holidays
  { value: "add_holiday", label: "Adicionar Feriado", fields: [
    { key: "day_idx", label: "Dia", type: "number" },
  ]},
  { value: "remove_holiday", label: "Remover Feriado", fields: [
    { key: "day_idx", label: "Dia", type: "number" },
  ]},
  // Advisory
  { value: "operator_shortage", label: "Falta Operadores", fields: [
    { key: "note", label: "Nota", type: "text" },
  ]},
];

const inputStyle: React.CSSProperties = {
  background: T.elevated,
  border: `0.5px solid ${T.border}`,
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

// ── Main Component ───────────────────────────────────────────

export function SimulatorPage() {
  const {
    mutations, result, ctpResult,
    addMutation, removeMutation, updateMutationType, updateMutationParam,
    setResult, setCtpResult,
  } = useSimulatorStore();
  const refreshAll = useDataStore((s) => s.refreshAll);
  const applySimulation = useDataStore((s) => s.applySimulation);
  const isSimulated = useDataStore((s) => s.isSimulated);
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

  const runSimulation = async () => {
    const validMutations = mutations.filter((m) => m.type).map(({ type, params }) => ({ type, params }));
    if (validMutations.length === 0) return;
    setLoading(true);
    setError(null);
    setApplied(false);
    try {
      const res = await simulate(validMutations);
      setResult(res);
      refreshAll();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async () => {
    const validMutations = mutations.filter((m) => m.type).map(({ type, params }) => ({ type, params }));
    if (validMutations.length === 0) return;
    setApplying(true);
    try {
      await applySimulation(validMutations);
      setApplied(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setApplying(false);
    }
  };

  const runCTP = async () => {
    if (!ctpSku || !ctpQty || !ctpDeadline) return;
    setCtpLoading(true);
    setCtpError(null);
    setCtpApplied(false);
    try {
      const res = await checkCTP(ctpSku, parseInt(ctpQty), parseInt(ctpDeadline));
      setCtpResult(res);
    } catch (e: any) {
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
    } catch (e: any) {
      setCtpError(String(e));
    } finally {
      setCtpApplying(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* ── Mutation Builder ── */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <span style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Simulador de Cenarios</span>
          <button onClick={addMutation} style={{ ...btnStyle, background: T.elevated, color: T.blue, border: `0.5px solid ${T.border}` }}>
            + Adicionar Mutacao
          </button>
        </div>

        {mutations.length === 0 ? (
          <Card>
            <div style={{ textAlign: "center", padding: 24, color: T.secondary, fontSize: 13 }}>
              Adiciona mutacoes para simular cenarios what-if.
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

                    {schema?.fields.map((f) => (
                      <input
                        key={f.key}
                        type={f.type}
                        placeholder={f.label}
                        value={(m.params[f.key] as string) ?? ""}
                        onChange={(e) => updateMutationParam(m._key, f.key, e.target.value)}
                        style={inputStyle}
                      />
                    ))}

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
            disabled={loading || mutations.filter((m) => m.type).length === 0}
            style={{
              ...btnStyle,
              opacity: loading || mutations.filter((m) => m.type).length === 0 ? 0.5 : 1,
            }}
          >
            {loading ? "A simular..." : "Simular"}
          </button>
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

          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button
              onClick={handleApply}
              disabled={applying || applied || isSimulated}
              style={{
                ...btnStyle,
                background: applied ? T.green : isSimulated ? T.tertiary : T.blue,
                opacity: applying || applied || isSimulated ? 0.6 : 1,
              }}
            >
              {applying ? "A aplicar..." : applied ? "Aplicado" : isSimulated ? "Cenario ja activo" : "Aplicar no Gantt"}
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
          <input
            type="text"
            placeholder="SKU"
            value={ctpSku}
            onChange={(e) => setCtpSku(e.target.value)}
            style={{ ...inputStyle, width: 160 }}
          />
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

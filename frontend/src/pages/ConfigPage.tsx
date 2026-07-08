import { useEffect, useMemo, useState } from "react";
import { T } from "../theme/tokens";
import {
  getConfig, getOps, updateConfig,
  editMachine, editTool, updateOperators,
  addHoliday, removeHoliday, addTwin, removeTwin, applyPreset,
  previewSkuPlanning, previewSubcontracts, resetSkuPlanning, updateSkuPlanning, updateSubcontracts,
} from "../api/endpoints";
import type {
  EOp,
  FactoryConfig,
  PlanningDelta,
  Score,
  SkuPlanningResponse,
  SkuPlanningRule,
} from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Divider } from "../components/ui/Divider";
import { Modal } from "../components/ui/Modal";
import { useDataStore } from "../stores/useDataStore";

type Section = "geral" | "turnos" | "maquinas" | "ferramentas" | "gemeas" | "operadores" | "feriados" | "parametros" | "planeamento" | "subcontratacoes" | "operacoes";

const SECTIONS: { id: Section; label: string }[] = [
  { id: "geral", label: "Geral" },
  { id: "turnos", label: "Turnos" },
  { id: "maquinas", label: "Maquinas" },
  { id: "ferramentas", label: "Ferramentas" },
  { id: "gemeas", label: "Gemeas" },
  { id: "operadores", label: "Operadores" },
  { id: "feriados", label: "Feriados" },
  { id: "parametros", label: "Parametros" },
  { id: "planeamento", label: "Planeamento SKU" },
  { id: "subcontratacoes", label: "Subcontratacoes" },
  { id: "operacoes", label: "Operacoes" },
];

const thStyle: React.CSSProperties = {
  fontSize: 11, color: T.tertiary, fontWeight: 500, textAlign: "left",
  padding: "8px 12px", borderBottom: `1px solid ${T.border}`,
  position: "sticky", top: 0, background: T.card,
  textTransform: "uppercase", letterSpacing: "0.04em",
};

const tdStyle: React.CSSProperties = {
  fontSize: 12, color: T.primary, padding: "6px 12px",
  borderBottom: `1px solid ${T.border}`, fontFamily: T.mono,
};

const inputStyle: React.CSSProperties = {
  background: T.elevated, border: `1px solid ${T.border}`,
  borderRadius: 6, padding: "4px 8px", fontSize: 12,
  color: T.primary, fontFamily: T.mono, outline: "none",
  width: 100, textAlign: "right",
};

const btnStyle: React.CSSProperties = {
  background: T.elevated, border: `1px solid ${T.border}`,
  borderRadius: 8, padding: "6px 14px", cursor: "pointer",
  fontSize: 12, color: T.secondary, fontFamily: "inherit",
};

const saveBtnStyle = (active: boolean, saving: boolean): React.CSSProperties => ({
  background: active ? T.blue : T.elevated,
  border: "none", borderRadius: 8, padding: "6px 20px",
  cursor: active ? "pointer" : "default",
  fontSize: 12, fontWeight: 600,
  color: active ? "#fff" : T.tertiary,
  fontFamily: "inherit", opacity: saving ? 0.6 : 1,
});

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
      <span style={{ fontSize: 12, color: T.secondary }}>{label}</span>
      <span style={{ fontSize: 12, color: T.primary, fontFamily: T.mono }}>{String(value)}</span>
    </div>
  );
}

// ── Score Delta Banner ──────────────────────────────────────────

function ScoreDelta({ prev, curr, onClear }: { prev: Score; curr: Score; onClear: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClear, 6000);
    return () => clearTimeout(t);
  }, [onClear]);

  const fmt = (v: unknown) => typeof v === "number" ? (v % 1 === 0 ? String(v) : (v as number).toFixed(1)) : String(v);
  const items = [
    { l: "OTD", p: prev.otd, c: curr.otd, u: "%" },
    { l: "OTD-D", p: prev.otd_d, c: curr.otd_d, u: "%" },
    { l: "Setups", p: prev.setups, c: curr.setups },
    { l: "Atrasos", p: prev.tardy_count, c: curr.tardy_count },
  ];

  return (
    <div style={{
      display: "flex", gap: 16, alignItems: "center",
      padding: "10px 16px", background: T.green + "12",
      border: `1px solid ${T.green}40`, borderRadius: 10,
    }}>
      <span style={{ fontSize: 12, color: T.green, fontWeight: 600 }}>Guardado</span>
      {items.map((it) => {
        const changed = it.p !== it.c;
        return (
          <span key={it.l} style={{ fontSize: 11, color: changed ? T.primary : T.tertiary, fontFamily: T.mono }}>
            {it.l}: {fmt(it.p)}→{fmt(it.c)}{it.u ?? ""}
          </span>
        );
      })}
    </div>
  );
}

// ── Presets Row ──────────────────────────────────────────────────

const PRESETS = [
  { id: "urgente", label: "Urgente", color: T.red },
  { id: "equilibrado", label: "Equilibrado", color: T.blue },
  { id: "min_setups", label: "Min Setups", color: T.orange },
  { id: "max_otd", label: "Max OTD", color: T.green },
];

// ── Tunables ─────────────────────────────────────────────────────

const TUNABLES: { key: string; label: string; type: "number" | "boolean" | "select"; options?: string[] }[] = [
  { key: "oee_default", label: "OEE Default", type: "number" },
  { key: "jit_enabled", label: "JIT Activo", type: "boolean" },
  { key: "jit_buffer_pct", label: "JIT Buffer %", type: "number" },
  { key: "jit_threshold", label: "JIT Threshold", type: "number" },
  { key: "jit_max_retries", label: "JIT Max Retries", type: "number" },
  { key: "max_run_days", label: "Max Run Days", type: "number" },
  { key: "max_edd_gap", label: "Max EDD Gap", type: "number" },
  { key: "max_edd_span", label: "Max EDD Span", type: "number" },
  { key: "edd_swap_tolerance", label: "EDD Swap Tolerance", type: "number" },
  { key: "edd_assign_threshold", label: "EDD Assign Threshold", type: "number" },
  { key: "campaign_window", label: "Campaign Window", type: "number" },
  { key: "urgency_threshold", label: "Urgency Threshold", type: "number" },
  { key: "interleave_enabled", label: "Interleave Activo", type: "boolean" },
  { key: "auto_buffer", label: "Auto Buffer", type: "boolean" },
  { key: "vns_enabled", label: "VNS Activo", type: "boolean" },
  { key: "vns_max_iter", label: "VNS Max Iter", type: "number" },
  { key: "compact_enabled", label: "Compactar Plano", type: "boolean" },
  { key: "weight_earliness", label: "Peso Earliness", type: "number" },
  { key: "weight_setups", label: "Peso Setups", type: "number" },
  { key: "weight_balance", label: "Peso Balance", type: "number" },
  { key: "eco_lot_mode", label: "Eco Lot Mode", type: "select", options: ["hard", "soft"] },
];

// ── ParametrosEditor ─────────────────────────────────────────────

function ParametrosEditor({ config, onSaved, onDelta }: {
  config: FactoryConfig;
  onSaved: (c: FactoryConfig) => void;
  onDelta: (prev: Score, curr: Score) => void;
}) {
  const isSimulated = useDataStore((s) => s.isSimulated);
  const refreshAll = useDataStore((s) => s.refreshAll);
  const [edits, setEdits] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [activePreset, setActivePreset] = useState<string | null>(null);

  const hasChanges = Object.keys(edits).length > 0;

  const getValue = (key: string) => {
    if (key in edits) return edits[key];
    return (config as unknown as Record<string, unknown>)[key];
  };

  const handleChange = (key: string, value: unknown, type: "number" | "boolean" | "select") => {
    const original = (config as unknown as Record<string, unknown>)[key];
    const parsed = type === "boolean" ? value : type === "select" ? value : Number(value);
    if (parsed === original) {
      const next = { ...edits };
      delete next[key];
      setEdits(next);
    } else {
      setEdits({ ...edits, [key]: parsed });
    }
  };

  const handleSave = async () => {
    if (!hasChanges) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await updateConfig(edits);
      setEdits({});
      setActivePreset(null);
      const fresh = await getConfig();
      onSaved(fresh);
      onDelta(config as unknown as Score, res.score as unknown as Score);
      refreshAll();
    } catch (e) {
      setMsg(`Erro: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handlePreset = async (name: string) => {
    if (!confirm(`Aplicar preset "${name}"? Os parametros serao substituidos.`)) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await applyPreset(name);
      setEdits({});
      const fresh = await getConfig();
      onSaved(fresh);
      // Show the score delta so the planner sees the impact immediately
      if (res.score && res.score_previous) {
        onDelta(res.score_previous, res.score);
      }
      const simNote = res.simulation_active ? " — simulacao mantida" : "";
      setMsg(`Preset "${name}" aplicado (${res.changed.length} parametros)${simNote}`);
      setActivePreset(name);
      await refreshAll();
    } catch (e) {
      setMsg(`Erro: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card>
      {/* Presets row */}
      <div style={{ marginBottom: 12 }}>
        <Label style={{ marginBottom: 8 }}>Presets</Label>
        {isSimulated && (
          <div style={{ fontSize: 11, color: T.orange, marginBottom: 8 }}>
            Simulacao activa — o preset sera aplicado por cima dela.
          </div>
        )}
        <div style={{ display: "flex", gap: 6 }}>
          {PRESETS.map((p) => {
            const isActive = activePreset === p.id;
            return (
              <button
                key={p.id}
                onClick={() => handlePreset(p.id)}
                disabled={saving}
                style={{
                  background: isActive ? p.color + "30" : p.color + "18",
                  border: isActive ? `2px solid ${p.color}` : `1px solid ${p.color}50`,
                  borderRadius: 8, padding: isActive ? "4px 13px" : "5px 14px",
                  cursor: "pointer",
                  fontSize: 12, fontWeight: isActive ? 700 : 500,
                  color: p.color, fontFamily: "inherit",
                  opacity: saving ? 0.5 : 1,
                  boxShadow: isActive ? `0 0 10px ${p.color}25` : "none",
                  transition: "all 0.15s ease",
                }}
              >
                {isActive ? "● " : ""}{p.label}
              </button>
            );
          })}
        </div>
      </div>

      <Divider />

      {/* Tunables */}
      <div style={{ marginTop: 8 }}>
        {TUNABLES.map((t) => (
          <div key={t.key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0" }}>
            <span style={{ fontSize: 12, color: T.secondary }}>{t.label}</span>
            {t.type === "boolean" ? (
              <button
                onClick={() => handleChange(t.key, !getValue(t.key), "boolean")}
                style={{
                  background: getValue(t.key) ? T.green + "22" : T.red + "22",
                  border: `1px solid ${getValue(t.key) ? T.green : T.red}`,
                  borderRadius: 6, padding: "3px 12px", cursor: "pointer",
                  fontSize: 12, color: getValue(t.key) ? T.green : T.red, fontFamily: "inherit",
                }}
              >
                {getValue(t.key) ? "Sim" : "Nao"}
              </button>
            ) : t.type === "select" ? (
              <select
                value={String(getValue(t.key) ?? "")}
                onChange={(e) => handleChange(t.key, e.target.value, "select")}
                style={{ ...inputStyle, width: 120, cursor: "pointer", textAlign: "left", borderColor: t.key in edits ? T.blue : T.border }}
              >
                {t.options?.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                type="number" step="any"
                value={String(getValue(t.key) ?? "")}
                onChange={(e) => handleChange(t.key, e.target.value, "number")}
                style={{ ...inputStyle, borderColor: t.key in edits ? T.blue : T.border }}
              />
            )}
          </div>
        ))}
      </div>

      <Divider />

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
        <button onClick={handleSave} disabled={!hasChanges || saving} style={saveBtnStyle(hasChanges, saving)}>
          {saving ? "A guardar..." : "Guardar"}
        </button>
        {hasChanges && (
          <button onClick={() => setEdits({})} style={btnStyle}>Cancelar</button>
        )}
        {msg && <span style={{ fontSize: 11, color: msg.startsWith("Erro") ? T.red : T.green }}>{msg}</span>}
      </div>
    </Card>
  );
}

function cleanRule(rule: SkuPlanningRule): SkuPlanningRule {
  const cleaned: Record<string, number> = {};
  for (const [key, value] of Object.entries(rule) as [string, number | undefined][]) {
    if (value !== undefined && value !== null && !Number.isNaN(value)) {
      cleaned[key] = value;
    }
  }
  return cleaned as SkuPlanningRule;
}

function metricDelta(res: { delta?: PlanningDelta } | null) {
  if (!res?.delta) return null;
  const d = res.delta;
  return `OTD ${d.otd >= 0 ? "+" : ""}${d.otd.toFixed(1)} · Setups ${d.setups >= 0 ? "+" : ""}${d.setups} · Penalização ${d.planning_penalty >= 0 ? "+" : ""}${d.planning_penalty.toFixed(1)}`;
}

function apiErrorMessage(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (
      parsed.detail &&
      typeof parsed.detail === "object" &&
      "message" in parsed.detail &&
      typeof parsed.detail.message === "string"
    ) {
      return parsed.detail.message;
    }
  } catch {
    // Keep the original message when the backend did not send JSON.
  }
  return raw;
}

function SkuPlanningEditor({
  config,
  ops,
  onReload,
  onDelta,
}: {
  config: FactoryConfig;
  ops: EOp[];
  onReload: () => Promise<void>;
  onDelta: (prev: Score, curr: Score) => void;
}) {
  const [search, setSearch] = useState("");
  const [drafts, setDrafts] = useState<Record<string, SkuPlanningRule>>({});
  const [preview, setPreview] = useState<Record<string, SkuPlanningResponse>>({});
  const [busySku, setBusySku] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    return ops
      .filter((op) => !q || op.sku.toLowerCase().includes(q) || op.client.toLowerCase().includes(q) || op.tool.toLowerCase().includes(q))
      .slice(0, 80);
  }, [ops, search]);

  const ruleFor = (sku: string) => drafts[sku] ?? config.sku_planning_rules?.[sku] ?? {};
  const setField = (sku: string, field: keyof SkuPlanningRule, raw: string) => {
    const base = { ...(drafts[sku] ?? config.sku_planning_rules?.[sku] ?? {}) };
    if (raw === "") {
      delete base[field];
    } else {
      base[field] = Number(raw);
    }
    setDrafts({ ...drafts, [sku]: base });
  };

  const runPreview = async (sku: string) => {
    setBusySku(sku);
    setMsg(null);
    try {
      const res = await previewSkuPlanning(sku, cleanRule(ruleFor(sku)));
      setPreview({ ...preview, [sku]: res });
    } catch (e) {
      setMsg(`Erro: ${e}`);
    } finally {
      setBusySku(null);
    }
  };

  const apply = async (sku: string) => {
    setBusySku(sku);
    setMsg(null);
    try {
      const res = await updateSkuPlanning(sku, cleanRule(ruleFor(sku)));
      if (res.score_previous && res.score) onDelta(res.score_previous, res.score);
      const nextDrafts = { ...drafts };
      delete nextDrafts[sku];
      setDrafts(nextDrafts);
      setMsg(`Aplicado ${sku}: ${metricDelta(res) ?? "plano recalculado"}`);
      await onReload();
    } catch (e) {
      setMsg(`Erro: ${e}`);
    } finally {
      setBusySku(null);
    }
  };

  const reset = async (sku: string) => {
    setBusySku(sku);
    setMsg(null);
    try {
      const res = await resetSkuPlanning(sku);
      if (res.score_previous && res.score) onDelta(res.score_previous, res.score);
      const nextDrafts = { ...drafts };
      delete nextDrafts[sku];
      setDrafts(nextDrafts);
      setMsg(`Reposto para ISOP: ${sku}`);
      await onReload();
    } catch (e) {
      setMsg(`Erro: ${e}`);
    } finally {
      setBusySku(null);
    }
  };

  const numberInput = (op: EOp, field: keyof SkuPlanningRule, width = 88) => {
    const rule = ruleFor(op.sku);
    return (
      <input
        type="number"
        min="0"
        step={field === "min_campaign_prod_min" ? "0.1" : "1"}
        value={rule[field] ?? ""}
        onChange={(e) => setField(op.sku, field, e.target.value)}
        style={{ ...inputStyle, width, borderColor: op.sku in drafts ? T.blue : T.border }}
      />
    );
  };

  return (
    <>
      <input
        type="text"
        placeholder="Filtrar SKU, cliente, ferramenta..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{
          background: T.elevated, border: `1px solid ${T.border}`,
          borderRadius: 8, padding: "6px 12px", fontSize: 12,
          color: T.primary, fontFamily: T.mono, outline: "none", width: 300,
        }}
      />
      {msg && <div style={{ fontSize: 12, color: msg.startsWith("Erro") ? T.red : T.green }}>{msg}</div>}
      <Card style={{ padding: 0, overflow: "auto", maxHeight: 620 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1160 }}>
          <thead>
            <tr>
              <th style={thStyle}>SKU</th>
              <th style={thStyle}>Cliente</th>
              <th style={thStyle}>Eco ISOP</th>
              <th style={thStyle}>Eco efetivo</th>
              <th style={thStyle}>Novo eco</th>
              <th style={thStyle}>Começar antes</th>
              <th style={thStyle}>Acabar antes</th>
              <th style={thStyle}>Campanha min pç</th>
              <th style={thStyle}>Campanha min min</th>
              <th style={thStyle}>Janela dias</th>
              <th style={thStyle}>Impacto</th>
              <th style={thStyle}>Ações</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((op) => {
              const rule = ruleFor(op.sku);
              const hasOverride = (op.eco_lot_isop ?? op.eco_lot) !== (op.eco_lot_effective ?? op.eco_lot);
              const isBusy = busySku === op.sku;
              const p = preview[op.sku];
              return (
                <tr key={op.id}>
                  <td style={tdStyle}>{op.sku}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>{op.client}</td>
                  <td style={tdStyle}>{(op.eco_lot_isop ?? op.eco_lot).toLocaleString()}</td>
                  <td style={{ ...tdStyle, color: hasOverride ? T.orange : T.primary }}>
                    {(op.eco_lot_effective ?? op.eco_lot).toLocaleString()}
                  </td>
                  <td style={tdStyle}>{numberInput(op, "eco_lot")}</td>
                  <td style={tdStyle}>{numberInput(op, "start_buffer_days", 76)}</td>
                  <td style={tdStyle}>{numberInput(op, "finish_buffer_days", 76)}</td>
                  <td style={tdStyle}>{numberInput(op, "min_campaign_qty")}</td>
                  <td style={tdStyle}>{numberInput(op, "min_campaign_prod_min", 86)}</td>
                  <td style={tdStyle}>{numberInput(op, "max_group_gap_days", 76)}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans, color: p ? T.secondary : T.tertiary }}>
                    {p ? `${metricDelta(p)} · lotes ${p.impact_before?.lots ?? 0}→${p.impact_after?.lots ?? 0}` : "-"}
                    {p?.impact_after?.warnings?.length ? (
                      <div style={{ color: T.orange, marginTop: 3 }}>{p.impact_after.warnings[0]}</div>
                    ) : null}
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button disabled={isBusy} onClick={() => runPreview(op.sku)} style={btnStyle}>Preview</button>
                      <button disabled={isBusy} onClick={() => apply(op.sku)} style={{ ...btnStyle, color: T.blue }}>Aplicar</button>
                      <button disabled={isBusy || (!config.sku_planning_rules?.[op.sku] && !(op.sku in drafts))} onClick={() => reset(op.sku)} style={{ ...btnStyle, color: T.red }}>ISOP</button>
                    </div>
                    {Object.keys(rule).length > 0 && (
                      <div style={{ fontSize: 10, color: T.tertiary, marginTop: 4 }}>regra ativa</div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </>
  );
}

const SUBCONTRACT_COMPANY = {
  id: "SUBCONTRATO",
  name: "Subcontrato",
  lead_time_days: 7,
};

function subcontractInitialSelection(config: FactoryConfig) {
  return new Set([
    ...(config.subcontract_skus ?? []),
    ...Object.entries(config.sku_subcontracts ?? {})
      .filter(([, rule]) => rule.enabled !== false)
      .map(([sku]) => sku),
  ]);
}

function SubcontractEditor({
  config,
  ops,
  onReload,
  onDelta,
}: {
  config: FactoryConfig;
  ops: EOp[];
  onReload: () => Promise<void>;
  onDelta: (prev: Score, curr: Score) => void;
}) {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => subcontractInitialSelection(config));
  const [busy, setBusy] = useState<"preview" | "save" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [previewDelta, setPreviewDelta] = useState<PlanningDelta | null>(null);

  useEffect(() => {
    setSelected(subcontractInitialSelection(config));
    setPreviewDelta(null);
  }, [config]);

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    const unique = new Map<string, EOp>();
    for (const op of ops) {
      if (!unique.has(op.sku)) unique.set(op.sku, op);
    }
    return [...unique.values()]
      .filter((op) => !q || op.sku.toLowerCase().includes(q) || op.client.toLowerCase().includes(q))
      .slice(0, 80);
  }, [ops, search]);

  const toggle = (sku: string) => {
    const next = new Set(selected);
    if (next.has(sku)) next.delete(sku);
    else next.add(sku);
    setSelected(next);
    setPreviewDelta(null);
  };

  const bodyFor = () => {
    const companies = [
      ...(config.subcontract_companies ?? []).filter((c) => c.id !== SUBCONTRACT_COMPANY.id),
      SUBCONTRACT_COMPANY,
    ];
    const sku_subcontracts = Object.fromEntries(
      [...selected].sort().map((sku) => [
        sku,
        {
          enabled: true,
          company_id: SUBCONTRACT_COMPANY.id,
          lead_time_days: 7,
          buffer_days: 0,
        },
      ]),
    );
    return {
      companies,
      sku_subcontracts,
    };
  };

  const runPreview = async () => {
    setBusy("preview");
    setMsg(null);
    try {
      const res = await previewSubcontracts(bodyFor());
      setPreviewDelta(res.delta ?? null);
      setMsg(`Preview: ${metricDelta(res) ?? "plano recalculado"}`);
    } catch (e) {
      setMsg(`Erro: ${apiErrorMessage(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy("save");
    setMsg(null);
    try {
      const res = await updateSubcontracts(bodyFor());
      if (res.score_previous && res.score) onDelta(res.score_previous, res.score);
      setPreviewDelta(res.delta ?? null);
      setMsg(`${selected.size} referência${selected.size === 1 ? "" : "s"} guardada${selected.size === 1 ? "" : "s"} para subcontrato.`);
      await onReload();
    } catch (e) {
      setMsg(`Erro: ${apiErrorMessage(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <input
          type="text"
          placeholder="Filtrar SKU ou cliente..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: T.elevated, border: `1px solid ${T.border}`,
            borderRadius: 8, padding: "6px 12px", fontSize: 12,
            color: T.primary, fontFamily: T.mono, outline: "none", width: 300,
          }}
        />
        <span style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}>
          {selected.size} selecionada{selected.size === 1 ? "" : "s"} · lead 7d
        </span>
        <button type="button" disabled={busy !== null} onClick={runPreview} style={btnStyle}>
          {busy === "preview" ? "A calcular..." : "Preview"}
        </button>
        <button type="button" disabled={busy !== null} onClick={save} style={{ ...btnStyle, color: T.blue }}>
          {busy === "save" ? "A guardar..." : "Guardar"}
        </button>
        {previewDelta && <span style={{ fontSize: 12, color: T.secondary }}>{metricDelta({ delta: previewDelta })}</span>}
      </div>
      {msg && <div style={{ fontSize: 12, color: msg.startsWith("Erro") ? T.red : T.green }}>{msg}</div>}
      <Card style={{ padding: 0, overflow: "auto", maxHeight: 620 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 560 }}>
          <thead>
            <tr>
              <th style={thStyle}>Subcontratar</th>
              <th style={thStyle}>Referência</th>
              <th style={thStyle}>Cliente</th>
              <th style={thStyle}>Procura</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((op) => {
              const active = selected.has(op.sku);
              return (
                <tr key={op.sku}>
                  <td style={tdStyle}>
                    <input
                      type="checkbox"
                      checked={active}
                      onChange={() => toggle(op.sku)}
                      style={{ width: 16, height: 16, cursor: "pointer" }}
                    />
                  </td>
                  <td style={{ ...tdStyle, color: active ? T.primary : T.secondary }}>{op.sku}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>{op.client}</td>
                  <td style={tdStyle}>{op.demand.reduce((sum, qty) => sum + qty, 0).toLocaleString()} pç</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </>
  );
}

// ── Main ConfigPage ──────────────────────────────────────────────

export function ConfigPage() {
  const refreshAll = useDataStore((s) => s.refreshAll);
  const [config, setConfig] = useState<FactoryConfig | null>(null);
  const [ops, setOps] = useState<EOp[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("geral");
  const [opsSearch, setOpsSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [delta, setDelta] = useState<{ prev: Score; curr: Score } | null>(null);

  // Operators inline edit state
  const [opEdits, setOpEdits] = useState<Record<string, number>>({});
  const opHasChanges = Object.keys(opEdits).length > 0;

  // Tools inline edit state
  const [toolEdits, setToolEdits] = useState<Record<string, { setup_hours?: number; alt?: string | null }>>({});

  // Feriados add state
  const [newHoliday, setNewHoliday] = useState("");

  // Gemeas modal state
  const [twinModal, setTwinModal] = useState(false);
  const [twinForm, setTwinForm] = useState({ tool_id: "", sku_a: "", sku_b: "" });

  useEffect(() => {
    Promise.all([getConfig(), getOps()])
      .then(([c, o]) => { setConfig(c); setOps(o); })
      .catch((e) => setError(String(e)));
  }, []);

  const filteredOps = useMemo(() => {
    if (!ops) return [];
    if (!opsSearch) return ops;
    const q = opsSearch.toLowerCase();
    return ops.filter((o) => o.sku.toLowerCase().includes(q) || o.client.toLowerCase().includes(q) || o.machine.toLowerCase().includes(q));
  }, [ops, opsSearch]);

  const reload = async () => {
    const [fresh, freshOps] = await Promise.all([getConfig(), getOps()]);
    setConfig(fresh);
    setOps(freshOps);
    refreshAll();
  };

  const showDelta = (prev: Score, curr: Score) => setDelta({ prev, curr });

  // Generic save wrapper
  const withSave = async (fn: () => Promise<{ score?: Score; score_anterior?: Score; [k: string]: unknown }>) => {
    setSaving(true);
    try {
      const res = await fn();
      await reload();
      if (res.score && res.score_anterior) {
        showDelta(res.score_anterior as Score, res.score as Score);
      }
    } catch (e) {
      alert(`Erro: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (!config) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const machineIds = Object.keys(config.machines);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Section tabs */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            style={{
              background: section === s.id ? T.elevated : "transparent",
              border: `1px solid ${section === s.id ? T.borderHover : T.border}`,
              color: section === s.id ? T.primary : T.secondary,
              borderRadius: 8, padding: "5px 12px", cursor: "pointer",
              fontSize: 12, fontWeight: section === s.id ? 600 : 400, fontFamily: "inherit",
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Score delta banner */}
      {delta && <ScoreDelta prev={delta.prev} curr={delta.curr} onClear={() => setDelta(null)} />}

      {/* ── GERAL ──────────────────────────────────────────────── */}
      {section === "geral" && (
        <Card>
          <KV label="Nome" value={config.name} />
          <KV label="Site" value={config.site} />
          <KV label="Timezone" value={config.timezone} />
          <KV label="Capacidade Diaria (min)" value={config.day_capacity_min} />
          <KV label="OEE Default" value={config.oee_default} />
          <KV label="Eco Lot Mode" value={config.eco_lot_mode} />
        </Card>
      )}

      {/* ── TURNOS (read-only) ─────────────────────────────────── */}
      {section === "turnos" && (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>ID</th>
                <th style={thStyle}>Label</th>
                <th style={thStyle}>Inicio (min)</th>
                <th style={thStyle}>Fim (min)</th>
                <th style={thStyle}>Duracao (min)</th>
              </tr>
            </thead>
            <tbody>
              {config.shifts.map((s) => (
                <tr key={s.id}>
                  <td style={tdStyle}>{s.id}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>{s.label}</td>
                  <td style={tdStyle}>{s.start_min}</td>
                  <td style={tdStyle}>{s.end_min}</td>
                  <td style={tdStyle}>{s.duration_min}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── MAQUINAS (toggle activa) ───────────────────────────── */}
      {section === "maquinas" && (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Maquina</th>
                <th style={thStyle}>Grupo</th>
                <th style={{ ...thStyle, width: 80 }}>Activa</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.machines).map(([id, m]) => (
                <tr key={id}>
                  <td style={tdStyle}>{id}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>{m.group}</td>
                  <td style={tdStyle}>
                    <button
                      disabled={saving}
                      onClick={() => withSave(() => editMachine(id, { activa: !m.active }))}
                      style={{
                        background: m.active ? T.green + "22" : T.red + "22",
                        border: `1px solid ${m.active ? T.green : T.red}`,
                        borderRadius: 6, padding: "2px 10px", cursor: "pointer",
                        fontSize: 11, color: m.active ? T.green : T.red, fontFamily: "inherit",
                        opacity: saving ? 0.5 : 1,
                      }}
                    >
                      {m.active ? "Sim" : "Nao"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── FERRAMENTAS (inline edit setup + alt) ──────────────── */}
      {section === "ferramentas" && (
        <Card style={{ padding: 0, overflow: "auto", maxHeight: 500 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Ferramenta</th>
                <th style={thStyle}>Maquina Primaria</th>
                <th style={{ ...thStyle, width: 140 }}>Alternativa</th>
                <th style={{ ...thStyle, width: 100 }}>Setup (h)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.tools).map(([id, t]) => {
                const editState = toolEdits[id];
                return (
                  <tr key={id}>
                    <td style={tdStyle}>{id}</td>
                    <td style={tdStyle}>{t.primary}</td>
                    <td style={tdStyle}>
                      <select
                        value={editState?.alt !== undefined ? (editState.alt ?? "") : (t.alt ?? "")}
                        disabled={saving}
                        onChange={(e) => {
                          const val = e.target.value || null;
                          if (val === t.alt) {
                            const next = { ...toolEdits };
                            if (next[id]) { delete next[id].alt; if (!Object.keys(next[id]).length) delete next[id]; }
                            setToolEdits(next);
                          } else {
                            setToolEdits({ ...toolEdits, [id]: { ...toolEdits[id], alt: val } });
                          }
                        }}
                        onBlur={() => {
                          const ed = toolEdits[id];
                          if (ed?.alt !== undefined && ed.alt !== t.alt) {
                            withSave(() => editTool(id, { alt: ed.alt }));
                            const next = { ...toolEdits }; delete next[id]; setToolEdits(next);
                          }
                        }}
                        style={{ ...inputStyle, width: 110, textAlign: "left", cursor: "pointer" }}
                      >
                        <option value="">—</option>
                        {machineIds.filter((mid) => mid !== t.primary).map((mid) => (
                          <option key={mid} value={mid}>{mid}</option>
                        ))}
                      </select>
                    </td>
                    <td style={tdStyle}>
                      <input
                        type="number" step="0.25" min="0"
                        disabled={saving}
                        defaultValue={t.setup_hours}
                        onBlur={(e) => {
                          const val = parseFloat(e.target.value);
                          if (!isNaN(val) && val !== t.setup_hours) {
                            withSave(() => editTool(id, { setup_hours: val }));
                          }
                        }}
                        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                        style={{ ...inputStyle, width: 70 }}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── GEMEAS (add/remove) ────────────────────────────────── */}
      {section === "gemeas" && (
        <>
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Label>Pecas Gemeas ({config.twins.length})</Label>
              <button onClick={() => setTwinModal(true)} style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}>
                + Adicionar
              </button>
            </div>
            {config.twins.length === 0 ? (
              <div style={{ padding: "12px 20px", color: T.secondary, fontSize: 13 }}>Sem pecas gemeas configuradas.</div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={thStyle}>Ferramenta</th>
                    <th style={thStyle}>SKU A</th>
                    <th style={thStyle}>SKU B</th>
                    <th style={{ ...thStyle, width: 50 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {config.twins.map((tw) => (
                    <tr key={tw.tool_id}>
                      <td style={tdStyle}>{tw.tool_id}</td>
                      <td style={tdStyle}>{tw.sku_a}</td>
                      <td style={tdStyle}>{tw.sku_b}</td>
                      <td style={tdStyle}>
                        <button
                          disabled={saving}
                          onClick={() => {
                            if (confirm(`Remover twin ${tw.tool_id}?`)) {
                              withSave(() => removeTwin(tw.tool_id));
                            }
                          }}
                          style={{ background: "none", border: "none", color: T.red, cursor: "pointer", fontSize: 14, fontFamily: "inherit", opacity: saving ? 0.5 : 1 }}
                        >
                          ×
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          {twinModal && (
            <Modal title="Adicionar Gemea" onClose={() => setTwinModal(false)}>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {(["tool_id", "sku_a", "sku_b"] as const).map((field) => (
                  <div key={field}>
                    <Label style={{ marginBottom: 4 }}>{field === "tool_id" ? "Ferramenta" : field === "sku_a" ? "SKU A" : "SKU B"}</Label>
                    <input
                      type="text"
                      value={twinForm[field]}
                      onChange={(e) => setTwinForm({ ...twinForm, [field]: e.target.value })}
                      style={{ ...inputStyle, width: "100%", textAlign: "left" }}
                      placeholder={field === "tool_id" ? "BFP001" : "SKU..."}
                    />
                  </div>
                ))}
                <button
                  disabled={!twinForm.tool_id || !twinForm.sku_a || !twinForm.sku_b || saving}
                  onClick={async () => {
                    await withSave(() => addTwin(twinForm.tool_id, twinForm.sku_a, twinForm.sku_b));
                    setTwinForm({ tool_id: "", sku_a: "", sku_b: "" });
                    setTwinModal(false);
                  }}
                  style={saveBtnStyle(!!twinForm.tool_id && !!twinForm.sku_a && !!twinForm.sku_b, saving)}
                >
                  {saving ? "A guardar..." : "Adicionar"}
                </button>
              </div>
            </Modal>
          )}
        </>
      )}

      {/* ── OPERADORES (inline edit + batch save) ──────────────── */}
      {section === "operadores" && (
        <Card style={{ padding: 0, overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Grupo/Turno</th>
                <th style={{ ...thStyle, width: 100 }}>Operadores</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(config.operators).map(([key, count]) => (
                <tr key={key}>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>{key}</td>
                  <td style={tdStyle}>
                    <input
                      type="number" min="0"
                      disabled={saving}
                      value={key in opEdits ? opEdits[key] : count}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        if (isNaN(val)) return;
                        if (val === count) {
                          const next = { ...opEdits }; delete next[key]; setOpEdits(next);
                        } else {
                          setOpEdits({ ...opEdits, [key]: val });
                        }
                      }}
                      style={{ ...inputStyle, width: 70, borderColor: key in opEdits ? T.blue : T.border }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {opHasChanges && (
            <div style={{ padding: "12px 16px", display: "flex", gap: 8, alignItems: "center" }}>
              <button
                disabled={saving}
                onClick={async () => {
                  await withSave(() => updateOperators(opEdits));
                  setOpEdits({});
                }}
                style={saveBtnStyle(true, saving)}
              >
                {saving ? "A guardar..." : "Guardar"}
              </button>
              <button onClick={() => setOpEdits({})} style={btnStyle}>Cancelar</button>
            </div>
          )}
        </Card>
      )}

      {/* ── FERIADOS (add/remove) ──────────────────────────────── */}
      {section === "feriados" && (
        <Card>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
            <input
              type="date"
              value={newHoliday}
              onChange={(e) => setNewHoliday(e.target.value)}
              style={{ ...inputStyle, width: 160, textAlign: "left" }}
            />
            <button
              disabled={!newHoliday || saving}
              onClick={async () => {
                await withSave(() => addHoliday(newHoliday));
                setNewHoliday("");
              }}
              style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50", opacity: !newHoliday || saving ? 0.5 : 1 }}
            >
              Adicionar
            </button>
          </div>
          {config.holidays.length === 0 ? (
            <div style={{ color: T.secondary, fontSize: 13 }}>Sem feriados configurados.</div>
          ) : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {config.holidays.map((h) => (
                <span key={h} style={{
                  fontSize: 12, fontFamily: T.mono, color: T.primary,
                  background: T.elevated, padding: "4px 10px", borderRadius: 6,
                  display: "flex", alignItems: "center", gap: 6,
                }}>
                  {h}
                  <button
                    disabled={saving}
                    onClick={() => {
                      if (confirm(`Remover feriado ${h}?`)) {
                        withSave(() => removeHoliday(h));
                      }
                    }}
                    style={{ background: "none", border: "none", color: T.red, cursor: "pointer", fontSize: 13, fontFamily: "inherit", padding: 0, opacity: saving ? 0.5 : 1 }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* ── PARAMETROS ─────────────────────────────────────────── */}
      {section === "parametros" && (
        <ParametrosEditor config={config} onSaved={(c) => setConfig(c)} onDelta={showDelta} />
      )}

      {/* ── PLANEAMENTO SKU ───────────────────────────────────── */}
      {section === "planeamento" && (
        ops ? (
          <SkuPlanningEditor
            config={config}
            ops={ops}
            onReload={reload}
            onDelta={showDelta}
          />
        ) : (
          <div style={{ color: T.secondary, padding: 24 }}>A carregar SKUs...</div>
        )
      )}

      {/* ── SUBCONTRATACOES ───────────────────────────────────── */}
      {section === "subcontratacoes" && (
        ops ? (
          <SubcontractEditor
            config={config}
            ops={ops}
            onReload={reload}
            onDelta={showDelta}
          />
        ) : (
          <div style={{ color: T.secondary, padding: 24 }}>A carregar SKUs...</div>
        )
      )}

      {/* ── OPERACOES (read-only) ──────────────────────────────── */}
      {section === "operacoes" && (
        <>
          <input
            type="text"
            placeholder="Filtrar SKU, cliente, maquina..."
            value={opsSearch}
            onChange={(e) => setOpsSearch(e.target.value)}
            style={{
              background: T.elevated, border: `1px solid ${T.border}`,
              borderRadius: 8, padding: "6px 12px", fontSize: 12,
              color: T.primary, fontFamily: T.mono, outline: "none", width: 280,
            }}
          />
          <Card style={{ padding: 0, overflow: "auto", maxHeight: 600 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>SKU</th>
                  <th style={thStyle}>Cliente</th>
                  <th style={thStyle}>Maquina</th>
                  <th style={thStyle}>Ferramenta</th>
                  <th style={thStyle}>Alt</th>
                  <th style={thStyle}>Pcs/H</th>
                  <th style={thStyle}>Setup (h)</th>
                  <th style={thStyle}>Eco ISOP</th>
                  <th style={thStyle}>Eco efetivo</th>
                  <th style={thStyle}>Stock</th>
                  <th style={thStyle}>OEE</th>
                </tr>
              </thead>
              <tbody>
                {filteredOps.map((op) => (
                  <tr key={op.id}>
                    <td style={tdStyle}>{op.sku}</td>
                    <td style={{ ...tdStyle, fontFamily: T.sans }}>{op.client}</td>
                    <td style={tdStyle}>{op.machine}</td>
                    <td style={tdStyle}>{op.tool}</td>
                    <td style={tdStyle}>{op.alt_machine ?? "-"}</td>
                    <td style={tdStyle}>{op.pcs_hour}</td>
                    <td style={tdStyle}>{op.setup_hours}</td>
                    <td style={tdStyle}>{(op.eco_lot_isop ?? op.eco_lot).toLocaleString()}</td>
                    <td style={{ ...tdStyle, color: (op.eco_lot_isop ?? op.eco_lot) !== (op.eco_lot_effective ?? op.eco_lot) ? T.orange : T.primary }}>
                      {(op.eco_lot_effective ?? op.eco_lot).toLocaleString()}
                    </td>
                    <td style={tdStyle}>{op.stock.toLocaleString()}</td>
                    <td style={tdStyle}>{op.oee}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}

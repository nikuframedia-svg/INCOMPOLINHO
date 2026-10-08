import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { T } from "../theme/tokens";
import {
  getCatalog, getConfig, getOps, updateConfig,
  updateOperators,
  addExtraWorkday, addHoliday, addHolidayRange, addTwin,
  removeExtraWorkday, removeHoliday, removeHolidayRange, removeTwin,
  replaceSetupOverrides, applyPreset,
  applyReplan, cancelReplan, getReplan, getReplans, startReplan,
  previewSkuPlanning, previewSubcontracts, resetSkuPlanning, updateSkuPlanning, updateSubcontracts,
  getTrust,
} from "../api/endpoints";
import type {
  EOp,
  FactoryConfig,
  GateReport,
  MasterCatalog,
  PlanningDelta,
  ReplanJob,
  Score,
  SetupOverride,
  SkuPlanningResponse,
  SkuPlanningRule,
  TrustIndex,
} from "../api/types";
import { Card } from "../components/ui/Card";
import { Label } from "../components/ui/Label";
import { Divider } from "../components/ui/Divider";
import { Modal } from "../components/ui/Modal";
import { ProgressBar } from "../components/ui/ProgressBar";
import { useConfirm, type ConfirmContextValue } from "../components/ui/confirmContext";
import { useDataStore } from "../stores/useDataStore";
import { useAppStore } from "../stores/useAppStore";
import { ApiError } from "../api/client";
import { remainingDraft, remainingToolDraft } from "../lib/configDraft";
import {
  approvalImpactMessage,
  approvalReasonLabel,
  sendWithGateApproval,
  type GateApproval,
  gateStatusLabel,
} from "../lib/gateApproval";
import { getReadIdentity } from "../lib/planRevision";

type Section = "geral" | "turnos" | "maquinas" | "ferramentas" | "gemeas" | "setup_overrides" | "operadores" | "feriados" | "indisponibilidades" | "parametros" | "planeamento" | "subcontratacoes" | "operacoes" | "qualidade_dados";
type ConfigGroup = "factory" | "articles" | "calendar" | "availability" | "engine";
type SortDirection = "asc" | "desc";
type UnavailabilityKind = "machine" | "tool" | "operator";
type UnavailabilityCategory = "Avaria" | "Manutenção" | "Ensaio" | "Outra";
type UnavailabilityForm = {
  kind: UnavailabilityKind;
  resource: string;
  operatorKey: string;
  start_at: string;
  end_at: string;
  category: UnavailabilityCategory;
  count: number;
  reason: string;
};
type UnavailabilityEditTarget = { source: "existing" | "addition"; id: string };
type UnavailabilityRow = UnavailabilityForm & {
  id: string;
  kindLabel: string;
  resourceLabel: string;
  status: { label: string; color: string };
  draftState: "unchanged" | "edited" | "added" | "removed";
};

const CONFIG_GROUPS: { id: ConfigGroup; label: string; sections: { id: Section; label: string }[] }[] = [
  { id: "factory", label: "Fábrica", sections: [
    { id: "maquinas", label: "Máquinas" },
    { id: "turnos", label: "Turnos" },
    { id: "operadores", label: "Operadores" },
  ] },
  { id: "articles", label: "Ferramentas e artigos", sections: [
    { id: "ferramentas", label: "Ferramentas" },
    { id: "setup_overrides", label: "Exceções de setup" },
    { id: "gemeas", label: "Gémeas" },
    { id: "subcontratacoes", label: "Subcontratações" },
  ] },
  { id: "calendar", label: "Calendário", sections: [
    { id: "feriados", label: "Feriados & dias extra" },
  ] },
  { id: "availability", label: "Indisponibilidades", sections: [
    { id: "indisponibilidades", label: "Indisponibilidades" },
  ] },
  { id: "engine", label: "Administração / Avançado", sections: [
    { id: "qualidade_dados", label: "Qualidade de dados" },
    { id: "operacoes", label: "Ver dados ISOP" },
    { id: "planeamento", label: "Correções de planeamento" },
    { id: "parametros", label: "Parâmetros" },
  ] },
];

const GROUP_HELP: Record<ConfigGroup, string> = {
  factory: "Define os recursos que existem na fábrica, os turnos e as pessoas disponíveis. As alterações só entram no plano depois de Guardar.",
  articles: "Consulta ferramentas e referências vindas do ISOP e guarda apenas as exceções necessárias entre carregamentos.",
  calendar: "Regista dias fechados e dias de trabalho extra que alteram o calendário fabril.",
  availability: "Regista indisponibilidades com início e fim exatos para o planeador não usar recursos indisponíveis.",
  engine: "Concentra os dados recebidos do ISOP e os parâmetros técnicos. Usa esta área apenas quando precisares de corrigir a origem dos dados ou o cálculo.",
};

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

const sortMultiplier = (direction: SortDirection) => direction === "asc" ? 1 : -1;

const REPLAN_POLL_INTERVAL_MS = 750;
const REPLAN_MAX_BACKOFF_MS = 6000;

const emptyUnavailability = (
  kind: UnavailabilityKind = "machine",
  category: UnavailabilityCategory = "Avaria",
): UnavailabilityForm => ({
  kind,
  resource: "",
  operatorKey: "",
  start_at: "",
  end_at: "",
  category,
  count: 1,
  reason: "",
});

const datetimeLocalValue = (value?: string) => value ? value.slice(0, 16) : "";

const unavailabilityPayload = (form: UnavailabilityForm, id?: string) => {
  const payload: Record<string, unknown> = {
    ...(id ? { id } : {}),
    kind: form.kind,
    start_at: form.start_at,
    end_at: form.end_at,
    category: form.category,
    reason: form.reason,
  };
  if (form.kind === "operator") {
    const parts = form.operatorKey.trim().split(/\s+/);
    payload.shift = parts.pop() ?? "";
    payload.group = parts.join(" ");
    payload.count = form.count;
  } else {
    payload.resource = form.resource;
  }
  return payload;
};

type ReplanFollowup = {
  reason: string;
  changes: string[];
  successMessage: string;
  onSuccess: () => void;
};

function formatElapsedTime(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes} min ${seconds.toString().padStart(2, "0")} s` : `${seconds} s`;
}

function compareText(left: unknown, right: unknown) {
  return String(left ?? "").localeCompare(String(right ?? ""), "pt-PT", { numeric: true });
}

function compareNumber(left: unknown, right: unknown) {
  return Number(left ?? 0) - Number(right ?? 0);
}

function unavailabilityStatus(entry: {
  start_at?: string;
  end_at?: string;
  from?: string;
  to?: string;
}) {
  const now = Date.now();
  const start = Date.parse(entry.start_at ?? entry.from ?? "");
  const end = Date.parse(entry.end_at ?? entry.to ?? "");
  if (Number.isFinite(end) && end <= now) return { label: "Expirada", color: T.tertiary };
  if (Number.isFinite(start) && start > now) return { label: "Agendada", color: T.orange };
  return { label: "Atual", color: T.red };
}

function SortableTh<T extends string>({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
  style,
  title,
}: {
  label: string;
  sortKey: T;
  activeKey: T;
  direction: SortDirection;
  onSort: (key: T) => void;
  style?: React.CSSProperties;
  title?: string;
}) {
  const active = activeKey === sortKey;
  return (
    <th title={title} style={{ ...thStyle, ...style, cursor: "pointer", userSelect: "none" }} onClick={() => onSort(sortKey)}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        {label}
        <span style={{ color: active ? T.primary : T.borderHover, fontSize: 10 }}>
          {active ? (direction === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </span>
    </th>
  );
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
      <span style={{ fontSize: 12, color: T.secondary }}>{label}</span>
      <span style={{ fontSize: 12, color: T.primary, fontFamily: T.mono }}>{String(value)}</span>
    </div>
  );
}

function HelpPanel({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="note"
      style={{
        display: "grid",
        gridTemplateColumns: "4px minmax(0, 1fr)",
        gap: 12,
        alignItems: "stretch",
        padding: "11px 14px",
        border: `1px solid ${T.blue}30`,
        borderRadius: 9,
        background: `${T.blue}08`,
      }}
    >
      <div style={{ background: T.blue, borderRadius: 4 }} />
      <div>
        <div style={{ color: T.blue, fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" }}>
          Para que serve
        </div>
        <div style={{ color: T.secondary, fontSize: 12, lineHeight: 1.55, marginTop: 3 }}>
          {children}
        </div>
      </div>
    </div>
  );
}

const TRUST_DIMENSION_COPY: Record<string, { label: string; checks: string[] }> = {
  completeness: {
    label: "Completude",
    checks: [
      "Verifica se as operações têm tempo produtivo preenchido.",
      "Verifica se existe cliente e designação.",
      "Verifica se a procura/demanda tem o tamanho correto para o horizonte.",
    ],
  },
  validity: {
    label: "Validade",
    checks: [
      "Verifica se os tempos e valores numéricos estão em intervalos válidos.",
      "Confirma se o OEE está entre 0 e 1.",
      "Confirma se a máquina principal e a alternativa existem na configuração.",
    ],
  },
  consistency: {
    label: "Consistência",
    checks: [
      "Verifica se as operações gémeas referem operações válidas.",
      "Confirma se as operações gémeas estão na mesma máquina.",
      "Confirma se o calendário cobre o horizonte e se não há IDs duplicados.",
    ],
  },
  richness: {
    label: "Riqueza dos dados",
    checks: [
      "Mede se existem dados opcionais úteis para planear melhor.",
      "Conta máquinas alternativas, lotes económicos, feriados e procura por cliente.",
      "Um valor baixo aqui não significa erro crítico; significa que o planeamento tem menos contexto.",
    ],
  },
};

function trustGateLabel(gate: string) {
  if (gate === "full_auto") return "Automático completo";
  if (gate === "monitoring") return "Automático com monitorização";
  if (gate === "suggestion") return "Sugestões, requer atenção";
  if (gate === "manual") return "Manual";
  return gate;
}

function scoreColor(score: number) {
  if (score >= 80) return T.green;
  if (score >= 50) return T.orange;
  return T.red;
}

function BulletList({ items }: { items: string[] }) {
  return (
    <ul style={{ margin: "6px 0 0 18px", padding: 0, display: "grid", gap: 4 }}>
      {items.map((item) => (
        <li key={item} style={{ color: T.secondary, fontSize: 12, lineHeight: 1.45 }}>{item}</li>
      ))}
    </ul>
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
    { l: "Lotes no prazo", p: prev.otd, c: curr.otd, u: "%" },
    { l: "Cumprimento diário", p: prev.otd_d, c: curr.otd_d, u: "%" },
    { l: "Setups", p: prev.setups, c: curr.setups },
    { l: "Lotes atrasados", p: prev.tardy_count, c: curr.tardy_count },
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
  { id: "min_setups", label: "Menos setups", color: T.orange },
  { id: "max_otd", label: "Mais entregas a tempo", color: T.green },
];

const DEFAULT_SUBCONTRACT_READ_DAYS = 7;
const DEFAULT_SUBCONTRACT_WORKDAYS = 5;

function calendarDaysToWorkdays(days: number) {
  const safe = Math.max(0, Math.trunc(days));
  const fullWeeks = Math.floor(safe / 7);
  const remainder = safe % 7;
  return fullWeeks * 5 + Math.min(remainder, 5);
}

function workdaysToCalendarDays(days: number) {
  const safe = Math.max(0, Math.trunc(days));
  const fullWeeks = Math.floor(safe / 5);
  const remainder = safe % 5;
  return fullWeeks * 7 + remainder;
}

// ── Tunables ─────────────────────────────────────────────────────

const TUNABLES: { key: string; label: string; type: "number" | "boolean" | "select"; options?: string[] }[] = [
  { key: "oee_default", label: "OEE Default", type: "number" },
  { key: "jit_buffer_pct", label: "JIT Buffer %", type: "number" },
  { key: "jit_max_retries", label: "JIT Max Retries", type: "number" },
  { key: "max_run_days", label: "Max Run Days", type: "number" },
  { key: "max_edd_gap", label: "Max EDD Gap", type: "number" },
  { key: "max_edd_span", label: "Max EDD Span", type: "number" },
  { key: "edd_swap_tolerance", label: "EDD Swap Tolerance", type: "number" },
  { key: "edd_assign_threshold", label: "EDD Assign Threshold", type: "number" },
  { key: "campaign_window", label: "Campaign Window", type: "number" },
  { key: "urgency_threshold", label: "Urgency Threshold", type: "number" },
  { key: "interleave_enabled", label: "Interleave Activo", type: "boolean" },
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
  const { confirm, prompt } = useConfirm();
  const ask = justificationAsker(prompt);
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
    const submitted = { ...edits };
    setSaving(true);
    setMsg(null);
    try {
      const res = await sendWithGateApproval((approval) => updateConfig(submitted, approval), ask);
      if (res === null) {
        setMsg(NOT_APPLIED);
        return;
      }
      setEdits((current) => Object.fromEntries(Object.entries(current).filter(
        ([key, value]) => !(key in submitted) || value !== submitted[key],
      )));
      setActivePreset(null);
      const fresh = await getConfig();
      onSaved(fresh);
      onDelta(res.score_previous, res.score);
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
    } catch (e) {
      setMsg(failureMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const handlePreset = async (name: string) => {
    const submitted = { ...edits };
    const approved = await confirm({
      title: "Aplicar preset",
      message: `Aplicar preset “${name}”? Os parâmetros serão substituídos.`,
      confirmLabel: "Aplicar preset",
    });
    if (!approved) return;
    setSaving(true);
    setMsg(null);
    try {
      const res = await sendWithGateApproval((approval) => applyPreset(name, approval), ask);
      if (res === null) {
        setMsg(NOT_APPLIED);
        return;
      }
      setEdits((current) => Object.fromEntries(Object.entries(current).filter(
        ([key, value]) => !(key in submitted) || value !== submitted[key],
      )));
      const fresh = await getConfig();
      onSaved(fresh);
      // Show the score delta so the planner sees the impact immediately
      if (res.score && res.score_previous) {
        onDelta(res.score_previous, res.score);
      }
      const simNote = res.simulation_active ? " — simulacao mantida" : "";
      setMsg(`Preset "${name}" aplicado (${res.changed.length} parametros)${simNote}`);
      setActivePreset(name);
      assertRefreshed(await refreshAfterCommit(refreshAll), true);
    } catch (e) {
      setMsg(failureMessage(e));
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
            Simulação ativa — a predefinição será aplicada por cima dela.
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

      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", color: T.secondary, fontSize: 12, fontWeight: 600 }}>
          Avançado
        </summary>
        <div style={{ marginTop: 8, padding: "10px 12px", background: T.elevated, borderRadius: 8, color: T.secondary, fontSize: 11 }}>
          O plano executável começa sempre no dia 0. O antigo Auto Buffer que
          criava dias negativos deixou de estar disponível; os buffers JIT, de
          artigo e de subcontratação continuam a ser margens de planeamento.
        </div>
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
                {getValue(t.key) ? "Sim" : "Não"}
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
        </div>
      </details>
      {msg && <div style={{ marginTop: 10, fontSize: 11, color: msg.startsWith("Erro") ? T.red : T.green }}>{msg}</div>}
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
  return `Lotes no prazo ${d.otd >= 0 ? "+" : ""}${d.otd.toFixed(1)} · Envios a subcontratado falhados ${d.subcontract_dispatch_misses >= 0 ? "+" : ""}${d.subcontract_dispatch_misses} · Dias úteis de atraso no subcontratado ${d.subcontract_dispatch_late_workdays >= 0 ? "+" : ""}${d.subcontract_dispatch_late_workdays} · Setups ${d.setups >= 0 ? "+" : ""}${d.setups}`;
}

const NOT_APPLIED = "Alteração não aplicada. O plano não mudou.";

/** Ask the planner to justify a candidate that needs explicit approval. */
function justificationAsker(prompt: ConfirmContextValue["prompt"]) {
  return (gate: GateReport) => prompt({
    title: "Aplicar alteração com exceções?",
    message: approvalImpactMessage(gate),
    inputLabel: "Justificação obrigatória",
    placeholder: "Explica por que motivo este impacto é aceite…",
    confirmLabel: "Confirmar e aplicar",
    variant: "danger",
    required: true,
  });
}

/** "Erro: …", except when the change was saved and only the screen is behind. */
function failureMessage(error: unknown) {
  return isAppliedRefreshError(error) ? error.message : `Erro: ${apiErrorMessage(error)}`;
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
  const ask = justificationAsker(useConfirm().prompt);
  const [search, setSearch] = useState("");
  const [drafts, setDrafts] = useState<Record<string, SkuPlanningRule>>({});
  const [preview, setPreview] = useState<Record<string, SkuPlanningResponse>>({});
  const [busySku, setBusySku] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [sort, setSort] = useState<"sku" | "client" | "machine" | "tool" | "effective" | "source">("sku");

  const visible = useMemo(() => {
    const q = search.toLowerCase();
    const filtered = ops.filter((op) => !q || (
      op.sku.toLowerCase().includes(q)
      || op.client.toLowerCase().includes(q)
      || op.tool.toLowerCase().includes(q)
    ));
    return filtered.sort((left, right) => {
      if (sort === "client") return left.client.localeCompare(right.client, "pt-PT") || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
      if (sort === "machine") return left.machine.localeCompare(right.machine, "pt-PT", { numeric: true }) || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
      if (sort === "tool") return left.tool.localeCompare(right.tool, "pt-PT", { numeric: true }) || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
      if (sort === "effective") return Number(right.eco_lot_effective ?? right.eco_lot) - Number(left.eco_lot_effective ?? left.eco_lot);
      if (sort === "source") return Number(left.active === false) - Number(right.active === false) || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
      return left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
    });
  }, [ops, search, sort]);

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
      setMsg(failureMessage(e));
    } finally {
      setBusySku(null);
    }
  };

  const apply = async (sku: string) => {
    setBusySku(sku);
    setMsg(null);
    try {
      const res = await sendWithGateApproval(
        (approval) => updateSkuPlanning(sku, cleanRule(ruleFor(sku)), approval), ask,
      );
      if (res === null) {
        setMsg(NOT_APPLIED);
        return;
      }
      if (res.score_previous && res.score) onDelta(res.score_previous, res.score);
      const nextDrafts = { ...drafts };
      delete nextDrafts[sku];
      setDrafts(nextDrafts);
      setMsg(`Aplicado ${sku}: ${metricDelta(res) ?? "plano recalculado"}`);
      await onReload();
    } catch (e) {
      setMsg(failureMessage(e));
    } finally {
      setBusySku(null);
    }
  };

  const reset = async (sku: string) => {
    setBusySku(sku);
    setMsg(null);
    try {
      const res = await sendWithGateApproval((approval) => resetSkuPlanning(sku, approval), ask);
      if (res === null) {
        setMsg(NOT_APPLIED);
        return;
      }
      if (res.score_previous && res.score) onDelta(res.score_previous, res.score);
      const nextDrafts = { ...drafts };
      delete nextDrafts[sku];
      setDrafts(nextDrafts);
      setMsg(`Reposto para ISOP: ${sku}`);
      await onReload();
    } catch (e) {
      setMsg(failureMessage(e));
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
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          type="search"
          placeholder="Filtrar referência, cliente ou ferramenta…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: T.elevated, border: `1px solid ${T.border}`,
            borderRadius: 8, padding: "6px 12px", fontSize: 12,
            color: T.primary, fontFamily: T.mono, outline: "none", width: 300,
          }}
        />
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as typeof sort)}
          aria-label="Ordenar correções de planeamento"
          style={{ ...inputStyle, width: 185, textAlign: "left" }}
        >
          <option value="sku">Ordenar: referência</option>
          <option value="client">Ordenar: cliente</option>
          <option value="machine">Ordenar: máquina</option>
          <option value="tool">Ordenar: ferramenta</option>
          <option value="effective">Ordenar: eco efetivo</option>
          <option value="source">Ordenar: origem</option>
        </select>
        <span style={{ marginLeft: "auto", color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
          {visible.length} de {ops.length}
        </span>
      </div>
      {msg && <div style={{ fontSize: 12, color: msg.startsWith("Erro") ? T.red : T.green }}>{msg}</div>}
      <Card style={{ padding: 0, overflow: "auto", maxHeight: 620 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1240 }}>
          <thead>
            <tr>
              <th style={thStyle}>Referência</th>
              <th style={thStyle}>Cliente</th>
              <th style={thStyle}>Máquina</th>
              <th style={thStyle}>Ferramenta</th>
              <th style={thStyle}>Peças/h</th>
              <th style={thStyle}>Operadores</th>
              <th style={thStyle}>Eco ISOP</th>
              <th style={thStyle}>Eco efetivo</th>
              <th style={thStyle}>Novo eco</th>
              <th style={thStyle}>Começar antes</th>
              <th style={thStyle}>Acabar antes</th>
              <th style={thStyle}>Campanha min pç</th>
              <th style={thStyle}>Campanha min min</th>
              <th style={thStyle}>Janela dias</th>
              <th style={thStyle}>Prioridade cliente/ref.</th>
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
                  <td style={tdStyle}>
                    {op.sku}
                    {op.active === false && (
                      <div style={{ color: T.tertiary, fontSize: 9, marginTop: 2 }}>inativo · histórico</div>
                    )}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>{op.client}</td>
                  <td style={tdStyle}>{op.machine}</td>
                  <td style={tdStyle}>{op.tool}</td>
                  <td style={tdStyle}>{op.pcs_hour}</td>
                  <td style={tdStyle}>{op.operators}</td>
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
                  <td style={tdStyle}>{numberInput(op, "planning_priority", 76)}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans, color: p ? T.secondary : T.tertiary }}>
                    {p ? `${metricDelta(p)} · lotes ${p.impact_before?.lots ?? 0}→${p.impact_after?.lots ?? 0}` : "-"}
                    {p?.impact_after?.warnings?.length ? (
                      <div style={{ color: T.orange, marginTop: 3 }}>{p.impact_after.warnings[0]}</div>
                    ) : null}
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button disabled={isBusy || op.active === false} onClick={() => runPreview(op.sku)} style={btnStyle}>Rever impacto</button>
                      <button disabled={isBusy || op.active === false} onClick={() => apply(op.sku)} style={{ ...btnStyle, color: T.blue }}>Aplicar</button>
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
  lead_time_days: DEFAULT_SUBCONTRACT_READ_DAYS,
  lead_time_workdays: DEFAULT_SUBCONTRACT_WORKDAYS,
};

function subcontractInitialSelection(config: FactoryConfig) {
  return new Set([
    ...(config.subcontract_skus ?? []),
    ...Object.entries(config.sku_subcontracts ?? {})
      .filter(([, rule]) => rule.enabled !== false)
      .map(([sku]) => sku),
  ]);
}

function subcontractInitialLeadTimes(config: FactoryConfig) {
  return Object.fromEntries(
    Object.entries(config.sku_subcontracts ?? {}).map(([sku, rule]) => [
      sku,
      Math.max(
        0,
        Number(
          rule.lead_time_workdays
            ?? calendarDaysToWorkdays(Number(rule.lead_time_days ?? DEFAULT_SUBCONTRACT_READ_DAYS)),
        ),
      ),
    ]),
  );
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
  const ask = justificationAsker(useConfirm().prompt);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => subcontractInitialSelection(config));
  const [leadTimes, setLeadTimes] = useState<Record<string, number>>(() => subcontractInitialLeadTimes(config));
  const [busy, setBusy] = useState<"preview" | "save" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [previewDelta, setPreviewDelta] = useState<PlanningDelta | null>(null);
  const [sort, setSort] = useState<"selected" | "sku" | "client" | "demand" | "lead" | "source">("selected");

  useEffect(() => {
    setSelected(subcontractInitialSelection(config));
    setLeadTimes(subcontractInitialLeadTimes(config));
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
      .sort((left, right) => {
        if (sort === "selected") return Number(selected.has(right.sku)) - Number(selected.has(left.sku)) || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
        if (sort === "client") return left.client.localeCompare(right.client, "pt-PT") || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
        if (sort === "demand") return right.demand.reduce((sum, qty) => sum + qty, 0) - left.demand.reduce((sum, qty) => sum + qty, 0);
        if (sort === "lead") return Number(leadTimes[right.sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS) - Number(leadTimes[left.sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS);
        if (sort === "source") return Number(left.active === false) - Number(right.active === false) || left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
        return left.sku.localeCompare(right.sku, "pt-PT", { numeric: true });
      });
  }, [leadTimes, ops, search, selected, sort]);

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
          lead_time_days: workdaysToCalendarDays(leadTimes[sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS),
          lead_time_workdays: leadTimes[sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS,
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
      setMsg(`Impacto revisto: ${metricDelta(res) ?? "plano recalculado"}`);
    } catch (e) {
      setMsg(failureMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy("save");
    setMsg(null);
    try {
      const res = await sendWithGateApproval((approval) => updateSubcontracts(bodyFor(), approval), ask);
      if (res === null) {
        setMsg(NOT_APPLIED);
        return;
      }
      if (res.score_previous && res.score) onDelta(res.score_previous, res.score);
      setPreviewDelta(res.delta ?? null);
      setMsg(`${selected.size} referência${selected.size === 1 ? "" : "s"} guardada${selected.size === 1 ? "" : "s"} para subcontrato.`);
      await onReload();
    } catch (e) {
      setMsg(failureMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <input
          type="search"
          placeholder="Filtrar referência ou cliente…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            background: T.elevated, border: `1px solid ${T.border}`,
            borderRadius: 8, padding: "6px 12px", fontSize: 12,
            color: T.primary, fontFamily: T.mono, outline: "none", width: 300,
          }}
        />
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as typeof sort)}
          aria-label="Ordenar subcontratações"
          style={{ ...inputStyle, width: 185, textAlign: "left" }}
        >
          <option value="selected">Ordenar: selecionadas</option>
          <option value="sku">Ordenar: referência</option>
          <option value="client">Ordenar: cliente</option>
          <option value="demand">Ordenar: procura</option>
          <option value="lead">Ordenar: antecedência</option>
          <option value="source">Ordenar: origem</option>
        </select>
        <span style={{ fontSize: 12, color: T.secondary, fontFamily: T.mono }}>
          {selected.size} selecionada{selected.size === 1 ? "" : "s"} · 7 dias corridos de leitura · 5 dias úteis por defeito
        </span>
        <button type="button" disabled={busy !== null} onClick={runPreview} style={btnStyle}>
          {busy === "preview" ? "A calcular..." : "Rever impacto"}
        </button>
        <button type="button" disabled={busy !== null} onClick={save} style={{ ...btnStyle, color: T.blue }}>
          {busy === "save" ? "A guardar..." : "Guardar alterações"}
        </button>
        <button
          type="button"
          disabled={busy !== null}
          onClick={() => {
            setSelected(subcontractInitialSelection(config));
            setLeadTimes(subcontractInitialLeadTimes(config));
            setPreviewDelta(null);
            setMsg(null);
          }}
          style={btnStyle}
        >
          Cancelar
        </button>
        {previewDelta && <span style={{ fontSize: 12, color: T.secondary }}>{metricDelta({ delta: previewDelta })}</span>}
      </div>
      {msg && <div style={{ fontSize: 12, color: msg.startsWith("Erro") ? T.red : T.green }}>{msg}</div>}
      <Card style={{ padding: 0, overflow: "auto", maxHeight: 620 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 720 }}>
          <thead>
            <tr>
              <th style={thStyle}>Subcontratar</th>
              <th style={thStyle}>Referência</th>
              <th style={thStyle}>Cliente</th>
              <th style={thStyle}>Procura</th>
              <th style={thStyle}>Lead fornecedor</th>
              <th style={thStyle}>Planeamento — dias úteis</th>
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
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>
                    {op.client || <span style={{ color: T.tertiary }}>histórico</span>}
                    {op.active === false && (
                      <div style={{ color: T.tertiary, fontSize: 9, marginTop: 2 }}>ausente no ISOP atual</div>
                    )}
                  </td>
                  <td style={tdStyle}>{op.demand.reduce((sum, qty) => sum + qty, 0).toLocaleString()} pç</td>
                  <td style={{ ...tdStyle, color: T.secondary }}>
                    {workdaysToCalendarDays(leadTimes[op.sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS)} dias corridos
                  </td>
                  <td style={tdStyle}>
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={leadTimes[op.sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS}
                      onChange={(event) => setLeadTimes({
                        ...leadTimes,
                        [op.sku]: Math.max(0, Number(event.target.value)),
                      })}
                      aria-label={`Antecedência em dias úteis para ${op.sku}`}
                      style={{ ...inputStyle, width: 90 }}
                    />
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

// ── Main ConfigPage ──────────────────────────────────────────────

export function ConfigPage() {
  const { confirm, prompt } = useConfirm();
  const refreshAll = useDataStore((s) => s.refreshAll);
  const setPage = useAppStore((s) => s.setPage);
  const [config, setConfig] = useState<FactoryConfig | null>(null);
  const [ops, setOps] = useState<EOp[] | null>(null);
  const [catalog, setCatalog] = useState<MasterCatalog | null>(null);
  const [trust, setTrust] = useState<TrustIndex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [trustError, setTrustError] = useState<string | null>(null);
  const [catalogWarning, setCatalogWarning] = useState<string | null>(null);
  const [group, setGroup] = useState<ConfigGroup>("factory");
  const [section, setSection] = useState<Section>("maquinas");
  const [opsSearch, setOpsSearch] = useState("");
  const [opsSort, setOpsSort] = useState<"sku" | "source" | "client" | "machine" | "tool" | "alt" | "pcs_hour" | "setup" | "eco_isop" | "eco_effective" | "stock" | "oee" | "demand">("sku");
  const [opsSortDir, setOpsSortDir] = useState<SortDirection>("asc");
  const [saving, setSaving] = useState(false);
  const [delta, setDelta] = useState<{ prev: Score; curr: Score } | null>(null);

  // Operators inline edit state
  const [opEdits, setOpEdits] = useState<Record<string, number>>({});
  const opHasChanges = Object.keys(opEdits).length > 0;

  // Tools inline edit state
  const [toolEdits, setToolEdits] = useState<Record<string, { setup_hours?: number; alt?: string | null }>>({});
  const [oeeEdits, setOeeEdits] = useState<Record<string, number | null>>({});
  const [machineGroupEdits, setMachineGroupEdits] = useState<Record<string, string>>({});
  const [machineActiveEdits, setMachineActiveEdits] = useState<Record<string, boolean>>({});
  const [shiftEdits, setShiftEdits] = useState<FactoryConfig["shifts"] | null>(null);
  const [crewEdits, setCrewEdits] = useState<Record<string, number>>({});
  const [replanMessage, setReplanMessage] = useState<string | null>(null);
  const [activeReplanJobId, setActiveReplanJobId] = useState<string | null>(null);
  const [replanStartedAt, setReplanStartedAt] = useState<number | null>(null);
  const [replanElapsedSeconds, setReplanElapsedSeconds] = useState(0);
  const [replanConnectionMessage, setReplanConnectionMessage] = useState<string | null>(null);
  const replanPollGeneration = useRef(0);
  const configurationGeneration = useRef(0);
  const mounted = useRef(true);
  const followedJob = useRef<{ job: ReplanJob; followup: ReplanFollowup } | null>(null);
  const cancelling = useRef(false);
  const readOnly = useAppStore((s) => s.accessMode === "view");
  const [pendingReplan, setPendingReplan] = useState<{
    job: ReplanJob;
    reason: string;
    changes: string[];
    successMessage: string;
    onSuccess: () => void;
  } | null>(null);
  const pendingReplanBlocked = pendingReplan?.job.result?.gate_report.apply_decision === "blocked";
  const [machineSearch, setMachineSearch] = useState("");
  const [toolSearch, setToolSearch] = useState("");
  const [unavailabilitySearch, setUnavailabilitySearch] = useState("");
  const [machineSort, setMachineSort] = useState<"id" | "source" | "group" | "oee" | "active">("id");
  const [machineSortDir, setMachineSortDir] = useState<SortDirection>("asc");
  const [toolSort, setToolSort] = useState<"id" | "article" | "source" | "primary" | "alt" | "setup">("id");
  const [toolSortDir, setToolSortDir] = useState<SortDirection>("asc");
  const [unavailabilitySort, setUnavailabilitySort] = useState<"kind" | "resource" | "period" | "category" | "reason">("period");
  const [unavailabilitySortDir, setUnavailabilitySortDir] = useState<SortDirection>("asc");
  const [operatorSort, setOperatorSort] = useState<"key" | "count">("key");
  const [operatorSortDir, setOperatorSortDir] = useState<SortDirection>("asc");
  const [newMachine, setNewMachine] = useState({ id: "", group: "Grandes" });

  // Feriados add state
  const [newHoliday, setNewHoliday] = useState("");
  const [holidayRange, setHolidayRange] = useState({ from: "", to: "" });
  const [extraWorkday, setExtraWorkday] = useState("");

  // Persistent setup and calendar exceptions
  const [setupOverride, setSetupOverride] = useState<SetupOverride>({ sku: "", machine: "", hours: 0.5 });
  const [unavailability, setUnavailability] = useState<UnavailabilityForm>(emptyUnavailability());
  const [unavailabilityEdits, setUnavailabilityEdits] = useState<Record<string, UnavailabilityForm>>({});
  const [unavailabilityAdditions, setUnavailabilityAdditions] = useState<Record<string, UnavailabilityForm>>({});
  const [unavailabilityRemovals, setUnavailabilityRemovals] = useState<string[]>([]);
  const [unavailabilityEditTarget, setUnavailabilityEditTarget] = useState<UnavailabilityEditTarget | null>(null);
  const unavailabilityDraftCounter = useRef(0);

  // Gemeas modal state
  const [twinModal, setTwinModal] = useState(false);
  const [twinForm, setTwinForm] = useState({ tool_id: "", sku_a: "", sku_b: "" });

  const loadConfiguration = useCallback(async () => {
    const generation = ++configurationGeneration.current;
    const identity = JSON.stringify(getReadIdentity());
    setError(null);
    const [configResult, opsResult, catalogResult, trustResult] = await Promise.allSettled([
      getConfig(),
      getOps(),
      getCatalog(),
      getTrust(),
    ]);

    if (!mounted.current || generation !== configurationGeneration.current
      || identity !== JSON.stringify(getReadIdentity())) return;

    if (configResult.status === "rejected" || opsResult.status === "rejected") {
      const configFailed = configResult.status === "rejected";
      const failedArea = configFailed ? "as definições da fábrica" : "as referências do ISOP";
      const reason = configFailed
        ? configResult.reason
        : opsResult.status === "rejected"
          ? opsResult.reason
          : "Erro desconhecido";
      throw new Error(`Não foi possível carregar ${failedArea}. ${apiErrorMessage(reason)}`);
    }

    setConfig(configResult.value);
    setOps(opsResult.value);
    if (catalogResult.status === "fulfilled") {
      setCatalog(catalogResult.value);
      setCatalogWarning(null);
    } else {
      setCatalog(null);
      setCatalogWarning(
        "Não foi possível confirmar a origem dos dados. Podes continuar a consultar e alterar as restantes definições.",
      );
    }
    if (trustResult.status === "fulfilled") {
      setTrust(trustResult.value);
      setTrustError(null);
    } else {
      setTrust(null);
      setTrustError(apiErrorMessage(trustResult.reason));
    }
  }, []);

  useEffect(() => {
    void loadConfiguration().catch((failure) => {
      setError(apiErrorMessage(failure));
    });
  }, [loadConfiguration]);

  useEffect(() => {
    if (!activeReplanJobId || replanStartedAt === null) return;
    const updateElapsed = () => setReplanElapsedSeconds(Math.max(0, Math.floor((Date.now() - replanStartedAt) / 1000)));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [activeReplanJobId, replanStartedAt]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      replanPollGeneration.current += 1;
      configurationGeneration.current += 1;
    };
  }, []);

  const filteredOps = useMemo(() => {
    if (!ops) return [];
    const q = opsSearch.toLowerCase();
    return ops
      .filter((op) => !q || [
        op.sku,
        op.client,
        op.machine,
        op.tool,
        op.designation,
      ].some((value) => value.toLowerCase().includes(q)))
      .sort((left, right) => {
        const direction = sortMultiplier(opsSortDir);
        let result = 0;
        if (opsSort === "client") result = compareText(left.client, right.client);
        else if (opsSort === "machine") result = compareText(left.machine, right.machine);
        else if (opsSort === "tool") result = compareText(left.tool, right.tool);
        else if (opsSort === "alt") result = compareText(left.alt_machine, right.alt_machine);
        else if (opsSort === "pcs_hour") result = compareNumber(left.pcs_hour, right.pcs_hour);
        else if (opsSort === "setup") result = compareNumber(left.setup_hours, right.setup_hours);
        else if (opsSort === "eco_isop") result = compareNumber(left.eco_lot_isop ?? left.eco_lot, right.eco_lot_isop ?? right.eco_lot);
        else if (opsSort === "eco_effective") result = compareNumber(left.eco_lot_effective ?? left.eco_lot, right.eco_lot_effective ?? right.eco_lot);
        else if (opsSort === "stock") result = compareNumber(left.stock, right.stock);
        else if (opsSort === "oee") result = compareNumber(left.oee, right.oee);
        else if (opsSort === "demand") result = compareNumber(left.demand.reduce((sum, qty) => sum + qty, 0), right.demand.reduce((sum, qty) => sum + qty, 0));
        else if (opsSort === "source") result = compareNumber(Number(left.active === false), Number(right.active === false));
        else result = compareText(left.sku, right.sku);
        return result * direction || compareText(left.sku, right.sku);
      });
  }, [ops, opsSearch, opsSort, opsSortDir]);

  const reload = async () => {
    const outcome = await refreshAfterCommit(refreshAll);
    assertRefreshed(outcome, true);
    await loadConfiguration();
  };

  const showDelta = (prev: Score, curr: Score) => setDelta({ prev, curr });

  const describeConfigUpdates = (updates: Record<string, unknown>): string[] => {
    const changes: string[] = [];
    const machineOee = updates.machine_oee as Record<string, number | null> | undefined;
    if (machineOee) {
      for (const [machineId, value] of Object.entries(machineOee)) {
        changes.push(`${machineId}: OEE ${value === null ? "base" : value}`);
      }
    }
    const machineGroups = updates.machine_groups as Record<string, string> | undefined;
    if (machineGroups) {
      for (const [machineId, value] of Object.entries(machineGroups)) {
        changes.push(`${machineId}: grupo ${value}`);
      }
    }
    const machineActive = updates.machine_active as Record<string, boolean> | undefined;
    if (machineActive) {
      for (const [machineId, value] of Object.entries(machineActive)) {
        changes.push(`${machineId}: ${value ? "ativa" : "inativa"}`);
      }
    }
    if (updates.tool_updates) changes.push("Ferramentas alteradas");
    if (updates.shifts) changes.push("Turnos alterados");
    if (updates.setup_crews_by_group) changes.push("Equipas de setup alteradas");
    const addedUnavailability = updates.unavailability_additions as Array<Record<string, unknown>> | undefined;
    if (addedUnavailability) {
      for (const entry of addedUnavailability) {
        const resource = String(entry.resource ?? `${entry.group ?? ""} ${entry.shift ?? ""}`).trim();
        const period = `${String(entry.start_at ?? "-")} -> ${String(entry.end_at ?? "sem previsão")}`;
        const category = String(entry.category ?? "Sem categoria");
        const reason = String(entry.reason ?? "").trim() || "Sem motivo indicado";
        changes.push(`Nova indisponibilidade: ${resource} · ${period} · Categoria: ${category} · Motivo: ${reason}`);
      }
    }
    const removedUnavailability = updates.unavailability_removals as string[] | undefined;
    if (removedUnavailability?.length) {
      changes.push(`${removedUnavailability.length} indisponibilidade(s) a remover`);
    }
    const updatedUnavailability = updates.unavailability_updates as Array<Record<string, unknown>> | undefined;
    if (updatedUnavailability) {
      for (const entry of updatedUnavailability) {
        const resource = String(entry.resource ?? `${entry.group ?? ""} ${entry.shift ?? ""}`).trim();
        const period = `${String(entry.start_at ?? "-")} -> ${String(entry.end_at ?? "sem previsão")}`;
        changes.push(`Indisponibilidade editada: ${resource} · ${period}`);
      }
    }
    return changes.length ? changes : ["Alterações de configuração"];
  };

  const followReplanJob = useCallback(async (
    initialJob: ReplanJob,
    followup: ReplanFollowup,
    generation = ++replanPollGeneration.current,
  ) => {
    let job = initialJob;
    let consecutivePollingFailures = 0;
    const stillFollowing = () => mounted.current && replanPollGeneration.current === generation;
    if (!stillFollowing()) return;
    followedJob.current = { job, followup };

    if (job.status === "queued" || job.status === "running") {
      setPendingReplan((current) => current?.job.id === job.id ? null : current);
      setSaving(true);
      setActiveReplanJobId(job.id);
      const createdAt = Date.parse(job.created_at);
      setReplanStartedAt(Number.isFinite(createdAt) ? createdAt : Date.now());
      setReplanMessage(job.message || "A calcular o plano…");
    }

    while (job.status === "queued" || job.status === "running") {
      if (!stillFollowing()) return;
      setReplanMessage(job.message || "A calcular o plano…");
      await new Promise((resolve) => window.setTimeout(resolve, REPLAN_POLL_INTERVAL_MS));
      if (!stillFollowing()) return;
      try {
        job = (await getReplan(job.id)).job;
        if (!stillFollowing()) return;
        followedJob.current = { job, followup };
        consecutivePollingFailures = 0;
        setReplanConnectionMessage(null);
      } catch (failure) {
        if (!stillFollowing()) return;
        if (failure instanceof ApiError && [403, 404, 410].includes(failure.status)) {
          setActiveReplanJobId(null);
          setSaving(false);
          setReplanConnectionMessage(null);
          setReplanMessage(failureMessage(failure));
          return;
        }
        consecutivePollingFailures += 1;
        const retryDelay = Math.min(
          REPLAN_POLL_INTERVAL_MS * (2 ** (consecutivePollingFailures - 1)),
          REPLAN_MAX_BACKOFF_MS,
        );
        setReplanConnectionMessage(
          consecutivePollingFailures <= 3
            ? `Ligação temporariamente interrompida. Nova tentativa ${consecutivePollingFailures} de 3…`
            : "Ligação temporariamente interrompida. Continuamos a tentar…",
        );
        await new Promise((resolve) => window.setTimeout(resolve, retryDelay));
      }
    }
    if (!stillFollowing()) return;

    setActiveReplanJobId(null);
    setReplanConnectionMessage(null);
    setSaving(false);
    if (job.status !== "ready") setPendingReplan((current) => current?.job.id === job.id ? null : current);
    if (job.status === "cancelled") {
      setReplanMessage("Pedido cancelado. O plano não foi alterado.");
      return;
    }
    if (job.status === "failed") {
      setReplanMessage(`Erro: ${job.error ?? "Replaneamento falhou."}`);
      return;
    }
    if (job.status === "completed") {
      setPendingReplan(null);
      setReplanMessage("Alteração já aplicada. A atualizar o plano.");
      try {
        await loadConfiguration();
        assertRefreshed(await refreshAfterCommit(refreshAll), true);
      } catch (failure) {
        if (stillFollowing()) setReplanMessage(failureMessage(failure));
      }
      return;
    }
    if (job.status !== "ready") {
      setReplanMessage("Erro: o plano proposto não ficou pronto para aplicar.");
      return;
    }
    setPendingReplan({ job, ...followup });
    setReplanMessage(job.result?.gate_report.apply_decision === "blocked"
      ? job.message
      : "Candidato pronto. Revê as alterações antes de aplicar.");
  }, [loadConfiguration, refreshAll]);

  useEffect(() => {
    let disposed = false;
    const generation = replanPollGeneration.current;
    void getReplans(true)
      .then((response) => {
        if (disposed || replanPollGeneration.current !== generation) return;
        const job = response.jobs.find((candidate) => (
          candidate.status === "queued"
          || candidate.status === "running"
          || candidate.status === "ready"
        ));
        if (!job) return;
        void followReplanJob(job, {
          reason: job.reason,
          changes: [`Alteração pendente: ${job.reason}`],
          successMessage: "Alteração guardada e plano atualizado.",
          onSuccess: () => undefined,
        });
      })
      .catch(() => {
        // A configuração continua utilizável; a consulta será repetida no próximo acesso.
      });
    return () => {
      disposed = true;
    };
  }, [followReplanJob]);

  // Generic save wrapper for synchronous plan writes. A candidate that needs
  // explicit approval is shown with its impact; the planner's justification
  // applies exactly that candidate, cancelling applies nothing.
  const withSave = async (
    fn: (approval?: GateApproval) => Promise<{ score?: Score; score_anterior?: Score; score_previous?: Score; [k: string]: unknown }>,
  ) => {
    if (readOnly) return false;
    setSaving(true);
    try {
      const res = await sendWithGateApproval(fn, justificationAsker(prompt));
      if (res === null) {
        setReplanMessage(NOT_APPLIED);
        return false;
      }
      await reload();
      const previous = res.score_anterior ?? res.score_previous;
      if (res.score && previous) {
        showDelta(previous as Score, res.score as Score);
      }
      return true;
    } catch (e) {
      if (isAppliedRefreshError(e)) {
        setReplanMessage(e.message);
        return true;
      }
      alert(failureMessage(e));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const runBackgroundConfigSave = async (
    reason: string,
    configUpdates: Record<string, unknown>,
    successMessage: string,
    onSuccess: () => void,
  ) => {
    if (readOnly || saving || cancelling.current) return;
    const generation = ++replanPollGeneration.current;
    setSaving(true);
    setPendingReplan(null);
    setReplanMessage("A colocar o replaneamento em fila…");
    setReplanConnectionMessage(null);
    setReplanStartedAt(Date.now());
    setReplanElapsedSeconds(0);
    try {
      const started = await startReplan({
        reason,
        config_updates: configUpdates,
        expected_revision: config?.plan_revision,
      });
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      await followReplanJob(started.job, {
        reason,
        changes: describeConfigUpdates(configUpdates),
        successMessage,
        onSuccess,
      }, generation);
    } catch (failure) {
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      setReplanMessage(failureMessage(failure));
      setActiveReplanJobId(null);
      setReplanConnectionMessage(null);
      setSaving(false);
    }
  };

  const cancelTrackedReplan = async (jobId: string, fallback: { job: ReplanJob; followup: ReplanFollowup }) => {
    if (readOnly || cancelling.current) return;
    cancelling.current = true;
    const generation = ++replanPollGeneration.current;
    setSaving(true);
    try {
      const response = await cancelReplan(jobId);
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      setPendingReplan(null);
      await followReplanJob(response.job, fallback.followup, generation);
    } catch (failure) {
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      setReplanMessage(`Erro ao cancelar: ${apiErrorMessage(failure)}`);
      // A lost cancellation response is ambiguous. Recover the authoritative job.
      let job = fallback.job;
      try { job = (await getReplan(jobId)).job; } catch { /* Polling resumes below. */ }
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      await followReplanJob(job, fallback.followup, generation);
      if (mounted.current && generation === replanPollGeneration.current && job.status === "ready") {
        setReplanMessage(`Erro ao cancelar: ${apiErrorMessage(failure)}. Candidato recuperado; podes tentar novamente.`);
      }
    } finally {
      cancelling.current = false;
    }
  };

  const cancelActiveReplan = async () => {
    if (!activeReplanJobId || !followedJob.current) return;
    await cancelTrackedReplan(activeReplanJobId, followedJob.current);
  };

  const cancelPendingReplan = async () => {
    if (!pendingReplan || saving) return;
    await cancelTrackedReplan(pendingReplan.job.id, { job: pendingReplan.job, followup: pendingReplan });
  };

  const applyPendingReplan = async () => {
    if (readOnly || saving || cancelling.current || !pendingReplan || pendingReplanBlocked) return;
    const generation = replanPollGeneration.current;
    const gateReport = pendingReplan.job.result?.gate_report;
    let approval: { reason: string; author: string } | undefined;
    if (gateReport?.requires_approval) {
      const reasons = gateReport.approval_reasons?.length
        ? gateReport.approval_reasons.map((reason) => `• ${approvalReasonLabel(reason)}`).join("\n")
        : "• O plano proposto tem exceções que precisam da aprovação do planeador.";
      const score = pendingReplan.job.result?.score;
      const impact = [
        `Lotes no prazo: ${score?.otd?.toFixed?.(1) ?? score?.otd ?? "-"}%`,
        `Lotes atrasados: ${score?.tardy_count ?? 0}`,
        `Avisos: ${pendingReplan.job.warnings.length}`,
      ].join(" · ");
      const justification = await prompt({
        title: "Aplicar plano com exceções?",
        message: `Motivos para aprovação:\n${reasons}\n\nImpacto previsto:\n${impact}\n\nIndica a justificação para aplicar este plano.`,
        inputLabel: "Justificação obrigatória",
        placeholder: "Explica por que motivo este impacto é aceite…",
        confirmLabel: "Confirmar e aplicar",
        variant: "danger",
      });
      if (justification === null) return;
      approval = { reason: justification, author: "planeador" };
    }
    if (!mounted.current || generation !== replanPollGeneration.current || cancelling.current) return;
    setSaving(true);
    try {
      const applied = await applyReplan(
        pendingReplan.job.id,
        approval,
        pendingReplan.job.base_revision,
      );
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      const job = applied.job;
      setReplanMessage(job.warnings.length ? `Guardado com ${job.warnings.length} aviso(s).` : pendingReplan.successMessage);
      pendingReplan.onSuccess();
      setPendingReplan(null);
      await reload();
    } catch (failure) {
      if (mounted.current && generation === replanPollGeneration.current) setReplanMessage(failureMessage(failure));
    } finally {
      if (mounted.current && generation === replanPollGeneration.current) setSaving(false);
    }
  };

  const saveMachineDraft = async () => {
    if (
      Object.keys(oeeEdits).length === 0
      && Object.keys(machineGroupEdits).length === 0
      && Object.keys(machineActiveEdits).length === 0
    ) return;
    const deactivated = Object.entries(machineActiveEdits)
      .filter(([, active]) => !active)
      .map(([machineId]) => machineId);
    if (deactivated.length > 0) {
      const approved = await confirm({
        title: "Desativar máquina",
        message: `Desativar ${deactivated.join(", ")}? A máquina deixa de receber produção, o histórico é mantido e o plano será recalculado.`,
        confirmLabel: "Desativar e recalcular",
        variant: "danger",
      });
      if (!approved) return;
    }
    await runBackgroundConfigSave(
      "Máquinas, grupos ou OEE alterados",
      {
        machine_oee: oeeEdits,
        machine_groups: machineGroupEdits,
        machine_active: machineActiveEdits,
      },
      "Máquinas guardadas e plano atualizado.",
      () => {
        setOeeEdits((current) => remainingDraft(current, oeeEdits));
        setMachineGroupEdits((current) => remainingDraft(current, machineGroupEdits));
        setMachineActiveEdits((current) => remainingDraft(current, machineActiveEdits));
      },
    );
  };

  const saveToolDraft = async () => {
    if (Object.keys(toolEdits).length === 0) return;
    await runBackgroundConfigSave(
      "Ferramentas alteradas",
      { tool_updates: toolEdits },
      "Ferramentas guardadas e plano atualizado.",
      () => setToolEdits((current) => remainingToolDraft(current, toolEdits)),
    );
  };

  if (error) {
    return (
      <Card
        style={{
          display: "grid",
          justifyItems: "start",
          gap: 10,
          padding: 20,
          borderColor: `${T.red}55`,
        }}
      >
        <div role="alert" style={{ color: T.primary, fontSize: 14, fontWeight: 700 }}>
          Não foi possível abrir a Configuração
        </div>
        <div style={{ color: T.secondary, fontSize: 12 }}>
          {error}
        </div>
        <button
          type="button"
          onClick={() => {
            void loadConfiguration().catch((failure) => {
              setError(apiErrorMessage(failure));
            });
          }}
          style={{ ...btnStyle, color: T.primary }}
        >
          Tentar novamente
        </button>
      </Card>
    );
  }
  if (!config) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const machineIds = Object.keys(config.machines);
  const skuIds = Array.from(new Set((ops ?? []).map((op) => op.sku))).sort();
  const toolIds = Array.from(new Set([
    ...Object.keys(config.tools),
    ...(catalog?.tools ?? []).map((tool) => tool.id),
    ...(ops ?? []).map((op) => op.tool),
  ])).sort();
  const rowFromForm = (
    id: string,
    form: UnavailabilityForm,
    draftState: UnavailabilityRow["draftState"],
  ): UnavailabilityRow => ({
    ...form,
    id,
    kindLabel: form.kind === "machine" ? "Máquina" : form.kind === "tool" ? "Ferramenta" : "Operadores",
    resourceLabel: form.kind === "operator" ? `${form.operatorKey} · −${form.count}` : form.resource,
    status: draftState === "removed"
      ? { label: "A remover", color: T.red }
      : draftState === "added"
        ? { label: "Nova", color: T.blue }
        : draftState === "edited"
          ? { label: "Editada", color: T.blue }
          : unavailabilityStatus(form),
    draftState,
  });
  const existingUnavailabilityForms: Array<[string, UnavailabilityForm]> = [
    ...config.unavailability.machines.map((entry): [string, UnavailabilityForm] => [entry.id, {
      kind: "machine",
      resource: entry.resource,
      operatorKey: "",
      start_at: datetimeLocalValue(entry.start_at || entry.from),
      end_at: datetimeLocalValue(entry.end_at || entry.to),
      category: entry.category,
      count: 1,
      reason: entry.reason,
    }]),
    ...config.unavailability.tools.map((entry): [string, UnavailabilityForm] => [entry.id, {
      kind: "tool",
      resource: entry.resource,
      operatorKey: "",
      start_at: datetimeLocalValue(entry.start_at || entry.from),
      end_at: datetimeLocalValue(entry.end_at || entry.to),
      category: entry.category,
      count: 1,
      reason: entry.reason,
    }]),
    ...config.unavailability.operators.map((entry): [string, UnavailabilityForm] => [entry.id, {
      kind: "operator",
      resource: "",
      operatorKey: `${entry.group} ${entry.shift}`,
      start_at: datetimeLocalValue(entry.start_at || entry.from),
      end_at: datetimeLocalValue(entry.end_at || entry.to),
      category: entry.category,
      count: entry.count,
      reason: entry.reason,
    }]),
  ];
  const unavailabilityRows: UnavailabilityRow[] = [
    ...existingUnavailabilityForms.map(([id, original]) => rowFromForm(
      id,
      unavailabilityEdits[id] ?? original,
      unavailabilityRemovals.includes(id)
        ? "removed"
        : unavailabilityEdits[id] ? "edited" : "unchanged",
    )),
    ...Object.entries(unavailabilityAdditions).map(([id, form]) => rowFromForm(id, form, "added")),
  ];
  const unavailabilityHasChanges = (
    Object.keys(unavailabilityEdits).length > 0
    || Object.keys(unavailabilityAdditions).length > 0
    || unavailabilityRemovals.length > 0
  );
  const unavailabilityDraftLocked = saving || pendingReplan !== null;
  const machineSource = new Map((catalog?.machines ?? []).map((item) => [item.id, item.source]));
  const toolSource = new Map((catalog?.tools ?? []).map((item) => [item.id, item.source]));
  const catalogTools = new Map((catalog?.tools ?? []).map((item) => [item.id, item]));
  const toolArticles = new Map<string, Array<{ sku: string; designation: string; client: string }>>();
  const observedToolMachines = new Map<string, Set<string>>();
  for (const op of ops ?? []) {
    if (!op.tool) continue;
    const entries = toolArticles.get(op.tool) ?? [];
    if (!entries.some((entry) => entry.sku === op.sku)) {
      entries.push({ sku: op.sku, designation: op.designation, client: op.client });
      toolArticles.set(op.tool, entries);
    }
    if (op.machine) {
      const observed = observedToolMachines.get(op.tool) ?? new Set<string>();
      observed.add(op.machine);
      observedToolMachines.set(op.tool, observed);
    }
  }
  for (const entries of toolArticles.values()) {
    entries.sort((left, right) => compareText(left.sku, right.sku));
  }
  const toolArticleSearchText = (toolId: string) => (toolArticles.get(toolId) ?? [])
    .map((entry) => `${entry.sku} ${entry.designation} ${entry.client}`)
    .join(" ");
  const toolArticleLabel = (toolId: string) => (toolArticles.get(toolId) ?? [])
    .map((entry) => entry.sku)
    .join(", ");
  const sourceLabel = (source: string | undefined) => source === "both"
    ? "ISOP + configuração"
    : source === "isop"
      ? "ISOP"
      : "Configuração";
  const handleMachineSort = (next: typeof machineSort) => {
    setMachineSortDir((current) => machineSort === next ? (current === "asc" ? "desc" : "asc") : "asc");
    setMachineSort(next);
  };
  const handleToolSort = (next: typeof toolSort) => {
    setToolSortDir((current) => toolSort === next ? (current === "asc" ? "desc" : "asc") : "asc");
    setToolSort(next);
  };
  const handleUnavailabilitySort = (next: typeof unavailabilitySort) => {
    setUnavailabilitySortDir((current) => unavailabilitySort === next ? (current === "asc" ? "desc" : "asc") : "asc");
    setUnavailabilitySort(next);
  };
  const resetUnavailabilityEditor = () => {
    setUnavailabilityEditTarget(null);
    setUnavailability((current) => emptyUnavailability(current.kind, current.category));
  };
  const stageUnavailabilityForm = () => {
    const resourceSelected = unavailability.kind === "operator"
      ? unavailability.operatorKey
      : unavailability.resource;
    const endRequired = !(unavailability.kind === "machine" && unavailability.category === "Avaria");
    if (!resourceSelected || !unavailability.start_at || (endRequired && !unavailability.end_at)) return;
    if (unavailability.end_at && unavailability.start_at >= unavailability.end_at) {
      setReplanMessage("Erro: o início da indisponibilidade deve ser anterior ao fim.");
      return;
    }
    if (unavailability.kind === "operator") {
      const available = Number(config.operators[unavailability.operatorKey] ?? 0);
      if (!Number.isInteger(unavailability.count) || unavailability.count < 1 || unavailability.count > available) {
        setReplanMessage(`Erro: as pessoas ausentes devem ser um inteiro entre 1 e ${available}.`);
        return;
      }
    }
    if (unavailabilityEditTarget?.source === "existing") {
      setUnavailabilityEdits((current) => ({
        ...current,
        [unavailabilityEditTarget.id]: { ...unavailability },
      }));
    } else if (unavailabilityEditTarget?.source === "addition") {
      setUnavailabilityAdditions((current) => ({
        ...current,
        [unavailabilityEditTarget.id]: { ...unavailability },
      }));
    } else {
      unavailabilityDraftCounter.current += 1;
      const draftId = `draft-${unavailabilityDraftCounter.current}`;
      setUnavailabilityAdditions((current) => ({ ...current, [draftId]: { ...unavailability } }));
    }
    setReplanMessage("Alterações por guardar. O plano ainda não foi recalculado.");
    resetUnavailabilityEditor();
  };
  const editUnavailabilityRow = (entry: UnavailabilityRow) => {
    if (entry.draftState === "removed" || unavailabilityDraftLocked) return;
    setUnavailability({
      kind: entry.kind,
      resource: entry.resource,
      operatorKey: entry.operatorKey,
      start_at: entry.start_at,
      end_at: entry.end_at,
      category: entry.category,
      count: entry.count,
      reason: entry.reason,
    });
    setUnavailabilityEditTarget({
      source: entry.draftState === "added" ? "addition" : "existing",
      id: entry.id,
    });
  };
  const toggleUnavailabilityRemoval = (entry: UnavailabilityRow) => {
    if (unavailabilityDraftLocked) return;
    if (entry.draftState === "added") {
      setUnavailabilityAdditions((current) => {
        const next = { ...current };
        delete next[entry.id];
        return next;
      });
      if (unavailabilityEditTarget?.id === entry.id) resetUnavailabilityEditor();
      return;
    }
    setUnavailabilityRemovals((current) => current.includes(entry.id)
      ? current.filter((id) => id !== entry.id)
      : [...current, entry.id]);
    if (unavailabilityEditTarget?.id === entry.id) resetUnavailabilityEditor();
    setReplanMessage("Alterações por guardar. O plano ainda não foi recalculado.");
  };
  const cancelUnavailabilityDraft = () => {
    setUnavailabilityEdits({});
    setUnavailabilityAdditions({});
    setUnavailabilityRemovals([]);
    resetUnavailabilityEditor();
    setReplanMessage(null);
  };
  const saveUnavailabilityDraft = () => {
    if (!unavailabilityHasChanges || unavailabilityDraftLocked) return;
    const updates = Object.entries(unavailabilityEdits)
      .filter(([id]) => !unavailabilityRemovals.includes(id))
      .map(([id, form]) => unavailabilityPayload(form, id));
    const additions = Object.values(unavailabilityAdditions).map((form) => unavailabilityPayload(form));
    const configUpdates: Record<string, unknown> = {};
    if (unavailabilityRemovals.length) configUpdates.unavailability_removals = unavailabilityRemovals;
    if (updates.length) configUpdates.unavailability_updates = updates;
    if (additions.length) configUpdates.unavailability_additions = additions;
    void runBackgroundConfigSave(
      "Indisponibilidades alteradas",
      configUpdates,
      "Indisponibilidades guardadas e plano atualizado.",
      () => {
        setUnavailabilityEdits({});
        setUnavailabilityAdditions({});
        setUnavailabilityRemovals([]);
        resetUnavailabilityEditor();
      },
    );
  };
  const handleOpsSort = (next: typeof opsSort) => {
    setOpsSortDir((current) => opsSort === next ? (current === "asc" ? "desc" : "asc") : "asc");
    setOpsSort(next);
  };
  const handleOperatorSort = (next: typeof operatorSort) => {
    setOperatorSortDir((current) => operatorSort === next ? (current === "asc" ? "desc" : "asc") : "asc");
    setOperatorSort(next);
  };
  const visibleOperatorEntries = Object.entries(config.operators).sort(([leftKey, leftCount], [rightKey, rightCount]) => {
    const direction = sortMultiplier(operatorSortDir);
    const result = operatorSort === "count"
      ? compareNumber(leftCount, rightCount)
      : compareText(leftKey, rightKey);
    return result * direction || compareText(leftKey, rightKey);
  });
  const visibleMachines = Object.entries(config.machines)
    .filter(([id, machine]) => {
      const q = machineSearch.trim().toLocaleLowerCase("pt-PT");
      return !q || [id, machine.group, sourceLabel(machineSource.get(id))]
        .some((value) => value.toLocaleLowerCase("pt-PT").includes(q));
    })
    .sort(([leftId, left], [rightId, right]) => {
      const direction = sortMultiplier(machineSortDir);
      let result = 0;
      if (machineSort === "source") result = compareText(sourceLabel(machineSource.get(leftId)), sourceLabel(machineSource.get(rightId)));
      else if (machineSort === "group") result = compareText(left.group, right.group);
      else if (machineSort === "oee") result = compareNumber(left.oee ?? config.oee_default, right.oee ?? config.oee_default);
      else if (machineSort === "active") result = compareNumber(Number(right.active), Number(left.active));
      else result = compareText(leftId, rightId);
      return result * direction || compareText(leftId, rightId);
    });
  const allToolEntries = toolIds.map((id) => {
    const configured = config.tools[id];
    const fromCatalog = catalogTools.get(id);
    const observedMachines = fromCatalog?.observed_machines
      ?? [...(observedToolMachines.get(id) ?? [])].sort(compareText);
    const configuredPrimary = String(configured?.primary ?? "").trim();
    const primary = String(fromCatalog?.primary ?? "").trim()
      || configuredPrimary
      || (observedMachines.length === 1 ? observedMachines[0] : "");
    const primarySource = fromCatalog?.primary_source
      ?? (configuredPrimary
        ? "config"
        : observedMachines.length === 1
          ? "isop"
          : observedMachines.length > 1
            ? "conflict"
            : "missing");
    return [id, {
      primary,
      primarySource,
      observedMachines,
      alt: fromCatalog ? fromCatalog.alt : (configured?.alt ?? null),
      setup_hours: fromCatalog?.setup_hours ?? configured?.setup_hours ?? 0.5,
    }] as const;
  });
  const visibleTools = allToolEntries
    .filter(([id, tool]) => {
      const q = toolSearch.trim().toLocaleLowerCase("pt-PT");
      return !q || [
        id,
        toolArticleSearchText(id),
        String(tool.primary ?? ""),
        String(tool.alt ?? ""),
        sourceLabel(toolSource.get(id)),
      ].some((value) => value.toLocaleLowerCase("pt-PT").includes(q));
    })
    .sort(([leftId, left], [rightId, right]) => {
      const direction = sortMultiplier(toolSortDir);
      let result = 0;
      if (toolSort === "source") result = compareText(sourceLabel(toolSource.get(leftId)), sourceLabel(toolSource.get(rightId)));
      else if (toolSort === "article") result = compareText(toolArticleLabel(leftId), toolArticleLabel(rightId));
      else if (toolSort === "primary") result = compareText(left.primary, right.primary);
      else if (toolSort === "alt") result = compareText(left.alt, right.alt);
      else if (toolSort === "setup") result = compareNumber(left.setup_hours, right.setup_hours);
      else result = compareText(leftId, rightId);
      return result * direction || compareText(leftId, rightId);
    });
  const visibleUnavailability = unavailabilityRows
    .filter((entry) => {
      const q = unavailabilitySearch.trim().toLocaleLowerCase("pt-PT");
      return !q || [
        entry.kindLabel,
        entry.resourceLabel,
        entry.category,
        entry.reason ?? "",
        entry.start_at,
        entry.end_at,
      ].some((value) => String(value).toLocaleLowerCase("pt-PT").includes(q));
    })
    .sort((left, right) => {
      const direction = sortMultiplier(unavailabilitySortDir);
      let result = 0;
      if (unavailabilitySort === "kind") result = compareText(left.kindLabel, right.kindLabel);
      else if (unavailabilitySort === "resource") result = compareText(left.resourceLabel, right.resourceLabel);
      else if (unavailabilitySort === "category") result = compareText(left.category, right.category);
      else if (unavailabilitySort === "reason") result = compareText(left.reason, right.reason);
      else result = compareText(left.start_at, right.start_at);
      return result * direction || compareText(left.resourceLabel, right.resourceLabel);
    });
  const activeGroup = CONFIG_GROUPS.find((item) => item.id === group) ?? CONFIG_GROUPS[0];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card style={{ padding: "12px 16px" }}>
        <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ minWidth: 180 }}>
            <div style={{ color: T.primary, fontSize: 14, fontWeight: 700 }}>{config.name}</div>
            <div style={{ color: T.tertiary, fontSize: 11, marginTop: 2 }}>{config.site} · {config.timezone}</div>
          </div>
          <KV label="Capacidade diária" value={`${config.day_capacity_min} min`} />
          <KV label="OEE base" value={config.oee_default} />
          <details style={{ marginLeft: "auto" }}>
            <summary style={{ cursor: "pointer", color: T.secondary, fontSize: 11 }}>Ver turnos</summary>
            <div style={{ marginTop: 8, display: "grid", gap: 4 }}>
              {config.shifts.map((shift) => (
                <span key={shift.id} style={{ color: T.secondary, fontSize: 11, fontFamily: T.mono }}>
                  {shift.label}: {shift.start_min}–{shift.end_min} ({shift.duration_min} min)
                </span>
              ))}
            </div>
          </details>
        </div>
      </Card>

      {catalogWarning && (
        <div
          role="status"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            padding: "10px 14px",
            border: `1px solid ${T.orange}55`,
            borderRadius: 9,
            background: `${T.orange}0A`,
            color: T.secondary,
            fontSize: 12,
          }}
        >
          <span>{catalogWarning}</span>
          <button
            type="button"
            onClick={() => {
              void loadConfiguration().catch((failure) => {
                setError(apiErrorMessage(failure));
              });
            }}
            style={{ ...btnStyle, flexShrink: 0, color: T.primary }}
          >
            Tentar novamente
          </button>
        </div>
      )}

      {/* Primary configuration groups */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", borderBottom: `1px solid ${T.border}`, paddingBottom: 8 }}>
        {CONFIG_GROUPS.map((item) => (
          <button
            key={item.id}
            onClick={() => {
              setGroup(item.id);
              setSection(item.sections[0].id);
            }}
            style={{
              background: group === item.id ? T.primary : "transparent",
              border: `1px solid ${group === item.id ? T.primary : T.border}`,
              color: group === item.id ? T.card : T.secondary,
              borderRadius: 8, padding: "5px 12px", cursor: "pointer",
              fontSize: 12, fontWeight: group === item.id ? 600 : 400, fontFamily: "inherit",
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Sections inside the active group */}
      <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap" }}>
        {activeGroup.sections.map((item) => (
          <button
            key={item.id}
            onClick={() => setSection(item.id)}
            style={{
              background: section === item.id ? T.elevated : "transparent",
              border: `1px solid ${section === item.id ? T.borderHover : T.border}`,
              color: section === item.id ? T.primary : T.secondary,
              borderRadius: 8, padding: "5px 12px", cursor: "pointer",
              fontSize: 12, fontWeight: section === item.id ? 600 : 400, fontFamily: "inherit",
            }}
          >
            {item.label}
          </button>
        ))}
        {group === "engine" && (
          <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
            <button onClick={() => setPage("rules")} style={btnStyle}>Ver regras</button>
            <button onClick={() => setPage("journal")} style={btnStyle}>Diagnóstico</button>
          </div>
        )}
      </div>

      <HelpPanel>
        {GROUP_HELP[group]}
        {group === "articles" && catalog
          ? ` ${catalog.source_policy.active} ${catalog.source_policy.persistent}`
          : ""}
      </HelpPanel>

      {/* Score delta banner */}
      {delta && <ScoreDelta prev={delta.prev} curr={delta.curr} onClear={() => setDelta(null)} />}

      {(replanMessage || activeReplanJobId || pendingReplan) && (
        <Card style={{ borderColor: pendingReplanBlocked ? T.red : pendingReplan ? T.blue : T.border, background: "#FFFFFF" }}>
          <div style={{ display: "grid", gap: 10 }}>
            {replanMessage && (
              <div
                role={activeReplanJobId ? "status" : undefined}
                aria-live={activeReplanJobId ? "polite" : undefined}
                aria-atomic={activeReplanJobId ? "true" : undefined}
                style={{ display: "flex", alignItems: "center", gap: 10, color: pendingReplanBlocked || replanMessage.startsWith("Erro") ? T.red : T.secondary, fontSize: 12 }}
              >
                {activeReplanJobId && (
                  <span style={{
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    border: `2px solid ${T.border}`,
                    borderTopColor: T.blue,
                    animation: "config-replan-spin 0.8s linear infinite",
                  }} />
                )}
                <span>
                  {activeReplanJobId ? `Fase atual: ${replanMessage}` : replanMessage}
                  {activeReplanJobId && (
                    <span style={{ display: "block", marginTop: 2, color: T.tertiary }}>
                      Tempo decorrido: {formatElapsedTime(replanElapsedSeconds)}
                      {replanConnectionMessage ? ` · ${replanConnectionMessage}` : " · Esta fase pode demorar vários minutos."}
                    </span>
                  )}
                </span>
                {activeReplanJobId && (
                  <button
                    type="button"
                    disabled={readOnly || cancelling.current}
                    onClick={() => void cancelActiveReplan()}
                    style={{ ...btnStyle, color: T.red, marginLeft: "auto" }}
                  >
                    Cancelar pedido
                  </button>
                )}
              </div>
            )}
            {pendingReplan && (
              <div style={{ display: "grid", gap: 10 }}>
                <div>
                  <div style={{ color: T.primary, fontWeight: 800, fontSize: 14 }}>
                    {pendingReplanBlocked ? "Resultado do cenário calculado" : "Alterações prontas para aplicar"}
                  </div>
                  <div style={{ color: T.secondary, fontSize: 12, marginTop: 4 }}>
                    {pendingReplanBlocked
                      ? "O resultado está disponível para análise. A configuração e o plano não foram alterados porque o resultado não é aplicável ao plano ativo."
                      : "A configuração e o plano ainda não foram alterados. Aplica para guardar definitivamente."}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 20, flexWrap: "wrap", color: T.secondary, fontSize: 12 }}>
                  <span>Lotes no prazo: {pendingReplan.job.result?.score.otd?.toFixed?.(1) ?? pendingReplan.job.result?.score.otd}%</span>
                  <span>Lotes atrasados: {pendingReplan.job.result?.score.tardy_count ?? 0}</span>
                  <span>
                    Estado: {gateStatusLabel(pendingReplan.job.result?.gate_report.status)}
                    {pendingReplan.job.result?.gate_report.improvement?.status === "partial"
                      ? " · a melhoria automática parou antes de rever todas as hipóteses" : ""}
                  </span>
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, color: T.primary, fontSize: 12 }}>
                  {pendingReplan.changes.map((change) => <li key={change}>{change}</li>)}
                </ul>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button type="button" disabled={readOnly || saving || pendingReplanBlocked} onClick={() => void applyPendingReplan()} style={{ ...btnStyle, color: pendingReplanBlocked ? T.tertiary : T.blue, cursor: pendingReplanBlocked ? "not-allowed" : "pointer" }}>
                    {saving ? "A aplicar…" : pendingReplanBlocked ? "Não aplicável ao plano" : "Aplicar e guardar"}
                  </button>
                  <button type="button" disabled={readOnly || saving} onClick={() => void cancelPendingReplan()} style={{ ...btnStyle, color: T.red }}>
                    Cancelar mudança
                  </button>
                </div>
              </div>
            )}
          </div>
        </Card>
      )}
      {activeReplanJobId && (
        <style>{"@keyframes config-replan-spin { to { transform: rotate(360deg); } }"}</style>
      )}

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

      {/* ── TURNOS (staged edit + background replan) ───────────── */}
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
              {(shiftEdits ?? config.shifts).map((s, index) => (
                <tr key={s.id}>
                  <td style={tdStyle}>{s.id}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>
                    <input
                      value={s.label}
                      onChange={(event) => {
                        const next = [...(shiftEdits ?? config.shifts)].map((item) => ({ ...item }));
                        next[index].label = event.target.value;
                        setShiftEdits(next);
                      }}
                      style={{ ...inputStyle, width: 130 }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <input
                      type="time"
                      value={`${String(Math.floor((s.start_min % 1440) / 60)).padStart(2, "0")}:${String(s.start_min % 60).padStart(2, "0")}`}
                      onChange={(event) => {
                        const [hours, minutes] = event.target.value.split(":").map(Number);
                        const next = [...(shiftEdits ?? config.shifts)].map((item) => ({ ...item }));
                        next[index].start_min = hours * 60 + minutes;
                        setShiftEdits(next);
                      }}
                      style={{ ...inputStyle, width: 105 }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <input
                      type="time"
                      value={`${String(Math.floor((s.end_min % 1440) / 60)).padStart(2, "0")}:${String(s.end_min % 60).padStart(2, "0")}`}
                      onChange={(event) => {
                        const [hours, minutes] = event.target.value.split(":").map(Number);
                        const next = [...(shiftEdits ?? config.shifts)].map((item) => ({ ...item }));
                        let value = hours * 60 + minutes;
                        if (value === 0) value = 1440;
                        next[index].end_min = value;
                        setShiftEdits(next);
                      }}
                      style={{ ...inputStyle, width: 105 }}
                    />
                  </td>
                  <td style={tdStyle}>{Math.max(0, s.end_min - s.start_min)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: "12px 16px", display: "flex", alignItems: "center", gap: 8 }}>
            <button
              disabled={saving || shiftEdits === null}
              onClick={() => {
                if (!shiftEdits) return;
                void runBackgroundConfigSave(
                  "Turnos alterados",
                  { shifts: shiftEdits },
                  "Turnos guardados e plano atualizado.",
                  () => setShiftEdits((current) => current === shiftEdits ? null : current),
                );
              }}
              style={saveBtnStyle(shiftEdits !== null, saving)}
            >
              Recalcular e rever
            </button>
            <button disabled={saving || shiftEdits === null} onClick={() => setShiftEdits(null)} style={btnStyle}>
              Cancelar
            </button>
            <span style={{ color: T.tertiary, fontSize: 11 }}>
              O plano só muda depois de Aplicar e guardar.
            </span>
          </div>
        </Card>
      )}

      {/* ── MAQUINAS (toggle activa) ───────────────────────────── */}
      {section === "maquinas" && (
        <div style={{ display: "grid", gap: 10 }}>
        <Card>
          <Label>Adicionar máquina</Label>
          <div style={{ color: T.secondary, fontSize: 11, margin: "4px 0 10px" }}>
            Máquinas existentes não são apagadas: podem ser desativadas para manter o histórico.
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
            <label style={{ display: "grid", gap: 4 }}>
              <span style={{ color: T.tertiary, fontSize: 10 }}>Identificador</span>
              <input
                value={newMachine.id}
                onChange={(event) => setNewMachine({ ...newMachine, id: event.target.value.toUpperCase() })}
                placeholder="Ex.: PRM044"
                style={{ ...inputStyle, width: 130, textAlign: "left" }}
              />
            </label>
            <label style={{ display: "grid", gap: 4 }}>
              <span style={{ color: T.tertiary, fontSize: 10 }}>Grupo</span>
              <select
                value={newMachine.group}
                onChange={(event) => setNewMachine({ ...newMachine, group: event.target.value })}
                style={{ ...inputStyle, width: 130, textAlign: "left" }}
              >
                <option value="Grandes">Grandes</option>
                <option value="Medias">Médias</option>
              </select>
            </label>
            <button
              disabled={saving || !newMachine.id.trim()}
              onClick={async () => {
                const machineId = newMachine.id.trim().toUpperCase();
                const approved = await confirm({
                  title: "Adicionar máquina",
                  message: `Adicionar a máquina ${machineId} e rever o plano?`,
                  confirmLabel: "Adicionar e recalcular",
                });
                if (!approved) return;
                void runBackgroundConfigSave(
                  `Adicionar máquina ${machineId}`,
                  {
                    machine_additions: [{
                      id: machineId,
                      group: newMachine.group,
                      active: true,
                    }],
                  },
                  `Máquina ${machineId} adicionada e plano atualizado.`,
                  () => setNewMachine((current) => current === newMachine ? { id: "", group: newMachine.group } : current),
                );
              }}
              style={{ ...btnStyle, color: T.blue, opacity: saving || !newMachine.id.trim() ? 0.5 : 1 }}
            >
              Adicionar e recalcular
            </button>
          </div>
        </Card>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="search"
            value={machineSearch}
            onChange={(event) => setMachineSearch(event.target.value)}
            placeholder="Pesquisar máquinas…"
            style={{ ...inputStyle, width: 220, textAlign: "left" }}
          />
          <select
            value={machineSort}
            onChange={(event) => setMachineSort(event.target.value as typeof machineSort)}
            aria-label="Ordenar máquinas"
            style={{ ...inputStyle, width: 150, textAlign: "left" }}
          >
            <option value="id">Ordenar: máquina</option>
            <option value="source">Ordenar: origem</option>
            <option value="group">Ordenar: grupo</option>
            <option value="oee">Ordenar: OEE</option>
            <option value="active">Ordenar: estado</option>
          </select>
          <button
            disabled={saving || (
              Object.keys(oeeEdits).length === 0
              && Object.keys(machineGroupEdits).length === 0
              && Object.keys(machineActiveEdits).length === 0
            )}
            onClick={() => void saveMachineDraft()}
            style={{ ...btnStyle, color: T.blue }}
          >
            {saving ? "A recalcular…" : "Guardar alterações"}
          </button>
          <button
            disabled={saving || (
              Object.keys(oeeEdits).length === 0
              && Object.keys(machineGroupEdits).length === 0
              && Object.keys(machineActiveEdits).length === 0
            )}
            onClick={() => {
              setOeeEdits({});
              setMachineGroupEdits({});
              setMachineActiveEdits({});
            }}
            style={btnStyle}
          >
            Cancelar
          </button>
          <span style={{ marginLeft: "auto", color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
            {visibleMachines.length} de {Object.keys(config.machines).length}
          </span>
          <span style={{ color: T.tertiary, fontSize: 10 }}>
            OEE entre 0,10 e 1,00 · vazio usa o valor base {config.oee_default.toLocaleString("pt-PT")}
          </span>
        </div>
        <Card style={{ padding: 0, overflow: "auto", maxHeight: 520 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <SortableTh label="Máquina" sortKey="id" activeKey={machineSort} direction={machineSortDir} onSort={handleMachineSort} />
                <SortableTh label="Origem" sortKey="source" activeKey={machineSort} direction={machineSortDir} onSort={handleMachineSort} />
                <SortableTh label="Grupo" sortKey="group" activeKey={machineSort} direction={machineSortDir} onSort={handleMachineSort} />
                <SortableTh label="OEE próprio" sortKey="oee" activeKey={machineSort} direction={machineSortDir} onSort={handleMachineSort} title="Eficiência própria da máquina. Vazio usa o OEE base." style={{ width: 130 }} />
                <SortableTh label="Ativa" sortKey="active" activeKey={machineSort} direction={machineSortDir} onSort={handleMachineSort} style={{ width: 80 }} />
              </tr>
            </thead>
            <tbody>
              {visibleMachines.map(([id, m]) => {
                const effectiveActive = machineActiveEdits[id] ?? m.active;
                return (
                <tr key={id}>
                  <td style={tdStyle}>{id}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans, color: T.secondary }}>{sourceLabel(machineSource.get(id))}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>
                    <select
                      value={machineGroupEdits[id] ?? m.group}
                      onChange={(event) => {
                        const value = event.target.value;
                        setMachineGroupEdits((current) => {
                          const next = { ...current };
                          if (value === m.group) delete next[id];
                          else next[id] = value;
                          return next;
                        });
                      }}
                      style={{ ...inputStyle, width: 110 }}
                    >
                      <option value="Grandes">Grandes</option>
                      <option value="Medias">Médias</option>
                    </select>
                  </td>
                  <td style={tdStyle}>
                    <input
                      type="number"
                      min="0.1"
                      max="1"
                      step="0.01"
                      disabled={saving}
                      value={id in oeeEdits ? oeeEdits[id] ?? "" : m.oee ?? ""}
                      placeholder={String(config.oee_default)}
                      aria-label={`OEE da máquina ${id}`}
                      onChange={(e) => {
                        const raw = e.target.value.trim();
                        const value = raw === "" ? null : Number(raw);
                        setOeeEdits((current) => {
                          const next = { ...current };
                          if (value === m.oee) delete next[id];
                          else next[id] = value;
                          return next;
                        });
                      }}
                      style={{ ...inputStyle, width: 78 }}
                    />
                    <span style={{ marginLeft: 6, color: T.tertiary, fontSize: 10 }}>
                      {m.oee === null ? "base" : ""}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <button
                      disabled={saving}
                      aria-pressed={effectiveActive}
                      onClick={() => {
                        const next = !effectiveActive;
                        setMachineActiveEdits((current) => {
                          const updated = { ...current };
                          if (next === m.active) delete updated[id];
                          else updated[id] = next;
                          return updated;
                        });
                      }}
                      style={{
                        background: effectiveActive ? T.green + "22" : T.red + "22",
                        border: `1px solid ${effectiveActive ? T.green : T.red}`,
                        borderRadius: 6, padding: "2px 10px", cursor: "pointer",
                        fontSize: 11, color: effectiveActive ? T.green : T.red, fontFamily: "inherit",
                        opacity: saving ? 0.5 : 1,
                      }}
                    >
                      {effectiveActive ? "Sim" : "Não"}
                    </button>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          {visibleMachines.length === 0 && (
            <div style={{ padding: 18, color: T.secondary, fontSize: 12 }}>Sem máquinas correspondentes à pesquisa.</div>
          )}
        </Card>
        </div>
      )}

      {/* ── FERRAMENTAS (inline edit setup + alt) ──────────────── */}
      {section === "ferramentas" && (
        <div style={{ display: "grid", gap: 10 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="search"
              value={toolSearch}
              onChange={(event) => setToolSearch(event.target.value)}
              placeholder="Pesquisar ferramenta, artigo ou cliente…"
              style={{ ...inputStyle, width: 300, textAlign: "left" }}
            />
            <select
              value={toolSort}
              onChange={(event) => setToolSort(event.target.value as typeof toolSort)}
              aria-label="Ordenar ferramentas"
              style={{ ...inputStyle, width: 175, textAlign: "left" }}
            >
              <option value="id">Ordenar: ferramenta</option>
              <option value="article">Ordenar: artigo</option>
              <option value="source">Ordenar: origem</option>
              <option value="primary">Ordenar: máquina principal</option>
              <option value="alt">Ordenar: alternativa</option>
              <option value="setup">Ordenar: setup</option>
            </select>
            <button
              disabled={saving || Object.keys(toolEdits).length === 0}
              onClick={() => void saveToolDraft()}
              style={saveBtnStyle(Object.keys(toolEdits).length > 0, saving)}
            >
              {saving ? "A recalcular…" : "Guardar alterações"}
            </button>
            <button
              disabled={saving || Object.keys(toolEdits).length === 0}
              onClick={() => setToolEdits({})}
              style={btnStyle}
            >
              Cancelar
            </button>
            <span style={{ color: T.tertiary, fontSize: 11 }}>O plano só muda depois de Guardar.</span>
            <span style={{ marginLeft: "auto", color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
              {visibleTools.length} de {allToolEntries.length}
            </span>
          </div>
        <Card style={{ padding: 0, overflow: "auto", maxHeight: 500 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 1100 }}>
            <thead>
              <tr>
                <SortableTh label="Ferramenta" sortKey="id" activeKey={toolSort} direction={toolSortDir} onSort={handleToolSort} />
                <SortableTh label="Artigos" sortKey="article" activeKey={toolSort} direction={toolSortDir} onSort={handleToolSort} />
                <SortableTh label="Origem" sortKey="source" activeKey={toolSort} direction={toolSortDir} onSort={handleToolSort} />
                <SortableTh label="Máquina principal" sortKey="primary" activeKey={toolSort} direction={toolSortDir} onSort={handleToolSort} />
                <SortableTh label="Alternativa" sortKey="alt" activeKey={toolSort} direction={toolSortDir} onSort={handleToolSort} style={{ width: 140 }} />
                <SortableTh label="Setup (h)" sortKey="setup" activeKey={toolSort} direction={toolSortDir} onSort={handleToolSort} style={{ width: 100 }} />
              </tr>
            </thead>
            <tbody>
              {visibleTools.map(([id, t]) => {
                const editState = toolEdits[id];
                return (
                  <tr key={id}>
                    <td style={tdStyle}>{id}</td>
                    <td style={{ ...tdStyle, maxWidth: 360 }}>
                      {(toolArticles.get(id) ?? []).length === 0 ? (
                        <span style={{ color: T.tertiary, fontFamily: T.sans }}>Sem artigos no ISOP atual</span>
                      ) : (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                          {(toolArticles.get(id) ?? []).slice(0, 8).map((article) => (
                            <span
                              key={article.sku}
                              title={`${article.sku} · ${article.designation}${article.client ? ` · ${article.client}` : ""}`}
                              style={{
                                display: "inline-flex",
                                maxWidth: 130,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                                whiteSpace: "nowrap",
                                border: `1px solid ${T.border}`,
                                borderRadius: 6,
                                color: T.primary,
                                background: T.elevated,
                                fontFamily: T.mono,
                                fontSize: 10,
                                padding: "2px 6px",
                              }}
                            >
                              {article.sku}
                            </span>
                          ))}
                          {(toolArticles.get(id) ?? []).length > 8 && (
                            <span style={{ color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
                              +{(toolArticles.get(id) ?? []).length - 8}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: T.sans, color: T.secondary }}>{sourceLabel(toolSource.get(id))}</td>
                    <td style={tdStyle}>
                      {t.primary ? (
                        <div style={{ display: "grid", gap: 2 }}>
                          <span>{t.primary}</span>
                          <span style={{ color: T.tertiary, fontFamily: T.sans, fontSize: 9 }}>
                            {t.primarySource === "config" ? "Configuração" : "ISOP"}
                          </span>
                        </div>
                      ) : t.primarySource === "conflict" ? (
                        <span
                          role="alert"
                          title="A ferramenta aparece associada a mais do que uma máquina no ISOP."
                          style={{ color: T.red, fontFamily: T.sans }}
                        >
                          Conflito: {t.observedMachines.join(", ")}
                        </span>
                      ) : (
                        <span style={{ color: T.tertiary, fontFamily: T.sans }}>Sem dados no ISOP atual</span>
                      )}
                    </td>
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
                        value={editState?.setup_hours ?? t.setup_hours}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          if (!Number.isFinite(value)) return;
                          if (value === t.setup_hours) {
                            const next = { ...toolEdits };
                            if (next[id]) {
                              delete next[id].setup_hours;
                              if (!Object.keys(next[id]).length) delete next[id];
                            }
                            setToolEdits(next);
                          } else {
                            setToolEdits({
                              ...toolEdits,
                              [id]: { ...toolEdits[id], setup_hours: value },
                            });
                          }
                        }}
                        style={{ ...inputStyle, width: 70, borderColor: editState?.setup_hours !== undefined ? T.blue : T.border }}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {visibleTools.length === 0 && (
            <div style={{ padding: 18, color: T.secondary, fontSize: 12 }}>Sem ferramentas correspondentes à pesquisa.</div>
          )}
        </Card>
        </div>
      )}

      {/* ── EXCEÇÕES DE SETUP (SKU × máquina) ───────────────── */}
      {section === "setup_overrides" && (
        <div style={{ display: "grid", gap: 12 }}>
          <Card>
            <div style={{ marginBottom: 12 }}>
              <Label>Nova exceção</Label>
              <div style={{ color: T.secondary, fontSize: 11, marginTop: 4 }}>
                Substitui o tempo de setup apenas para a combinação de artigo e máquina escolhida.
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Artigo</span>
                <select
                  value={setupOverride.sku}
                  onChange={(e) => setSetupOverride({ ...setupOverride, sku: e.target.value })}
                  style={{ ...inputStyle, width: 190, textAlign: "left" }}
                >
                  <option value="">Escolher referência…</option>
                  {skuIds.map((sku) => <option key={sku} value={sku}>{sku}</option>)}
                </select>
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Máquina</span>
                <select
                  value={setupOverride.machine}
                  onChange={(e) => setSetupOverride({ ...setupOverride, machine: e.target.value })}
                  style={{ ...inputStyle, width: 130, textAlign: "left" }}
                >
                  <option value="">Escolher…</option>
                  {machineIds.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Setup (horas)</span>
                <input
                  type="number"
                  min="0.01"
                  max="8"
                  step="0.25"
                  value={setupOverride.hours}
                  onChange={(e) => setSetupOverride({ ...setupOverride, hours: Number(e.target.value) })}
                  style={{ ...inputStyle, width: 100 }}
                />
              </label>
              <button
                disabled={saving || !setupOverride.sku || !setupOverride.machine || setupOverride.hours <= 0 || setupOverride.hours > 8}
                onClick={async () => {
                  const next = config.setup_overrides.filter((item) => (
                    item.sku !== setupOverride.sku || item.machine !== setupOverride.machine
                  ));
                  next.push(setupOverride);
                  if (await withSave((approval) => replaceSetupOverrides(next, approval))) {
                    setSetupOverride({ sku: "", machine: "", hours: 0.5 });
                  }
                }}
                style={{
                  ...btnStyle,
                  color: T.blue,
                  borderColor: T.blue + "50",
                  opacity: saving || !setupOverride.sku || !setupOverride.machine ? 0.5 : 1,
                }}
              >
                Guardar exceção
              </button>
            </div>
          </Card>

          <Card style={{ padding: 0, overflow: "hidden" }}>
            {config.setup_overrides.length === 0 ? (
              <div style={{ color: T.secondary, fontSize: 13, padding: 16 }}>
                Sem exceções: aplica-se o setup da ferramenta.
              </div>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={thStyle}>Artigo</th>
                    <th style={thStyle}>Máquina</th>
                    <th style={thStyle}>Setup</th>
                    <th style={{ ...thStyle, width: 60 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {config.setup_overrides.map((item) => (
                    <tr key={`${item.sku}-${item.machine}`}>
                      <td style={tdStyle}>{item.sku}</td>
                      <td style={tdStyle}>{item.machine}</td>
                      <td style={tdStyle}>{item.hours} h</td>
                      <td style={tdStyle}>
                        <button
                          disabled={saving}
                          aria-label={`Remover exceção ${item.sku} ${item.machine}`}
                          onClick={() => withSave((approval) => replaceSetupOverrides(
                            config.setup_overrides.filter((candidate) => candidate !== item),
                            approval,
                          ))}
                          style={{ background: "none", border: "none", color: T.red, cursor: "pointer" }}
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
        </div>
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
                    <th style={thStyle}>Referência A</th>
                    <th style={thStyle}>Referência B</th>
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
                          onClick={async () => {
                            const approved = await confirm({
                              title: "Remover gémea",
                              message: `Remover a configuração gémea da ferramenta ${tw.tool_id}?`,
                              confirmLabel: "Remover",
                              variant: "danger",
                            });
                            if (!approved) return;
                            void withSave((approval) => removeTwin(tw.tool_id, approval));
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
                    <Label style={{ marginBottom: 4 }}>{field === "tool_id" ? "Ferramenta" : field === "sku_a" ? "Referência A" : "Referência B"}</Label>
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
                    if (await withSave((approval) => addTwin(twinForm.tool_id, twinForm.sku_a, twinForm.sku_b, approval))) {
                      setTwinForm({ tool_id: "", sku_a: "", sku_b: "" });
                      setTwinModal(false);
                    }
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
                <SortableTh label="Grupo/Turno" sortKey="key" activeKey={operatorSort} direction={operatorSortDir} onSort={handleOperatorSort} />
                <SortableTh label="Operadores" sortKey="count" activeKey={operatorSort} direction={operatorSortDir} onSort={handleOperatorSort} style={{ width: 100 }} />
              </tr>
            </thead>
            <tbody>
              {visibleOperatorEntries.map(([key, count]) => (
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
                  if (await withSave((approval) => updateOperators(opEdits, approval))) {
                    setOpEdits({});
                  }
                }}
                style={saveBtnStyle(true, saving)}
              >
                {saving ? "A guardar..." : "Guardar"}
              </button>
              <button onClick={() => setOpEdits({})} style={btnStyle}>Cancelar</button>
            </div>
          )}
          <div style={{ padding: "14px 16px", borderTop: `1px solid ${T.border}` }}>
            <Label>Equipas de setup por grupo</Label>
            <div style={{ color: T.tertiary, fontSize: 11, margin: "4px 0 10px" }}>
              Grandes e Médias são recursos independentes e podem preparar ao mesmo tempo.
            </div>
            <div style={{ display: "flex", gap: 14, alignItems: "end", flexWrap: "wrap" }}>
              {Object.entries(config.setup_crews_by_group).map(([setupGroup, count]) => (
                <label key={setupGroup} style={{ display: "grid", gap: 4, color: T.secondary, fontSize: 11 }}>
                  {setupGroup}
                  <input
                    type="number"
                    min="1"
                    value={crewEdits[setupGroup] ?? count}
                    onChange={(event) => {
                      const value = Math.max(1, Number(event.target.value));
                      setCrewEdits((current) => {
                        const next = { ...current };
                        if (value === count) delete next[setupGroup];
                        else next[setupGroup] = value;
                        return next;
                      });
                    }}
                    style={{ ...inputStyle, width: 70 }}
                  />
                </label>
              ))}
              <button
                disabled={saving || Object.keys(crewEdits).length === 0}
                onClick={() => {
                  const effective = {
                    ...config.setup_crews_by_group,
                    ...crewEdits,
                  };
                  void runBackgroundConfigSave(
                    "Equipas de setup alteradas",
                    { setup_crews_by_group: effective },
                    "Equipas de setup guardadas e plano atualizado.",
                    () => setCrewEdits((current) => remainingDraft(current, crewEdits)),
                  );
                }}
                style={saveBtnStyle(Object.keys(crewEdits).length > 0, saving)}
              >
                Guardar equipas
              </button>
              <button disabled={saving || Object.keys(crewEdits).length === 0} onClick={() => setCrewEdits({})} style={btnStyle}>
                Cancelar
              </button>
            </div>
          </div>
        </Card>
      )}

      {/* ── FERIADOS, FÉRIAS E FINS DE SEMANA EXTRA ──────────── */}
      {section === "feriados" && (
        <div style={{ display: "grid", gap: 12 }}>
          <Card>
            <Label>Feriados e férias</Label>
            <div style={{ color: T.secondary, fontSize: 11, margin: "4px 0 12px" }}>
              Estes dias ficam sem produção. Um intervalo permite registar férias de uma só vez.
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Um dia</span>
                <input
                  type="date"
                  value={newHoliday}
                  onChange={(e) => setNewHoliday(e.target.value)}
                  style={{ ...inputStyle, width: 160, textAlign: "left" }}
                />
              </label>
              <button
                disabled={!newHoliday || saving}
                onClick={async () => {
                  if (await withSave((approval) => addHoliday(newHoliday, approval))) {
                    setNewHoliday("");
                  }
                }}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50", opacity: !newHoliday || saving ? 0.5 : 1 }}
              >
                Adicionar dia
              </button>
              <div aria-hidden="true" style={{ width: 1, height: 32, background: T.border }} />
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>De</span>
                <input
                  type="date"
                  value={holidayRange.from}
                  onChange={(e) => setHolidayRange({ ...holidayRange, from: e.target.value })}
                  style={{ ...inputStyle, width: 150, textAlign: "left" }}
                />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Até</span>
                <input
                  type="date"
                  value={holidayRange.to}
                  onChange={(e) => setHolidayRange({ ...holidayRange, to: e.target.value })}
                  style={{ ...inputStyle, width: 150, textAlign: "left" }}
                />
              </label>
              <button
                disabled={!holidayRange.from || !holidayRange.to || saving}
                onClick={async () => {
                  if (await withSave((approval) => addHolidayRange(holidayRange.from, holidayRange.to, approval))) {
                    setHolidayRange({ from: "", to: "" });
                  }
                }}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}
              >
                Adicionar intervalo
              </button>
              <button
                disabled={!holidayRange.from || !holidayRange.to || saving}
                onClick={async () => {
                  const approved = await confirm({
                    title: "Reabrir intervalo",
                    message: `Reabrir os dias entre ${holidayRange.from} e ${holidayRange.to}?`,
                    confirmLabel: "Reabrir dias",
                    variant: "danger",
                  });
                  if (!approved) return;
                  if (await withSave((approval) => removeHolidayRange(holidayRange.from, holidayRange.to, approval))) {
                    setHolidayRange({ from: "", to: "" });
                  }
                }}
                style={{ ...btnStyle, color: T.red, borderColor: T.red + "50" }}
              >
                Remover intervalo
              </button>
            </div>
            <Divider />
            {config.holidays.length === 0 ? (
              <div style={{ color: T.secondary, fontSize: 13 }}>Sem feriados ou férias configurados.</div>
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
                      aria-label={`Remover dia sem produção ${h}`}
                      onClick={async () => {
                        const approved = await confirm({
                          title: "Remover dia fechado",
                          message: `Remover feriado/férias em ${h}?`,
                          confirmLabel: "Remover",
                          variant: "danger",
                        });
                        if (!approved) return;
                        void withSave((approval) => removeHoliday(h, approval));
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

          <Card>
            <Label>Fim de semana com produção</Label>
            <div style={{ color: T.secondary, fontSize: 11, margin: "4px 0 12px" }}>
              Abre excecionalmente um sábado ou domingo. Um feriado explícito continua a prevalecer.
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                type="date"
                value={extraWorkday}
                onChange={(e) => setExtraWorkday(e.target.value)}
                style={{ ...inputStyle, width: 160, textAlign: "left" }}
              />
              <button
                disabled={!extraWorkday || saving}
                onClick={async () => {
                  if (await withSave((approval) => addExtraWorkday(extraWorkday, approval))) {
                    setExtraWorkday("");
                  }
                }}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}
              >
                Abrir dia
              </button>
              {config.extra_workdays.map((date) => (
                <span key={date} style={{ ...btnStyle, cursor: "default", fontFamily: T.mono }}>
                  {date}
                  <button
                    disabled={saving}
                    aria-label={`Remover dia de trabalho extra ${date}`}
                    onClick={() => withSave((approval) => removeExtraWorkday(date, approval))}
                    style={{ background: "none", border: "none", color: T.red, cursor: "pointer", marginLeft: 8 }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* ── INDISPONIBILIDADES PERSISTENTES ──────────────────── */}
      {section === "indisponibilidades" && (
        <div style={{ display: "grid", gap: 12 }}>
          <Card>
            <Label>{unavailabilityEditTarget ? "Editar indisponibilidade" : "Adicionar indisponibilidade"}</Label>
            <div style={{ color: T.secondary, fontSize: 11, margin: "4px 0 12px" }}>
              Prepara todas as alterações nesta página. O plano só é recalculado depois de Guardar alterações.
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Tipo</span>
                <select
                  value={unavailability.kind}
                  disabled={unavailabilityDraftLocked}
                  onChange={(e) => setUnavailability({ ...unavailability, kind: e.target.value as UnavailabilityKind, resource: "", operatorKey: "" })}
                  style={{ ...inputStyle, width: 130, textAlign: "left" }}
                >
                  <option value="machine">Máquina</option>
                  <option value="tool">Ferramenta</option>
                  <option value="operator">Operadores</option>
                </select>
              </label>
              {unavailability.kind === "operator" ? (
                <>
                  <label style={{ display: "grid", gap: 4 }}>
                    <span style={{ color: T.tertiary, fontSize: 10 }}>Equipa/turno</span>
                    <select
                      value={unavailability.operatorKey}
                      disabled={unavailabilityDraftLocked}
                      onChange={(e) => setUnavailability({ ...unavailability, operatorKey: e.target.value })}
                      style={{ ...inputStyle, width: 170, textAlign: "left" }}
                    >
                      <option value="">Escolher…</option>
                      {Object.keys(config.operators).map((key) => <option key={key} value={key}>{key}</option>)}
                    </select>
                  </label>
                  <label style={{ display: "grid", gap: 4 }}>
                    <span style={{ color: T.tertiary, fontSize: 10 }}>Pessoas ausentes</span>
                    <input
                      type="number"
                      min="1"
                      value={unavailability.count}
                      disabled={unavailabilityDraftLocked}
                      onChange={(e) => setUnavailability({ ...unavailability, count: Number(e.target.value) })}
                      style={{ ...inputStyle, width: 90 }}
                    />
                  </label>
                </>
              ) : (
                <label style={{ display: "grid", gap: 4 }}>
                  <span style={{ color: T.tertiary, fontSize: 10 }}>
                    {unavailability.kind === "machine" ? "Máquina" : "Ferramenta"}
                  </span>
                  <select
                    value={unavailability.resource}
                    disabled={unavailabilityDraftLocked}
                    onChange={(e) => setUnavailability({ ...unavailability, resource: e.target.value })}
                    style={{ ...inputStyle, width: 160, textAlign: "left" }}
                  >
                    <option value="">Escolher…</option>
                    {(unavailability.kind === "machine" ? machineIds : toolIds).map((id) => (
                      <option key={id} value={id}>{id}</option>
                    ))}
                  </select>
                </label>
              )}
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Categoria</span>
                <select
                  value={unavailability.category}
                  disabled={unavailabilityDraftLocked}
                  onChange={(e) => setUnavailability({ ...unavailability, category: e.target.value as UnavailabilityCategory })}
                  style={{ ...inputStyle, width: 125, textAlign: "left" }}
                >
                  <option>Avaria</option>
                  <option>Manutenção</option>
                  <option>Ensaio</option>
                  <option>Outra</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Início exato</span>
                <input
                  type="datetime-local"
                  value={unavailability.start_at}
                  disabled={unavailabilityDraftLocked}
                  onChange={(e) => setUnavailability({ ...unavailability, start_at: e.target.value })}
                  style={{ ...inputStyle, width: 180, textAlign: "left" }}
                />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Fim exato</span>
                <input
                  type="datetime-local"
                  value={unavailability.end_at}
                  disabled={unavailabilityDraftLocked}
                  onChange={(e) => setUnavailability({ ...unavailability, end_at: e.target.value })}
                  style={{ ...inputStyle, width: 180, textAlign: "left" }}
                />
                {unavailability.kind === "machine" && unavailability.category === "Avaria" && (
                  <span style={{ color: T.tertiary, fontSize: 9 }}>Pode ficar vazio se não houver previsão.</span>
                )}
              </label>
              <label style={{ display: "grid", gap: 4, flex: "1 1 180px" }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Motivo (opcional)</span>
                <input
                  type="text"
                  value={unavailability.reason}
                  disabled={unavailabilityDraftLocked}
                  onChange={(e) => setUnavailability({ ...unavailability, reason: e.target.value })}
                  placeholder="Manutenção, férias…"
                  style={{ ...inputStyle, width: "100%", textAlign: "left" }}
                />
              </label>
              <button
                disabled={unavailabilityDraftLocked || !unavailability.start_at || (!(unavailability.kind === "machine" && unavailability.category === "Avaria") && !unavailability.end_at) || !(unavailability.kind === "operator" ? unavailability.operatorKey : unavailability.resource)}
                onClick={stageUnavailabilityForm}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}
              >
                {unavailabilityEditTarget ? "Atualizar rascunho" : "Adicionar ao rascunho"}
              </button>
              {unavailabilityEditTarget && (
                <button disabled={unavailabilityDraftLocked} onClick={resetUnavailabilityEditor} style={btnStyle}>
                  Cancelar edição
                </button>
              )}
            </div>
          </Card>

          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div data-testid="unavailability-toolbar" style={{ padding: "12px 16px", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, borderBottom: `1px solid ${T.border}` }}>
              <Label>Indisponibilidades registadas</Label>
              <input
                type="search"
                value={unavailabilitySearch}
                onChange={(event) => setUnavailabilitySearch(event.target.value)}
                placeholder="Pesquisar recurso, categoria ou motivo…"
                style={{ ...inputStyle, flex: "1 1 240px", minWidth: 0, maxWidth: "100%", textAlign: "left" }}
              />
              <select
                value={unavailabilitySort}
                onChange={(event) => setUnavailabilitySort(event.target.value as typeof unavailabilitySort)}
                aria-label="Ordenar indisponibilidades"
                style={{ ...inputStyle, width: 165, maxWidth: "100%", flexShrink: 0, textAlign: "left" }}
              >
                <option value="period">Ordenar: período</option>
                <option value="kind">Ordenar: tipo</option>
                <option value="resource">Ordenar: recurso</option>
                <option value="category">Ordenar: categoria</option>
                <option value="reason">Ordenar: motivo</option>
              </select>
              <span style={{ marginLeft: "auto", whiteSpace: "nowrap", color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
                {visibleUnavailability.length} de {unavailabilityRows.length}
              </span>
            </div>
            {unavailabilityRows.length === 0 ? (
              <div style={{ color: T.secondary, fontSize: 13, padding: 16 }}>Sem indisponibilidades configuradas.</div>
            ) : visibleUnavailability.length === 0 ? (
              <div style={{ color: T.secondary, fontSize: 13, padding: 16 }}>Sem indisponibilidades correspondentes à pesquisa.</div>
            ) : (
              <div data-testid="unavailability-table-scroll" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
              <table style={{ width: "100%", minWidth: 820, borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <SortableTh label="Tipo" sortKey="kind" activeKey={unavailabilitySort} direction={unavailabilitySortDir} onSort={handleUnavailabilitySort} />
                    <SortableTh label="Recurso" sortKey="resource" activeKey={unavailabilitySort} direction={unavailabilitySortDir} onSort={handleUnavailabilitySort} />
                    <SortableTh label="Período" sortKey="period" activeKey={unavailabilitySort} direction={unavailabilitySortDir} onSort={handleUnavailabilitySort} />
                    <SortableTh label="Categoria" sortKey="category" activeKey={unavailabilitySort} direction={unavailabilitySortDir} onSort={handleUnavailabilitySort} />
                    <SortableTh label="Motivo" sortKey="reason" activeKey={unavailabilitySort} direction={unavailabilitySortDir} onSort={handleUnavailabilitySort} />
                    <th style={thStyle}>Estado</th>
                    <th style={{ ...thStyle, width: 150 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {visibleUnavailability.map((entry) => (
                    <tr key={entry.id} style={{ opacity: entry.draftState === "removed" ? 0.55 : 1 }}>
                      <td style={{ ...tdStyle, fontFamily: T.sans }}>{entry.kindLabel}</td>
                      <td style={tdStyle}>{entry.resourceLabel}</td>
                      <td style={tdStyle}>{entry.start_at || "—"}{entry.end_at ? ` → ${entry.end_at}` : " → sem previsão"}</td>
                      <td style={{ ...tdStyle, fontFamily: T.sans }}>{entry.category}</td>
                      <td style={{ ...tdStyle, fontFamily: T.sans, color: T.secondary }}>{entry.reason || "—"}</td>
                      <td style={{ ...tdStyle, padding: "0 8px" }}>
                        <span style={{ color: entry.status.color, fontWeight: 600 }}>{entry.status.label}</span>
                      </td>
                      <td style={tdStyle}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
                        {entry.draftState !== "removed" && (
                          <button
                            disabled={unavailabilityDraftLocked}
                            aria-label={`Editar indisponibilidade ${entry.resourceLabel}`}
                            onClick={() => editUnavailabilityRow(entry)}
                            style={{ ...btnStyle, padding: "5px 8px", minHeight: 36 }}
                          >
                            Editar
                          </button>
                        )}
                        <button
                          disabled={unavailabilityDraftLocked}
                          aria-label={`${entry.draftState === "removed" ? "Desfazer remoção" : "Remover indisponibilidade"} ${entry.resourceLabel}`}
                          title={entry.draftState === "removed" ? "Desfazer remoção" : "Remover do rascunho"}
                          onClick={() => toggleUnavailabilityRemoval(entry)}
                          style={{
                            background: "none",
                            border: "none",
                            color: entry.draftState === "removed" ? T.blue : T.red,
                            cursor: "pointer",
                            fontSize: 18,
                            minWidth: 44,
                            minHeight: 44,
                            display: "grid",
                            placeItems: "center",
                          }}
                        >
                          {entry.draftState === "removed" ? "↶" : "×"}
                        </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
            <div style={{ padding: "12px 16px", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 8, borderTop: `1px solid ${T.border}` }}>
              <button
                disabled={!unavailabilityHasChanges || unavailabilityDraftLocked}
                onClick={saveUnavailabilityDraft}
                style={saveBtnStyle(unavailabilityHasChanges, unavailabilityDraftLocked)}
              >
                Guardar alterações
              </button>
              <button
                disabled={!unavailabilityHasChanges || unavailabilityDraftLocked}
                onClick={cancelUnavailabilityDraft}
                style={btnStyle}
              >
                Cancelar
              </button>
              <span style={{ color: T.tertiary, fontSize: 11 }}>
                {unavailabilityHasChanges
                  ? `${Object.keys(unavailabilityAdditions).length} nova(s) · ${Object.keys(unavailabilityEdits).length} editada(s) · ${unavailabilityRemovals.length} a remover`
                  : "Sem alterações por guardar."}
              </span>
            </div>
          </Card>
        </div>
      )}

      {/* ── PARAMETROS ─────────────────────────────────────────── */}
      {section === "parametros" && (
        <ParametrosEditor config={config} onSaved={(c) => setConfig(c)} onDelta={showDelta} />
      )}

      {/* ── PLANEAMENTO SKU ───────────────────────────────────── */}
      {section === "planeamento" && (
        ops ? (
          <div style={{ display: "grid", gap: 12 }}>
            <HelpPanel>
              Serve para consultar os valores recebidos do ISOP e definir correções usadas no planeamento. O valor ISOP fica guardado; o valor efetivo é o que entra no cálculo.
            </HelpPanel>
            <SkuPlanningEditor
              config={config}
              ops={ops}
              onReload={reload}
              onDelta={showDelta}
            />
          </div>
        ) : (
          <div style={{ color: T.secondary, padding: 24 }}>A carregar referências…</div>
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
          <div style={{ color: T.secondary, padding: 24 }}>A carregar referências…</div>
        )
      )}

      {/* ── QUALIDADE DE DADOS ───────────────────────────────── */}
      {section === "qualidade_dados" && (
        <div style={{ display: "grid", gap: 12 }}>
          <HelpPanel>
            A Qualidade de dados mede a confiança nos dados carregados do ISOP e da configuração. Não mede se o plano é bom, se há atrasos, se há violações JIT ou se a ocupação está correta; isso é avaliado pelo Score, Risco, Carga/Capacidade e Gate Report.
          </HelpPanel>

          {trustError && (
            <Card style={{ padding: 16, borderColor: `${T.orange}55` }}>
              <div style={{ color: T.primary, fontSize: 13, fontWeight: 700 }}>Qualidade ainda não calculada</div>
              <div style={{ color: T.secondary, fontSize: 12, marginTop: 4 }}>{trustError}</div>
            </Card>
          )}

          {trust && (
            <>
              <Card style={{ padding: 18 }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ color: T.primary, fontSize: 15, fontWeight: 700 }}>Qualidade de dados</div>
                    <div style={{ color: T.secondary, fontSize: 12, marginTop: 5 }}>
                      Confiança nos dados de entrada usados pelo planeador.
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ color: scoreColor(trust.score), fontSize: 28, fontWeight: 800, fontFamily: T.mono }}>{trust.score}</div>
                    <div style={{ color: T.secondary, fontSize: 11 }}>{trustGateLabel(trust.gate)}</div>
                  </div>
                </div>
                <div style={{ marginTop: 14 }}>
                  <ProgressBar value={trust.score} color={scoreColor(trust.score)} height={6} bg="#EFEBE3" />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginTop: 14 }}>
                  <KV label="Operações avaliadas" value={trust.n_ops} />
                  <KV label="Problemas encontrados" value={trust.n_issues} />
                  <KV label="Gate recomendado" value={trustGateLabel(trust.gate)} />
                </div>
              </Card>

              <Card style={{ padding: 18 }}>
                <div style={{ color: T.primary, fontSize: 14, fontWeight: 700 }}>Como o número é calculado</div>
                <BulletList
                  items={[
                    "O backend calcula quatro dimensões: completude, validade, consistência e riqueza dos dados.",
                    "A fórmula é: completude 25% + validade 30% + consistência 25% + riqueza dos dados 20%.",
                    "O resultado é arredondado para um valor entre 0 e 100.",
                    ">= 90 significa Automático completo; >= 70 Automático com monitorização; >= 50 Sugestões; abaixo de 50 Manual.",
                  ]}
                />
              </Card>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>
                {trust.dimensions.map((dimension) => {
                  const copy = TRUST_DIMENSION_COPY[dimension.name] ?? {
                    label: dimension.name,
                    checks: ["Dimensão técnica calculada pelo backend."],
                  };
                  const color = scoreColor(dimension.score);
                  return (
                    <Card key={dimension.name} style={{ padding: 16 }}>
                      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
                        <div style={{ color: T.primary, fontSize: 13, fontWeight: 700 }}>{copy.label}</div>
                        <div style={{ color, fontSize: 18, fontWeight: 800, fontFamily: T.mono }}>{dimension.score}</div>
                      </div>
                      <div style={{ marginTop: 8 }}>
                        <ProgressBar value={dimension.score} color={color} height={4} bg="#EFEBE3" />
                      </div>
                      <BulletList items={copy.checks} />
                      {dimension.details.length > 0 && (
                        <details style={{ marginTop: 10 }}>
                          <summary style={{ color: T.orange, fontSize: 12, cursor: "pointer" }}>Ver apontamentos técnicos</summary>
                          <BulletList items={dimension.details} />
                        </details>
                      )}
                    </Card>
                  );
                })}
              </div>

              <Card style={{ padding: 18 }}>
                <div style={{ color: T.primary, fontSize: 14, fontWeight: 700 }}>Interpretação correta</div>
                <BulletList
                  items={[
                    "Qualidade de dados = confiança nos dados de entrada.",
                    "Não substitui o Score do plano.",
                    "Não substitui o Risco, Carga/Capacidade ou análise JIT.",
                    "Um valor alto significa que o planeador recebeu dados completos e coerentes.",
                    "Um valor baixo significa que o planeamento pode estar limitado por dados em falta, inválidos ou pouco ricos.",
                  ]}
                />
              </Card>
            </>
          )}
        </div>
      )}

      {/* ── OPERACOES (read-only) ──────────────────────────────── */}
      {section === "operacoes" && (
        <div style={{ display: "grid", gap: 12 }}>
          <HelpPanel>
            Consulta read-only dos dados recebidos do ISOP e das referências guardadas em configuração. As alterações ficam no separador Correções de planeamento.
          </HelpPanel>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <input
              type="search"
              placeholder="Filtrar referência, cliente, máquina ou ferramenta…"
              value={opsSearch}
              onChange={(e) => setOpsSearch(e.target.value)}
              aria-label="Pesquisar dados ISOP"
              style={{
                background: T.elevated, border: `1px solid ${T.border}`,
                borderRadius: 8, padding: "6px 12px", fontSize: 12,
                color: T.primary, fontFamily: T.mono, outline: "none", width: 320,
              }}
            />
            <select
              value={opsSort}
              onChange={(event) => setOpsSort(event.target.value as typeof opsSort)}
              aria-label="Ordenar dados ISOP"
              style={{ ...inputStyle, width: 175, textAlign: "left" }}
            >
              <option value="sku">Ordenar: referência</option>
              <option value="client">Ordenar: cliente</option>
              <option value="machine">Ordenar: máquina</option>
              <option value="tool">Ordenar: ferramenta</option>
              <option value="alt">Ordenar: alternativa</option>
              <option value="pcs_hour">Ordenar: peças/h</option>
              <option value="setup">Ordenar: setup</option>
              <option value="eco_isop">Ordenar: eco ISOP</option>
              <option value="eco_effective">Ordenar: eco efetivo</option>
              <option value="stock">Ordenar: stock</option>
              <option value="oee">Ordenar: OEE</option>
              <option value="demand">Ordenar: procura</option>
              <option value="source">Ordenar: origem</option>
            </select>
            <span style={{ marginLeft: "auto", color: T.tertiary, fontSize: 10, fontFamily: T.mono }}>
              {filteredOps.length} de {ops?.length ?? 0}
            </span>
          </div>
          <Card style={{ padding: 0, overflow: "auto", maxHeight: 600 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 980 }}>
             <thead>
               <tr>
                  <SortableTh label="Referência" sortKey="sku" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Origem" sortKey="source" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Cliente" sortKey="client" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Máquina" sortKey="machine" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Ferramenta" sortKey="tool" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Alt" sortKey="alt" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Pcs/H" sortKey="pcs_hour" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Setup (h)" sortKey="setup" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Eco ISOP" sortKey="eco_isop" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Eco efetivo" sortKey="eco_effective" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="Stock" sortKey="stock" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                  <SortableTh label="OEE" sortKey="oee" activeKey={opsSort} direction={opsSortDir} onSort={handleOpsSort} />
                </tr>
              </thead>
              <tbody>
                {filteredOps.map((op) => (
                  <tr key={op.id}>
                    <td style={tdStyle}>
                      {op.sku}
                      {op.active === false && (
                        <div style={{ color: T.tertiary, fontSize: 9, marginTop: 2 }}>histórico</div>
                      )}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: T.sans, color: op.active === false ? T.tertiary : T.secondary }}>
                      {op.active === false ? "Configuração" : "ISOP"}
                    </td>
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
            {filteredOps.length === 0 && (
              <div style={{ padding: 18, color: T.secondary, fontSize: 12 }}>Sem dados ISOP correspondentes à pesquisa.</div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
import { assertRefreshed, isAppliedRefreshError, refreshAfterCommit } from "../lib/refreshOutcome";

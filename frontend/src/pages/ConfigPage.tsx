import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { T } from "../theme/tokens";
import {
  getCatalog, getConfig, getOps,
  applyReplan, cancelReplan, getReplan, getReplans, startReplan,
  previewSkuPlanning, previewSubcontracts,
  getTrust,
} from "../api/endpoints";
import type {
  EOp,
  FactoryConfig,
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
import { useConfirm } from "../components/ui/confirmContext";
import { useDataStore } from "../stores/useDataStore";
import { useAppStore } from "../stores/useAppStore";
import {
  buildConfigUpdates,
  useConfigDraftStore,
  type DraftChange,
  type DraftItem,
  type SubcontractsBody,
  type ToolDraft,
  type UnavailabilityCategory,
  type UnavailabilityForm,
  type UnavailabilityKind,
} from "../stores/useConfigDraftStore";
import { ApiError } from "../api/client";
import { gateReasonLabel, gateStatusLabel } from "../lib/gateApproval";
import { getReadIdentity } from "../lib/planRevision";
import { jobFailureText } from "../lib/jobFailure";
import { refusalCauses } from "../lib/refusal";
import { RefusalDetails } from "../components/RefusalDetails";
import { ConfigPendingBar } from "../components/ConfigPendingBar";
import { assertRefreshed, isAppliedRefreshError, refreshAfterCommit } from "../lib/refreshOutcome";

type Section = "geral" | "turnos" | "maquinas" | "ferramentas" | "gemeas" | "setup_overrides" | "operadores" | "feriados" | "indisponibilidades" | "parametros" | "planeamento" | "subcontratacoes" | "operacoes" | "qualidade_dados";
type ConfigGroup = "factory" | "articles" | "calendar" | "availability" | "engine";
type SortDirection = "asc" | "desc";
type UnavailabilityEditTarget = { source: "existing" | "addition"; id: string };
type UnavailabilityRow = UnavailabilityForm & {
  id: string;
  /** The pending list line behind this row, when there is one. */
  draftItemId?: string;
  kindLabel: string;
  resourceLabel: string;
  status: { label: string; color: string };
  draftState: "unchanged" | "edited" | "added" | "removed";
};

/** Stages one change in the page-wide list; returns nothing, never saves. */
type Stage = (change: DraftChange, label?: string) => void;

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
  factory: "Define os recursos que existem na fábrica, os turnos e as pessoas disponíveis. Cada alteração entra na lista no topo da página e só muda o plano depois de Aplicar.",
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

type ReplanFollowup = {
  reason: string;
  changes: string[];
  successMessage: string;
  /** Started by «Aplicar» on the pending list: apply as soon as it is ready. */
  auto: boolean;
  /** Score before the change, for the delta shown after applying. */
  previousScore?: Score | null;
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

type TunableOption = { value: string; label: string };

const TUNABLES: { key: string; label: string; type: "number" | "boolean" | "select"; options?: TunableOption[] }[] = [
  { key: "oee_default", label: "Rendimento (OEE) por omissão", type: "number" },
  { key: "jit_buffer_pct", label: "Margem de antecipação (%)", type: "number" },
  { key: "jit_max_retries", label: "Tentativas de antecipação", type: "number" },
  { key: "max_edd_gap", label: "Intervalo máximo entre prazos (dias)", type: "number" },
  { key: "max_edd_span", label: "Duração máxima de prazos numa campanha (dias)", type: "number" },
  { key: "edd_swap_tolerance", label: "Tolerância para trocar a ordem dos prazos (dias)", type: "number" },
  { key: "edd_assign_threshold", label: "Limite de prazo para escolher máquina (dias)", type: "number" },
  { key: "campaign_window", label: "Janela de campanha (dias)", type: "number" },
  { key: "urgency_threshold", label: "Limite de urgência (dias)", type: "number" },
  { key: "interleave_enabled", label: "Intercalar urgentes", type: "boolean" },
  { key: "vns_enabled", label: "Pesquisa de melhorias", type: "boolean" },
  { key: "vns_max_iter", label: "Máximo de iterações da pesquisa", type: "number" },
  { key: "compact_enabled", label: "Compactar plano", type: "boolean" },
  { key: "weight_earliness", label: "Peso da antecipação", type: "number" },
  { key: "weight_setups", label: "Peso das mudanças de ferramenta", type: "number" },
  { key: "weight_balance", label: "Peso do equilíbrio entre máquinas", type: "number" },
  {
    key: "eco_lot_mode", label: "Lote económico", type: "select",
    options: [
      { value: "hard", label: "Obrigatório" },
      { value: "soft", label: "Flexível" },
    ],
  },
];

// ── ParametrosEditor ─────────────────────────────────────────────

function ParametrosEditor({ config, items, stage, unstage, locked }: {
  config: FactoryConfig;
  items: DraftItem[];
  stage: Stage;
  unstage: (id: string) => void;
  locked: boolean;
}) {
  const isSimulated = useDataStore((s) => s.isSimulated);
  const edits = useMemo(() => Object.fromEntries(items.flatMap((item) => (
    item.kind === "config_param" ? [[item.key, item.value]] : []
  ))), [items]);
  const pendingPreset = items.find((item) => item.kind === "preset");
  const activePreset = pendingPreset?.kind === "preset" ? pendingPreset.name : null;

  const getValue = (key: string) => {
    if (key in edits) return edits[key];
    return (config as unknown as Record<string, unknown>)[key];
  };

  const handleChange = (key: string, label: string, value: unknown, type: "number" | "boolean" | "select") => {
    const original = (config as unknown as Record<string, unknown>)[key];
    const parsed = type === "number" ? Number(value) : value;
    if (type === "number" && !Number.isFinite(parsed)) return;
    if (parsed === original) {
      unstage(`config_param:${key}`);
      return;
    }
    const shown = typeof parsed === "boolean"
      ? (parsed ? "Sim" : "Não")
      : TUNABLES.find((t) => t.key === key)?.options?.find((o) => o.value === parsed)?.label
        ?? (typeof parsed === "number" ? parsed.toLocaleString("pt-PT") : String(parsed));
    stage({ kind: "config_param", key, value: parsed }, `Parâmetro «${label}»: ${shown}`);
  };

  const handlePreset = (name: string) => {
    if (activePreset === name) {
      unstage("preset");
      return;
    }
    const presetLabel = PRESETS.find((p) => p.id === name)?.label ?? name;
    stage({ kind: "preset", name }, `Predefinição «${presetLabel}» (substitui os parâmetros)`);
  };

  return (
    <Card>
      {/* Presets row */}
      <div style={{ marginBottom: 12 }}>
        <Label style={{ marginBottom: 8 }}>Predefinições</Label>
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
                disabled={locked}
                aria-pressed={isActive}
                style={{
                  background: isActive ? p.color + "30" : p.color + "18",
                  border: isActive ? `2px solid ${p.color}` : `1px solid ${p.color}50`,
                  borderRadius: 8, padding: isActive ? "4px 13px" : "5px 14px",
                  cursor: locked ? "default" : "pointer",
                  fontSize: 12, fontWeight: isActive ? 700 : 500,
                  color: p.color, fontFamily: "inherit",
                  opacity: locked ? 0.5 : 1,
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
          O plano executável começa sempre no dia 0. A antiga opção que criava
          dias antes do dia 0 deixou de estar disponível; as margens de
          antecipação, de artigo e de subcontratação continuam a ser usadas no
          planeamento.
        </div>
        <div style={{ marginTop: 8 }}>
          {TUNABLES.map((t) => (
          <div key={t.key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0" }}>
            <span style={{ fontSize: 12, color: T.secondary }}>{t.label}</span>
            {t.type === "boolean" ? (
              <button
                disabled={locked}
                onClick={() => handleChange(t.key, t.label, !getValue(t.key), "boolean")}
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
                disabled={locked}
                value={String(getValue(t.key) ?? "")}
                onChange={(e) => handleChange(t.key, t.label, e.target.value, "select")}
                style={{ ...inputStyle, width: 120, cursor: "pointer", textAlign: "left", borderColor: t.key in edits ? T.blue : T.border }}
              >
                {t.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : (
              <input
                type="number" step="any"
                disabled={locked}
                aria-label={t.label}
                value={String(getValue(t.key) ?? "")}
                onChange={(e) => handleChange(t.key, t.label, e.target.value, "number")}
                style={{ ...inputStyle, borderColor: t.key in edits ? T.blue : T.border }}
              />
            )}
          </div>
          ))}
        </div>
      </details>
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
  return `Lotes no prazo ${d.otd >= 0 ? "+" : ""}${d.otd.toFixed(1)} · Setups ${d.setups >= 0 ? "+" : ""}${d.setups}`;
}

function sameRule(left: SkuPlanningRule, right: SkuPlanningRule) {
  const normalized = (rule: SkuPlanningRule) => JSON.stringify(Object.entries(cleanRule(rule)).sort(([a], [b]) => a.localeCompare(b)));
  return normalized(left) === normalized(right);
}

/** `failureMessage` followed by the refusal's concrete causes, for one-line messages. */
function failureWithCauses(error: unknown) {
  return [failureMessage(error), ...refusalCauses(error)].join(" ");
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
  items,
  stage,
  unstage,
  locked,
}: {
  config: FactoryConfig;
  ops: EOp[];
  items: DraftItem[];
  stage: Stage;
  unstage: (id: string) => void;
  locked: boolean;
}) {
  const [search, setSearch] = useState("");
  const drafts = useMemo(() => Object.fromEntries(items.flatMap((item) => (
    item.kind === "sku_planning" ? [[item.sku, item.rule]] : []
  ))) as Record<string, SkuPlanningRule | null>, [items]);
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

  const savedRule = (sku: string) => config.sku_planning_rules?.[sku] ?? {};
  const ruleFor = (sku: string) => sku in drafts ? drafts[sku] ?? {} : savedRule(sku);
  /** Stage the rule in the list, or drop the line when it equals what is saved. */
  const stageRule = (sku: string, rule: SkuPlanningRule) => {
    const cleaned = cleanRule(rule);
    const hasSaved = Boolean(config.sku_planning_rules?.[sku]);
    if (sameRule(cleaned, savedRule(sku))) unstage(`sku_planning:${sku}`);
    else if (Object.keys(cleaned).length === 0) {
      if (hasSaved) stage({ kind: "sku_planning", sku, rule: null });
      else unstage(`sku_planning:${sku}`);
    } else stage({ kind: "sku_planning", sku, rule: cleaned });
  };
  const setField = (sku: string, field: keyof SkuPlanningRule, raw: string) => {
    const base = { ...ruleFor(sku) };
    if (raw === "") {
      delete base[field];
    } else {
      const value = Number(raw);
      if (!Number.isFinite(value)) return;
      base[field] = value;
    }
    stageRule(sku, base);
  };

  const runPreview = async (sku: string) => {
    setBusySku(sku);
    setMsg(null);
    try {
      const res = await previewSkuPlanning(sku, cleanRule(ruleFor(sku)));
      setPreview({ ...preview, [sku]: res });
    } catch (e) {
      setMsg(failureWithCauses(e));
    } finally {
      setBusySku(null);
    }
  };

  const reset = (sku: string) => {
    if (config.sku_planning_rules?.[sku]) stage({ kind: "sku_planning", sku, rule: null });
    else unstage(`sku_planning:${sku}`);
  };

  const numberInput = (op: EOp, field: keyof SkuPlanningRule, width = 88) => {
    const rule = ruleFor(op.sku);
    return (
      <input
        type="number"
        min="0"
        disabled={locked || op.active === false}
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
                      <button
                        disabled={locked || isBusy || (!config.sku_planning_rules?.[op.sku] && !(op.sku in drafts)) || drafts[op.sku] === null}
                        onClick={() => reset(op.sku)}
                        title="Repor os valores do ISOP"
                        style={{ ...btnStyle, color: T.red }}
                      >
                        ISOP
                      </button>
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

function subcontractsBody(config: FactoryConfig, selected: Set<string>, leadTimes: Record<string, number>): SubcontractsBody {
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
  return { companies, sku_subcontracts };
}

/** Selection and lead times shown: the pending list's version, else the saved one. */
function subcontractDraftState(config: FactoryConfig, pending: SubcontractsBody | null) {
  if (!pending) {
    return { selected: subcontractInitialSelection(config), leadTimes: subcontractInitialLeadTimes(config) };
  }
  return {
    selected: new Set(Object.keys(pending.sku_subcontracts)),
    leadTimes: {
      ...subcontractInitialLeadTimes(config),
      ...Object.fromEntries(Object.entries(pending.sku_subcontracts).map(([sku, rule]) => [
        sku, Number(rule.lead_time_workdays ?? DEFAULT_SUBCONTRACT_WORKDAYS),
      ])),
    },
  };
}

function SubcontractEditor({
  config,
  ops,
  items,
  stage,
  unstage,
  locked,
}: {
  config: FactoryConfig;
  ops: EOp[];
  items: DraftItem[];
  stage: Stage;
  unstage: (id: string) => void;
  locked: boolean;
}) {
  const pendingItem = items.find((item) => item.kind === "subcontracts");
  const pending = pendingItem?.kind === "subcontracts" ? pendingItem.body : null;
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => subcontractDraftState(config, pending).selected);
  const [leadTimes, setLeadTimes] = useState<Record<string, number>>(() => subcontractDraftState(config, pending).leadTimes);
  const [busy, setBusy] = useState<"preview" | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [previewDelta, setPreviewDelta] = useState<PlanningDelta | null>(null);
  const [sort, setSort] = useState<"selected" | "sku" | "client" | "demand" | "lead" | "source">("selected");

  useEffect(() => {
    // A new saved configuration (after Aplicar) or a line removed from the
    // pending list resets the editor to what is now pending or saved.
    const next = subcontractDraftState(config, pending);
    setSelected(next.selected);
    setLeadTimes(next.leadTimes);
    setPreviewDelta(null);
  }, [config, pending]);

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

  /** Stage the whole subcontract selection, or drop the line when it equals what is saved. */
  const stageSelection = (nextSelected: Set<string>, nextLeadTimes: Record<string, number>) => {
    if (locked) return;
    setSelected(nextSelected);
    setLeadTimes(nextLeadTimes);
    setPreviewDelta(null);
    const savedSelected = subcontractInitialSelection(config);
    const saved = subcontractsBody(config, savedSelected, subcontractInitialLeadTimes(config));
    const body = subcontractsBody(config, nextSelected, nextLeadTimes);
    if (JSON.stringify(body) === JSON.stringify(saved)) {
      unstage("subcontracts");
      return;
    }
    const added = [...nextSelected].filter((sku) => !savedSelected.has(sku)).sort();
    const removed = [...savedSelected].filter((sku) => !nextSelected.has(sku)).sort();
    const changedLead = [...nextSelected]
      .filter((sku) => savedSelected.has(sku)
        && body.sku_subcontracts[sku]?.lead_time_workdays !== saved.sku_subcontracts[sku]?.lead_time_workdays)
      .sort();
    const parts = [
      added.length ? `subcontratar ${added.join(", ")}` : "",
      removed.length ? `deixar de subcontratar ${removed.join(", ")}` : "",
      ...changedLead.map((sku) => `${sku} com ${body.sku_subcontracts[sku].lead_time_workdays} dias úteis`),
    ].filter(Boolean);
    stage({ kind: "subcontracts", body }, `Subcontratações: ${parts.join(" · ") || "antecedências alteradas"}`);
  };

  const toggle = (sku: string) => {
    const next = new Set(selected);
    if (next.has(sku)) next.delete(sku);
    else next.add(sku);
    stageSelection(next, leadTimes);
  };

  const runPreview = async () => {
    setBusy("preview");
    setMsg(null);
    try {
      const res = await previewSubcontracts(subcontractsBody(config, selected, leadTimes));
      setPreviewDelta(res.delta ?? null);
      setMsg(`Impacto revisto: ${metricDelta(res) ?? "plano recalculado"}`);
    } catch (e) {
      setMsg(failureWithCauses(e));
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
                      disabled={locked}
                      aria-label={`Subcontratar ${op.sku}`}
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
                      disabled={locked}
                      value={leadTimes[op.sku] ?? DEFAULT_SUBCONTRACT_WORKDAYS}
                      onChange={(event) => {
                        const value = Number(event.target.value);
                        if (!Number.isFinite(value)) return;
                        stageSelection(selected, { ...leadTimes, [op.sku]: Math.max(0, Math.trunc(value)) });
                      }}
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
  const { prompt } = useConfirm();
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

  // Page-wide pending list (decisão de 16/10/2026): every plan-input edit is
  // staged here and applied together by one replan job.
  const draftItems = useConfigDraftStore((s) => s.items);
  const draftApplying = useConfigDraftStore((s) => s.applying);
  const draftLines = useMemo(() => draftItems.map((item) => ({ id: item.id, text: item.label })), [draftItems]);
  const draftById = useMemo(() => new Map(draftItems.map((item) => [item.id, item])), [draftItems]);
  const draftValues = useMemo(() => {
    const oee: Record<string, number | null> = {};
    const groups: Record<string, string> = {};
    const active: Record<string, boolean> = {};
    const tools: Record<string, ToolDraft> = {};
    const operators: Record<string, number> = {};
    const crews: Record<string, number> = {};
    let shifts: FactoryConfig["shifts"] | null = null;
    for (const item of draftItems) {
      if (item.kind === "machine_oee") oee[item.machine] = item.value;
      else if (item.kind === "machine_group") groups[item.machine] = item.value;
      else if (item.kind === "machine_active") active[item.machine] = item.value;
      else if (item.kind === "tool_update") tools[item.tool] = item.value;
      else if (item.kind === "operators") operators[item.key] = item.value;
      else if (item.kind === "setup_crews") crews[item.group] = item.value;
      else if (item.kind === "shifts") shifts = item.value;
    }
    return { oee, groups, active, tools, operators, crews, shifts };
  }, [draftItems]);
  const { oee: oeeEdits, groups: machineGroupEdits, active: machineActiveEdits, tools: toolEdits, operators: opEdits, crews: crewEdits, shifts: shiftEdits } = draftValues;

  const [replanMessage, setReplanMessageText] = useState<string | null>(null);
  // Concrete causes of a refused change, shown under the message (15/10/2026).
  const [replanCauses, setReplanCauses] = useState<string[]>([]);
  const setReplanMessage = useCallback((message: string | null, causes: readonly string[] = []) => {
    setReplanMessageText(message);
    setReplanCauses([...causes]);
  }, []);
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
  // A candidate this page did not start (e.g. resumed from another screen):
  // it keeps its own review card. Candidates from the pending list apply alone.
  const [pendingReplan, setPendingReplan] = useState<({ job: ReplanJob } & ReplanFollowup) | null>(null);
  const pendingReplanBlocked = pendingReplan?.job.result?.gate_report.apply_decision === "blocked";
  /** No staging while read-only or while the list is being applied. */
  const locked = readOnly || saving || draftApplying;
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
  const [unavailabilityEditTarget, setUnavailabilityEditTarget] = useState<UnavailabilityEditTarget | null>(null);

  // Gemeas modal state
  const [twinModal, setTwinModal] = useState(false);
  const [twinForm, setTwinForm] = useState({ tool_id: "", sku_a: "", sku_b: "" });

  const stage: Stage = useCallback((change, label) => {
    if (locked) return;
    useConfigDraftStore.getState().upsert(change, label);
  }, [locked]);
  const unstage = useCallback((id: string) => {
    if (locked) return;
    useConfigDraftStore.getState().remove(id);
  }, [locked]);

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

  const reload = useCallback(async () => {
    const outcome = await refreshAfterCommit(refreshAll);
    assertRefreshed(outcome, true);
    await loadConfiguration();
  }, [loadConfiguration, refreshAll]);

  /** After a successful apply: drop the applied lines, show the delta, reload. */
  const finishAppliedDraft = useCallback(async (
    job: ReplanJob,
    followup: ReplanFollowup,
    stillFollowing: () => boolean,
  ) => {
    useConfigDraftStore.getState().finishApply(true);
    if (!stillFollowing()) return;
    setReplanMessage(job.warnings.length
      ? `Alterações aplicadas com ${job.warnings.length} aviso(s).`
      : followup.successMessage);
    const score = job.result?.score;
    if (followup.previousScore && score) setDelta({ prev: followup.previousScore, curr: score });
    try {
      await reload();
    } catch (failure) {
      if (stillFollowing()) setReplanMessage(failureMessage(failure), refusalCauses(failure));
    }
  }, [reload, setReplanMessage]);

  /**
   * A candidate from the pending list is applied as soon as it is ready
   * (decisão de 16/10/2026). Only a candidate that needs approval asks once
   * for the justification; a blocked or declined candidate applies nothing
   * and the list stays for the planner to correct.
   */
  const applyReadyDraftJob = useCallback(async (
    job: ReplanJob,
    followup: ReplanFollowup,
    stillFollowing: () => boolean,
  ) => {
    const gate = job.result?.gate_report;
    const keepList = (message: string, causes: readonly string[] = []) => {
      useConfigDraftStore.getState().finishApply(false);
      // The candidate is of no further use; drop it so it is not resumed later.
      void cancelReplan(job.id).catch(() => undefined);
      if (stillFollowing()) setReplanMessage(message, causes);
    };
    if (gate?.apply_decision === "blocked") {
      keepList(`Erro: ${job.message || "o plano calculado não pode ser aplicado."}`, job.causes ?? []);
      return;
    }
    let approval: { reason: string; author: string } | undefined;
    if (gate?.requires_approval) {
      const reasons = gate.approval_reasons?.length
        ? gate.approval_reasons.map((reason) => `• ${gateReasonLabel(reason, gate)}`).join("\n")
        : "• O plano proposto tem exceções que precisam da aprovação do planeador.";
      const score = job.result?.score;
      const impact = [
        `Lotes no prazo: ${score?.otd?.toFixed?.(1) ?? score?.otd ?? "-"}%`,
        `Lotes atrasados: ${score?.tardy_count ?? 0}`,
        `Avisos: ${job.warnings.length}`,
      ].join(" · ");
      const justification = await prompt({
        title: "Aplicar plano com exceções?",
        message: `Motivos para aprovação:\n${reasons}\n\nImpacto previsto:\n${impact}\n\nIndica a justificação para aplicar este plano.`,
        inputLabel: "Justificação obrigatória",
        placeholder: "Explica por que motivo este impacto é aceite…",
        confirmLabel: "Confirmar e aplicar",
        variant: "danger",
      });
      // Left the page with the question open: the candidate is resumed on return.
      if (!stillFollowing()) return;
      if (justification === null) {
        keepList("Alterações não aplicadas. O plano não mudou e a lista mantém-se.");
        return;
      }
      approval = { reason: justification, author: "planeador" };
    }
    setSaving(true);
    setReplanMessage("A aplicar as alterações…");
    try {
      const applied = await applyReplan(job.id, approval, job.base_revision);
      await finishAppliedDraft({ ...applied.job, result: applied.job.result ?? job.result }, followup, stillFollowing);
    } catch (failure) {
      // A lost answer is ambiguous: the job itself says whether it was applied.
      let current: ReplanJob | null = null;
      try { current = (await getReplan(job.id)).job; } catch { /* Treated as not applied. */ }
      if (current?.status === "completed") {
        await finishAppliedDraft({ ...current, result: current.result ?? job.result }, followup, stillFollowing);
      } else {
        keepList(failureMessage(failure), refusalCauses(failure));
      }
    } finally {
      if (stillFollowing()) setSaving(false);
    }
  }, [finishAppliedDraft, prompt, setReplanMessage]);

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
    const keepDraft = () => { if (followup.auto) useConfigDraftStore.getState().finishApply(false); };

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
          keepDraft();
          setActiveReplanJobId(null);
          setSaving(false);
          setReplanConnectionMessage(null);
          setReplanMessage(failureMessage(failure), refusalCauses(failure));
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
      keepDraft();
      setReplanMessage(followup.auto
        ? "Pedido cancelado. O plano não foi alterado e a lista mantém-se."
        : "Pedido cancelado. O plano não foi alterado.");
      return;
    }
    if (job.status === "failed") {
      keepDraft();
      setReplanMessage(
        `Erro: ${jobFailureText(job, "O replaneamento falhou. O plano não foi alterado.")}`,
        job.causes ?? [],
      );
      return;
    }
    if (job.status === "completed") {
      setPendingReplan(null);
      if (followup.auto) {
        await finishAppliedDraft(job, followup, stillFollowing);
        return;
      }
      setReplanMessage("Alteração já aplicada. A atualizar o plano.");
      try {
        await reload();
      } catch (failure) {
        if (stillFollowing()) setReplanMessage(failureMessage(failure), refusalCauses(failure));
      }
      return;
    }
    if (job.status !== "ready") {
      keepDraft();
      setReplanMessage("Erro: o plano proposto não ficou pronto para aplicar.");
      return;
    }
    if (followup.auto) {
      await applyReadyDraftJob(job, followup, stillFollowing);
      return;
    }
    setPendingReplan({ job, ...followup });
    setReplanMessage(job.result?.gate_report.apply_decision === "blocked"
      ? job.message
      : "Candidato pronto. Revê as alterações antes de aplicar.");
  }, [applyReadyDraftJob, finishAppliedDraft, reload, setReplanMessage]);

  useEffect(() => {
    let disposed = false;
    const generation = replanPollGeneration.current;
    const drafts = useConfigDraftStore.getState();
    // «Aplicar» was pressed but the job never got an id: nothing is running.
    if (drafts.applying && !drafts.applyingJobId) drafts.finishApply(false);
    const ownJobId = drafts.applying ? drafts.applyingJobId : null;
    const ownFollowup = (reason: string): ReplanFollowup => ({
      reason,
      changes: useConfigDraftStore.getState().items.map((item) => item.label),
      successMessage: "Alterações aplicadas e plano atualizado.",
      auto: true,
      previousScore: useDataStore.getState().score,
    });
    const current = () => !disposed && replanPollGeneration.current === generation;
    void getReplans(true)
      .then((response) => {
        if (!current()) return;
        const job = response.jobs.find((candidate) => (
          candidate.status === "queued"
          || candidate.status === "running"
          || candidate.status === "ready"
        ));
        if (ownJobId && job?.id !== ownJobId) {
          // The list's job is no longer pending: its own state says how it ended.
          void getReplan(ownJobId)
            .then(({ job: own }) => { if (current()) void followReplanJob(own, ownFollowup(own.reason)); })
            .catch(() => useConfigDraftStore.getState().finishApply(false));
          return;
        }
        if (!job) return;
        void followReplanJob(job, job.id === ownJobId ? ownFollowup(job.reason) : {
          reason: job.reason,
          changes: [`Alteração pendente: ${job.reason}`],
          successMessage: "Alteração guardada e plano atualizado.",
          auto: false,
        });
      })
      .catch(() => {
        // A configuração continua utilizável; a consulta será repetida no próximo acesso.
      });
    return () => {
      disposed = true;
    };
  }, [followReplanJob]);

  /** «Aplicar»: one replan job with every pending change; applied when ready. */
  const applyDraft = async () => {
    if (readOnly || saving || cancelling.current || pendingReplan || !config) return;
    const drafts = useConfigDraftStore.getState();
    if (drafts.applying || drafts.count === 0) return;
    const items = drafts.beginApply();
    const configUpdates = buildConfigUpdates(items, config);
    const reason = items.length === 1 ? items[0].label : `${items.length} alterações de configuração`;
    const followup: ReplanFollowup = {
      reason,
      changes: items.map((item) => item.label),
      successMessage: items.length === 1
        ? "Alteração aplicada e plano atualizado."
        : `${items.length} alterações aplicadas e plano atualizado.`,
      auto: true,
      previousScore: useDataStore.getState().score,
    };
    const generation = ++replanPollGeneration.current;
    setSaving(true);
    setDelta(null);
    setReplanMessage("A colocar o replaneamento em fila…");
    setReplanConnectionMessage(null);
    setReplanStartedAt(Date.now());
    setReplanElapsedSeconds(0);
    try {
      const started = await startReplan({
        reason,
        config_updates: configUpdates,
        expected_revision: config.plan_revision,
      });
      // Recorded even if the page was left: the job is resumed on return.
      useConfigDraftStore.getState().setApplyingJob(started.job.id);
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      await followReplanJob(started.job, followup, generation);
    } catch (failure) {
      useConfigDraftStore.getState().finishApply(false);
      if (!mounted.current || generation !== replanPollGeneration.current) return;
      setReplanMessage(failureMessage(failure), refusalCauses(failure));
      setActiveReplanJobId(null);
      setReplanConnectionMessage(null);
      setSaving(false);
    }
  };

  const discardDraft = () => {
    if (locked) return;
    useConfigDraftStore.getState().discard();
    setUnavailabilityEditTarget(null);
    setUnavailability((current) => emptyUnavailability(current.kind, current.category));
    setReplanMessage(null);
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

  /** Applies a candidate this page did not start (resumed from elsewhere). */
  const applyPendingReplan = async () => {
    if (readOnly || saving || cancelling.current || !pendingReplan || pendingReplanBlocked) return;
    const generation = replanPollGeneration.current;
    const gateReport = pendingReplan.job.result?.gate_report;
    let approval: { reason: string; author: string } | undefined;
    if (gateReport?.requires_approval) {
      const reasons = gateReport.approval_reasons?.length
        ? gateReport.approval_reasons.map((reason) => `• ${gateReasonLabel(reason, gateReport)}`).join("\n")
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
      setPendingReplan(null);
      await reload();
    } catch (failure) {
      if (mounted.current && generation === replanPollGeneration.current) setReplanMessage(failureMessage(failure), refusalCauses(failure));
    } finally {
      if (mounted.current && generation === replanPollGeneration.current) setSaving(false);
    }
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
  const unavailabilityEdit = (id: string) => {
    const item = draftById.get(`unavailability_update:${id}`);
    return item?.kind === "unavailability_update" ? item.form : undefined;
  };
  const unavailabilityRows: UnavailabilityRow[] = [
    ...existingUnavailabilityForms.map(([id, original]) => {
      const removed = draftById.has(`unavailability_remove:${id}`);
      const edited = unavailabilityEdit(id);
      return {
        ...rowFromForm(id, edited ?? original, removed ? "removed" : edited ? "edited" : "unchanged"),
        draftItemId: removed ? `unavailability_remove:${id}` : edited ? `unavailability_update:${id}` : undefined,
      };
    }),
    ...draftItems.flatMap((item) => item.kind === "unavailability_add"
      ? [{ ...rowFromForm(item.id, item.form, "added"), draftItemId: item.id }]
      : []),
  ];
  const unavailabilityDraftLocked = locked;
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
    if (unavailabilityDraftLocked) return;
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
    const form = { ...unavailability };
    if (unavailabilityEditTarget?.source === "existing") {
      stage({ kind: "unavailability_update", entryId: unavailabilityEditTarget.id, form });
    } else if (unavailabilityEditTarget?.source === "addition") {
      const item = draftById.get(unavailabilityEditTarget.id);
      if (item?.kind === "unavailability_add") stage({ kind: "unavailability_add", key: item.key, form });
    } else {
      stage({ kind: "unavailability_add", key: useConfigDraftStore.getState().nextKey(), form });
    }
    setReplanMessage(null);
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
      unstage(entry.id);
    } else if (entry.draftState === "removed") {
      unstage(`unavailability_remove:${entry.id}`);
    } else {
      unstage(`unavailability_update:${entry.id}`);
      stage(
        { kind: "unavailability_remove", entryId: entry.id },
        `Remover indisponibilidade: ${entry.kindLabel.toLowerCase()} ${entry.resourceLabel} · ${entry.start_at.replace("T", " ") || "—"}`,
      );
    }
    if (unavailabilityEditTarget?.id === entry.id) resetUnavailabilityEditor();
  };

  // ── Staging helpers: each edit becomes (or replaces) one line in the list ──
  const machineIdsPending = draftItems.flatMap((item) => item.kind === "machine_add" ? [item.machine.id] : []);
  const stageMachineAddition = () => {
    const machineId = newMachine.id.trim().toUpperCase();
    if (!machineId) return;
    if (machineId in config.machines || machineIdsPending.includes(machineId)) {
      setReplanMessage(`Erro: a máquina ${machineId} já existe.`);
      return;
    }
    stage({ kind: "machine_add", machine: { id: machineId, group: newMachine.group, active: true } });
    setReplanMessage(null);
    setNewMachine({ id: "", group: newMachine.group });
  };
  const stageToolField = (id: string, field: keyof ToolDraft, value: ToolDraft[keyof ToolDraft], original: ToolDraft[keyof ToolDraft]) => {
    const next: ToolDraft = { ...toolEdits[id] };
    if (value === original) delete next[field];
    else (next as Record<string, unknown>)[field] = value;
    if (Object.keys(next).length === 0) unstage(`tool:${id}`);
    else stage({ kind: "tool_update", tool: id, value: next });
  };
  const shiftTime = (minutes: number) => `${String(Math.floor((minutes % 1440) / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  const stageShifts = (next: FactoryConfig["shifts"]) => {
    const changed = next.filter((shift, index) => {
      const saved = config.shifts[index];
      return !saved || saved.label !== shift.label || saved.start_min !== shift.start_min || saved.end_min !== shift.end_min;
    });
    if (changed.length === 0) {
      unstage("shifts");
      return;
    }
    stage(
      { kind: "shifts", value: next },
      `Turnos: ${changed.map((shift) => `${shift.label} ${shiftTime(shift.start_min)}–${shiftTime(shift.end_min)}`).join(" · ")}`,
    );
  };
  /** The latest pending change that touches this date, if any. */
  const holidayChange = (date: string) => [...draftItems].reverse().find((item) => (
    (item.kind === "holiday_add" || item.kind === "holiday_remove") && item.dates.includes(date)
  ));
  const holidayRangeDates = (from: string, to: string) => {
    const start = new Date(`${from}T12:00:00Z`);
    const end = new Date(`${to}T12:00:00Z`);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start > end) return null;
    const dates: string[] = [];
    for (let day = start; day <= end && dates.length <= 366; day = new Date(day.getTime() + 86_400_000)) {
      dates.push(day.toISOString().slice(0, 10));
    }
    return dates.length > 366 ? null : dates;
  };
  const stageHolidays = (kind: "holiday_add" | "holiday_remove", from: string, to = from) => {
    const dates = holidayRangeDates(from, to);
    if (!dates) {
      setReplanMessage("Erro: a data inicial não pode ser posterior à data final (máximo 366 dias).");
      return false;
    }
    // Undoing a pending single day removes its line instead of adding another.
    if (dates.length === 1) {
      const pending = draftById.get(`holiday:${dates[0]}..${dates[0]}`);
      if (pending && pending.kind !== kind) {
        unstage(pending.id);
        return true;
      }
    }
    stage({ kind, dates });
    setReplanMessage(null);
    return true;
  };
  const removeHolidayChip = (date: string) => {
    const pending = holidayChange(date);
    if (pending?.kind === "holiday_add" && pending.dates.length === 1) unstage(pending.id);
    else stageHolidays("holiday_remove", date);
  };
  const pendingHolidayAdds = draftItems.flatMap((item) => item.kind === "holiday_add" ? item.dates : []);
  const holidayChips = Array.from(new Set([...config.holidays, ...pendingHolidayAdds])).sort().map((date) => {
    const lastChange = holidayChange(date);
    const state = lastChange?.kind === "holiday_remove"
      ? "removed"
      : !config.holidays.includes(date) && lastChange ? "added" : "saved";
    return { date, state } as const;
  });
  const extraDayChips = Array.from(new Set([
    ...config.extra_workdays,
    ...draftItems.flatMap((item) => item.kind === "extra_day_add" ? [item.date] : []),
  ])).sort().map((date) => {
    const pending = draftById.get(`extra_day:${date}`);
    return {
      date,
      state: pending?.kind === "extra_day_remove" ? "removed" : pending?.kind === "extra_day_add" ? "added" : "saved",
    } as const;
  });
  const toggleExtraDay = (date: string, add: boolean) => {
    const saved = config.extra_workdays.includes(date);
    if (add === saved) unstage(`extra_day:${date}`);
    else stage(add ? { kind: "extra_day_add", date } : { kind: "extra_day_remove", date });
  };
  const setupOverrideRows = [
    ...config.setup_overrides.map((item) => {
      const pending = draftById.get(`setup_override:${item.sku}|${item.machine}`);
      if (pending?.kind === "setup_override_set") return { item: pending.value, state: "edited" as const };
      if (pending?.kind === "setup_override_remove") return { item, state: "removed" as const };
      return { item, state: "saved" as const };
    }),
    ...draftItems.flatMap((pending) => pending.kind === "setup_override_set"
      && !config.setup_overrides.some((item) => item.sku === pending.value.sku && item.machine === pending.value.machine)
      ? [{ item: pending.value, state: "added" as const }]
      : []),
  ];
  const toggleSetupOverride = (item: SetupOverride, state: "saved" | "edited" | "added" | "removed") => {
    const id = `setup_override:${item.sku}|${item.machine}`;
    if (state === "saved") stage({ kind: "setup_override_remove", sku: item.sku, machine: item.machine });
    else unstage(id);
  };
  const twinRows = [
    ...config.twins.map((twin) => ({
      twin,
      state: draftById.get(`twin:${twin.tool_id}`)?.kind === "twin_remove" ? "removed" as const : "saved" as const,
    })),
    ...draftItems.flatMap((item) => item.kind === "twin_add" && !config.twins.some((twin) => twin.tool_id === item.value.tool_id)
      ? [{ twin: item.value, state: "added" as const }]
      : []),
  ];
  const draftStateBadge = (state: "saved" | "edited" | "added" | "removed") => state === "saved" ? null : (
    <span style={{ color: state === "removed" ? T.red : T.blue, fontSize: 10, fontWeight: 700, marginLeft: 6, fontFamily: T.sans }}>
      {state === "removed" ? "A remover" : state === "added" ? "Nova" : "Editada"}
    </span>
  );
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
      <ConfigPendingBar
        lines={draftLines}
        busy={draftApplying || saving}
        disabled={readOnly || pendingReplan !== null}
        onRemove={unstage}
        onApply={() => void applyDraft()}
        onDiscard={discardDraft}
      />

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
                  {!activeReplanJobId && <RefusalDetails causes={replanCauses} />}
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

      {/* ── TURNOS (each edit goes to the pending list) ───────── */}
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
              {(shiftEdits ?? config.shifts).map((s, index) => {
                const edit = (update: (shift: FactoryConfig["shifts"][number]) => void) => {
                  const next = [...(shiftEdits ?? config.shifts)].map((item) => ({ ...item }));
                  update(next[index]);
                  next[index].duration_min = Math.max(0, next[index].end_min - next[index].start_min);
                  stageShifts(next);
                };
                return (
                <tr key={s.id}>
                  <td style={tdStyle}>{s.id}</td>
                  <td style={{ ...tdStyle, fontFamily: T.sans }}>
                    <input
                      value={s.label}
                      disabled={locked}
                      onChange={(event) => edit((shift) => { shift.label = event.target.value; })}
                      style={{ ...inputStyle, width: 130 }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <input
                      type="time"
                      disabled={locked}
                      value={shiftTime(s.start_min)}
                      onChange={(event) => {
                        const [hours, minutes] = event.target.value.split(":").map(Number);
                        if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return;
                        edit((shift) => { shift.start_min = hours * 60 + minutes; });
                      }}
                      style={{ ...inputStyle, width: 105 }}
                    />
                  </td>
                  <td style={tdStyle}>
                    <input
                      type="time"
                      disabled={locked}
                      value={shiftTime(s.end_min)}
                      onChange={(event) => {
                        const [hours, minutes] = event.target.value.split(":").map(Number);
                        if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return;
                        let value = hours * 60 + minutes;
                        if (value === 0) value = 1440;
                        edit((shift) => { shift.end_min = value; });
                      }}
                      style={{ ...inputStyle, width: 105 }}
                    />
                  </td>
                  <td style={tdStyle}>{Math.max(0, s.end_min - s.start_min)}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {/* ── MAQUINAS (toggle activa) ───────────────────────────── */}
      {section === "maquinas" && (
        <div style={{ display: "grid", gap: 10 }}>
        <Card>
          <Label>Adicionar máquina</Label>
          <div style={{ color: T.secondary, fontSize: 11, margin: "4px 0 10px" }}>
            Podes adicionar várias. Máquinas existentes não são apagadas: podem ser desativadas para manter o histórico.
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}>
            <label style={{ display: "grid", gap: 4 }}>
              <span style={{ color: T.tertiary, fontSize: 10 }}>Identificador</span>
              <input
                value={newMachine.id}
                disabled={locked}
                onKeyDown={(event) => { if (event.key === "Enter") stageMachineAddition(); }}
                onChange={(event) => setNewMachine({ ...newMachine, id: event.target.value.toUpperCase() })}
                placeholder="Ex.: PRM044"
                style={{ ...inputStyle, width: 130, textAlign: "left" }}
              />
            </label>
            <label style={{ display: "grid", gap: 4 }}>
              <span style={{ color: T.tertiary, fontSize: 10 }}>Grupo</span>
              <select
                value={newMachine.group}
                disabled={locked}
                onChange={(event) => setNewMachine({ ...newMachine, group: event.target.value })}
                style={{ ...inputStyle, width: 130, textAlign: "left" }}
              >
                <option value="Grandes">Grandes</option>
                <option value="Medias">Médias</option>
              </select>
            </label>
            <button
              disabled={locked || !newMachine.id.trim()}
              onClick={stageMachineAddition}
              style={{ ...btnStyle, color: T.blue, opacity: locked || !newMachine.id.trim() ? 0.5 : 1 }}
            >
              Adicionar à lista
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
                      disabled={locked}
                      aria-label={`Grupo da máquina ${id}`}
                      onChange={(event) => {
                        const value = event.target.value;
                        if (value === m.group) unstage(`machine_group:${id}`);
                        else stage({ kind: "machine_group", machine: id, value });
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
                      disabled={locked}
                      value={id in oeeEdits ? oeeEdits[id] ?? "" : m.oee ?? ""}
                      placeholder={String(config.oee_default)}
                      aria-label={`OEE da máquina ${id}`}
                      onChange={(e) => {
                        const raw = e.target.value.trim();
                        const value = raw === "" ? null : Number(raw);
                        if (value !== null && !Number.isFinite(value)) return;
                        if (value === m.oee) unstage(`machine_oee:${id}`);
                        else stage({ kind: "machine_oee", machine: id, value });
                      }}
                      style={{ ...inputStyle, width: 78 }}
                    />
                    <span style={{ marginLeft: 6, color: T.tertiary, fontSize: 10 }}>
                      {m.oee === null ? "base" : ""}
                    </span>
                  </td>
                  <td style={tdStyle}>
                    <button
                      disabled={locked}
                      aria-pressed={effectiveActive}
                      aria-label={`Máquina ${id} ativa`}
                      onClick={() => {
                        const next = !effectiveActive;
                        if (next === m.active) unstage(`machine_active:${id}`);
                        else stage({ kind: "machine_active", machine: id, value: next });
                      }}
                      style={{
                        background: effectiveActive ? T.green + "22" : T.red + "22",
                        border: `1px solid ${effectiveActive ? T.green : T.red}`,
                        borderRadius: 6, padding: "2px 10px", cursor: "pointer",
                        fontSize: 11, color: effectiveActive ? T.green : T.red, fontFamily: "inherit",
                        opacity: locked ? 0.5 : 1,
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
                        disabled={locked}
                        aria-label={`Máquina alternativa de ${id}`}
                        onChange={(e) => stageToolField(id, "alt", e.target.value || null, t.alt ?? null)}
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
                        disabled={locked}
                        aria-label={`Setup de ${id} em horas`}
                        value={editState?.setup_hours ?? t.setup_hours}
                        onChange={(event) => {
                          const value = Number(event.target.value);
                          if (!Number.isFinite(value)) return;
                          stageToolField(id, "setup_hours", value, t.setup_hours);
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
                  disabled={locked}
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
                  disabled={locked}
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
                  disabled={locked}
                  value={setupOverride.hours}
                  onChange={(e) => setSetupOverride({ ...setupOverride, hours: Number(e.target.value) })}
                  style={{ ...inputStyle, width: 100 }}
                />
              </label>
              <button
                disabled={locked || !setupOverride.sku || !setupOverride.machine || !(setupOverride.hours > 0) || setupOverride.hours > 8}
                onClick={() => {
                  stage({ kind: "setup_override_set", value: { ...setupOverride } });
                  setSetupOverride({ sku: "", machine: "", hours: 0.5 });
                }}
                style={{
                  ...btnStyle,
                  color: T.blue,
                  borderColor: T.blue + "50",
                  opacity: locked || !setupOverride.sku || !setupOverride.machine ? 0.5 : 1,
                }}
              >
                Adicionar à lista
              </button>
            </div>
          </Card>

          <Card style={{ padding: 0, overflow: "hidden" }}>
            {setupOverrideRows.length === 0 ? (
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
                  {setupOverrideRows.map(({ item, state }) => (
                    <tr key={`${item.sku}-${item.machine}`} style={{ opacity: state === "removed" ? 0.55 : 1 }}>
                      <td style={tdStyle}>{item.sku}{draftStateBadge(state)}</td>
                      <td style={tdStyle}>{item.machine}</td>
                      <td style={tdStyle}>{item.hours} h</td>
                      <td style={tdStyle}>
                        <button
                          disabled={locked}
                          aria-label={`${state === "saved" ? "Remover" : "Desfazer"} exceção ${item.sku} ${item.machine}`}
                          title={state === "saved" ? "Remover" : "Desfazer"}
                          onClick={() => toggleSetupOverride(item, state)}
                          style={{ background: "none", border: "none", color: state === "saved" ? T.red : T.blue, cursor: "pointer" }}
                        >
                          {state === "saved" ? "×" : "↶"}
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

      {/* ── GEMEAS (add/remove go to the pending list) ─────────── */}
      {section === "gemeas" && (
        <>
          <Card style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ padding: "12px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <Label>Pecas Gemeas ({config.twins.length})</Label>
              <button disabled={locked} onClick={() => setTwinModal(true)} style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}>
                + Adicionar
              </button>
            </div>
            {twinRows.length === 0 ? (
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
                  {twinRows.map(({ twin: tw, state }) => (
                    <tr key={tw.tool_id} style={{ opacity: state === "removed" ? 0.55 : 1 }}>
                      <td style={tdStyle}>{tw.tool_id}{draftStateBadge(state)}</td>
                      <td style={tdStyle}>{tw.sku_a}</td>
                      <td style={tdStyle}>{tw.sku_b}</td>
                      <td style={tdStyle}>
                        <button
                          disabled={locked}
                          aria-label={`${state === "saved" ? "Remover" : "Desfazer"} gémeas ${tw.tool_id}`}
                          title={state === "saved" ? "Remover" : "Desfazer"}
                          onClick={() => {
                            if (state === "saved") stage({ kind: "twin_remove", tool_id: tw.tool_id });
                            else unstage(`twin:${tw.tool_id}`);
                          }}
                          style={{ background: "none", border: "none", color: state === "saved" ? T.red : T.blue, cursor: "pointer", fontSize: 14, fontFamily: "inherit", opacity: locked ? 0.5 : 1 }}
                        >
                          {state === "saved" ? "×" : "↶"}
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
                      aria-label={field === "tool_id" ? "Ferramenta" : field === "sku_a" ? "Referência A" : "Referência B"}
                      value={twinForm[field]}
                      onChange={(e) => setTwinForm({ ...twinForm, [field]: e.target.value })}
                      style={{ ...inputStyle, width: "100%", textAlign: "left" }}
                      placeholder={field === "tool_id" ? "BFP001" : "SKU..."}
                    />
                  </div>
                ))}
                <button
                  disabled={!twinForm.tool_id || !twinForm.sku_a || !twinForm.sku_b || locked}
                  onClick={() => {
                    const value = {
                      tool_id: twinForm.tool_id.trim(),
                      sku_a: twinForm.sku_a.trim(),
                      sku_b: twinForm.sku_b.trim(),
                    };
                    stage({ kind: "twin_add", value });
                    setTwinForm({ tool_id: "", sku_a: "", sku_b: "" });
                    setTwinModal(false);
                  }}
                  style={saveBtnStyle(!!twinForm.tool_id && !!twinForm.sku_a && !!twinForm.sku_b, locked)}
                >
                  Adicionar à lista
                </button>
              </div>
            </Modal>
          )}
        </>
      )}

      {/* ── OPERADORES (each edit goes to the pending list) ───── */}
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
                      disabled={locked}
                      aria-label={`Operadores ${key}`}
                      value={key in opEdits ? opEdits[key] : count}
                      onChange={(e) => {
                        const val = parseInt(e.target.value, 10);
                        if (isNaN(val) || val < 0) return;
                        if (val === count) unstage(`operators:${key}`);
                        else stage({ kind: "operators", key, value: val });
                      }}
                      style={{ ...inputStyle, width: 70, borderColor: key in opEdits ? T.blue : T.border }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
                    disabled={locked}
                    value={crewEdits[setupGroup] ?? count}
                    onChange={(event) => {
                      const raw = Number(event.target.value);
                      if (!Number.isFinite(raw)) return;
                      const value = Math.max(1, Math.trunc(raw));
                      if (value === count) unstage(`setup_crews:${setupGroup}`);
                      else stage({ kind: "setup_crews", group: setupGroup, value });
                    }}
                    style={{ ...inputStyle, width: 70, borderColor: setupGroup in crewEdits ? T.blue : T.border }}
                  />
                </label>
              ))}
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
                  disabled={locked}
                  value={newHoliday}
                  onChange={(e) => setNewHoliday(e.target.value)}
                  style={{ ...inputStyle, width: 160, textAlign: "left" }}
                />
              </label>
              <button
                disabled={!newHoliday || locked}
                onClick={() => {
                  if (stageHolidays("holiday_add", newHoliday)) setNewHoliday("");
                }}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50", opacity: !newHoliday || locked ? 0.5 : 1 }}
              >
                Adicionar dia
              </button>
              <div aria-hidden="true" style={{ width: 1, height: 32, background: T.border }} />
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>De</span>
                <input
                  type="date"
                  disabled={locked}
                  value={holidayRange.from}
                  onChange={(e) => setHolidayRange({ ...holidayRange, from: e.target.value })}
                  style={{ ...inputStyle, width: 150, textAlign: "left" }}
                />
              </label>
              <label style={{ display: "grid", gap: 4 }}>
                <span style={{ color: T.tertiary, fontSize: 10 }}>Até</span>
                <input
                  type="date"
                  disabled={locked}
                  value={holidayRange.to}
                  onChange={(e) => setHolidayRange({ ...holidayRange, to: e.target.value })}
                  style={{ ...inputStyle, width: 150, textAlign: "left" }}
                />
              </label>
              <button
                disabled={!holidayRange.from || !holidayRange.to || locked}
                onClick={() => {
                  if (stageHolidays("holiday_add", holidayRange.from, holidayRange.to)) setHolidayRange({ from: "", to: "" });
                }}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}
              >
                Adicionar intervalo
              </button>
              <button
                disabled={!holidayRange.from || !holidayRange.to || locked}
                onClick={() => {
                  if (stageHolidays("holiday_remove", holidayRange.from, holidayRange.to)) setHolidayRange({ from: "", to: "" });
                }}
                style={{ ...btnStyle, color: T.red, borderColor: T.red + "50" }}
              >
                Reabrir intervalo
              </button>
            </div>
            <Divider />
            {holidayChips.length === 0 ? (
              <div style={{ color: T.secondary, fontSize: 13 }}>Sem feriados ou férias configurados.</div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {holidayChips.map(({ date: h, state }) => (
                  <span key={h} style={{
                    fontSize: 12, fontFamily: T.mono, color: T.primary,
                    background: T.elevated, padding: "4px 10px", borderRadius: 6,
                    display: "flex", alignItems: "center", gap: 6,
                    border: `1px solid ${state === "saved" ? "transparent" : state === "removed" ? T.red : T.blue}`,
                    textDecoration: state === "removed" ? "line-through" : "none",
                  }}>
                    {h}
                    <button
                      disabled={locked}
                      aria-label={state === "saved" ? `Remover dia sem produção ${h}` : `Desfazer ${h}`}
                      title={state === "saved" ? "Remover" : "Desfazer"}
                      onClick={() => {
                        if (state === "removed") stageHolidays("holiday_add", h);
                        else removeHolidayChip(h);
                      }}
                      style={{ background: "none", border: "none", color: state === "saved" ? T.red : T.blue, cursor: "pointer", fontSize: 13, fontFamily: "inherit", padding: 0, opacity: locked ? 0.5 : 1 }}
                    >
                      {state === "saved" ? "×" : "↶"}
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
                disabled={locked}
                aria-label="Dia extra de produção"
                value={extraWorkday}
                onChange={(e) => setExtraWorkday(e.target.value)}
                style={{ ...inputStyle, width: 160, textAlign: "left" }}
              />
              <button
                disabled={!extraWorkday || locked}
                onClick={() => {
                  toggleExtraDay(extraWorkday, true);
                  setExtraWorkday("");
                }}
                style={{ ...btnStyle, color: T.blue, borderColor: T.blue + "50" }}
              >
                Abrir dia
              </button>
              {extraDayChips.map(({ date, state }) => (
                <span key={date} style={{
                  ...btnStyle, cursor: "default", fontFamily: T.mono,
                  borderColor: state === "saved" ? T.border : state === "removed" ? T.red : T.blue,
                  textDecoration: state === "removed" ? "line-through" : "none",
                }}>
                  {date}
                  <button
                    disabled={locked}
                    aria-label={state === "saved" ? `Remover dia de trabalho extra ${date}` : `Desfazer ${date}`}
                    onClick={() => {
                      if (state === "saved") toggleExtraDay(date, false);
                      else unstage(`extra_day:${date}`);
                    }}
                    style={{ background: "none", border: "none", color: state === "saved" ? T.red : T.blue, cursor: "pointer", marginLeft: 8 }}
                  >
                    {state === "saved" ? "×" : "↶"}
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
              Cada indisponibilidade entra na lista de alterações no topo da página. O plano só muda depois de Aplicar.
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
                {unavailabilityEditTarget ? "Atualizar na lista" : "Adicionar à lista"}
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
                          title={entry.draftState === "removed" ? "Desfazer remoção" : entry.draftState === "added" ? "Retirar da lista" : "Remover"}
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
          </Card>
        </div>
      )}

      {/* ── PARAMETROS ─────────────────────────────────────────── */}
      {section === "parametros" && (
        <ParametrosEditor config={config} items={draftItems} stage={stage} unstage={unstage} locked={locked} />
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
              items={draftItems}
              stage={stage}
              unstage={unstage}
              locked={locked}
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
            items={draftItems}
            stage={stage}
            unstage={unstage}
            locked={locked}
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

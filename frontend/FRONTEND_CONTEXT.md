# ProdPlan PP1 — Frontend Context (para Claude AI)

Sistema APS industrial. React 19 + TypeScript + Zustand + Vite.
Dark theme Apple-inspired. Zero CSS files — tudo inline styles com objecto `T` (tokens).
9 páginas, 9 UI components, 3 stores Zustand, ~30 endpoints API.

---

## ESTRUTURA DE FICHEIROS

```
frontend/src/
├── theme/tokens.ts              — Design tokens (cores, fonts, radius)
├── constants/thresholds.ts      — KPI thresholds
├── api/
│   ├── client.ts                — Fetch wrapper
│   ├── endpoints.ts             — ~30 endpoints tipados
│   └── types.ts                 — Interfaces TS (467 linhas)
├── stores/
│   ├── useAppStore.ts           — Estado UI global
│   ├── useDataStore.ts          — Dados scheduling
│   └── useSimulatorStore.ts     — Estado simulações
├── components/
│   ├── Shell.tsx                — Layout master
│   ├── Sidebar.tsx              — Navegação
│   ├── ChatPanel.tsx            — Copilot chat
│   └── ui/
│       ├── Card.tsx
│       ├── Modal.tsx
│       ├── ProgressBar.tsx
│       ├── Label.tsx
│       ├── Num.tsx
│       ├── Pill.tsx
│       ├── Dot.tsx
│       ├── Divider.tsx
│       └── UploadZone.tsx
├── pages/
│   ├── ConsolePage.tsx          — Dashboard (314 linhas)
│   ├── GanttPage.tsx            — Gantt interactivo (1130 linhas)
│   ├── StockPage.tsx            — Grid stock (415 linhas)
│   ├── RiskPage.tsx             — Risco + workforce (345 linhas)
│   ├── ExpeditionPage.tsx       — Expedições (231 linhas)
│   ├── SimulatorPage.tsx        — What-if + CTP (464 linhas)
│   ├── ConfigPage.tsx           — Master data CRUD (762 linhas)
│   ├── JournalPage.tsx          — Logs (44 linhas)
│   └── RulesPage.tsx            — Regras scheduler (99 linhas)
├── App.tsx
└── main.tsx
```

---

## 1. DESIGN TOKENS — `src/theme/tokens.ts`

```ts
/** Apple-inspired dark industrial palette */
export const T = {
  bg: "#000000",
  card: "#0D0D0D",
  elevated: "#161616",
  hover: "#1C1C1E",
  border: "rgba(255,255,255,0.06)",
  borderHover: "rgba(255,255,255,0.12)",

  primary: "#F5F5F7",
  secondary: "#86868B",
  tertiary: "#48484A",

  blue: "#0A84FF",
  green: "#30D158",
  orange: "#FF9F0A",
  red: "#FF453A",
  purple: "#BF5AF2",
  yellow: "#FFD60A",
  teal: "#64D2FF",

  radius: 14,
  radiusSm: 10,

  mono: "ui-monospace,'SF Mono','Menlo','Consolas',monospace",
  sans: "-apple-system,'SF Pro Display','SF Pro Text','Helvetica Neue',sans-serif",
} as const;

/** Tool-id to color */
const TOOL_COLORS = [
  "#0A84FF", "#30D158", "#FF9F0A", "#FF453A", "#BF5AF2",
  "#64D2FF", "#FF6482", "#FFD60A", "#AC8E68", "#5E5CE6",
];

export function toolColor(toolId: string): string {
  const n = parseInt(toolId.replace(/\D/g, ""), 10) || 0;
  return TOOL_COLORS[n % TOOL_COLORS.length];
}
```

---

## 2. KPI THRESHOLDS — `src/constants/thresholds.ts`

```ts
export const TH = {
  OTD_GREEN: 98,
  OTD_D_GREEN: 95,
  FILL_GREEN: 95,
  FILL_ORANGE: 80,
  UTIL_RED: 95,
  UTIL_ORANGE: 85,
  UTIL_BLUE: 70,
  TRUST_GREEN: 80,
} as const;
```

---

## 3. GLOBAL STYLES — `index.html`

```html
<!doctype html>
<html lang="pt">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PP1 — ProdPlan</title>
    <style>
      *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
      html, body, #root { height: 100%; }
      body {
        background: #000000;
        color: rgba(255,255,255,0.92);
        font-family: -apple-system,'SF Pro Display','SF Pro Text','Helvetica Neue',sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
      }
      ::-webkit-scrollbar { width: 6px; height: 6px; }
      ::-webkit-scrollbar-track { background: transparent; }
      ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
      ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
      input, button, textarea, select { font: inherit; }
      a { color: inherit; text-decoration: none; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

---

## 4. API CLIENT — `src/api/client.ts`

```ts
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json();
}

export async function get<T>(url: string): Promise<T> {
  return request<T>(url);
}

export async function post<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, { method: "POST", body: JSON.stringify(body) });
}

export async function put<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, { method: "PUT", body: JSON.stringify(body) });
}

export async function del<T>(url: string): Promise<T> {
  return request<T>(url, { method: "DELETE" });
}

export async function upload<T>(url: string, file: File, params?: Record<string, string>): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  if (params) {
    for (const [k, v] of Object.entries(params)) form.append(k, v);
  }
  const res = await fetch(url, { method: "POST", body: form });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json();
}
```

---

## 5. API TYPES — `src/api/types.ts`

```ts
// ── Core ─────────────────────────────────────────────────────

export interface Score {
  otd: number;
  otd_d: number;
  tardy_count: number;
  setups: number;
  earliness_avg_days: number;
  utilization_avg: number;
  utilization_balance: number;
  weighted_score: number;
  [key: string]: unknown;
}

export interface Segment {
  lot_id: string;
  run_id: string;
  machine_id: string;
  tool_id: string;
  day_idx: number;
  start_min: number;
  end_min: number;
  shift: string;
  qty: number;
  prod_min: number;
  setup_min: number;
  is_continuation: boolean;
  edd: number;
  sku: string;
  twin_outputs: [string, string, number][] | null;
}

export interface Lot {
  id: string;
  op_id: string;
  tool_id: string;
  machine_id: string;
  alt_machine_id: string | null;
  qty: number;
  prod_min: number;
  setup_min: number;
  edd: number;
  is_twin: boolean;
  twin_outputs: [string, string, number][] | null;
}

export interface TrustIndex {
  score: number;
  gate: string;
  n_ops: number;
  n_issues: number;
  dimensions: { name: string; score: number; details: string[] }[];
}

// ── Analytics ────────────────────────────────────────────────

export interface StockDayCompact {
  day: number;
  date: string;
  stock: number;
  demand: number;
  produced: number;
  workday: boolean;
  is_buffer?: boolean;
}

export interface StockSummary {
  op_id: string;
  sku: string;
  client: string;
  machine: string;
  tool: string;
  initial_stock: number;
  stockout_day: number | null;
  coverage_days: number;
  total_demand: number;
  total_produced: number;
  days: StockDayCompact[];
}

export interface StockDay {
  day_idx: number;
  date: string;
  demand: number;
  produced: number;
  cum_demand: number;
  cum_produced: number;
  stock: number;
  machine: string | null;
  is_buffer?: boolean;
}

export interface StockProjection extends Omit<StockSummary, "days"> {
  days: StockDay[];
}

export interface ExpeditionEntry {
  client: string;
  sku: string;
  order_qty: number;
  produced_qty: number;
  shortfall: number;
  status: string;
  coverage_pct: number;
}

export interface ExpeditionDay {
  day_idx: number;
  date: string;
  total: number;
  ready: number;
  partial: number;
  not_planned: number;
  entries: ExpeditionEntry[];
}

export interface ExpeditionKPIs {
  fill_rate: number;
  at_risk_count: number;
  days: ExpeditionDay[];
}

export interface OrderTracking {
  sku: string;
  order_qty: number;
  delivery_day: number;
  delivery_date: string;
  status: string;
  production_machine: string | null;
  days_early: number | null;
  reason: string;
  [key: string]: unknown;
}

export interface ClientOrders {
  client: string;
  total_orders: number;
  total_ready: number;
  orders: OrderTracking[];
}

export interface ClientCoverage {
  client: string;
  total_orders: number;
  covered_orders: number;
  coverage_pct: number;
  at_risk_orders: number;
  worst_sku: string | null;
}

export interface CoverageAudit {
  overall_coverage_pct: number;
  overall_fill_rate: number;
  clients: ClientCoverage[];
  stockout_count: number;
  health_score: number;
  summary: string;
}

export interface LotRisk {
  lot_id: string;
  sku: string;
  machine_id: string;
  edd: number;
  slack: number;
  risk_level: string;
  [key: string]: unknown;
}

export interface HeatmapCell {
  machine_id: string;
  day_idx: number;
  utilization: number;
  risk_level: string;
}

export interface RiskResult {
  health_score: number;
  lot_risks: LotRisk[];
  machine_risks: unknown[];
  heatmap: HeatmapCell[];
  critical_count: number;
  top_risks: LotRisk[];
  bottleneck: string | null;
}

export interface TardyAnalysis {
  lot_id: string;
  sku: string;
  machine_id: string;
  edd: number;
  completion_day: number;
  delay_days: number;
  root_cause: string;
  suggestion: string;
}

export interface LateDeliveryReport {
  tardy_count: number;
  avg_delay: number;
  by_cause: Record<string, number>;
  analyses: TardyAnalysis[];
  worst_machine: string | null;
  suggestion: string;
}

export interface DayForecast {
  day_idx: number;
  date: string;
  shift: string;
  machine_group: string;
  required: number;
  available: number;
  surplus_or_deficit: number;
}

export interface WorkforceForecast {
  window_days: number;
  daily: DayForecast[];
  peak_day: number;
  peak_required: number;
  avg_required: number;
  deficit_days: number;
  trend: string;
  summary: string;
}

// ── Config / Master Data ─────────────────────────────────────

export interface ShiftConfig {
  id: string;
  start_min: number;
  end_min: number;
  duration_min: number;
  label: string;
}

export interface ToolConfig {
  primary: string;
  alt: string | null;
  setup_hours: number;
}

export interface TwinConfig {
  tool_id: string;
  sku_a: string;
  sku_b: string;
}

export interface FactoryConfig {
  name: string;
  site: string;
  timezone: string;
  shifts: ShiftConfig[];
  day_capacity_min: number;
  machines: Record<string, { group: string; active: boolean }>;
  tools: Record<string, ToolConfig>;
  twins: TwinConfig[];
  operators: Record<string, number>;
  holidays: string[];
  oee_default: number;
  jit_enabled: boolean;
  jit_buffer_pct: number;
  jit_threshold: number;
  max_run_days: number;
  max_edd_gap: number;
  edd_swap_tolerance: number;
  campaign_window: number;
  urgency_threshold: number;
  interleave_enabled: boolean;
  weight_earliness: number;
  weight_setups: number;
  weight_balance: number;
  eco_lot_mode: string;
}

export interface EOp {
  id: string;
  sku: string;
  client: string;
  designation: string;
  machine: string;
  tool: string;
  alt_machine: string | null;
  pcs_hour: number;
  setup_hours: number;
  eco_lot: number;
  stock: number;
  oee: number;
  backlog: number;
  operators: number;
  demand: number[];
}

// ── Console ──────────────────────────────────────────────────

export interface ConsoleAction {
  severity: string;
  title: string;
  detail: string;
  suggestion: string | null;
  machine_id: string | null;
  deadline: number | null;
  client: string | null;
  category: string | null;
}

export interface ConsoleMachine {
  machine_id: string;
  group: string;
  utilization_pct: number;
  current_tool: string | null;
  current_sku: string | null;
  runs: { tool_id: string; sku: string; qty: number; prod_min: number }[];
  next_setup_at: number | null;
  eta_current: number | null;
  total_pcs: number;
}

export interface ConsoleExpedition {
  client: string;
  ready: number;
  partial: number;
  not_ready: number;
  total: number;
}

export interface ConsoleSummaryLine {
  text: string;
  color: "red" | "orange" | "green" | "default";
}

export interface TomorrowSetup {
  time: string;
  machine: string;
  from_tool: string | null;
  to_tool: string;
  duration_min: number;
  already_mounted: boolean;
}

export interface TomorrowOperator {
  shift: string;
  group: string;
  required: number;
  available: number;
  deficit: number;
}

export interface TomorrowPrep {
  date: string | null;
  setups: TomorrowSetup[];
  operators: TomorrowOperator[];
  expeditions_summary: string | null;
  problems: string[];
  ok: boolean;
}

export interface ConsoleData {
  state: { color: string; phrase: string };
  actions: ConsoleAction[];
  machines: ConsoleMachine[];
  expedition: ConsoleExpedition[];
  tomorrow: TomorrowPrep | null;
  summary: ConsoleSummaryLine[];
}

// ── Actions ──────────────────────────────────────────────────

export interface MutationInput {
  type: string;
  params: Record<string, unknown>;
}

export interface DeltaReport {
  otd_before: number;
  otd_after: number;
  otd_d_before: number;
  otd_d_after: number;
  setups_before: number;
  setups_after: number;
  earliness_before: number;
  earliness_after: number;
  tardy_before: number;
  tardy_after: number;
}

export interface SimulateResponse {
  score_baseline: Score;
  score_scenario: Score;
  delta: DeltaReport;
  time_ms: number;
  summary: string[];
}

export interface SimulateApplyResponse {
  status: string;
  score: Score;
  score_previous: Score;
  summary: string[];
  n_segments_before: number;
  n_segments_after: number;
  time_ms: number;
  can_revert: boolean;
}

export interface CTPResult {
  sku: string;
  qty_requested: number;
  feasible: boolean;
  latest_day: number | null;
  earliest_end_day: number | null;
  machine: string | null;
  confidence: string;
  slack_min: number;
  reason: string;
  date_start: string | null;
  date_end: string | null;
  required_min: number;
  prod_days: number;
}

export interface LearningInfo {
  optimized: boolean;
  n_trials: number;
  confidence: string;
  improvement: { reward: number; earliness_delta: number; setups_delta: number };
  total_time_ms: number;
  best_params: Record<string, unknown>;
}

export interface LoadResponse {
  status: string;
  n_ops: number;
  n_segments: number;
  score: Score;
  time_ms: number;
  trust_index: { score: number; gate: string };
  journal_summary: { total: number; warnings: number } | null;
  learning: LearningInfo | null;
}

export interface ChatResponse {
  response: string;
  widgets: unknown[];
  tools_used: number;
}

export interface MasterDataResult {
  status: string;
  score: Score;
  score_anterior: Score;
  [key: string]: unknown;
}

export interface JournalEntry {
  step: string;
  severity: string;
  message: string;
  metadata?: Record<string, unknown>;
  elapsed_ms: number;
}
```

---

## 6. API ENDPOINTS — `src/api/endpoints.ts`

```ts
import { get, post, put, del, upload } from "./client";
import type {
  ChatResponse, ClientOrders, ConsoleData, CoverageAudit, CTPResult, EOp,
  ExpeditionKPIs, FactoryConfig, JournalEntry, LateDeliveryReport, LearningInfo,
  LoadResponse, Lot, MasterDataResult, MutationInput, RiskResult, Score, Segment,
  SimulateApplyResponse, SimulateResponse, StockProjection, StockSummary, TrustIndex,
  WorkforceForecast,
} from "./types";

// ── Core
export const getToday = () => get<{ today_idx: number; date: string }>("/api/data/today");
export const getWorkdays = () => get<string[]>("/api/data/workdays");
export const getScore = () => get<Score>("/api/data/score");
export const getSegments = () => get<Segment[]>("/api/data/segments");
export const getLots = () => get<Lot[]>("/api/data/lots");
export const getTrust = () => get<TrustIndex>("/api/data/trust");
export const getJournal = () => get<JournalEntry[]>("/api/data/journal");
export const getLearning = () => get<LearningInfo | null>("/api/data/learning");

// ── Analytics
export const getStockSummary = () => get<StockSummary[]>("/api/data/stock");
export const getStockDetail = (sku: string) => get<StockProjection>(`/api/data/stock/${encodeURIComponent(sku)}`);
export const getExpedition = () => get<ExpeditionKPIs>("/api/data/expedition");
export const getOrders = () => get<ClientOrders[]>("/api/data/orders");
export const getCoverage = () => get<CoverageAudit>("/api/data/coverage");
export const getRisk = () => get<RiskResult>("/api/data/risk");
export const getLateDeliveries = () => get<LateDeliveryReport>("/api/data/late");
export const getWorkforce = (window = 10) => get<WorkforceForecast>(`/api/data/workforce?window=${window}`);

// ── Config / Master Data
export const getConfig = () => get<FactoryConfig>("/api/data/config");
export const updateConfig = (updates: Record<string, unknown>) => put<{ status: string; changed: string[]; score: Score }>("/api/data/config", updates);
export const getOps = () => get<EOp[]>("/api/data/ops");
export const getRules = () => get<{ id: string; tipo: string; descricao: string }[]>("/api/data/rules");

// ── Master Data Mutations
export const editMachine = (mid: string, updates: Record<string, unknown>) => put<MasterDataResult>(`/api/data/machines/${encodeURIComponent(mid)}`, updates);
export const editTool = (tid: string, updates: Record<string, unknown>) => put<MasterDataResult>(`/api/data/tools/${encodeURIComponent(tid)}`, updates);
export const updateOperators = (ops: Record<string, number>) => put<MasterDataResult>("/api/data/operators", ops);
export const addHoliday = (date: string) => post<MasterDataResult>("/api/data/holidays", { data: date });
export const removeHoliday = (date: string) => del<MasterDataResult>(`/api/data/holidays/${encodeURIComponent(date)}`);
export const addTwin = (tool_id: string, sku_a: string, sku_b: string) => post<MasterDataResult>("/api/data/twins", { tool_id, sku_a, sku_b });
export const removeTwin = (tool_id: string) => del<MasterDataResult>(`/api/data/twins/${encodeURIComponent(tool_id)}`);
export const applyPreset = (name: string) => post<{ status: string; changed: string[]; score: Score }>(`/api/data/presets/${name}`, {});

// ── Console
export const getConsole = (dayIdx = 0) => get<ConsoleData>(`/api/console?day_idx=${dayIdx}`);

// ── Actions
export const simulate = (mutations: MutationInput[]) => post<SimulateResponse>("/api/data/simulate", { mutations });
export const simulateApply = (mutations: MutationInput[]) => post<SimulateApplyResponse>("/api/data/simulate-apply", { mutations });
export const revertSimulation = () => post<{ status: string; score: Score }>("/api/data/revert", {});
export const canRevert = () => get<{ can_revert: boolean }>("/api/data/can-revert");
export const checkCTP = (sku: string, qty: number, deadline: number) => post<CTPResult>("/api/data/ctp", { sku, qty, deadline });
export const applyCTP = (sku: string, qty: number, deadline: number) => post<SimulateApplyResponse>("/api/data/ctp-apply", { sku, qty, deadline });
export const recalculate = () => post<{ status: string; score: Score; score_previous: Score; time_ms: number; n_segments: number }>("/api/data/recalculate", {});

// ── Upload
export const uploadISOP = (file: File) => upload<LoadResponse>("/api/data/load", file);

// ── Chat
export const chatCopilot = (messages: { role: string; content: string }[]) => post<ChatResponse>("/api/copilot/chat", { messages });
```

---

## 7. STORES

### `src/stores/useAppStore.ts`

```ts
import { create } from "zustand";

interface AppState {
  activePage: string;
  chatOpen: boolean;
  hasData: boolean;
  isUploading: boolean;
  trustScore: number | null;
  trustGate: string | null;
  setPage: (page: string) => void;
  toggleChat: () => void;
  setHasData: (v: boolean) => void;
  setUploading: (v: boolean) => void;
  setTrust: (score: number, gate: string) => void;
}

export const useAppStore = create<AppState>((set) => ({
  activePage: "console",
  chatOpen: false,
  hasData: false,
  isUploading: false,
  trustScore: null,
  trustGate: null,
  setPage: (page) => set({ activePage: page }),
  toggleChat: () => set((s) => ({ chatOpen: !s.chatOpen })),
  setHasData: (v) => set({ hasData: v }),
  setUploading: (v) => set({ isUploading: v }),
  setTrust: (score, gate) => set({ trustScore: score, trustGate: gate }),
}));
```

### `src/stores/useDataStore.ts`

```ts
import { create } from "zustand";
import { getScore, getSegments, getLots, getConfig, getLearning, simulateApply, revertSimulation } from "../api/endpoints";
import type { Score, Segment, Lot, FactoryConfig, LearningInfo, MutationInput, SimulateApplyResponse } from "../api/types";

interface DataState {
  score: Score | null;
  segments: Segment[] | null;
  lots: Lot[] | null;
  config: FactoryConfig | null;
  learning: LearningInfo | null;
  isSimulated: boolean;
  simulationSummary: string[];
  canRevert: boolean;
  refreshAll: () => Promise<void>;
  applySimulation: (mutations: MutationInput[]) => Promise<SimulateApplyResponse>;
  revert: () => Promise<void>;
  clear: () => void;
}

export const useDataStore = create<DataState>((set, get) => ({
  score: null, segments: null, lots: null, config: null, learning: null,
  isSimulated: false, simulationSummary: [], canRevert: false,

  refreshAll: async () => {
    const results = await Promise.allSettled([getScore(), getSegments(), getLots(), getConfig(), getLearning()]);
    set({
      score: results[0].status === "fulfilled" ? results[0].value : null,
      segments: results[1].status === "fulfilled" ? results[1].value : null,
      lots: results[2].status === "fulfilled" ? results[2].value : null,
      config: results[3].status === "fulfilled" ? results[3].value : null,
      learning: results[4].status === "fulfilled" ? results[4].value : null,
    });
  },

  applySimulation: async (mutations) => {
    const resp = await simulateApply(mutations);
    await get().refreshAll();
    set({ isSimulated: true, simulationSummary: resp.summary, canRevert: resp.can_revert });
    return resp;
  },

  revert: async () => {
    await revertSimulation();
    await get().refreshAll();
    set({ isSimulated: false, simulationSummary: [], canRevert: false });
  },

  clear: () => set({
    score: null, segments: null, lots: null, config: null, learning: null,
    isSimulated: false, simulationSummary: [], canRevert: false,
  }),
}));
```

### `src/stores/useSimulatorStore.ts`

```ts
import { create } from "zustand";
import type { MutationInput, SimulateResponse, CTPResult } from "../api/types";

interface SimulatorState {
  mutations: (MutationInput & { _key: number })[];
  result: SimulateResponse | null;
  ctpResult: CTPResult | null;
  nextKey: number;
  setMutations: (m: (MutationInput & { _key: number })[]) => void;
  setResult: (r: SimulateResponse | null) => void;
  setCtpResult: (r: CTPResult | null) => void;
  addMutation: () => void;
  removeMutation: (key: number) => void;
  updateMutationType: (key: number, type: string) => void;
  updateMutationParam: (key: number, paramKey: string, value: string) => void;
  clear: () => void;
}

export const useSimulatorStore = create<SimulatorState>((set, get) => ({
  mutations: [], result: null, ctpResult: null, nextKey: 0,
  setMutations: (m) => set({ mutations: m }),
  setResult: (r) => set({ result: r }),
  setCtpResult: (r) => set({ ctpResult: r }),
  addMutation: () => {
    const { mutations, nextKey } = get();
    set({ mutations: [...mutations, { type: "", params: {}, _key: nextKey }], nextKey: nextKey + 1 });
  },
  removeMutation: (key) => set((s) => ({ mutations: s.mutations.filter((m) => m._key !== key) })),
  updateMutationType: (key, type) => set((s) => ({
    mutations: s.mutations.map((m) => m._key === key ? { ...m, type, params: {} } : m),
  })),
  updateMutationParam: (key, paramKey, value) => set((s) => ({
    mutations: s.mutations.map((m) => m._key === key ? { ...m, params: { ...m.params, [paramKey]: value } } : m),
  })),
  clear: () => set({ mutations: [], result: null, ctpResult: null, nextKey: 0 }),
}));
```

---

## 8. UI COMPONENTS — `src/components/ui/`

### Card.tsx

```tsx
import { useState, type CSSProperties, type ReactNode } from "react";
import { T } from "../../theme/tokens";

interface Props { children: ReactNode; style?: CSSProperties; onClick?: () => void; hoverable?: boolean; }

export function Card({ children, style, onClick, hoverable = false }: Props) {
  const [hovered, setH] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => hoverable && setH(true)}
      onMouseLeave={() => hoverable && setH(false)}
      style={{
        background: hovered ? T.hover : T.card,
        borderRadius: T.radius,
        padding: 20,
        border: `0.5px solid ${hovered ? T.borderHover : T.border}`,
        transition: "all 0.2s ease",
        cursor: onClick ? "pointer" : "default",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
```

### Modal.tsx

```tsx
import { T } from "../../theme/tokens";

interface Props { children: React.ReactNode; onClose: () => void; title: string; }

export function Modal({ children, onClose, title }: Props) {
  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
        backdropFilter: "blur(20px)", WebkitBackdropFilter: "blur(20px)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: T.card, borderRadius: 16, padding: 28, width: 400,
          maxHeight: "80vh", overflowY: "auto",
          border: `0.5px solid ${T.border}`, boxShadow: "0 24px 80px rgba(0,0,0,0.5)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <span style={{ fontSize: 17, fontWeight: 600, color: T.primary }}>{title}</span>
          <button onClick={onClose} style={{ background: "none", border: "none", color: T.tertiary, cursor: "pointer", fontSize: 18, fontFamily: "inherit" }}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}
```

### ProgressBar.tsx

```tsx
import { T } from "../../theme/tokens";

interface Props { value: number; color?: string; height?: number; bg?: string; }

export function ProgressBar({ value, color = T.blue, height = 4, bg = "rgba(255,255,255,0.06)" }: Props) {
  return (
    <div style={{ width: "100%", height, borderRadius: height, background: bg, overflow: "hidden" }}>
      <div style={{ width: `${Math.min(value, 100)}%`, height: "100%", borderRadius: height, background: color, transition: "width 0.5s ease" }} />
    </div>
  );
}
```

### Label.tsx

```tsx
import type { CSSProperties } from "react";
import { T } from "../../theme/tokens";

interface Props { children: React.ReactNode; style?: CSSProperties; }

export function Label({ children, style }: Props) {
  return <span style={{ fontSize: 12, color: T.secondary, fontWeight: 500, letterSpacing: "0.01em", ...style }}>{children}</span>;
}
```

### Num.tsx

```tsx
import { T } from "../../theme/tokens";

interface Props { children: React.ReactNode; size?: number; color?: string; mono?: boolean; }

export function Num({ children, size = 32, color = T.primary, mono = true }: Props) {
  return (
    <span style={{
      fontSize: size, fontWeight: 600, color, letterSpacing: "-0.03em",
      fontFamily: mono ? T.mono : "inherit", fontFeatureSettings: "'tnum'",
    }}>
      {children}
    </span>
  );
}
```

### Pill.tsx

```tsx
import { T } from "../../theme/tokens";

interface Props { children: React.ReactNode; color?: string }

export function Pill({ children, color = T.secondary }: Props) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", padding: "3px 8px",
      borderRadius: 6, fontSize: 11, fontWeight: 500, color,
      background: `${color}15`, letterSpacing: "0.01em",
    }}>
      {children}
    </span>
  );
}
```

### Dot.tsx

```tsx
interface Props { color: string; size?: number }

export function Dot({ color, size = 6 }: Props) {
  return <span style={{ width: size, height: size, borderRadius: "50%", background: color, display: "inline-block", flexShrink: 0 }} />;
}
```

### Divider.tsx

```tsx
import { T } from "../../theme/tokens";

export function Divider() {
  return <div style={{ height: 0.5, background: T.border }} />;
}
```

### UploadZone.tsx

```tsx
import { useCallback, useRef, useState } from "react";
import { T } from "../../theme/tokens";
import { uploadISOP } from "../../api/endpoints";
import { useAppStore } from "../../stores/useAppStore";
import { useDataStore } from "../../stores/useDataStore";

export function UploadZone() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const setUploading = useAppStore((s) => s.setUploading);
  const setHasData = useAppStore((s) => s.setHasData);
  const setTrust = useAppStore((s) => s.setTrust);
  const isUploading = useAppStore((s) => s.isUploading);
  const refreshAll = useDataStore((s) => s.refreshAll);

  const doUpload = useCallback(async (file: File) => {
    setError(null); setUploading(true);
    try {
      const res = await uploadISOP(file);
      setTrust(res.trust_index.score, res.trust_index.gate);
      await refreshAll();
      setHasData(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro ao carregar ISOP");
    } finally { setUploading(false); }
  }, [setUploading, setHasData, setTrust, refreshAll]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) doUpload(file);
  }, [doUpload]);

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) doUpload(file);
  }, [doUpload]);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 24 }}>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => fileRef.current?.click()}
        style={{
          width: 400, padding: "48px 32px", borderRadius: T.radius,
          border: `2px dashed ${dragging ? T.blue : T.border}`,
          background: dragging ? `${T.blue}08` : T.card,
          cursor: "pointer", textAlign: "center", transition: "all 0.2s",
        }}
      >
        <input ref={fileRef} type="file" accept=".xlsx,.xls" style={{ display: "none" }} onChange={onFileChange} />
        {isUploading ? (
          <>
            <div style={{ fontSize: 32, marginBottom: 16 }}>⏳</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>A processar ISOP...</div>
            <div style={{ fontSize: 13, color: T.secondary, marginTop: 8 }}>Scheduling + Analytics</div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 32, marginBottom: 16 }}>📄</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>Carregar ISOP</div>
            <div style={{ fontSize: 13, color: T.secondary, marginTop: 8 }}>Arrasta ficheiro .xlsx ou clica para seleccionar</div>
          </>
        )}
      </div>
      {error && <div style={{ fontSize: 13, color: T.red, maxWidth: 400, textAlign: "center" }}>{error}</div>}
    </div>
  );
}
```

---

## 9. LAYOUT — `src/components/Shell.tsx`

```tsx
import { useState } from "react";
import { T } from "../theme/tokens";
import { useAppStore } from "../stores/useAppStore";
import { useDataStore } from "../stores/useDataStore";
import { recalculate } from "../api/endpoints";
import { TH } from "../constants/thresholds";
import { Sidebar } from "./Sidebar";
import { ChatPanel } from "./ChatPanel";
import { UploadZone } from "./ui/UploadZone";
import { ConsolePage } from "../pages/ConsolePage";
import { GanttPage } from "../pages/GanttPage";
import { StockPage } from "../pages/StockPage";
import { RiskPage } from "../pages/RiskPage";
import { SimulatorPage } from "../pages/SimulatorPage";
import { ConfigPage } from "../pages/ConfigPage";
import { ExpeditionPage } from "../pages/ExpeditionPage";
import { JournalPage } from "../pages/JournalPage";
import { RulesPage } from "../pages/RulesPage";

const NAV_LABELS: Record<string, string> = {
  console: "Consola", gantt: "Produção", stock: "Stock", risk: "Risco",
  expedition: "Expedição", sim: "Simulador", config: "Configuração",
  journal: "Journal", rules: "Regras",
};

function PageContent() {
  const page = useAppStore((s) => s.activePage);
  switch (page) {
    case "console": return <ConsolePage />;
    case "gantt": return <GanttPage />;
    case "stock": return <StockPage />;
    case "risk": return <RiskPage />;
    case "expedition": return <ExpeditionPage />;
    case "sim": return <SimulatorPage />;
    case "config": return <ConfigPage />;
    case "journal": return <JournalPage />;
    case "rules": return <RulesPage />;
    default: return <ConsolePage />;
  }
}

export function Shell() {
  const hasData = useAppStore((s) => s.hasData);
  const chatOpen = useAppStore((s) => s.chatOpen);
  const toggleChat = useAppStore((s) => s.toggleChat);
  const page = useAppStore((s) => s.activePage);
  const score = useDataStore((s) => s.score);
  const refreshAll = useDataStore((s) => s.refreshAll);
  const isSimulated = useDataStore((s) => s.isSimulated);
  const simulationSummary = useDataStore((s) => s.simulationSummary);
  const revert = useDataStore((s) => s.revert);
  const [recalcing, setRecalcing] = useState(false);
  const [reverting, setReverting] = useState(false);

  const handleRevert = async () => {
    setReverting(true);
    try { await revert(); } catch (err) { console.error("Revert failed:", err); }
    setReverting(false);
  };

  const handleRecalc = async () => {
    setRecalcing(true);
    try { await recalculate(); await refreshAll(); } catch (err) { console.error("Recalculate failed:", err); }
    setRecalcing(false);
  };

  return (
    <div style={{ display: "flex", height: "100vh", background: T.bg, color: T.primary, fontFamily: T.sans, WebkitFontSmoothing: "antialiased" }}>
      <Sidebar />
      <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <header style={{ height: 48, padding: "0 24px", display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: `0.5px solid ${T.border}`, flexShrink: 0 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: T.primary }}>{NAV_LABELS[page] || page}</span>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {hasData && score && (
              <div style={{ display: "flex", gap: 12 }}>
                <span style={{ fontSize: 11, color: (score.otd ?? 0) >= TH.OTD_GREEN ? T.green : T.orange, fontFamily: T.mono, fontWeight: 500 }}>OTD {score.otd?.toFixed(1)}%</span>
                <span style={{ fontSize: 11, color: (score.otd_d ?? 0) >= TH.OTD_D_GREEN ? T.green : T.orange, fontFamily: T.mono, fontWeight: 500 }}>OTD-D {score.otd_d?.toFixed(1)}%</span>
              </div>
            )}
            {hasData && (
              <>
                <button onClick={() => refreshAll()} title="Actualizar dados" style={{ background: "transparent", border: `0.5px solid ${T.border}`, color: T.secondary, borderRadius: 8, padding: "5px 10px", cursor: "pointer", fontSize: 12, fontFamily: "inherit" }}>↻</button>
                <button onClick={handleRecalc} disabled={recalcing || isSimulated} title={isSimulated ? "Reverta o cenario simulado primeiro" : "Recalcular schedule"} style={{ background: "transparent", border: `0.5px solid ${T.border}`, color: (recalcing || isSimulated) ? T.tertiary : T.secondary, borderRadius: 8, padding: "5px 10px", cursor: (recalcing || isSimulated) ? "default" : "pointer", fontSize: 11, fontFamily: "inherit" }}>
                  {recalcing ? "..." : "Recalcular"}
                </button>
              </>
            )}
            <button onClick={toggleChat} style={{ background: chatOpen ? `${T.blue}18` : "transparent", border: `0.5px solid ${chatOpen ? `${T.blue}44` : T.border}`, color: chatOpen ? T.blue : T.secondary, borderRadius: 8, padding: "5px 12px", cursor: "pointer", fontSize: 12, fontWeight: 500, fontFamily: "inherit" }}>Copilot</button>
          </div>
        </header>

        {isSimulated && (
          <div style={{ padding: "8px 24px", background: `${T.orange}12`, borderBottom: `1px solid ${T.orange}40`, display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: T.orange }}>Cenario simulado</span>
            {simulationSummary.length > 0 && <span style={{ fontSize: 11, color: T.secondary, flex: 1 }}>{simulationSummary[0]}</span>}
            <button onClick={handleRevert} disabled={reverting} style={{ background: "transparent", border: `1px solid ${T.orange}`, color: T.orange, borderRadius: 6, padding: "4px 12px", cursor: reverting ? "default" : "pointer", fontSize: 11, fontWeight: 600, fontFamily: "inherit" }}>
              {reverting ? "A reverter..." : "Reverter"}
            </button>
          </div>
        )}

        <div style={{ flex: 1, overflow: "auto", padding: 24 }}>
          {hasData ? <PageContent /> : <UploadZone />}
        </div>
      </main>
      {chatOpen && <ChatPanel />}
    </div>
  );
}
```

---

## 10. SIDEBAR — `src/components/Sidebar.tsx`

```tsx
import { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { useAppStore } from "../stores/useAppStore";
import { getTrust } from "../api/endpoints";
import type { TrustIndex } from "../api/types";
import { ProgressBar } from "./ui/ProgressBar";
import { Label } from "./ui/Label";

const NAV = [
  { id: "console", label: "Consola" }, { id: "gantt", label: "Produção" },
  { id: "stock", label: "Stock" }, { id: "risk", label: "Risco" },
  { id: "expedition", label: "Expedição" }, { id: "sim", label: "Simulador" },
  { id: "config", label: "Configuração" }, { id: "journal", label: "Journal" },
  { id: "rules", label: "Regras" },
];

export function Sidebar() {
  const page = useAppStore((s) => s.activePage);
  const setPage = useAppStore((s) => s.setPage);
  const trustScore = useAppStore((s) => s.trustScore);
  const hasData = useAppStore((s) => s.hasData);
  const [trust, setTrust] = useState<TrustIndex | null>(null);

  useEffect(() => {
    if (!hasData) return;
    getTrust().then(setTrust).catch(() => {});
  }, [hasData]);

  return (
    <nav style={{ width: 200, flexShrink: 0, background: T.card, borderRight: `0.5px solid ${T.border}`, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "20px 20px 24px" }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: T.primary, letterSpacing: "-0.02em" }}>ProdPlan ONE</div>
        <div style={{ fontSize: 11, color: T.tertiary, marginTop: 2 }}>Incompol</div>
      </div>
      <div style={{ flex: 1, padding: "0 8px", display: "flex", flexDirection: "column", gap: 1 }}>
        {NAV.map((n) => {
          const active = page === n.id;
          return (
            <button key={n.id} onClick={() => setPage(n.id)} style={{
              background: active ? "rgba(255,255,255,0.06)" : "transparent",
              border: "none", borderRadius: 8, padding: "8px 12px",
              color: active ? T.primary : T.secondary, fontSize: 13,
              fontWeight: active ? 600 : 400, cursor: "pointer",
              textAlign: "left", transition: "all 0.15s", width: "100%", fontFamily: "inherit",
            }}>
              {n.label}
            </button>
          );
        })}
      </div>
      {trustScore !== null && (
        <div style={{ padding: 16, borderTop: `0.5px solid ${T.border}` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <Label>Trust Index</Label>
            <span style={{ fontSize: 18, fontWeight: 600, color: trustScore >= 80 ? T.green : T.orange, fontFamily: T.mono }}>{trustScore}</span>
          </div>
          <div style={{ marginTop: 6 }}>
            <ProgressBar value={trustScore} color={trustScore >= 80 ? T.green : T.orange} height={3} bg="rgba(255,255,255,0.04)" />
          </div>
          {trust?.dimensions && trust.dimensions.length > 0 && (
            <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 4 }}>
              {trust.dimensions.map((d) => {
                const c = d.score >= 80 ? T.green : d.score >= 50 ? T.orange : T.red;
                return (
                  <div key={d.name}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                      <span style={{ fontSize: 10, color: T.tertiary }}>{d.name}</span>
                      <span style={{ fontSize: 10, color: c, fontFamily: T.mono }}>{d.score}</span>
                    </div>
                    <ProgressBar value={d.score} color={c} height={2} bg="rgba(255,255,255,0.04)" />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </nav>
  );
}
```

---

## 11. CHAT PANEL — `src/components/ChatPanel.tsx`

```tsx
import { useState, useRef, useEffect } from "react";
import { T } from "../theme/tokens";
import { chatCopilot } from "../api/endpoints";
import { useAppStore } from "../stores/useAppStore";

interface Widget { type: string; data: unknown; }
interface Message { role: "user" | "assistant"; content: string; widgets?: Widget[]; }

export function ChatPanel() {
  const toggleChat = useAppStore((s) => s.toggleChat);
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", content: "Olá. Posso ajudar com análise de produção, simulações, ou perguntas sobre o plano." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg: Message = { role: "user", content: input.trim() };
    const updated = [...messages, userMsg];
    setMessages(updated); setInput(""); setLoading(true);
    try {
      const res = await chatCopilot(updated.map((m) => ({ role: m.role, content: m.content })));
      setMessages((prev) => [...prev, { role: "assistant", content: res.response, widgets: res.widgets?.length ? res.widgets as Widget[] : undefined }]);
    } catch {
      setMessages((prev) => [...prev, { role: "assistant", content: "Erro ao contactar o copilot." }]);
    } finally { setLoading(false); }
  };

  return (
    <aside style={{ width: 360, flexShrink: 0, background: T.card, borderLeft: `0.5px solid ${T.border}`, display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "14px 20px", borderBottom: `0.5px solid ${T.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: T.primary }}>Copilot</span>
        <button onClick={toggleChat} style={{ background: "none", border: "none", color: T.tertiary, cursor: "pointer", fontSize: 16, fontFamily: "inherit" }}>×</button>
      </div>
      <div style={{ flex: 1, padding: 20, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            background: m.role === "user" ? `${T.blue}15` : T.elevated,
            borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
            padding: "12px 16px", maxWidth: "85%",
            alignSelf: m.role === "user" ? "flex-end" : "flex-start",
          }}>
            <p style={{ fontSize: 13, color: m.role === "user" ? T.blue : T.secondary, lineHeight: 1.6, margin: 0, whiteSpace: "pre-wrap" }}>{m.content}</p>
            {m.widgets?.map((w, wi) => (
              <div key={wi} style={{ marginTop: 8, padding: "8px 10px", background: T.card, borderRadius: 8, border: `0.5px solid ${T.border}` }}>
                <div style={{ fontSize: 10, color: T.tertiary, fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>{w.type}</div>
                <pre style={{ fontSize: 11, color: T.secondary, overflow: "auto", maxHeight: 200, margin: 0, whiteSpace: "pre-wrap", fontFamily: T.mono }}>{JSON.stringify(w.data, null, 2)}</pre>
              </div>
            ))}
          </div>
        ))}
        {loading && (
          <div style={{ background: T.elevated, borderRadius: "14px 14px 14px 4px", padding: "12px 16px", maxWidth: "85%" }}>
            <span style={{ fontSize: 13, color: T.tertiary }}>...</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div style={{ padding: "12px 20px", borderTop: `0.5px solid ${T.border}` }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder="Perguntar..."
            style={{ flex: 1, background: T.elevated, border: `0.5px solid ${T.border}`, color: T.primary, borderRadius: 10, padding: "10px 14px", fontSize: 13, fontFamily: "inherit", outline: "none" }} />
          <button onClick={send} style={{ background: T.blue, border: "none", color: "#fff", borderRadius: 10, width: 38, cursor: "pointer", fontSize: 15, fontWeight: 600, fontFamily: "inherit" }}>↑</button>
        </div>
      </div>
    </aside>
  );
}
```

---

## 12. PÁGINAS

### ConsolePage.tsx (314 linhas)

```tsx
import React, { useEffect, useState } from "react";
import { T } from "../theme/tokens";
import { getConsole, getToday } from "../api/endpoints";
import { useDataStore } from "../stores/useDataStore";
import type { ConsoleData } from "../api/types";
import { Card } from "../components/ui/Card";
import { Num } from "../components/ui/Num";
import { Label } from "../components/ui/Label";
import { Dot } from "../components/ui/Dot";
import { Divider } from "../components/ui/Divider";
import { ProgressBar } from "../components/ui/ProgressBar";
import { TH } from "../constants/thresholds";

export function ConsolePage() {
  const [day, setDay] = useState<number | null>(null);
  const [data, setData] = useState<ConsoleData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const score = useDataStore((s) => s.score);

  useEffect(() => { getToday().then((t) => setDay(t.today_idx)).catch(() => setDay(0)); }, []);
  useEffect(() => { if (day === null) return; getConsole(day).then(setData).catch((e) => setError(e.message)); }, [day]);

  if (error) return <div style={{ color: T.red, padding: 24 }}>{error}</div>;
  if (day === null || !data) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  const stateColor = data.state.color === "red" ? T.red : data.state.color === "yellow" ? T.orange : T.green;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* State Banner */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", background: T.card, borderRadius: T.radius, border: `0.5px solid ${T.border}` }}>
        <Dot color={stateColor} size={8} />
        <span style={{ fontSize: 15, fontWeight: 500, color: T.primary, flex: 1 }}>{data.state.phrase}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6, background: T.elevated, borderRadius: 8, padding: "4px 4px" }}>
          <button onClick={() => setDay(Math.max(-(Number(score?.buffer_days) || 0), (day ?? 0) - 1))} style={navBtnStyle}>‹</button>
          <span style={{ fontSize: 12, fontWeight: 600, color: T.primary, minWidth: 54, textAlign: "center", fontFamily: T.mono }}>Dia {day ?? 0}</span>
          <button onClick={() => setDay((day ?? 0) + 1)} style={navBtnStyle}>›</button>
        </div>
      </div>

      {/* KPI Strip */}
      {score && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12 }}>
          {[
            { l: "OTD", v: score.otd?.toFixed(1), u: "%", c: (score.otd ?? 0) >= TH.OTD_GREEN ? T.green : T.orange },
            { l: "OTD-D", v: score.otd_d?.toFixed(1), u: "%", c: (score.otd_d ?? 0) >= TH.OTD_D_GREEN ? T.green : T.orange },
            { l: "Atrasos", v: score.tardy_count, c: score.tardy_count === 0 ? T.green : T.red },
            { l: "Setups", v: score.setups, c: T.primary },
            { l: "Antecipação", v: score.earliness_avg_days?.toFixed(1), u: "d", c: T.primary },
            { l: "Buffer", v: Number(score.buffer_days) || 0, u: "d", c: T.primary },
          ].map((k, i) => (
            <Card key={i} style={{ padding: 16 }}>
              <Label>{k.l}</Label>
              <div style={{ marginTop: 8, display: "flex", alignItems: "baseline", gap: 3 }}>
                <Num size={28} color={k.c}>{k.v}</Num>
                {k.u && <span style={{ fontSize: 13, color: T.tertiary, fontWeight: 500 }}>{k.u}</span>}
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Two-column layout: Actions + Machines/Expedition + Tomorrow */}
      {/* ... (ver ficheiro completo para detalhes) */}
    </div>
  );
}

const navBtnStyle: React.CSSProperties = {
  background: "none", border: "none", color: T.secondary, cursor: "pointer",
  padding: "4px 8px", borderRadius: 6, fontSize: 13, fontFamily: "inherit",
};

const fixBtnStyle: React.CSSProperties = {
  background: T.elevated, border: `0.5px solid ${T.border}`, color: T.blue,
  fontSize: 11, fontWeight: 500, padding: "5px 10px", borderRadius: 6,
  cursor: "pointer", fontFamily: "inherit",
};
```

### GanttPage.tsx (1130 linhas) — RESUMO ESTRUTURAL

O Gantt é a página mais complexa. Características:
- **Multi-day e single-day view** com zoom slider (50-300px por dia)
- **Range presets**: 1 Dia, Semana, 2 Sem, Mês, Tudo + custom range
- **Machine lanes** com segmentos posicionados por start_min/end_min
- **Setup overlay** com pattern diagonal (hatch)
- **Twin badges** ("T") nos segmentos gémeos
- **EDD markers** (dashed red lines)
- **Shift change marker** (orange line at 930min)
- **Day detail panel** quando zoom 1 dia — breakdown por máquina/ferramenta
- **Table view** alternativa com colunas: Máq, Dia, Data, Turno, Tool, SKU, Qty, Setup, Prod, EDD
- **Export CSV** com segmentos + resumo diário + KPIs
- **Utilization bars** por máquina no topo
- **Segment detail modal** ao clicar num segmento

Constantes: `DAY_CAP=1020`, `SHIFT_CHANGE=930`, `DAY_START=420`, `LANE_H=60`, `SINGLE_BAR_H=52`

### StockPage.tsx (415 linhas) — Grid de stock por SKU x dia

- **Heatmap grid** com sticky headers e sticky left column
- **Filtros**: cliente, máquina, só rupturas, esconder sem demanda
- **Cell coloring**: vermelho=ruptura, laranja=cobertura baixa, cinza=fim-de-semana, azul=buffer
- **Detail modal** ao clicar SKU — tabela com procura/produção/stock por dia
- **Legend** no fundo

### RiskPage.tsx (345 linhas) — 4 tabs

- **Visão Geral**: Health Score, Riscos Críticos, Bottleneck, Heatmap máquina×dia, Top Riscos
- **Atrasos**: Contagem, atraso médio, pior máquina, filtro por causa, tabela detalhada
- **Mão de Obra**: Pico, média, déficit, tendência, tabela diária
- **Propostas**: Recomendação geral + sugestões por atraso

### ExpeditionPage.tsx (231 linhas) — 2 views

- **Timeline**: Cards por dia com ready/partial/not_planned, expandível com tabela
- **Clientes**: Cards por cliente com orders, expandível + cobertura por cliente

### SimulatorPage.tsx (464 linhas) — 2 secções

- **Mutation Builder**: 15 tipos de mutação (advance_edd, machine_down, rush_order, etc.)
- **Delta Results**: 5 KPI cards before→after + resumo + botão "Aplicar no Gantt"
- **CTP (Capable-To-Promise)**: SKU + Qty + Deadline → viável/inviável + detalhes + aplicar

### ConfigPage.tsx (762 linhas) — 9 secções

Geral, Turnos, Máquinas (toggle activa), Ferramentas (edit setup/alt), Gémeas (add/remove), Operadores (batch edit), Feriados (add/remove), Parâmetros (14 tunables + presets), Operações (read-only table com filtro)

### JournalPage.tsx (44 linhas)

Lista simples de entries com severity pill + step + message + elapsed_ms

### RulesPage.tsx (99 linhas)

15 regras do scheduler agrupadas por categoria (Lotes, JIT, Dispatch, Scoring, Capacidade), read-only

---

## 13. ENTRY POINTS

### `src/App.tsx`

```tsx
import { Shell } from "./components/Shell";
export default function App() { return <Shell />; }
```

### `src/main.tsx`

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
```

---

## PADRÕES DE DESIGN

1. **Inline styles everywhere** — objecto `T` para cores/fonts, sem CSS files
2. **Componentes funcionais** — React hooks, sem classes
3. **Zustand** para state — 3 stores, sem Redux/Context
4. **Cores semânticas**: green=bom, orange=warning, red=critical
5. **Mono font** para números/dados, sans para texto
6. **0.5px borders** com rgba para subtileza
7. **Glassmorphism** nos modals (backdrop-filter: blur(20px))
8. **Compact spacing** — 8-16px gaps, density alta
9. **Grid layouts** — CSS Grid para KPI strips, tabelas
10. **Flexbox** para layout principal (sidebar + main + chat)

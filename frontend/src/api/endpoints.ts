/** Typed endpoint functions — one per backend route. */

import { get, post, put, del, upload } from "./client";
import type {
  ChatResponse,
  ClientOrders,
  ConsoleData,
  CoverageAudit,
  CTPResult,
  EOp,
  ExpeditionKPIs,
  FactoryConfig,
  JournalEntry,
  LateDeliveryReport,
  LearningInfo,
  LoadResponse,
  Lot,
  MasterDataResult,
  MutationInput,
  RiskResult,
  Score,
  Segment,
  SimulateResponse,
  StockProjection,
  StockSummary,
  TrustIndex,
  WorkforceForecast,
} from "./types";

// ── Core ─────────────────────────────────────────────────────

export const getToday = () => get<{ today_idx: number; date: string }>("/api/data/today");
export const getWorkdays = () => get<string[]>("/api/data/workdays");
export const getScore = () => get<Score>("/api/data/score");
export const getSegments = () => get<Segment[]>("/api/data/segments");
export const getLots = () => get<Lot[]>("/api/data/lots");
export const getTrust = () => get<TrustIndex>("/api/data/trust");
export const getJournal = () => get<JournalEntry[]>("/api/data/journal");
export const getLearning = () => get<LearningInfo | null>("/api/data/learning");

// ── Analytics ────────────────────────────────────────────────

export const getStockSummary = () => get<StockSummary[]>("/api/data/stock");
export const getStockDetail = (sku: string) =>
  get<StockProjection>(`/api/data/stock/${encodeURIComponent(sku)}`);
export const getExpedition = () => get<ExpeditionKPIs>("/api/data/expedition");
export const getOrders = () => get<ClientOrders[]>("/api/data/orders");
export const getCoverage = () => get<CoverageAudit>("/api/data/coverage");
export const getRisk = () => get<RiskResult>("/api/data/risk");
export const getLateDeliveries = () => get<LateDeliveryReport>("/api/data/late");
export const getWorkforce = (window = 10) =>
  get<WorkforceForecast>(`/api/data/workforce?window=${window}`);

// ── Config / Master Data ─────────────────────────────────────

export const getConfig = () => get<FactoryConfig>("/api/data/config");
export const updateConfig = (updates: Record<string, unknown>) =>
  put<{ status: string; changed: string[]; score: Score }>("/api/data/config", updates);
export const getOps = () => get<EOp[]>("/api/data/ops");
export const getRules = () => get<{ id: string; tipo: string; descricao: string }[]>("/api/data/rules");

// ── Master Data Mutations ────────────────────────────────────

export const editMachine = (mid: string, updates: Record<string, unknown>) =>
  put<MasterDataResult>(`/api/data/machines/${encodeURIComponent(mid)}`, updates);

export const editTool = (tid: string, updates: Record<string, unknown>) =>
  put<MasterDataResult>(`/api/data/tools/${encodeURIComponent(tid)}`, updates);

export const updateOperators = (ops: Record<string, number>) =>
  put<MasterDataResult>("/api/data/operators", ops);

export const addHoliday = (date: string) =>
  post<MasterDataResult>("/api/data/holidays", { data: date });

export const removeHoliday = (date: string) =>
  del<MasterDataResult>(`/api/data/holidays/${encodeURIComponent(date)}`);

export const addTwin = (tool_id: string, sku_a: string, sku_b: string) =>
  post<MasterDataResult>("/api/data/twins", { tool_id, sku_a, sku_b });

export const removeTwin = (tool_id: string) =>
  del<MasterDataResult>(`/api/data/twins/${encodeURIComponent(tool_id)}`);

export const applyPreset = (name: string) =>
  post<{ status: string; changed: string[]; score: Score }>(`/api/data/presets/${name}`, {});

// ── Console ──────────────────────────────────────────────────

export const getConsole = (dayIdx = 0) =>
  get<ConsoleData>(`/api/console?day_idx=${dayIdx}`);

// ── Actions ──────────────────────────────────────────────────

export const simulate = (mutations: MutationInput[]) =>
  post<SimulateResponse>("/api/data/simulate", { mutations });

export const checkCTP = (sku: string, qty: number, deadline: number) =>
  post<CTPResult>("/api/data/ctp", { sku, qty, deadline });

export const recalculate = () =>
  post<{ status: string; score: Score; score_previous: Score; time_ms: number; n_segments: number }>(
    "/api/data/recalculate",
    {},
  );

// ── Upload ───────────────────────────────────────────────────

export const uploadISOP = (file: File) =>
  upload<LoadResponse>("/api/data/load", file);

// ── Chat ─────────────────────────────────────────────────────

export const chatCopilot = (messages: { role: string; content: string }[]) =>
  post<ChatResponse>("/api/copilot/chat", { messages });

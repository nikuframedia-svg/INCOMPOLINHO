/** Typed endpoint functions — one per backend route. */

import { get, post, put, del, delWithBody, upload } from "./client";
import type {
  ChatResponse,
  BlockedDaysResponse,
  CapacityResponse,
  ClientOrders,
  ConsoleData,
  CoverageAudit,
  CTPResult,
  CandidateIdentity,
  EOp,
  ExpeditionKPIs,
  FactoryConfig,
  GateReport,
  HealthResponse,
  JournalEntry,
  LateDeliveryReport,
  LearningInfo,
  LoadJobResponse,
  CurrentMachineState,
  Lot,
  ManualEdit,
  ManualMoveJob,
  MasterCatalog,
  MasterDataResult,
  MutationInput,
  PlanSummary,
  PlanView,
  RiskResult,
  RobustnessJob,
  ReplanJob,
  RestorePlanResponse,
  Score,
  Segment,
  SetupOverride,
  SkuPlanningResponse,
  SkuPlanningRule,
  SimulateApplyResponse,
  SimulateResponse,
  StockProjection,
  StockSummary,
  SubcontractsResponse,
  TrustIndex,
  WorkforceForecast,
} from "./types";
import { normalizeManualMoveJob, normalizeManualMoveResponse } from "../lib/manualMoveContract";
import { commitPlanRevision, getPlanRevision, getReadIdentity } from "../lib/planRevision";
import { candidateApplyBody } from "../lib/previewCandidate";
import { operationIdentity } from "../lib/operationIdentity";
import { withApprovalCandidate } from "../lib/approvalRetry";
import { approvalFields, type GateApproval } from "../lib/gateApproval";

export { commitPlanRevision };
const COMPUTE_OPTIONS = { timeoutMs: 600_000 };
const JOB_OPTIONS = { timeoutMs: 15_000, blocking: false };
const analyticGet = <T,>(url: string) => get<T>(url, { planIdentity: getReadIdentity() });

const revisionBody = <T extends Record<string, unknown>>(body: T) => ({
  ...body,
  expected_revision: body.expected_revision ?? getPlanRevision(),
});

function postWithRevision<T>(
  url: string,
  body: Record<string, unknown>,
  options?: { timeoutMs?: number; blocking?: boolean },
): Promise<T> {
  const input = revisionBody(body);
  const operation = operationIdentity(`POST ${url}`, input);
  return withApprovalCandidate(operation.id, input, (candidateBody) =>
    post<T>(url, { ...candidateBody, request_id: operation.id }, options),
  ).then((response) => {
    operation.confirmed();
    return response;
  });
}

function deleteWithRevision<T>(
  url: string,
  body: Record<string, unknown>,
): Promise<T> {
  const input = revisionBody(body);
  const operation = operationIdentity(`DELETE ${url}`, input);
  return withApprovalCandidate(operation.id, input, (candidateBody) =>
    delWithBody<T>(url, { ...candidateBody, request_id: operation.id }),
  ).then((response) => {
    operation.confirmed();
    return response;
  });
}

function putWithRevision<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const input = revisionBody(body);
  const operation = operationIdentity(`PUT ${url}`, input);
  return withApprovalCandidate(operation.id, input, (candidateBody) =>
    put<T>(url, { ...candidateBody, request_id: operation.id }),
  ).then((response) => {
    operation.confirmed();
    return response;
  });
}

// ── Core ─────────────────────────────────────────────────────

export const getToday = () => analyticGet<{ today_idx: number; date: string }>("/api/data/today");
export const getWorkdays = () => analyticGet<string[]>("/api/data/workdays");
export const getScore = () => get<Score>("/api/data/score");
export const getGateReport = () => get<GateReport>("/api/data/gate-report");
export const getSegments = () => get<Segment[]>("/api/data/segments");
export const getLots = () => get<Lot[]>("/api/data/lots");
export const getPlanView = () => get<PlanView>("/api/data/plan-view");
export const getTrust = () => analyticGet<TrustIndex>("/api/data/trust");
export const getJournal = () => analyticGet<JournalEntry[]>("/api/data/journal");
export const getLearning = () => get<LearningInfo | null>("/api/data/learning");
export const getHealth = () => get<HealthResponse>("/api/copilot/health", { timeoutMs: 10000 });

// ── Analytics ────────────────────────────────────────────────

export const getStockSummary = () => analyticGet<StockSummary[]>("/api/data/stock");
export const getStockDetail = (sku: string) =>
  analyticGet<StockProjection>(`/api/data/stock/${encodeURIComponent(sku)}`);
export const getExpedition = () => analyticGet<ExpeditionKPIs>("/api/data/expedition");
export const getOrders = () => analyticGet<ClientOrders[]>("/api/data/orders");
export const getCoverage = () => analyticGet<CoverageAudit>("/api/data/coverage");
export const getRisk = () => analyticGet<RiskResult>("/api/data/risk");
export const getLateDeliveries = () => analyticGet<LateDeliveryReport>("/api/data/late");
export const getWorkforce = (window = 10) =>
  analyticGet<WorkforceForecast>(`/api/data/workforce?window=${window}`);
export const getCapacity = (granularity: "day" | "week" = "day") =>
  analyticGet<CapacityResponse>(`/api/data/capacity?granularity=${granularity}`);
export const getBlockedDays = () => get<BlockedDaysResponse>("/api/data/blocked-days");

export const startRobustnessRun = (body: {
  profile: "quick" | "standard" | "intensive";
  samples?: number;
  seed?: number;
}) => postWithRevision<{ status: string; job: RobustnessJob }>("/api/data/robustness-runs", { ...body, dataset_id: getReadIdentity()?.datasetId }, JOB_OPTIONS);

export const getRobustnessRun = (id: string) =>
  analyticGet<{ job: RobustnessJob }>(`/api/data/robustness-runs/${encodeURIComponent(id)}`);

/** Without a trigger the backend returns the newest job of either kind. */
export const getLatestRobustnessRun = (trigger?: "auto" | "manual") =>
  analyticGet<{ job: RobustnessJob | null; refreshing?: boolean }>(
    `/api/data/robustness-runs/latest${trigger ? `?trigger=${trigger}` : ""}`,
  );

export const cancelRobustnessRun = (id: string) =>
  post<{ job: RobustnessJob }>(`/api/data/robustness-runs/${encodeURIComponent(id)}/cancel`, {}, JOB_OPTIONS);

export const startReplan = (body: {
  reason: string;
  config_updates?: Record<string, unknown>;
  expected_revision?: number;
}) => postWithRevision<{ status: "queued"; job: ReplanJob }>(
  "/api/data/replan-jobs",
  body,
  JOB_OPTIONS,
);

export const getReplan = (id: string) =>
  get<{ job: ReplanJob }>(`/api/data/replan-jobs/${encodeURIComponent(id)}`);

export const getReplans = (pending?: boolean) =>
  get<{
    dataset_id: string;
    base_revision: number;
    jobs: ReplanJob[];
  }>(`/api/data/replan-jobs${pending === undefined ? "" : `?pending=${pending}`}`);

export const cancelReplan = (id: string) =>
  post<{ job: ReplanJob }>(`/api/data/replan-jobs/${encodeURIComponent(id)}/cancel`, {}, JOB_OPTIONS);

export const applyReplan = (
  id: string,
  approval?: { reason: string; author: string },
  expectedRevision?: number,
) => postWithRevision<{
  status: "applied";
  job: ReplanJob;
  plan_revision: number;
}>(`/api/data/replan-jobs/${encodeURIComponent(id)}/apply`, {
  expected_revision: expectedRevision,
  approve_exceptions: Boolean(approval),
  approval_reason: approval?.reason ?? "",
  approval_author: approval?.author ?? "",
}, COMPUTE_OPTIONS);

// ── Config / Master Data ─────────────────────────────────────

export const getConfig = () => analyticGet<FactoryConfig>("/api/data/config");
export const updateConfig = (updates: Record<string, unknown>, approval?: GateApproval) =>
  putWithRevision<{ status: string; changed: string[]; score: Score; score_previous: Score }>(
    "/api/data/config",
    revisionBody({ ...updates, ...approvalFields(approval) }),
  );
export const getOps = () => analyticGet<EOp[]>("/api/data/ops");
export const getCatalog = () => analyticGet<MasterCatalog>("/api/data/catalog");
export const getCurrentState = () =>
  get<{ confirmed: boolean; items: CurrentMachineState[] }>("/api/data/current-state");
export const getRules = () => get<{ id: string; tipo: string; descricao: string }[]>("/api/data/rules");
export const previewSkuPlanning = (sku: string, rule: SkuPlanningRule) =>
  post<SkuPlanningResponse>(`/api/data/skus/${encodeURIComponent(sku)}/planning/preview`, rule);
export const updateSkuPlanning = (sku: string, rule: SkuPlanningRule, approval?: GateApproval) =>
  putWithRevision<SkuPlanningResponse>(
    `/api/data/skus/${encodeURIComponent(sku)}/planning`,
    revisionBody({ ...(rule as unknown as Record<string, unknown>), ...approvalFields(approval) }),
  );
export const resetSkuPlanning = (sku: string, approval?: GateApproval) =>
  deleteWithRevision<SkuPlanningResponse>(
    `/api/data/skus/${encodeURIComponent(sku)}/planning`,
    revisionBody(approvalFields(approval)),
  );
export const getSubcontracts = () => get<SubcontractsResponse>("/api/data/subcontracts");
export const previewSubcontracts = (body: SubcontractsResponse) =>
  post<SubcontractsResponse>("/api/data/subcontracts/preview", body);
export const updateSubcontracts = (body: SubcontractsResponse, approval?: GateApproval) =>
  putWithRevision<SubcontractsResponse>(
    "/api/data/subcontracts",
    revisionBody({ ...(body as unknown as Record<string, unknown>), ...approvalFields(approval) }),
  );

// ── Master Data Mutations ────────────────────────────────────

export const editMachine = (mid: string, updates: Record<string, unknown>) =>
  putWithRevision<MasterDataResult>(
    `/api/data/machines/${encodeURIComponent(mid)}`,
    revisionBody(updates),
  );

export const addMachine = (body: {
  id: string;
  group: string;
  active?: boolean;
}) =>
  postWithRevision<{ status: "queued"; job: ReplanJob }>("/api/data/machines", body);

export const editTool = (tid: string, updates: Record<string, unknown>) =>
  putWithRevision<MasterDataResult>(
    `/api/data/tools/${encodeURIComponent(tid)}`,
    revisionBody(updates),
  );

export const addTool = (body: {
  id: string;
  primary: string;
  alt?: string | null;
  setup_hours: number;
}) =>
  postWithRevision<{ status: "queued"; job: ReplanJob }>("/api/data/tools", body);

export const updateOperators = (ops: Record<string, number>, approval?: GateApproval) =>
  putWithRevision<MasterDataResult>("/api/data/operators", { ...ops, ...approvalFields(approval) });

export const addHoliday = (date: string, approval?: GateApproval) =>
  postWithRevision<MasterDataResult>("/api/data/holidays", { data: date, ...approvalFields(approval) });

export const removeHoliday = (date: string, approval?: GateApproval) =>
  deleteWithRevision<MasterDataResult>(
    `/api/data/holidays/${encodeURIComponent(date)}`,
    revisionBody(approvalFields(approval)),
  );

export const addHolidayRange = (from: string, to: string, approval?: GateApproval) =>
  postWithRevision<MasterDataResult>("/api/data/holidays/range", { from, to, ...approvalFields(approval) });

export const removeHolidayRange = (from: string, to: string, approval?: GateApproval) =>
  deleteWithRevision<MasterDataResult>(
    "/api/data/holidays/range",
    revisionBody({ from, to, ...approvalFields(approval) }),
  );

export const addExtraWorkday = (date: string, approval?: GateApproval) =>
  postWithRevision<MasterDataResult>("/api/data/workdays-extra", { date, ...approvalFields(approval) });

export const removeExtraWorkday = (date: string, approval?: GateApproval) =>
  deleteWithRevision<MasterDataResult>(
    `/api/data/workdays-extra/${encodeURIComponent(date)}`,
    revisionBody(approvalFields(approval)),
  );

export const addUnavailability = (body: Record<string, unknown>) =>
  postWithRevision<MasterDataResult>("/api/data/unavailability", body);

export const removeUnavailability = (entryId: string) =>
  deleteWithRevision<MasterDataResult>(
    `/api/data/unavailability/${encodeURIComponent(entryId)}`,
    {},
  );

export const replaceSetupOverrides = (items: SetupOverride[], approval?: GateApproval) =>
  putWithRevision<MasterDataResult>("/api/data/setup-overrides", { items, ...approvalFields(approval) });

export const addTwin = (tool_id: string, sku_a: string, sku_b: string, approval?: GateApproval) =>
  postWithRevision<MasterDataResult>(
    "/api/data/twins",
    revisionBody({ tool_id, sku_a, sku_b, ...approvalFields(approval) }),
  );

export const removeTwin = (tool_id: string, approval?: GateApproval) =>
  deleteWithRevision<MasterDataResult>(
    `/api/data/twins/${encodeURIComponent(tool_id)}`,
    revisionBody(approvalFields(approval)),
  );

export const applyPreset = (name: string, approval?: GateApproval) =>
  postWithRevision<{
    status: string;
    preset: string;
    changed: string[];
    score: Score;
    score_previous: Score;
    simulation_active: boolean;
  }>(`/api/data/presets/${name}`, revisionBody(approvalFields(approval)));

// ── Persistent plans ─────────────────────────────────────────

export const getPlans = () =>
  get<{ plans: PlanSummary[] }>("/api/data/plans");

export const savePlan = (name: string, note: string) =>
  post<{ status: string; plan: PlanSummary }>("/api/data/plans", { name, note });

export const restorePlan = (
  planId: string,
  approval?: { reason: string; author: string },
) =>
  postWithRevision<RestorePlanResponse>(
    `/api/data/plans/${encodeURIComponent(planId)}/restore`,
    revisionBody({
      approve_exceptions: Boolean(approval),
      approval_reason: approval?.reason ?? "",
      approval_author: approval?.author ?? "",
    }),
  );

export const deletePlan = (planId: string) =>
  del<{ status: string; deleted: string }>(`/api/data/plans/${encodeURIComponent(planId)}`);

export const getScenarios = () =>
  get<{ scenarios: PlanSummary[] }>("/api/data/scenarios");

export const saveScenario = (name: string, note: string, mutations: MutationInput[], candidate: CandidateIdentity) =>
  post<{
    status: string;
    scenario: PlanSummary;
    score_baseline: Score;
    score_scenario: Score;
    gate_report: GateReport;
  }>("/api/data/scenarios", { name, note, mutations, candidate_id: candidate.candidate_id });

export const applySavedScenario = (
  scenarioId: string,
  approval?: { reason: string; author: string },
) =>
  postWithRevision<RestorePlanResponse>(
    `/api/data/scenarios/${encodeURIComponent(scenarioId)}/apply`,
    revisionBody({
      approve_exceptions: Boolean(approval),
      approval_reason: approval?.reason ?? "",
      approval_author: approval?.author ?? "",
    }),
  );

export const deleteSavedScenario = (scenarioId: string) =>
  del<{ status: string; deleted: string }>(
    `/api/data/scenarios/${encodeURIComponent(scenarioId)}`,
  );

export const previewManualMove = (body: {
  lot_id: string;
  target_day: number;
  target_machine?: string;
  target_start_min?: number;
  reason?: string;
  author?: string;
}) => post<unknown>("/api/data/plan/move-preview", body)
  .then(normalizeManualMoveResponse);

export const startManualMovePreview = (body: {
  lot_id: string;
  target_day: number;
  target_machine?: string;
  target_start_min?: number;
  reason?: string;
  author?: string;
}) => post<{ status: "queued" | "running" | "ready"; job: unknown }>(
  "/api/data/plan/move-preview-jobs",
  body,
  JOB_OPTIONS,
).then((response) => ({
  status: response.status,
  job: normalizeManualMoveJob(response.job),
}));

export const getManualMovePreview = (id: string) =>
  get<{ job: unknown }>(
    `/api/data/plan/move-preview-jobs/${encodeURIComponent(id)}`,
  ).then((response): { job: ManualMoveJob } => ({
    job: normalizeManualMoveJob(response.job),
  }));

export const cancelManualMovePreview = (id: string) =>
  post<{ job: unknown }>(
    `/api/data/plan/move-preview-jobs/${encodeURIComponent(id)}/cancel`,
    {},
    JOB_OPTIONS,
  ).then((response): { job: ManualMoveJob } => ({
    job: normalizeManualMoveJob(response.job),
  }));

export const applyManualMove = (body: {
  lot_id: string;
  target_day: number;
  target_machine?: string;
  target_start_min?: number;
  reason?: string;
  author?: string;
  expected_revision?: number;
  approve_exceptions?: boolean;
  approval_reason?: string;
  approval_author?: string;
  confirm_delivery_risk?: boolean;
  preview_job_id?: string;
}) => postWithRevision<unknown>(
  "/api/data/plan/move-apply",
  revisionBody(body),
  COMPUTE_OPTIONS,
).then(normalizeManualMoveResponse);

export const getManualEdits = () =>
  get<{ active: boolean; edits: ManualEdit[]; can_revert: boolean }>("/api/data/plan/edits");

// ── Console ──────────────────────────────────────────────────

export const getConsole = (dayIdx = 0) =>
  analyticGet<ConsoleData>(`/api/console?day_idx=${dayIdx}`);

// ── Actions ──────────────────────────────────────────────────

export const simulate = (mutations: MutationInput[]) =>
  post<SimulateResponse>("/api/data/simulate", { mutations }, COMPUTE_OPTIONS);

export const simulateApply = (
  mutations: MutationInput[],
  approval: { reason: string; author: string } | undefined,
  candidate: CandidateIdentity,
) =>
  post<SimulateApplyResponse>(
    "/api/data/simulate-apply",
    {
      ...candidateApplyBody(candidate),
      mutations,
      approve_exceptions: Boolean(approval),
      approval_reason: approval?.reason ?? "",
      approval_author: approval?.author ?? "",
    },
    COMPUTE_OPTIONS,
  );

export const revertSimulation = () =>
  postWithRevision<{ status: string; score: Score }>(
    "/api/data/revert",
    {},
  );

export const canRevert = () =>
  get<{ can_revert: boolean }>("/api/data/can-revert");

export const getActiveMutations = () =>
  get<{ active: boolean; mutations: MutationInput[] }>("/api/data/active-mutations");

export const checkCTP = (sku: string, qty: number, deadline: number) =>
  post<CTPResult>("/api/data/ctp", { sku, qty, deadline }, COMPUTE_OPTIONS);

export const applyCTP = (
  sku: string,
  qty: number,
  deadline: number,
  approval: { reason: string; author: string } | undefined,
  candidate: CandidateIdentity,
) =>
  post<SimulateApplyResponse>(
    "/api/data/ctp-apply",
    {
      ...candidateApplyBody(candidate),
      sku,
      qty,
      deadline,
      approve_exceptions: Boolean(approval),
      approval_reason: approval?.reason ?? "",
      approval_author: approval?.author ?? "",
    },
    COMPUTE_OPTIONS,
  );

export const recalculate = (
  approval?: { reason: string; author: string },
) => postWithRevision<{
  status: string;
  score: Score;
  score_previous: Score;
  time_ms: number;
  n_segments: number;
}>("/api/data/recalculate", {
  compact_active_plan: true,
  approve_exceptions: Boolean(approval),
  approval_reason: approval?.reason ?? "",
  approval_author: approval?.author ?? "",
});

// ── Upload ───────────────────────────────────────────────────

const loadRequestOptions = { blocking: false, timeoutMs: 15000 };
export const AUTOMATIC_LOAD_APPROVAL = {
  reason: "Aceitação automática das exceções permitidas no carregamento do ISOP.",
  author: "sistema",
};

export const uploadISOP = (file: File, requestId: string, expectedRevision: number) =>
  upload<LoadJobResponse>(
    `/api/data/load?${new URLSearchParams({
      expected_revision: String(expectedRevision), assume_machines_free: "true",
      approve_exceptions: "true", approval_reason: AUTOMATIC_LOAD_APPROVAL.reason,
      approval_author: AUTOMATIC_LOAD_APPROVAL.author,
    })}`,
    file, { request_id: requestId }, { blocking: false, timeoutMs: 120000 },
  );

export const prepareISOP = (file: File, requestId: string) =>
  upload<LoadJobResponse>("/api/data/load/prepare", file, { request_id: requestId },
    { blocking: false, timeoutMs: 120000 });

// A job keeps its original revision. Never auto-retry an import with a newer
// revision: that would silently overwrite a plan changed by another operator.
export const confirmPreparedISOP = (token: string, expectedRevision: number) =>
  post<LoadJobResponse>("/api/data/load/confirm", {
    token, expected_revision: expectedRevision, mode: "all_free",
  }, loadRequestOptions);

export const getLoadJob = (id: string) =>
  get<LoadJobResponse>(`/api/data/load/jobs/${encodeURIComponent(id)}`, { timeoutMs: 10000 });

export const approveLoadJob = (id: string, expectedRevision: number, approval: { reason: string; author: string }) =>
  post<LoadJobResponse>(`/api/data/load/jobs/${encodeURIComponent(id)}/approve`, {
    expected_revision: expectedRevision,
    approval_reason: approval.reason, approval_author: approval.author,
  }, loadRequestOptions);

export const cancelLoadJob = (id: string) =>
  post<LoadJobResponse>(`/api/data/load/jobs/${encodeURIComponent(id)}/cancel`, {}, loadRequestOptions);

// ── Chat ─────────────────────────────────────────────────────

export const chatCopilot = (messages: { role: string; content: string }[]) =>
  post<ChatResponse>("/api/copilot/chat", { messages });

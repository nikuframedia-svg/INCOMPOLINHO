// Config edits that need explicit approval (NOK #5 of the 07/10/2026 factory test:
// non-working days were always refused because the UI never sent approval).
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  addExtraWorkday,
  addHoliday,
  addHolidayRange,
  addTwin,
  applyPreset,
  removeExtraWorkday,
  removeHoliday,
  removeHolidayRange,
  removeTwin,
  replaceSetupOverrides,
  resetSkuPlanning,
  updateOperators,
  updateSkuPlanning,
} from "../src/api/endpoints";
import { sendWithGateApproval, type GateApproval } from "../src/lib/gateApproval";
import { commitPlanRevision } from "../src/lib/planRevision";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let revision = 5000;
beforeEach(() => { sessionStorage.clear(); commitPlanRevision(++revision, "dataset-a"); });
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

const approvalRequired = () => ({
  detail: {
    message: "O candidato exige aprovação explícita: delivery_risk, long_production.",
    candidate_id: `calendar-${revision}`, dataset_id: "dataset-a", base_revision: revision,
    input_fingerprint: "input", candidate_fingerprint: "result",
    gate_report: {
      requires_approval: true, apply_decision: "approval_required",
      approval_reasons: ["delivery_risk", "long_production"], metrics: { tardy_count: 9 },
    },
  },
});
const body = (fetch: ReturnType<typeof vi.fn>, index: number) => JSON.parse(fetch.mock.calls[index][1].body);

it("asks for a justification and applies exactly the presented holiday candidate", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(approvalRequired(), 409))
    .mockResolvedValueOnce(response({ status: "ok", plan_revision: revision + 1 }));
  vi.stubGlobal("fetch", fetch);
  const ask = vi.fn().mockResolvedValue("Fecho acordado com a fábrica");

  const result = await sendWithGateApproval((approval) => addHoliday("2026-12-24", approval), ask);

  expect(result).toMatchObject({ status: "ok" });
  expect(ask).toHaveBeenCalledOnce();
  expect(ask.mock.calls[0][0].approval_reasons).toEqual(["delivery_risk", "long_production"]);
  expect(body(fetch, 0)).not.toHaveProperty("approve_exceptions");
  expect(body(fetch, 1)).toMatchObject({
    data: "2026-12-24", candidate_id: `calendar-${revision}`, approve_exceptions: true,
    approval_reason: "Fecho acordado com a fábrica", approval_author: "planeador",
    expected_revision: revision, request_id: body(fetch, 0).request_id,
  });
});

it("applies nothing when the planner cancels", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(approvalRequired(), 409));
  vi.stubGlobal("fetch", fetch);

  const result = await sendWithGateApproval(
    (approval) => addHolidayRange("2026-12-24", "2026-12-31", approval), () => Promise.resolve(null),
  );

  expect(result).toBeNull();
  expect(fetch).toHaveBeenCalledOnce();
});

it("asks again after a cancelled attempt is resubmitted", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(approvalRequired(), 409))
    .mockResolvedValueOnce(response(approvalRequired(), 409))
    .mockResolvedValueOnce(response({ status: "ok" }));
  vi.stubGlobal("fetch", fetch);
  const ask = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce("Revisto");

  expect(await sendWithGateApproval((a) => removeHoliday("2026-12-25", a), ask)).toBeNull();
  expect(await sendWithGateApproval((a) => removeHoliday("2026-12-25", a), ask)).toMatchObject({ status: "ok" });
  expect(ask).toHaveBeenCalledTimes(2);
});

it("does not ask for approval on other errors", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ detail: { code: "stale_preview", message: "mudou" } }, 409));
  vi.stubGlobal("fetch", fetch);
  const ask = vi.fn();

  await expect(sendWithGateApproval((a) => addHoliday("2026-12-24", a), ask)).rejects.toMatchObject({ status: 409 });
  expect(ask).not.toHaveBeenCalled();
});

const approval: GateApproval = { reason: "Revisto", author: "planeador" };
const APPROVED_FIELDS = { approve_exceptions: true, approval_reason: "Revisto", approval_author: "planeador" };

it.each([
  ["addHoliday", () => addHoliday("2026-12-24", approval)],
  ["removeHoliday", () => removeHoliday("2026-12-24", approval)],
  ["addHolidayRange", () => addHolidayRange("2026-12-24", "2026-12-31", approval)],
  ["removeHolidayRange", () => removeHolidayRange("2026-12-24", "2026-12-31", approval)],
  ["addExtraWorkday", () => addExtraWorkday("2026-12-19", approval)],
  ["removeExtraWorkday", () => removeExtraWorkday("2026-12-19", approval)],
  ["replaceSetupOverrides", () => replaceSetupOverrides([], approval)],
  ["updateOperators", () => updateOperators({ "Grandes.A": 6 }, approval)],
  ["addTwin", () => addTwin("T1", "A", "B", approval)],
  ["removeTwin", () => removeTwin("T1", approval)],
  ["applyPreset", () => applyPreset("default", approval)],
  ["updateSkuPlanning", () => updateSkuPlanning("SKU1", {}, approval)],
  ["resetSkuPlanning", () => resetSkuPlanning("SKU1", approval)],
])("%s sends the planner's approval", async (_name, call) => {
  const fetch = vi.fn().mockResolvedValue(response({ status: "ok" }));
  vi.stubGlobal("fetch", fetch);
  await call();
  expect(body(fetch, 0)).toMatchObject({ ...APPROVED_FIELDS, expected_revision: revision });
});

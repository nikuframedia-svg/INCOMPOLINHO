import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";
import { recalculate, updateConfig } from "../src/api/endpoints";
import { commitPlanRevision } from "../src/lib/planRevision";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const approval = { reason: "Reviewed exact result", author: "planner" };
let nextRevision = 1000;
beforeEach(() => { sessionStorage.clear(); commitPlanRevision(++nextRevision, "dataset-a"); });
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
const detail = () => ({
  candidate_id: `recompute-${nextRevision}`, dataset_id: "dataset-a", base_revision: nextRevision,
  input_fingerprint: "input", candidate_fingerprint: "result", gate_report: { requires_approval: true },
});
const body = (fetch: ReturnType<typeof vi.fn>, index: number) => JSON.parse(fetch.mock.calls[index][1].body);

it("confirms the presented recompute without automatic resubmission", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ detail: detail() }, 409))
    .mockResolvedValueOnce(response({ plan_revision: nextRevision + 1 }));
  vi.stubGlobal("fetch", fetch);
  await expect(recalculate()).rejects.toMatchObject({ status: 409 });
  expect(fetch).toHaveBeenCalledTimes(1);
  await recalculate(approval);
  expect(body(fetch, 0).candidate_id).toBeUndefined();
  expect(body(fetch, 1)).toMatchObject({ candidate_id: detail().candidate_id, approve_exceptions: true,
    expected_revision: nextRevision, request_id: body(fetch, 0).request_id });
});

it("retains the exact candidate and operation after a lost application response", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ detail: detail() }, 409))
    .mockRejectedValueOnce(new TypeError("Response lost"))
    .mockResolvedValueOnce(response({ plan_revision: nextRevision + 1 }));
  vi.stubGlobal("fetch", fetch);
  await expect(recalculate()).rejects.toBeInstanceOf(ApiError);
  await expect(recalculate(approval)).rejects.toMatchObject({ status: 0 });
  await recalculate();
  expect(body(fetch, 2)).toMatchObject({ candidate_id: detail().candidate_id,
    request_id: body(fetch, 1).request_id, expected_revision: nextRevision });
});

it("does not reuse a confirmation for a changed draft or revision", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ detail: detail() }, 409))
    .mockImplementation(() => Promise.resolve(response({})));
  vi.stubGlobal("fetch", fetch);
  await expect(updateConfig({ oee_default: 0.66 })).rejects.toMatchObject({ status: 409 });
  await updateConfig({ oee_default: 0.44 }, approval);
  expect(body(fetch, 1).candidate_id).toBeUndefined();
  expect(body(fetch, 1).request_id).not.toBe(body(fetch, 0).request_id);
  commitPlanRevision(nextRevision + 1, "dataset-a");
  await updateConfig({ oee_default: 0.66 }, approval);
  expect(body(fetch, 2).candidate_id).toBeUndefined();
});

it("discards rejected candidate identity instead of rebasing the command", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response({ detail: detail() }, 409))
    .mockResolvedValueOnce(response({ detail: { code: "stale_preview" } }, 409))
    .mockResolvedValueOnce(response({}));
  vi.stubGlobal("fetch", fetch);
  await expect(recalculate()).rejects.toMatchObject({ status: 409 });
  await expect(recalculate(approval)).rejects.toMatchObject({ status: 409 });
  expect(fetch).toHaveBeenCalledTimes(2);
  await recalculate();
  expect(body(fetch, 2).candidate_id).toBeUndefined();
  expect(body(fetch, 2).expected_revision).toBe(nextRevision);
});

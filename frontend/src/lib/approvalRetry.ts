import { ApiError } from "../api/client";
import type { CandidateIdentity } from "../api/types";
import { hasCandidateIdentity } from "./previewCandidate";

const STORAGE_KEY = "incompolinho-approval-candidates-v1";
const candidates = new Map<string, CandidateIdentity>();

try {
  const stored: unknown = JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "[]");
  if (Array.isArray(stored)) for (const pair of stored.slice(-100)) {
    if (Array.isArray(pair) && typeof pair[0] === "string" && hasCandidateIdentity(pair[1])) {
      candidates.set(pair[0], pair[1]);
    }
  }
} catch { /* In-memory retries still use the presented candidate. */ }

function persist() {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...candidates])); } catch { /* Optional storage. */ }
}

export async function withApprovalCandidate<T>(
  operationId: string,
  body: Record<string, unknown>,
  send: (body: Record<string, unknown>) => Promise<T>,
): Promise<T> {
  const candidate = candidates.get(operationId);
  const input = !body.candidate_id && candidate && candidate.base_revision === body.expected_revision
    ? { ...body, candidate_id: candidate.candidate_id } : body;
  try {
    const response = await send(input);
    candidates.delete(operationId);
    persist();
    return response;
  } catch (error) {
    if (error instanceof ApiError && error.status === 409 && !body.candidate_id) {
      const detail = error.detail as (CandidateIdentity & { gate_report?: { requires_approval?: boolean } }) | undefined;
      if (hasCandidateIdentity(detail) && detail?.gate_report?.requires_approval === true
        && detail.base_revision === body.expected_revision) {
        const { candidate_id, dataset_id, base_revision, input_fingerprint, candidate_fingerprint } = detail;
        candidates.set(operationId, { candidate_id, dataset_id, base_revision, input_fingerprint, candidate_fingerprint });
        while (candidates.size > 100) candidates.delete(candidates.keys().next().value!);
      } else {
        candidates.delete(operationId);
      }
      persist();
    }
    throw error;
  }
}

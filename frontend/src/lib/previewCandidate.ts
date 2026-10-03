import type { CandidateIdentity } from "../api/types";

export function hasCandidateIdentity(value: CandidateIdentity | null | undefined): value is CandidateIdentity {
  return Boolean(value?.candidate_id && value.dataset_id
    && Number.isInteger(value.base_revision)
    && value.input_fingerprint && value.candidate_fingerprint);
}

export function candidateMatchesPlan(
  candidate: CandidateIdentity | null | undefined,
  datasetId: string | null,
  revision: number | null,
): candidate is CandidateIdentity {
  return hasCandidateIdentity(candidate)
    && candidate.dataset_id === datasetId && candidate.base_revision === revision;
}

export function candidateApplyBody(candidate: CandidateIdentity) {
  if (!hasCandidateIdentity(candidate)) {
    throw new Error("A verificação não identifica um candidato válido. Verifica novamente.");
  }
  return {
    candidate_id: candidate.candidate_id,
    dataset_id: candidate.dataset_id,
    base_revision: candidate.base_revision,
    input_fingerprint: candidate.input_fingerprint,
    candidate_fingerprint: candidate.candidate_fingerprint,
    // Retries, including approval and lost responses, consume the same candidate once.
    request_id: `apply-${candidate.candidate_id}`,
    expected_revision: candidate.base_revision,
  };
}

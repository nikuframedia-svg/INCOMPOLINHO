export type RefreshOutcome = "updated" | "superseded" | "failed";

export class RefreshError extends Error {
  applied: boolean;
  outcome: RefreshOutcome;
  constructor(applied: boolean, outcome: RefreshOutcome) {
    super(applied
      ? "A alteração foi guardada. O ecrã ainda não mostra a versão nova: atualiza a página (não é preciso voltar a aplicar)."
      : outcome === "superseded" ? "Esta atualização foi substituída por um pedido mais recente."
        : "Não foi possível atualizar os dados. O ecrã conserva o último plano confirmado.");
    this.applied = applied;
    this.outcome = outcome;
  }
}

export function assertRefreshed(outcome: RefreshOutcome, applied = false): void {
  if (outcome !== "updated") throw new RefreshError(applied, outcome);
}

/** True when the write succeeded and only the screen refresh is missing. */
export function isAppliedRefreshError(error: unknown): error is RefreshError {
  return error instanceof RefreshError && error.applied;
}

const COMMIT_REFRESH_DELAYS_MS = [1000, 3000];

/**
 * Refresh after a successful write. A failed read is retried (reads only;
 * the write is never repeated) before reporting that the screen is behind.
 */
export async function refreshAfterCommit(
  refresh: () => Promise<RefreshOutcome>,
  delays: readonly number[] = COMMIT_REFRESH_DELAYS_MS,
): Promise<RefreshOutcome> {
  let outcome = await refresh();
  for (const delay of delays) {
    if (outcome !== "failed") return outcome;
    await new Promise((resolve) => setTimeout(resolve, delay));
    outcome = await refresh();
  }
  return outcome;
}

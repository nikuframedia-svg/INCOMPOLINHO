export type RefreshOutcome = "updated" | "superseded" | "failed";

export class RefreshError extends Error {
  applied: boolean;
  outcome: RefreshOutcome;
  constructor(applied: boolean, outcome: RefreshOutcome) {
    super(applied
      ? "Aplicado; ecrã por atualizar. A alteração está guardada. Atualiza os dados, sem voltar a aplicar."
      : outcome === "superseded" ? "Esta atualização foi substituída por um pedido mais recente."
        : "Não foi possível atualizar os dados. O ecrã conserva o último plano confirmado.");
    this.applied = applied;
    this.outcome = outcome;
  }
}

export function assertRefreshed(outcome: RefreshOutcome, applied = false): void {
  if (outcome !== "updated") throw new RefreshError(applied, outcome);
}

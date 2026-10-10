/**
 * Plain Portuguese text for a failed background job (re-plan or move check).
 *
 * The backend stores a stable `code` and Portuguese `message`/`error`. Older
 * jobs (or an unexpected path) may still carry raw exception text, often in
 * English ("Planning deadline expired; candidate not committed."); that text
 * is never shown to the planner.
 */

export interface FailedJobLike {
  code?: string | null;
  message?: string | null;
  error?: string | null;
}

/** "replan": replaneamento (pode mudar a configuração); "move": verificação de um movimento de lote. */
export type JobFailureContext = "replan" | "move";

const CODE_TEXT: Record<JobFailureContext, Record<string, string>> = {
  replan: {
    planning_timeout:
      "Tempo de cálculo esgotado sem um plano válido. Isto não prova que a alteração seja impossível. O plano e a configuração não foram alterados.",
    invalid_plan:
      "Não foi possível obter um plano válido com esta alteração. O plano e a configuração não foram alterados.",
    blocked:
      "O plano proposto tem conflitos físicos ou peças em falta. O plano e a configuração não foram alterados.",
    internal_error:
      "Ocorreu um erro interno durante o cálculo. O plano e a configuração não foram alterados. Tente novamente; se repetir, avise o suporte.",
    interrupted:
      "O replaneamento foi interrompido (o servidor reiniciou ou o cálculo parou). O plano e a configuração não foram alterados. Pode iniciar novamente.",
  },
  move: {
    planning_timeout:
      "Tempo de cálculo esgotado sem um plano válido. Isto não prova que o movimento seja impossível. O plano não foi alterado.",
    invalid_plan:
      "Não foi possível obter um plano válido com este movimento. O plano não foi alterado.",
    blocked:
      "O plano proposto tem conflitos físicos ou peças em falta. O plano não foi alterado.",
    internal_error:
      "Ocorreu um erro interno durante o cálculo. O plano não foi alterado. Tente novamente; se repetir, avise o suporte.",
    interrupted:
      "A verificação do movimento foi interrompida (o servidor reiniciou ou o cálculo parou). O plano não foi alterado. Pode tentar novamente.",
  },
};

// Raw runtime/exception text that must never reach the screen.
const RAW_TEXT = [
  /deadline expired/i,
  /candidate not committed/i,
  /planning cancelled/i,
  /traceback/i,
  /\b(?:Key|Type|Value|Attribute|Index|Runtime|Assertion)Error\b/,
  /\bexception\b/i,
  /object has no attribute/i,
  // Só o "None" do Python (NoneType, "is None", "= None"); não deita fora
  // uma mensagem portuguesa que por acaso tenha a palavra.
  /\bNoneType\b|\bis None\b|=\s*None\b/,
];

export function isRawErrorText(text: string): boolean {
  return RAW_TEXT.some((pattern) => pattern.test(text));
}

function readable(text: string | null | undefined): string | null {
  const value = (text ?? "").trim();
  return value && !isRawErrorText(value) ? value : null;
}

/** Best Portuguese explanation of a failed job; `fallback` when nothing usable. */
export function jobFailureText(
  job: FailedJobLike,
  fallback: string,
  context: JobFailureContext = "replan",
): string {
  const error = readable(job.error);
  if (error) return error;
  const known = job.code ? CODE_TEXT[context][job.code] : undefined;
  if (known) return known;
  return readable(job.message) ?? fallback;
}

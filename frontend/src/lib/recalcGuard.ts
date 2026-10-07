/**
 * "Recalcular plano" reviews the whole ISOP from its first day (decision of
 * 06/10/2026, kept on 07/10). With an ISOP older than today that can place
 * production on days that have already passed, so the planner is warned and
 * advised to load today's ISOP first. Returns null when the ISOP is current.
 */
export function staleIsopWarning(
  today: { today_idx: number; date: string } | null,
  isopFirstDay: string | undefined,
): string | null {
  if (!today || today.today_idx <= 0 || !isopFirstDay) return null;
  const [, month, day] = isopFirstDay.slice(0, 10).split("-");
  const from = day && month ? `${day}/${month}` : isopFirstDay;
  return [
    `O ISOP carregado começa a ${from}, antes de hoje.`,
    "Recalcular revê o plano desde essa data e pode colocar produção em dias que já passaram.",
    "Recomendado: carregar o ISOP de hoje antes de recalcular.",
  ].join("\n");
}

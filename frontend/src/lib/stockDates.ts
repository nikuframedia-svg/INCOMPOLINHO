const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const DOWS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"];

type StockoutDayEntry = { date?: string | null; day?: number; day_idx?: number };

export function parseStockDate(iso: string | null | undefined): { short: string; dow: string } | null {
  if (typeof iso !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return null;
  const [, year, month, day] = match.map(Number);
  const date = new Date(Number(year), Number(month) - 1, Number(day), 12);
  if (
    Number.isNaN(date.getTime())
    || date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
  ) return null;
  return {
    short: `${String(day).padStart(2, "0")}-${MONTHS[month - 1]}`,
    dow: DOWS[date.getDay()],
  };
}

export function formatStockoutLabel(
  stockoutDay: number | null,
  days: readonly StockoutDayEntry[],
): string | null {
  if (stockoutDay === null) return null;
  const matchingDay = days.find((day) => (day.day ?? day.day_idx) === stockoutDay);
  const date = matchingDay ? parseStockDate(matchingDay.date)?.short : null;
  return `esgota dia ${stockoutDay}${date ? ` (${date})` : ""}`;
}

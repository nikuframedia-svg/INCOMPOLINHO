import type { Segment } from "../api/types";

type DeliveryAllocation = NonNullable<Segment["delivery_allocations"]>[number];

// Desloca os dias (que podem ser negativos nos dias de margem) para uma chave
// de ordenação sempre positiva; segmentos sem entregas vão para o fim.
const SORT_DAY_OFFSET = 10000;
const NO_DELIVERY_SORT_KEY = 99999;

function fmtQty(qty: number): string {
  return `${qty.toLocaleString("pt-PT")} pç`;
}

/** "2026-10-26" -> "26/10" (o dia útil vai à parte, como "dia N"). */
export function fmtDeliveryDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return day && month ? `${day}/${month}` : isoDate;
}

/**
 * O único formato de dia no Gantt (tooltip e janela de detalhe):
 * "dia 13 (26/10)", ou só "dia 13" sem data conhecida. Em minúscula, para
 * usar a meio de uma frase; no início de uma linha usar capitalize().
 */
export function fmtWorkday(day: number, isoDate?: string | null): string {
  return isoDate ? `dia ${day} (${fmtDeliveryDate(isoDate)})` : `dia ${day}`;
}

/** Primeira letra em maiúscula (início de linha ou de célula). */
export function capitalize(text: string): string {
  return text ? `${text.charAt(0).toUpperCase()}${text.slice(1)}` : text;
}

/** Texto quando o segmento ainda não tem entregas atribuídas. */
export const DELIVERIES_NOT_CALCULATED = "Entregas deste segmento ainda não calculadas";

function sortedAllocations(segment: Segment): DeliveryAllocation[] {
  return [...(segment.delivery_allocations ?? [])].sort((left, right) =>
    left.delivery_day - right.delivery_day
    || left.delivery_date.localeCompare(right.delivery_date)
    || left.sku.localeCompare(right.sku)
    || left.client.localeCompare(right.client),
  );
}

function hasProduction(segment: Segment): boolean {
  return !(segment.prod_min <= 0 && segment.qty <= 0);
}

function hasAllocationData(segment: Segment): boolean {
  return segment.delivery_allocations != null && segment.unallocated_output != null;
}

/** "dia 13 (26/10)" */
function deliveryWhen(entry: DeliveryAllocation): string {
  return fmtWorkday(entry.delivery_day, entry.delivery_date);
}

/** "dia 13 (26/10) · F. POLSKA · 494 pç"; com a referência quando o segmento produz várias (gémeas). */
function deliveryLine(entry: DeliveryAllocation, showSku: boolean): string {
  return [deliveryWhen(entry), ...(showSku ? [entry.sku] : []), entry.client, fmtQty(entry.qty)].join(" · ");
}

function showsSeveralSkus(segment: Segment): boolean {
  const skus = new Set([
    ...(segment.delivery_allocations ?? []).map((entry) => entry.sku),
    ...(segment.unallocated_output ?? []).map((entry) => entry.sku),
  ]);
  return skus.size > 1;
}

function surplusLine(segment: Segment, showSku: boolean): string | null {
  const surplus = (segment.unallocated_output ?? []).filter((entry) => entry.qty > 0);
  if (!surplus.length) return null;
  if (!showSku) {
    const total = surplus.reduce((sum, entry) => sum + entry.qty, 0);
    return `Excedente: ${fmtQty(total)} (fica em stock)`;
  }
  return `Excedente: ${surplus.map((entry) => `${entry.sku} ${fmtQty(entry.qty)}`).join(", ")} (fica em stock)`;
}

/** Linhas do tooltip nativo: próxima entrega, até onde cobre e o excedente. */
export function segmentDeliveryTooltipLines(segment: Segment): string[] {
  if (!hasProduction(segment)) return [];
  if (!hasAllocationData(segment)) return [DELIVERIES_NOT_CALCULATED];
  const allocations = sortedAllocations(segment);
  const showSku = showsSeveralSkus(segment);
  const lines: string[] = [];
  if (allocations.length) {
    lines.push(`Próxima entrega: ${deliveryLine(allocations[0], showSku)}`);
    if (allocations.length > 1) {
      lines.push(`Cobre até ${deliveryWhen(allocations[allocations.length - 1])} — ${allocations.length} entregas no total`);
    }
  }
  const surplus = surplusLine(segment, showSku);
  if (surplus) lines.push(surplus);
  return lines.length ? lines : ["Sem peças neste segmento"];
}

function subcontractedSkus(segment: Segment): Set<string> | null {
  const outputs = segment.output_milestones ?? [];
  if (outputs.length) return new Set(outputs.filter((output) => output.is_subcontracted).map((output) => output.sku));
  return segment.is_subcontracted ? null : new Set();
}

function joinWithAnd(items: string[]): string {
  return items.length > 1 ? `${items.slice(0, -1).join(", ")} e ${items[items.length - 1]}` : items.join("");
}

/**
 * "Subcontratado — volta a 19/10" para um segmento de uma referência
 * subcontratada. O dia de regresso vem do servidor (customer_ready_day de cada
 * entrega); dateAt só converte o dia útil em data. Null se não é subcontratado.
 */
export function segmentSubcontractLine(
  segment: Segment,
  dateAt: (day: number) => string | null,
): string | null {
  const skus = subcontractedSkus(segment);
  if ((skus && !skus.size) || !hasProduction(segment)) return null;
  const returnDays = [...new Set(
    (segment.delivery_allocations ?? [])
      .filter((entry) => !skus || skus.has(entry.sku))
      .map((entry) => entry.customer_ready_day),
  )].sort((left, right) => left - right);
  if (!returnDays.length) return "Subcontratado";
  const labels = returnDays.map((day) => {
    const isoDate = dateAt(day);
    return isoDate ? fmtDeliveryDate(isoDate) : `dia ${day}`;
  });
  return `Subcontratado — volta a ${joinWithAnd(labels)}`;
}

/** Uma linha por entrega (e o excedente no fim), para a janela de detalhe e a tabela. */
export function segmentDeliveryLines(segment: Segment): string[] {
  if (!hasProduction(segment)) return ["Preparação do lote"];
  if (!hasAllocationData(segment)) return [DELIVERIES_NOT_CALCULATED];
  const showSku = showsSeveralSkus(segment);
  const lines = sortedAllocations(segment).map((entry) => capitalize(deliveryLine(entry, showSku)));
  const surplus = surplusLine(segment, showSku);
  if (surplus) lines.push(surplus);
  return lines.length ? lines : ["Sem peças neste segmento"];
}

export function segmentDeliveriesText(segment: Segment): string {
  return segmentDeliveryLines(segment).join("; ");
}

/** Dia útil da primeira entrega abastecida pelo segmento, ou null. */
export function segmentFirstDeliveryDay(segment: Segment): number | null {
  if (!hasProduction(segment)) return null;
  const allocations = sortedAllocations(segment);
  return allocations.length ? allocations[0].delivery_day : null;
}

/**
 * Valor de ordenação/pesquisa da coluna de entregas: começa pelo dia da
 * primeira entrega com largura fixa (ordem numérica, não alfabética) e mantém
 * o texto para a pesquisa por cliente.
 */
export function segmentDeliveriesSortValue(segment: Segment): string {
  const day = segmentFirstDeliveryDay(segment);
  const key = day == null ? NO_DELIVERY_SORT_KEY : day + SORT_DAY_OFFSET;
  return `${String(key).padStart(5, "0")} ${segmentDeliveriesText(segment)}`;
}

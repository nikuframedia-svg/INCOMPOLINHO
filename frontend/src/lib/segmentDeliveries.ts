import type { Segment } from "../api/types";

export function segmentDeliveriesText(segment: Segment): string {
  if (segment.prod_min <= 0 && segment.qty <= 0) return "Preparação do lote";
  if (segment.delivery_allocations == null || segment.unallocated_output == null) {
    return "Alocação a entregas não disponível";
  }
  const deliveries = segment.delivery_allocations.map((entry) => {
    const date = entry.delivery_date.split("-").reverse().join("/");
    return `${entry.sku}: ${entry.qty.toLocaleString("pt-PT")} pç para ${entry.client}, entrega ${date}`;
  });
  const surplus = segment.unallocated_output.map((entry) =>
    `${entry.sku}: ${entry.qty.toLocaleString("pt-PT")} pç de excedente para stock`,
  );
  return [...deliveries, ...surplus].join("; ") || "Sem peças neste segmento";
}

import { describe, expect, it } from "vitest";
import type { Segment } from "../src/api/types";
import {
  DELIVERIES_NOT_CALCULATED,
  fmtDeliveryDate,
  fmtWorkday,
  segmentDeliveriesSortValue,
  segmentDeliveryLines,
  segmentDeliveryTooltipLines,
  segmentFirstDeliveryDay,
} from "../src/lib/segmentDeliveries";

const base = {
  lot_id: "L1", run_id: "R1", machine_id: "M1", tool_id: "T1", day_idx: 0,
  start_min: 420, end_min: 480, shift: "A", qty: 1000, prod_min: 45, setup_min: 0,
  is_continuation: false, edd: 0, sku: "SKU1", twin_outputs: null,
} satisfies Segment;

const delivery = (sku: string, client: string, qty: number, day: number, date: string) => ({
  sku, client, qty, delivery_day: day, delivery_date: date, customer_ready_day: day,
});

describe("segmentDeliveries", () => {
  it("formata a data como dd/mm", () => {
    expect(fmtDeliveryDate("2026-10-26")).toBe("26/10");
  });

  it("um só formato de dia: número operacional primeiro, data entre parênteses", () => {
    expect(fmtWorkday(13, "2026-10-26")).toBe("dia 13 (26/10)");
    expect(fmtWorkday(-2, null)).toBe("dia -2");
  });

  it("tooltip com uma entrega", () => {
    expect(segmentDeliveryTooltipLines({
      ...base, delivery_allocations: [delivery("SKU1", "F. POLSKA", 494, 13, "2026-10-26")], unallocated_output: [],
    })).toEqual(["Próxima entrega: dia 13 (26/10) · F. POLSKA · 494 pç"]);
  });

  it("tooltip com várias entregas e excedente, por ordem de dia", () => {
    expect(segmentDeliveryTooltipLines({
      ...base,
      delivery_allocations: [
        delivery("SKU1", "F. POLSKA", 300, 14, "2026-10-27"),
        delivery("SKU1", "F. POLSKA", 494, 13, "2026-10-26"),
      ],
      unallocated_output: [{ sku: "SKU1", qty: 206 }],
    })).toEqual([
      "Próxima entrega: dia 13 (26/10) · F. POLSKA · 494 pç",
      "Cobre até dia 14 (27/10) — 2 entregas no total",
      "Excedente: 206 pç (fica em stock)",
    ]);
  });

  it("tooltip só com excedente e sem dados de alocação", () => {
    expect(segmentDeliveryTooltipLines({ ...base, delivery_allocations: [], unallocated_output: [{ sku: "SKU1", qty: 1000 }] }))
      .toEqual(["Excedente: 1000 pç (fica em stock)"]);
    expect(segmentDeliveryTooltipLines(base)).toEqual([DELIVERIES_NOT_CALCULATED]);
    expect(DELIVERIES_NOT_CALCULATED).toBe("Entregas deste segmento ainda não calculadas");
    expect(segmentDeliveryLines(base)).toEqual([DELIVERIES_NOT_CALCULATED]);
    expect(segmentDeliveryTooltipLines({ ...base, qty: 0, prod_min: 0 })).toEqual([]);
  });

  it("gémeas mostram a referência em cada linha", () => {
    expect(segmentDeliveryLines({
      ...base,
      delivery_allocations: [delivery("SKU2", "C", 10, 3, "2026-10-14"), delivery("SKU1", "C", 20, 3, "2026-10-14")],
      unallocated_output: [{ sku: "SKU2", qty: 5 }],
    })).toEqual([
      "Dia 3 (14/10) · SKU1 · C · 20 pç",
      "Dia 3 (14/10) · SKU2 · C · 10 pç",
      "Excedente: SKU2 5 pç (fica em stock)",
    ]);
  });

  it("ordena numericamente pelo dia da primeira entrega, incluindo dias de margem", () => {
    const at = (day: number) => ({
      ...base, delivery_allocations: [delivery("SKU1", "C", 1, day, "2026-10-14")], unallocated_output: [],
    });
    const none = { ...base, delivery_allocations: [], unallocated_output: [{ sku: "SKU1", qty: 1 }] };
    const values = [at(100), none, at(13), at(-2), at(2)]
      .map((segment) => segmentDeliveriesSortValue(segment))
      .sort((a, b) => a.localeCompare(b));
    expect(values.map((value) => value.split(" ")[0])).toEqual(["09998", "10002", "10013", "10100", "99999"]);
    expect(segmentFirstDeliveryDay(at(13))).toBe(13);
    expect(segmentFirstDeliveryDay(none)).toBeNull();
  });

  it("quantidades no formato português", () => {
    expect(segmentDeliveryTooltipLines({
      ...base, qty: 12000,
      delivery_allocations: [delivery("SKU1", "C", 12000, 3, "2026-10-14")], unallocated_output: [],
    })).toEqual([`Próxima entrega: dia 3 (14/10) · C · ${(12000).toLocaleString("pt-PT")} pç`]);
    expect((12000).toLocaleString("pt-PT")).not.toBe("12,000");
  });
});

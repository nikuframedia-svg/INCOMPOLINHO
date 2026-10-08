import type { BlockedDaysResponse, Lot, Segment } from "../api/types";

export const JIT_MAX_ANTICIPATION_WORKDAYS = 5;

export type JitViolationReason =
  | "campaign_span"
  | "non_workday_start"
  | "twin_sequence"
  | "early_sequence";

export interface JitViolationDetail {
  lot_id: string;
  run_id: string;
  op_id: string;
  sku: string;
  tool_id: string;
  machine_id: string;
  qty: number;
  is_twin: boolean;
  start_day: number;
  start_date: string;
  delivery_day: number;
  delivery_date: string;
  customer_delivery_day: number;
  customer_delivery_date: string;
  material_reference_day: number;
  material_reference_date: string;
  material_reference_kind: string;
  production_due_day: number;
  production_due_date: string;
  subcontract_dispatch_day: number | null;
  subcontract_dispatch_date: string | null;
  earliest_allowed_start_day: number;
  earliest_allowed_start_date: string;
  anticipation_workdays: number;
  allowed_anticipation_workdays: number;
  excess_workdays: number;
  increment_workdays: number;
  reason_code: JitViolationReason;
  reason: string;
  campaign_lot_count: number;
  campaign_span_workdays: number;
}

export interface JitWindowAnalysis {
  violations: JitViolationDetail[];
  maxAnticipationWorkdays: number;
  averageAnticipationWorkdays: number;
}

function dateAt(workdays: string[], dayIdx: number): string {
  const direct = workdays[dayIdx];
  if (direct) return direct.slice(0, 10);
  const first = workdays[0];
  if (!first) return `D${dayIdx}`;
  const date = new Date(`${first.slice(0, 10)}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + dayIdx);
  return date.toISOString().slice(0, 10);
}

function buildNonWorkingDays(
  workdays: string[],
  blocked: BlockedDaysResponse | null,
  fromDay: number,
  toDay: number,
): Set<number> {
  const days = new Set((blocked?.holidays ?? []).map((entry) => entry.day_idx));
  for (let day = fromDay; day <= toDay; day += 1) {
    const iso = dateAt(workdays, day);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) continue;
    const weekday = new Date(`${iso}T00:00:00Z`).getUTCDay();
    if (weekday === 0 || weekday === 6) days.add(day);
  }
  return days;
}

function subtractWorkdays(dayIdx: number, count: number, nonWorking: Set<number>): number {
  let day = dayIdx;
  let remaining = count;
  while (remaining > 0) {
    day -= 1;
    if (!nonWorking.has(day)) remaining -= 1;
  }
  return day;
}

function workdaysBetween(startDay: number, endDay: number, nonWorking: Set<number>): number {
  let count = 0;
  for (let day = startDay + 1; day <= endDay; day += 1) {
    if (!nonWorking.has(day)) count += 1;
  }
  return count;
}

function customerDeliveryDay(lot: Lot): number {
  return lot.customer_delivery_day ?? lot.delivery_day ?? lot.original_edd ?? lot.edd;
}

function productionDueDay(lot: Lot): number {
  return lot.production_due_day ?? lot.edd;
}

function materialReferenceDay(lot: Lot): number {
  return lot.material_reference_day
    ?? lot.subcontract_dispatch_day
    ?? customerDeliveryDay(lot);
}

function materialReferenceKind(lot: Lot): string {
  if (lot.material_reference_kind) return lot.material_reference_kind;
  return lot.subcontract_dispatch_day != null || lot.is_subcontracted
    ? "subcontract_dispatch"
    : "customer_delivery";
}

function firstProductiveSegments(segments: Segment[]): Map<string, Segment> {
  const first = new Map<string, Segment>();
  for (const segment of segments) {
    if (segment.prod_min <= 0) continue;
    const previous = first.get(segment.lot_id);
    if (
      !previous
      || segment.day_idx < previous.day_idx
      || (segment.day_idx === previous.day_idx && segment.start_min < previous.start_min)
    ) {
      first.set(segment.lot_id, segment);
    }
  }
  return first;
}

function violationReason(
  lot: Lot,
  segment: Segment,
  nonWorking: Set<number>,
  campaignLotCount: number,
  campaignSpan: number,
): { code: JitViolationReason; text: string } {
  if (nonWorking.has(segment.day_idx)) {
    return {
      code: "non_workday_start",
      text: "Começou num dia em que não devia existir produção e ainda antes da data permitida.",
    };
  }
  if (campaignLotCount > 1 && campaignSpan > JIT_MAX_ANTICIPATION_WORKDAYS) {
    return {
      code: "campaign_span",
      text: `Foi produzido juntamente com outros ${campaignLotCount - 1} lotes para evitar outro setup. Como esses lotes saem em datas muito diferentes, este começou cedo demais.`,
    };
  }
  if (lot.is_twin) {
    return {
      code: "twin_sequence",
      text: "Foi antecipado juntamente com o artigo gémeo para aproveitar a mesma produção.",
    };
  }
  return {
    code: "early_sequence",
    text: "O planeamento colocou esta produção antes da primeira data permitida.",
  };
}

export function analyseJitWindow(
  segments: Segment[],
  lots: Lot[],
  workdays: string[],
  blocked: BlockedDaysResponse | null,
): JitWindowAnalysis {
  const first = firstProductiveSegments(segments);
  const startDays = [...first.values()].map((segment) => segment.day_idx);
  const milestoneDays = lots.flatMap((lot) => [
    customerDeliveryDay(lot),
    productionDueDay(lot),
    materialReferenceDay(lot),
    ...(lot.material_release_day == null ? [] : [lot.material_release_day]),
  ]);
  const minDay = Math.min(...startDays, ...milestoneDays, 0) - 14;
  const maxDay = Math.max(...startDays, ...milestoneDays, workdays.length - 1, 0) + 14;
  const nonWorking = buildNonWorkingDays(workdays, blocked, minDay, maxDay);

  const lotById = new Map(lots.map((lot) => [lot.id, lot]));
  const campaignLots = new Map<string, Set<string>>();
  for (const [lotId, segment] of first) {
    if (!lotById.has(lotId)) continue;
    const ids = campaignLots.get(segment.run_id) ?? new Set<string>();
    ids.add(lotId);
    campaignLots.set(segment.run_id, ids);
  }

  const campaignStats = new Map<string, { count: number; span: number }>();
  for (const [runId, ids] of campaignLots) {
    const dueDays = [...ids]
      .map((id) => lotById.get(id))
      .filter((lot): lot is Lot => Boolean(lot))
      .map(materialReferenceDay);
    const firstDue = Math.min(...dueDays);
    const lastDue = Math.max(...dueDays);
    campaignStats.set(runId, {
      count: ids.size,
      span: dueDays.length ? workdaysBetween(firstDue, lastDue, nonWorking) : 0,
    });
  }

  const anticipations: number[] = [];
  const violations: JitViolationDetail[] = [];
  for (const lot of lots) {
    const segment = first.get(lot.id);
    if (!segment) continue;
    const customerDelivery = customerDeliveryDay(lot);
    const reference = materialReferenceDay(lot);
    const earliest = lot.material_release_day
      ?? subtractWorkdays(reference, JIT_MAX_ANTICIPATION_WORKDAYS, nonWorking);
    const anticipation = workdaysBetween(segment.day_idx, reference, nonWorking);
    anticipations.push(anticipation);
    if (segment.day_idx >= earliest) continue;

    const campaign = campaignStats.get(segment.run_id) ?? { count: 1, span: 0 };
    const reason = violationReason(
      lot,
      segment,
      nonWorking,
      campaign.count,
      campaign.span,
    );
    const excess = Math.max(0, anticipation - JIT_MAX_ANTICIPATION_WORKDAYS);
    violations.push({
      lot_id: lot.id,
      run_id: segment.run_id,
      op_id: lot.op_id,
      sku: segment.sku,
      tool_id: lot.tool_id,
      machine_id: segment.machine_id,
      qty: lot.qty,
      is_twin: lot.is_twin,
      start_day: segment.day_idx,
      start_date: dateAt(workdays, segment.day_idx),
      delivery_day: customerDelivery,
      delivery_date: dateAt(workdays, customerDelivery),
      customer_delivery_day: customerDelivery,
      customer_delivery_date: dateAt(workdays, customerDelivery),
      material_reference_day: reference,
      material_reference_date: dateAt(workdays, reference),
      material_reference_kind: materialReferenceKind(lot),
      production_due_day: productionDueDay(lot),
      production_due_date: dateAt(workdays, productionDueDay(lot)),
      subcontract_dispatch_day: lot.subcontract_dispatch_day ?? null,
      subcontract_dispatch_date: lot.subcontract_dispatch_day == null
        ? null
        : dateAt(workdays, lot.subcontract_dispatch_day),
      earliest_allowed_start_day: earliest,
      earliest_allowed_start_date: dateAt(workdays, earliest),
      anticipation_workdays: anticipation,
      allowed_anticipation_workdays: JIT_MAX_ANTICIPATION_WORKDAYS,
      excess_workdays: excess,
      increment_workdays: excess,
      reason_code: reason.code,
      reason: reason.text,
      campaign_lot_count: campaign.count,
      campaign_span_workdays: campaign.span,
    });
  }

  violations.sort(
    (a, b) => b.excess_workdays - a.excess_workdays
      || a.material_reference_day - b.material_reference_day
      || a.lot_id.localeCompare(b.lot_id),
  );
  return {
    violations,
    maxAnticipationWorkdays: Math.max(...anticipations, 0),
    averageAnticipationWorkdays: anticipations.length
      ? Math.round((anticipations.reduce((sum, value) => sum + value, 0) / anticipations.length) * 10) / 10
      : 0,
  };
}

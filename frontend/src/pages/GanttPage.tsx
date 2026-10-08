import { useEffect, useMemo, useRef, useState } from "react";
import { T, toolColor } from "../theme/tokens";
import { useDataStore } from "../stores/useDataStore";
import { getToday } from "../api/endpoints";
import type { BlockedDaysResponse, CapacityResponse, FactoryConfig, Lot, MutationInput, PlacementReason, Score, Segment } from "../api/types";
import { Card } from "../components/ui/Card";
import { ProgressBar } from "../components/ui/ProgressBar";
import { Modal } from "../components/ui/Modal";
import { DataTable, type DataColumn } from "../components/ui/DataTable";
import { PlansDrawer } from "../components/PlansDrawer";
import { MoveLotModal } from "../components/MoveLotModal";
import { PlanSimulatorSection } from "../components/PlanSimulatorSection";
import { GateReportCard } from "../components/GateReportCard";
import { JitViolationPanel } from "../components/JitViolationPanel";
import { analyseJitWindow, type JitViolationDetail } from "../lib/jitAnalysis";

const DEFAULT_DAY_W = 110;
const LANE_H = 60;
const SHIFT_CHANGE = 930;
const DAY_START = 420;
const DAY_CAP = 1020;
const FALLBACK_MACHINES = ["PRM019", "PRM031", "PRM039", "PRM042", "PRM043"];
const SINGLE_BAR_H = 52;
const SINGLE_BAR_PAD = 8;
const MACHINE_COL_W = 104;
const GANTT_HEADER_H = 36;
const RESOURCE_ROW_H = 34;

type GanttOverlay = {
  kind: "machine_down" | "calendar_machine" | "holiday";
  machine_id: string;
  day_idx: number;
  start_min?: number;
  end_min?: number;
  category?: string;
  reason?: string;
  label: string;
};

type ResourceOverlay = {
  kind: "tool" | "machine" | "operator";
  resource_id: string;
  display_label: string;
  day_idx: number;
  start_min?: number;
  end_min?: number;
  category?: string;
  reason?: string;
  label: string;
  group?: string;
  shift?: string;
};

type PositionedResourceOverlay = ResourceOverlay & {
  left: number;
  width: number;
  level: number;
};

function isHistoricalPlacement(reason?: PlacementReason): boolean {
  return reason?.kind === "historical" || reason?.historical === true;
}

function placementReasonText(reason?: PlacementReason): string | null {
  if (!reason) return null;
  if (reason.kind === "manual") {
    const when = reason.start_at?.slice(0, 16).replace("T", " ") ?? "hora guardada";
    const motive = reason.reason ? ` Motivo: ${reason.reason}.` : "";
    return `Início da produção fixado manualmente em ${reason.machine_id ?? "máquina guardada"}, ${when}.${motive}${reason.historical ? " Plano passado; execução não confirmada na aplicação. Não pode ser movido." : ""}`;
  }
  if (reason.kind === "historical") {
    return "Plano passado; execução não confirmada na aplicação. Não pode ser movido. Alterações posteriores não reavaliaram este horário.";
  }
  return "Posição protegida; os bloqueios guardados de outras revisões não comprovam o horário atual.";
}

// ── Helpers ──────────────────────────────────────────────────

const MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"];
const DOWS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sab"];
const HOLIDAY_BACKGROUND = `${T.borderHover}1a`;
const HOLIDAY_PATTERN = `repeating-linear-gradient(-45deg, transparent 0, transparent 5px, ${T.tertiary}38 5px, ${T.tertiary}38 10px)`;

function matchesSearch(query: string, values: Array<string | null | undefined>): boolean {
  return !query || values.some((value) => value?.toLowerCase().includes(query));
}

function ganttOverlayAppearance(overlay: GanttOverlay) {
  if (overlay.kind === "holiday") {
    return {
      backgroundColor: HOLIDAY_BACKGROUND,
      backgroundImage: HOLIDAY_PATTERN,
      borderLeft: `1px solid ${T.borderHover}aa`,
      borderRight: `1px solid ${T.borderHover}66`,
    };
  }

  const color = overlay.category === "Ensaio"
    ? T.blue
    : overlay.kind === "machine_down" || overlay.kind === "calendar_machine"
      ? T.red
      : T.orange;
  return {
    backgroundColor: `${color}12`,
    backgroundImage: `repeating-linear-gradient(-45deg, transparent 0, transparent 6px, ${color}1f 6px, ${color}1f 12px)`,
    borderLeft: `1px solid ${color}55`,
    borderRight: `1px solid ${color}22`,
  };
}

function fmtDate(iso: string): { short: string; dow: string } {
  try {
    const d = new Date(iso + "T12:00:00");
    return {
      short: `${String(d.getDate()).padStart(2, "0")}-${MONTHS[d.getMonth()]}`,
      dow: DOWS[d.getDay()],
    };
  } catch {
    return { short: iso, dow: "" };
  }
}

function isoAtDay(workdays: string[], dayIdx: number): string | null {
  const direct = workdays[dayIdx];
  if (direct) return direct.slice(0, 10);
  const first = workdays[0];
  if (!first) return null;
  const date = new Date(`${first.slice(0, 10)}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + dayIdx);
  return date.toISOString().slice(0, 10);
}

function fmtMin(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h % 24).padStart(2, "0")}:${String(Math.round(m)).padStart(2, "0")}`;
}

function fmtDuration(min: number): string {
  const rounded = Math.max(0, Math.round(min));
  return `${String(Math.floor(rounded / 60)).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}`;
}

function isSetupOnlySegment(segment: Segment): boolean {
  return segment.setup_min > 0 && segment.prod_min <= 0 && segment.qty <= 0;
}

function buildDayLogic(segs: Segment[], dayIdx: number): string {
  const parts: string[] = [];
  const sorted = [...segs].sort((a, b) => a.start_min - b.start_min);

  const setupByRun = new Map<string, { tool: string; minutes: number }>();
  for (const segment of sorted.filter((s) => s.setup_min > 0)) {
    const entry = setupByRun.get(segment.run_id) ?? { tool: segment.tool_id, minutes: 0 };
    entry.minutes += segment.setup_min;
    setupByRun.set(segment.run_id, entry);
  }
  if (setupByRun.size > 0) {
    parts.push(`Setup/preparação: ${[...setupByRun.values()].map((entry) => `${entry.tool} (${entry.minutes.toFixed(0)}min)`).join(", ")}`);
  }

  const byTool: Record<string, { qty: number; skus: Set<string> }> = {};
  for (const s of sorted) {
    if (isSetupOnlySegment(s)) continue;
    const e = (byTool[s.tool_id] ??= { qty: 0, skus: new Set() });
    e.qty += s.qty;
    for (const sku of s.twin_outputs?.map(([, twinSku]) => twinSku) ?? [s.sku]) {
      e.skus.add(sku);
    }
  }
  for (const [tool, info] of Object.entries(byTool)) {
    parts.push(`${tool}: ${info.qty} pç (${[...info.skus].join("+")})`);
  }

  const productionDue = sorted.filter((s) => (s.production_due_day ?? s.edd) === dayIdx);
  if (productionDue.length > 0) parts.push(`${productionDue.length} prazo(s) de produção hoje`);

  const twins = sorted.filter((s) => s.twin_outputs);
  if (twins.length > 0) parts.push(`${twins.length} seg. gémeos`);

  const conts = sorted.filter((s) => s.is_continuation);
  if (conts.length > 0) parts.push(`${conts.length} continuação(ões)`);

  return parts.join(". ") + ".";
}

function numericParam(params: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const raw = params[key];
    if (raw === undefined || raw === null || raw === "") continue;
    const value = Number(raw);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function segmentReferenceLabel(segment: Segment): string {
  if (!segment.twin_outputs?.length) return segment.sku;
  return segment.twin_outputs.map(([, sku]) => sku).join(" + ");
}

function controllingReferenceLabel(segment: Segment): string {
  const references = segmentReferenceLabel(segment);
  return segment.twin_outputs ? `${references} (controla: ${segment.sku})` : references;
}

function toolMachines(
  config: FactoryConfig | null,
  toolId: string,
  fallback: string[],
  segments: Segment[] = [],
): string[] {
  const tool = config?.tools?.[toolId];
  const machines = [tool?.primary, tool?.alt].filter((m): m is string => Boolean(m));
  if (machines.length > 0) return [...new Set(machines)];

  const scheduledMachines = segments
    .filter((segment) => segment.tool_id === toolId)
    .map((segment) => segment.machine_id)
    .filter((machineId) => fallback.includes(machineId));
  return [...new Set(scheduledMachines)];
}

const capacityKey = (machineId: string, dayIdx: number) => `${machineId}::${dayIdx}`;

function buildCapacityLookup(capacity: CapacityResponse | null): Map<string, number> {
  const lookup = new Map<string, number>();
  for (const item of capacity?.items ?? []) {
    const capMin = Number.isFinite(item.cap_min) ? Math.max(0, item.cap_min) : 0;
    for (const dayIdx of item.day_indices) {
      const key = capacityKey(item.machine_id, dayIdx);
      lookup.set(key, (lookup.get(key) ?? 0) + capMin);
    }
  }
  return lookup;
}

function machineDayCapacity(
  lookup: Map<string, number>,
  hasCapacityData: boolean,
  machineId: string,
  dayIdx: number,
  fallbackDayCapacity: number,
): number {
  const known = lookup.get(capacityKey(machineId, dayIdx));
  if (known !== undefined) return known;
  return hasCapacityData ? 0 : fallbackDayCapacity;
}

function utilizationPct(loadMin: number, capacityMin: number): number {
  if (capacityMin <= 0) return 0;
  return Math.round((loadMin / capacityMin) * 100);
}

function buildOverlays(
  mutations: MutationInput[],
): GanttOverlay[] {
  const overlays: GanttOverlay[] = [];
  for (const mutation of mutations) {
    const start = numericParam(mutation.params, "start", "from_day", "day_idx");
    const end = numericParam(mutation.params, "end", "to_day", "day_idx");
    if (start === null || end === null) continue;
    if (mutation.type === "machine_down") {
      const machineId = String(mutation.params.machine_id ?? mutation.params.machine ?? "");
      if (!machineId) continue;
      for (let day = start; day <= end; day += 1) {
        overlays.push({
          kind: "machine_down",
          machine_id: machineId,
          day_idx: day,
          label: `${machineId} parada`,
        });
      }
    }
  }
  return overlays;
}

function buildResourceOverlays(
  blocked: BlockedDaysResponse | null,
  mutations: MutationInput[],
): ResourceOverlay[] {
  const overlays: ResourceOverlay[] = [];
  const toolIntervalDays = new Set<string>();
  const machineIntervalDays = new Set<string>();

  for (const entry of blocked?.tool_intervals ?? []) {
    toolIntervalDays.add(`${entry.tool_id}-${entry.start_day}`);
    overlays.push({
      kind: "tool",
      resource_id: entry.tool_id,
      display_label: entry.tool_id,
      day_idx: entry.start_day,
      start_min: entry.start_min,
      end_min: entry.end_min,
      category: entry.category,
      reason: entry.reason,
      label: `${entry.tool_id} indisponível`,
    });
  }

  for (const entry of blocked?.tool_blocks ?? []) {
    if (toolIntervalDays.has(`${entry.tool_id}-${entry.day_idx}`)) continue;
    overlays.push({
      kind: "tool",
      resource_id: entry.tool_id,
      display_label: entry.tool_id,
      day_idx: entry.day_idx,
      label: `${entry.tool_id} indisponível`,
    });
  }

  for (const entry of blocked?.machine_intervals ?? []) {
    machineIntervalDays.add(`${entry.machine_id}-${entry.start_day}`);
    overlays.push({
      kind: "machine",
      resource_id: entry.machine_id,
      display_label: entry.machine_id,
      day_idx: entry.start_day,
      start_min: entry.start_min,
      end_min: entry.end_min,
      category: entry.category,
      reason: entry.reason,
      label: `${entry.machine_id} indisponível`,
    });
  }

  for (const entry of blocked?.machine_blocks ?? []) {
    if (machineIntervalDays.has(`${entry.machine_id}-${entry.day_idx}`)) continue;
    overlays.push({
      kind: "machine",
      resource_id: entry.machine_id,
      display_label: entry.machine_id,
      day_idx: entry.day_idx,
      label: `${entry.machine_id} indisponível`,
    });
  }

  for (const entry of blocked?.operator_intervals ?? []) {
    if (entry.count <= 0) continue;
    overlays.push({
      kind: "operator",
      resource_id: `${entry.group} ${entry.shift} ${entry.id}`,
      display_label: `${entry.shift} -${entry.count} · ${entry.group}`,
      day_idx: entry.start_day,
      start_min: entry.start_min,
      end_min: entry.end_min,
      category: entry.category,
      reason: entry.reason,
      label: `${entry.count} ${entry.count === 1 ? "operador indisponível" : "operadores indisponíveis"} · ${entry.group} · turno ${entry.shift}`,
      group: entry.group,
      shift: entry.shift,
    });
  }

  for (const mutation of mutations) {
    if (mutation.type !== "tool_down" && mutation.type !== "machine_down") continue;
    const start = numericParam(mutation.params, "start", "from_day", "day_idx");
    const end = numericParam(mutation.params, "end", "to_day", "day_idx");
    const isTool = mutation.type === "tool_down";
    const resourceId = String(isTool
      ? mutation.params.tool_id ?? mutation.params.tool ?? ""
      : mutation.params.machine_id ?? mutation.params.machine ?? "");
    if (start === null || end === null || !resourceId) continue;
    for (let day = start; day <= end; day += 1) {
      overlays.push({
        kind: isTool ? "tool" : "machine",
        resource_id: resourceId,
        display_label: resourceId,
        day_idx: day,
        label: `${resourceId} indisponível`,
      });
    }
  }

  const unique = new Map<string, ResourceOverlay>();
  for (const overlay of overlays) {
    unique.set(
      `${overlay.kind}-${overlay.resource_id}-${overlay.day_idx}-${overlay.start_min ?? ""}-${overlay.end_min ?? ""}`,
      overlay,
    );
  }
  return [...unique.values()];
}

function buildCalendarOverlays(
  blocked: BlockedDaysResponse | null,
  machines: string[],
): GanttOverlay[] {
  if (!blocked) return [];
  const overlays: GanttOverlay[] = [];
  const machineIntervalDays = new Set(
    (blocked.machine_intervals ?? []).map((entry) => `${entry.machine_id}-${entry.start_day}`),
  );
  for (const holiday of blocked.holidays) {
    for (const machineId of machines) {
      overlays.push({
        kind: "holiday",
        machine_id: machineId,
        day_idx: holiday.day_idx,
        label: holiday.date ? `Sem produção · ${holiday.date}` : "Sem produção",
      });
    }
  }
  for (const entry of blocked.machine_blocks) {
    if (machineIntervalDays.has(`${entry.machine_id}-${entry.day_idx}`)) continue;
    overlays.push({
      kind: "calendar_machine",
      machine_id: entry.machine_id,
      day_idx: entry.day_idx,
      label: `${entry.machine_id} indisponível`,
    });
  }
  for (const entry of blocked.machine_intervals ?? []) {
    overlays.push({
      kind: "calendar_machine",
      machine_id: entry.machine_id,
      day_idx: entry.start_day,
      start_min: entry.start_min,
      end_min: entry.end_min,
      category: entry.category,
      reason: entry.reason,
      label: `${entry.category}: ${entry.reason || entry.machine_id}`,
    });
  }
  return overlays;
}

function positionResourceOverlays(
  overlays: ResourceOverlay[],
  rangeOffset: number,
  timelineStart: number,
  timelineEnd: number,
  timelineCap: number,
  dayW: number,
  timelineWidth: number,
  isSingleDay: boolean,
): PositionedResourceOverlay[] {
  const placed: PositionedResourceOverlay[] = [];
  const levelEnds: number[] = [];

  for (const overlay of [...overlays].sort((a, b) => (
    a.day_idx - b.day_idx
    || (a.start_min ?? timelineStart) - (b.start_min ?? timelineStart)
    || a.resource_id.localeCompare(b.resource_id)
  ))) {
    const rawStart = overlay.start_min ?? timelineStart;
    const rawEnd = overlay.end_min ?? timelineEnd;
    if (rawEnd <= timelineStart || rawStart >= timelineEnd) continue;

    const blockStart = Math.max(timelineStart, rawStart);
    const blockEnd = Math.min(timelineEnd, rawEnd);
    const baseLeft = isSingleDay ? 0 : (overlay.day_idx - rangeOffset) * dayW;
    const scale = isSingleDay ? timelineWidth : dayW;
    const left = baseLeft + ((blockStart - timelineStart) / timelineCap) * scale;
    const width = Math.max(8, ((blockEnd - blockStart) / timelineCap) * scale);
    let level = levelEnds.findIndex((end) => left >= end + 3);
    if (level < 0) {
      level = levelEnds.length;
      levelEnds.push(left + width);
    } else {
      levelEnds[level] = left + width;
    }
    placed.push({ ...overlay, left, width, level });
  }

  return placed;
}

function exportGantt(
  segs: Segment[],
  lots: Lot[] | null,
  score: Score,
  workdays: string[],
  dayRange: [number, number] | null,
  capacityLookup: Map<string, number>,
  hasCapacityData: boolean,
  fallbackDayCapacity: number,
) {
  const from = dayRange?.[0] ?? 0;
  const to = dayRange?.[1] ?? (segs.length ? Math.max(...segs.map((s) => s.day_idx)) : 0);
  const rangeSegs = segs.filter((s) => s.day_idx >= from && s.day_idx <= to);
  const lines: string[] = [];

  // Section 1: Segments
  lines.push("--- SEGMENTOS ---");
  lines.push(
    "Máquina,Dia,Data,Turno,Ferramenta,SKU,Segment_Qty,Lot_Qty,Setup(min),Produção(min),Início(min),Fim(min),Entrega_cliente,Prazo_produção,Envio_subcontratação_planeado,Último_envio_subcontratação,Tipo_referência_material,Referência_material,Libertação_material,EDD_legado,Continuação,Gémeos,Twin_SKU_1,Twin_Qty_1,Twin_SKU_2,Twin_Qty_2",
  );
  const lotMap = new Map((lots ?? []).map((lot) => [lot.id, lot.qty]));
  const sorted = [...rangeSegs].sort(
    (a, b) => a.day_idx - b.day_idx || a.machine_id.localeCompare(b.machine_id) || a.start_min - b.start_min,
  );
  for (const s of sorted) {
    const date = isoAtDay(workdays, s.day_idx) ?? "";
    const lotQty = lotMap.get(s.lot_id) ?? s.qty;
    const customerDelivery = s.customer_delivery_day ?? s.delivery_day ?? s.original_edd ?? s.edd;
    const productionDue = s.production_due_day ?? s.edd;
    const materialReference = s.material_reference_day ?? s.subcontract_dispatch_day ?? customerDelivery;
    lines.push(
      [
        s.machine_id, s.day_idx, date, s.shift, s.tool_id,
        `"${s.sku}"`, s.qty, lotQty, s.setup_min.toFixed(1), s.prod_min.toFixed(1),
        s.start_min, s.end_min,
        customerDelivery,
        productionDue,
        s.subcontract_dispatch_day ?? "",
        s.latest_subcontract_dispatch_day ?? "",
        s.material_reference_kind ?? (s.subcontract_dispatch_day == null ? "customer_delivery" : "subcontract_dispatch"),
        materialReference,
        s.material_release_day ?? "",
        s.edd,
        s.is_continuation ? "Sim" : "Não",
        s.twin_outputs ? "Sim" : "Não",
        s.twin_outputs ? `"${s.twin_outputs[0]?.[1] ?? ""}"` : "",
        s.twin_outputs ? (s.twin_outputs[0]?.[2] ?? 0) : "",
        s.twin_outputs ? `"${s.twin_outputs[1]?.[1] ?? ""}"` : "",
        s.twin_outputs ? (s.twin_outputs[1]?.[2] ?? 0) : "",
      ].join(","),
    );
  }

  // Section 2: Daily summary with logic
  lines.push("");
  lines.push("--- RESUMO POR DIA ---");
  lines.push("Dia,Data,Máquina,Ferramentas,Setups,Produção(min),Utilização(%),Peças,Lógica");
  for (let d = from; d <= to; d++) {
    const daySegs = rangeSegs.filter((s) => s.day_idx === d);
    const byMachine: Record<string, Segment[]> = {};
    for (const s of daySegs) (byMachine[s.machine_id] ??= []).push(s);
    const date = workdays[d] ?? "";
    for (const [mid, mSegs] of Object.entries(byMachine).sort()) {
      const tools = [...new Set(mSegs.map((s) => s.tool_id))];
      const setups = new Set(mSegs.filter((s) => s.setup_min > 0).map((s) => s.run_id)).size;
      const prodMin = mSegs.reduce((a, s) => a + s.prod_min + s.setup_min, 0);
      const capMin = machineDayCapacity(capacityLookup, hasCapacityData, mid, d, fallbackDayCapacity);
      const util = utilizationPct(prodMin, capMin);
      const pcs = mSegs.reduce((a, s) => a + s.qty, 0);
      const logic = buildDayLogic(mSegs, d);
      lines.push(
        [mid, d, date, `"${tools.join(";")}"`, setups, prodMin.toFixed(0), util, pcs, `"${logic}"`].join(","),
      );
    }
  }

  // Section 3: KPIs
  lines.push("");
  lines.push("--- KPIs ---");
  lines.push("OTD,OTD-D,Atrasos_cliente,Envios_sub_atraso,Atraso_sub_dias_uteis,Setups,Antecipação_média,Material_max_dias_uteis,Violações_libertação");
  lines.push(
    [
      `${score.otd?.toFixed(1)}%`,
      `${score.otd_d?.toFixed(1)}%`,
      score.tardy_count,
      String(score.subcontract_dispatch_misses ?? ""),
      String(score.subcontract_dispatch_late_workdays ?? ""),
      score.setups,
      `${score.earliness_avg_days?.toFixed(1)}d`,
      String(score.start_anticipation_max_workdays ?? ""),
      String(score.early_window_violations ?? ""),
    ].join(","),
  );

  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `gantt_dia${from}-${to}_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Styles ───────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  background: T.elevated,
  border: `1px solid ${T.border}`,
  color: T.primary,
  borderRadius: 8,
  padding: "6px 12px",
  fontSize: 12,
  fontFamily: T.mono,
  outline: "none",
};

const smallInputStyle: React.CSSProperties = {
  ...inputStyle,
  width: 48,
  padding: "4px 6px",
  textAlign: "center" as const,
};

const btnStyle = (active: boolean): React.CSSProperties => ({
  background: active ? T.elevated : "transparent",
  border: "none",
  color: active ? T.primary : T.tertiary,
  padding: "4px 10px",
  fontSize: 11,
  fontWeight: 500,
  cursor: "pointer",
  fontFamily: "inherit",
  borderRadius: 6,
  margin: 1,
  transition: "all 0.15s",
});

// ── Component ────────────────────────────────────────────────

export function GanttPage() {
  const segments = useDataStore((s) => s.segments);
  const placementReasons = useDataStore((s) => s.placementReasons);
  const lots = useDataStore((s) => s.lots);
  const score = useDataStore((s) => s.score);
  const gateReport = useDataStore((s) => s.gateReport);
  const config = useDataStore((s) => s.config);
  const capacity = useDataStore((s) => s.capacity);
  const workdays = useDataStore((s) => s.workdays);
  const blockedDays = useDataStore((s) => s.blockedDays);
  const activeMutations = useDataStore((s) => s.activeMutations);
  const [showInactive, setShowInactive] = useState(false);

  const machines = useMemo(() => {
    if (!config?.machines) return FALLBACK_MACHINES;
    return Object.entries(config.machines)
      .filter(([, m]) => showInactive || (m as { active?: boolean }).active !== false)
      .map(([id]) => id)
      .sort();
  }, [config, showInactive]);

  const overlays = useMemo(() => {
    const combined = [
      ...buildCalendarOverlays(blockedDays, machines),
      ...buildOverlays(activeMutations),
    ];
    const unique = new Map<string, GanttOverlay>();
    for (const overlay of combined) {
      const key = `${overlay.machine_id}-${overlay.day_idx}-${overlay.start_min ?? ""}-${overlay.end_min ?? ""}-${overlay.kind}`;
      unique.set(key, overlay);
    }
    return [...unique.values()];
  }, [activeMutations, blockedDays, machines]);

  const resourceOverlays = useMemo(() => (
    buildResourceOverlays(blockedDays, activeMutations)
  ), [activeMutations, blockedDays]);

  const lotById = useMemo(() => new Map((lots ?? []).map((lot) => [lot.id, lot])), [lots]);

  const [view, setView] = useState<"gantt" | "tabela">("gantt");
  const [sel, setSel] = useState<Segment | null>(null);
  useEffect(() => {
    setSel((current) => current
      ? segments?.find((item) => item.lot_id === current.lot_id
        && item.day_idx === current.day_idx
        && item.start_min === current.start_min
        && item.machine_id === current.machine_id) ?? null
      : null);
  }, [segments]);
  const [skuFilter, setSkuFilter] = useState("");
  const [machineFilter, setMachineFilter] = useState("todas");
  const [dayW, setDayW] = useState(DEFAULT_DAY_W);
  const [dayRange, setDayRange] = useState<[number, number] | null>(null);
  const [rangeFrom, setRangeFrom] = useState("");
  const [rangeTo, setRangeTo] = useState("");
  const [currentDay, setCurrentDay] = useState(0);
  const [todayDay, setTodayDay] = useState(0);
  const [currentDayInitialized, setCurrentDayInitialized] = useState(false);
  const [plansOpen, setPlansOpen] = useState(false);
  const [moveRequest, setMoveRequest] = useState<{ segment: Segment; targetDay: number; targetStartMin?: number; targetMachine?: string } | null>(null);
  const [dragSegment, setDragSegment] = useState<Segment | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [shiftFocus, setShiftFocus] = useState<string>("all");
  const [simulatorOpen, setSimulatorOpen] = useState(false);
  const planTopRef = useRef<HTMLDivElement>(null);
  const externalFocusApplied = useRef(false);
  const searchQuery = skuFilter.trim().toLowerCase();
  const displayedMachines = useMemo(() => (
    machineFilter === "todas"
      ? machines
      : machines.filter((machine) => machine === machineFilter)
  ), [machineFilter, machines]);
  const holidayDays = useMemo(
    () => new Set((blockedDays?.holidays ?? []).map((holiday) => holiday.day_idx)),
    [blockedDays],
  );

  const jitAnalysis = useMemo(() => {
    if (!segments || !lots || workdays.length === 0) return null;
    return analyseJitWindow(segments, lots, workdays, blockedDays);
  }, [blockedDays, lots, segments, workdays]);

  const isSingleDay = dayRange !== null && dayRange[0] === dayRange[1];
  const fallbackDayCapacity = config?.day_capacity_min ?? DAY_CAP;
  const configuredShifts = useMemo(() => (
    config?.shifts?.length
      ? config.shifts
      : [
        { id: "A", start_min: DAY_START, end_min: SHIFT_CHANGE, duration_min: SHIFT_CHANGE - DAY_START, label: "Turno A" },
        { id: "B", start_min: SHIFT_CHANGE, end_min: DAY_START + fallbackDayCapacity, duration_min: DAY_START + fallbackDayCapacity - SHIFT_CHANGE, label: "Turno B" },
      ]
  ), [config?.shifts, fallbackDayCapacity]);
  const selectedShift = shiftFocus === "all"
    ? null
    : configuredShifts.find((shift) => shift.id === shiftFocus) ?? null;
  const timelineStart = selectedShift?.start_min ?? configuredShifts[0]?.start_min ?? DAY_START;
  const timelineEnd = selectedShift?.end_min ?? configuredShifts.at(-1)?.end_min ?? DAY_START + fallbackDayCapacity;
  const timelineCap = Math.max(1, timelineEnd - timelineStart);
  const capacityLookup = useMemo(() => buildCapacityLookup(capacity), [capacity]);
  const hasCapacityData = capacity !== null;
  const shiftBoundaries = configuredShifts.slice(1).map((shift) => shift.start_min);
  const shiftOptions = [
    {
      id: "all",
      label: configuredShifts.length
        ? `Turnos ${configuredShifts.map((shift) => shift.id).join("+")}`
        : "Turnos",
    },
    ...configuredShifts.map((shift) => ({
      id: shift.id,
      label: shift.label ? `${shift.id} · ${shift.label}` : `Turno ${shift.id}`,
    })),
  ];

  useEffect(() => {
    if (isSingleDay) setCurrentDay(dayRange![0]);
    if (!isSingleDay) setShiftFocus("all");
  }, [isSingleDay, dayRange]);

  useEffect(() => {
    if (shiftFocus !== "all" && !configuredShifts.some((shift) => shift.id === shiftFocus)) {
      setShiftFocus("all");
    }
  }, [configuredShifts, shiftFocus]);

  useEffect(() => {
    if (machineFilter !== "todas" && !machines.includes(machineFilter)) {
      setMachineFilter("todas");
    }
  }, [machineFilter, machines]);

  useEffect(() => {
    getToday().then((today) => {
      const day = Math.max(0, today.today_idx);
      setTodayDay(day);
      if (!externalFocusApplied.current) {
        setCurrentDay(day);
        setCurrentDayInitialized(true);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const rawFocus = sessionStorage.getItem("pp1PlanFocus");
    if (!rawFocus) return;
    sessionStorage.removeItem("pp1PlanFocus");
    try {
      const focus = JSON.parse(rawFocus) as { day?: number; query?: string };
      externalFocusApplied.current = true;
      if (focus.query) setSkuFilter(focus.query);
      if (Number.isInteger(focus.day) && Number(focus.day) >= 0) {
        const targetDay = Number(focus.day);
        setCurrentDay(targetDay);
        setDayRange([targetDay, targetDay]);
        setRangeFrom(String(targetDay));
        setRangeTo(String(targetDay));
        setCurrentDayInitialized(true);
      }
    } catch {
      // A ligação é apenas uma ajuda de navegação; um valor antigo não bloqueia o plano.
    }
  }, []);

  const minDay = useMemo(() => {
    return 0;
  }, []);

  // Initialize currentDay to minDay on first load
  useEffect(() => {
    if (!currentDayInitialized && segments?.length) {
      setCurrentDay(minDay);
      setCurrentDayInitialized(true);
    }
  }, [minDay, segments, currentDayInitialized]);

  const nDays = useMemo(() => {
    const segmentDays = segments?.map((s) => s.day_idx) ?? [];
    const overlayDays = overlays.map((o) => o.day_idx);
    const resourceDays = resourceOverlays.map((o) => o.day_idx);
    if (!segmentDays.length && !overlayDays.length && !resourceDays.length) return 14;
    return Math.max(...segmentDays, ...overlayDays, ...resourceDays) + 1;
  }, [segments, overlays, resourceOverlays]);

  const filteredSegments = useMemo(() => {
    if (!segments) return [];
    return segments.filter((segment) => {
      if (segment.day_idx < 0) return false;
      if (machineFilter !== "todas" && segment.machine_id !== machineFilter) return false;
      return matchesSearch(searchQuery, [
        segment.sku,
        ...(segment.twin_outputs?.map(([, twinSku]) => twinSku) ?? []),
        ...(segment.output_milestones?.map((output) => output.sku) ?? []),
        segment.tool_id,
        segment.machine_id,
        segment.lot_id,
      ]);
    });
  }, [machineFilter, searchQuery, segments]);

  const filteredMachineIds = useMemo(
    () => new Set(filteredSegments.map((segment) => segment.machine_id)),
    [filteredSegments],
  );
  const filteredToolIds = useMemo(
    () => new Set(filteredSegments.map((segment) => segment.tool_id)),
    [filteredSegments],
  );

  const visibleDays = useMemo(() => {
    if (!dayRange) return Array.from({ length: nDays - minDay }, (_, i) => minDay + i);
    return Array.from({ length: dayRange[1] - dayRange[0] + 1 }, (_, i) => dayRange[0] + i);
  }, [nDays, minDay, dayRange]);

  const visibleSegs = useMemo(() => {
    const inRange = dayRange
      ? filteredSegments.filter((s) => s.day_idx >= dayRange[0] && s.day_idx <= dayRange[1])
      : filteredSegments;
    if (!isSingleDay || shiftFocus === "all") return inRange;
    return inRange.filter((segment) => segment.shift === shiftFocus);
  }, [dayRange, filteredSegments, isSingleDay, shiftFocus]);

  const visibleOverlays = useMemo(() => {
    return overlays.filter((overlay) => {
      if (dayRange && (overlay.day_idx < dayRange[0] || overlay.day_idx > dayRange[1])) return false;
      if (machineFilter !== "todas" && overlay.machine_id !== machineFilter) return false;
      if (overlay.kind === "holiday" || filteredMachineIds.has(overlay.machine_id)) return true;
      return matchesSearch(searchQuery, [
        overlay.label,
        overlay.category ?? "",
        overlay.reason ?? "",
        overlay.machine_id,
      ]);
    });
  }, [dayRange, filteredMachineIds, machineFilter, overlays, searchQuery]);

  const visibleResourceOverlays = useMemo(() => {
    const scheduleSegments = segments ?? [];
    return resourceOverlays.filter((overlay) => {
      if (dayRange && (overlay.day_idx < dayRange[0] || overlay.day_idx > dayRange[1])) return false;
      if (machineFilter !== "todas") {
        if (overlay.kind === "tool") {
          const compatible = toolMachines(config, overlay.resource_id, machines, scheduleSegments);
          if (!compatible.includes(machineFilter)) return false;
        } else if (overlay.kind === "machine" && overlay.resource_id !== machineFilter) {
          return false;
        } else if (overlay.kind === "operator" && overlay.group !== config?.machines?.[machineFilter]?.group) {
          return false;
        }
      }
      if (isSingleDay && shiftFocus !== "all" && overlay.kind === "operator" && overlay.shift !== shiftFocus) return false;
      if (!searchQuery) return true;
      if (overlay.kind === "tool" && filteredToolIds.has(overlay.resource_id)) return true;
      if (overlay.kind === "machine" && filteredMachineIds.has(overlay.resource_id)) return true;
      if (overlay.kind === "operator" && [...filteredMachineIds].some((id) => config?.machines?.[id]?.group === overlay.group)) return true;
      return matchesSearch(searchQuery, [
        overlay.label,
        overlay.category ?? "",
        overlay.reason ?? "",
        overlay.resource_id,
      ]);
    });
  }, [config, dayRange, filteredMachineIds, filteredToolIds, isSingleDay, machineFilter, machines, resourceOverlays, searchQuery, segments, shiftFocus]);

  const tableColumns = useMemo<DataColumn<Segment>[]>(() => [
    { id: "machine", label: "Máquina", value: (segment) => segment.machine_id, render: (segment) => <strong style={{ color: T.primary, fontFamily: T.mono }}>{segment.machine_id}</strong> },
    { id: "date", label: "Data", value: (segment) => workdays[segment.day_idx] ?? "", render: (segment) => workdays[segment.day_idx] ? fmtDate(workdays[segment.day_idx]).short : "—" },
    { id: "shift", label: "Turno", value: (segment) => segment.shift },
    { id: "tool", label: "Ferramenta", value: (segment) => segment.tool_id, render: (segment) => <span style={{ color: toolColor(segment.tool_id), fontWeight: 650 }}>{segment.tool_id}</span> },
    { id: "sku", label: "Referência", value: controllingReferenceLabel, render: (segment) => <span style={{ fontFamily: T.mono }}>{controllingReferenceLabel(segment)}</span> },
    { id: "segment_qty", label: "Qtd. deste segmento", value: (segment) => segment.qty, render: (segment) => isSetupOnlySegment(segment) ? "—" : segment.qty.toLocaleString() },
    { id: "lot_qty", label: "Qtd. total do lote", value: (segment) => segment.lot_qty || lotById.get(segment.lot_id)?.qty || segment.qty },
    { id: "setup", label: "Tempo de setup", value: (segment) => segment.setup_min, render: (segment) => <span style={{ color: segment.setup_min > 0 ? T.orange : T.tertiary, fontFamily: T.mono }}>{fmtDuration(segment.setup_min)}</span> },
    { id: "production", label: "Tempo de produção", value: (segment) => segment.prod_min, render: (segment) => <span style={{ fontFamily: T.mono }}>{isSetupOnlySegment(segment) ? "—" : fmtDuration(segment.prod_min)}</span> },
    {
      id: "delivery",
      label: "Entrega cliente",
      help: "Compromisso de entrega recebido do ISOP.",
      value: (segment) => isoAtDay(workdays, segment.customer_delivery_day ?? segment.delivery_day ?? segment.original_edd ?? segment.edd) ?? "",
      render: (segment) => {
        const value = isoAtDay(workdays, segment.customer_delivery_day ?? segment.delivery_day ?? segment.original_edd ?? segment.edd);
        return value ? fmtDate(value).short : "—";
      },
    },
    {
      id: "production_due",
      label: "Prazo produção",
      help: "Último dia para concluir na fábrica; nos artigos subcontratados coincide com o envio planeado ao fornecedor.",
      value: (segment) => isoAtDay(workdays, segment.production_due_day ?? segment.edd) ?? "",
      render: (segment) => {
        const value = isoAtDay(workdays, segment.production_due_day ?? segment.edd);
        return value ? fmtDate(value).short : "—";
      },
    },
    {
      id: "material_release",
      label: "Libertação material",
      help: "Primeiro dia em que a produção pode começar segundo a disponibilidade simulada de matéria-prima.",
      value: (segment) => segment.material_release_day == null ? "" : isoAtDay(workdays, segment.material_release_day) ?? "",
      render: (segment) => {
        const value = segment.material_release_day == null ? null : isoAtDay(workdays, segment.material_release_day);
        return value ? fmtDate(value).short : "—";
      },
    },
  ], [lotById, workdays]);

  const rangeOffset = dayRange?.[0] ?? minDay;
  const timelineWidth = isSingleDay ? Math.max(dayW * 4, 800) : dayW * visibleDays.length;
  const positionedResourceOverlays = useMemo(() => (
    positionResourceOverlays(
      visibleResourceOverlays,
      rangeOffset,
      timelineStart,
      timelineEnd,
      timelineCap,
      dayW,
      timelineWidth,
      isSingleDay,
    )
  ), [
    dayW,
    isSingleDay,
    rangeOffset,
    timelineCap,
    timelineEnd,
    timelineStart,
    timelineWidth,
    visibleResourceOverlays,
  ]);
  const resourceRowHeight = positionedResourceOverlays.length
    ? RESOURCE_ROW_H + Math.max(0, ...positionedResourceOverlays.map((overlay) => overlay.level)) * 22
    : 0;

  // Machine utilization (visible range)
  const utilization = useMemo(() => {
    const segs = visibleSegs;
    if (!segs.length) return {};
    const totals: Record<string, number> = {};
    for (const s of segs) {
      totals[s.machine_id] = (totals[s.machine_id] || 0) + s.prod_min + s.setup_min;
    }
    const result: Record<string, number> = {};
    for (const m of displayedMachines) {
      const capMin = visibleDays.reduce(
        (sum, dayIdx) => sum + machineDayCapacity(capacityLookup, hasCapacityData, m, dayIdx, fallbackDayCapacity),
        0,
      );
      result[m] = utilizationPct(totals[m] || 0, capMin);
    }
    return result;
  }, [capacityLookup, displayedMachines, fallbackDayCapacity, hasCapacityData, visibleSegs, visibleDays]);

  // Day detail (computed from segments when zoomed to single day)
  const dayDetail = useMemo(() => {
    if (!isSingleDay || !segments) return null;
    const dayIdx = dayRange![0];
    const daySegs = segments.filter((s) => s.day_idx === dayIdx);
    if (!daySegs.length) return { machineDetails: [], allProductionDue: [], totalSegs: 0 };

    const byMachine: Record<string, Segment[]> = {};
    for (const s of daySegs) (byMachine[s.machine_id] ??= []).push(s);

    const machineDetails = Object.entries(byMachine)
      .sort()
      .map(([mid, segs]) => {
        const sorted = [...segs].sort((a, b) => a.start_min - b.start_min);
        const tools = [...new Set(sorted.map((s) => s.tool_id))];
        const setupSegs = sorted.filter((s) => s.setup_min > 0);
        const totalProd = sorted.reduce((a, s) => a + s.prod_min, 0);
        const totalSetup = sorted.reduce((a, s) => a + s.setup_min, 0);
        const totalPcs = sorted.reduce((a, s) => a + s.qty, 0);
        const capMin = machineDayCapacity(capacityLookup, hasCapacityData, mid, dayIdx, fallbackDayCapacity);
        const util = utilizationPct(totalProd + totalSetup, capMin);
        const productionDueHere = sorted.filter((s) => (s.production_due_day ?? s.edd) === dayIdx);
        const twins = sorted.filter((s) => s.twin_outputs);
        return { mid, segs: sorted, tools, setupSegs, totalProd, totalSetup, totalPcs, util, productionDueHere, twins };
      });

    const allProductionDue = daySegs.filter((s) => (s.production_due_day ?? s.edd) === dayIdx);
    return { machineDetails, allProductionDue, totalSegs: daySegs.length };
  }, [capacityLookup, fallbackDayCapacity, hasCapacityData, isSingleDay, dayRange, segments]);

  // Range presets
  const setPreset = (name: string) => {
    if (name === "tudo") {
      setDayRange(null);
      setRangeFrom("");
      setRangeTo("");
    } else if (name === "1dia") {
      const d = currentDay;
      setDayRange([d, d]);
      setRangeFrom(String(d));
      setRangeTo(String(d));
    } else if (name === "2dias") {
      const range: [number, number] = [currentDay, Math.min(currentDay + 1, nDays - 1)];
      setDayRange(range);
      setRangeFrom(String(range[0]));
      setRangeTo(String(range[1]));
    } else {
      const end = name === "semana" ? 4 : name === "2sem" ? 9 : 19;
      const r: [number, number] = [minDay, Math.min(end, nDays - 1)];
      setDayRange(r);
      setRangeFrom(String(r[0]));
      setRangeTo(String(r[1]));
    }
  };

  const applyCustomRange = () => {
    const f = parseInt(rangeFrom);
    const t = parseInt(rangeTo);
    if (!isNaN(f) && !isNaN(t) && f >= minDay && t >= f && t < nDays) {
      setDayRange([f, t]);
    }
  };

  const setSingleDay = (day: number) => {
    const next = Math.max(minDay, Math.min(nDays - 1, day));
    setCurrentDay(next);
    setDayRange([next, next]);
    setRangeFrom(String(next));
    setRangeTo(String(next));
  };

  const handleSimulationApplied = (range?: [number, number]) => {
    setView("gantt");
    if (range) {
      setCurrentDay(range[0]);
      setDayRange(range);
      setRangeFrom(String(range[0]));
      setRangeTo(String(range[1]));
    }
    setSimulatorOpen(false);
    requestAnimationFrame(() => {
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      planTopRef.current?.scrollIntoView({
        behavior: reducedMotion ? "auto" : "smooth",
        block: "start",
      });
    });
  };

  const focusJitViolation = (violation: JitViolationDetail) => {
    setView("gantt");
    setSkuFilter(violation.sku || violation.tool_id);
    setCurrentDay(violation.start_day);
    setDayRange([violation.start_day, violation.start_day]);
    setRangeFrom(String(violation.start_day));
    setRangeTo(String(violation.start_day));
  };

  if (!segments) return <div style={{ color: T.secondary, padding: 24 }}>A carregar...</div>;

  return (
    <div ref={planTopRef} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <JitViolationPanel analysis={jitAnalysis} gate={gateReport} onFocus={focusJitViolation} />
      {gateReport && gateReport.status !== "jit_window_blocked" && <GateReportCard gate={gateReport} activePlan />}
      {moveError && (
        <div role="alert" style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "10px 12px", border: `1px solid ${T.red}45`, borderRadius: 8, background: `${T.red}10`, color: T.red, fontSize: 11 }}>
          <span>{moveError}</span>
          <button type="button" onClick={() => setMoveError(null)} aria-label="Fechar aviso" style={{ border: 0, background: "transparent", color: T.red, cursor: "pointer" }}>×</button>
        </div>
      )}
      {/* Plano toolbar */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div
          aria-label="Escolher vista do plano"
          style={{
            display: "flex",
            background: T.card,
            borderRadius: 8,
            border: `1px solid ${T.border}`,
            overflow: "hidden",
          }}
        >
          {(["gantt", "tabela"] as const).map((v) => (
            <button key={v} onClick={() => setView(v)} style={btnStyle(view === v)}>
              {v === "gantt" ? "Gantt" : "Tabela"}
            </button>
          ))}
        </div>
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flex: "1 1 480px",
            flexWrap: "wrap",
            justifyContent: "flex-end",
            minWidth: 0,
          }}
        >
          <input
            value={skuFilter}
            onChange={(e) => setSkuFilter(e.target.value)}
            placeholder="Pesquisar referência, ferramenta, máquina ou avaria…"
            aria-label="Pesquisar no plano"
            style={{ ...inputStyle, width: 295, maxWidth: "100%", flex: "1 1 220px" }}
          />
          <select
            value={machineFilter}
            onChange={(event) => setMachineFilter(event.target.value)}
            aria-label="Filtrar o plano por máquina"
            style={{ ...inputStyle, width: 150, maxWidth: "100%", flex: "0 1 150px" }}
          >
            <option value="todas">Todas as máquinas</option>
            {machines.map((machine) => <option key={machine} value={machine}>{machine}</option>)}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: 5, color: T.secondary, fontSize: 10, cursor: "pointer" }}>
            <input type="checkbox" checked={showInactive} onChange={(event) => setShowInactive(event.target.checked)} />
            Mostrar máquinas inativas
          </label>
        </div>
      </div>

      {/* Header row 2: Zoom + Range + Export */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        {/* Zoom slider */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 11, color: T.tertiary }}>Zoom</span>
          <input
            type="range"
            min={50}
            max={300}
            value={dayW}
            onChange={(e) => setDayW(Number(e.target.value))}
            style={{ width: 100, accentColor: T.blue }}
          />
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 20, background: T.border }} />

        {/* Range presets */}
        <div
          style={{
            display: "flex",
            background: T.card,
            borderRadius: 8,
            border: `1px solid ${T.border}`,
            overflow: "hidden",
          }}
        >
          {(
            [
              ["1dia", "1 Dia"],
              ["2dias", "2 Dias"],
              ["semana", "Semana"],
              ["2sem", "2 Sem"],
              ["mes", "Mês"],
              ["tudo", "Tudo"],
            ] as const
          ).map(([id, label]) => {
            const active =
              id === "tudo"
                ? !dayRange
                : id === "1dia"
                  ? isSingleDay
                  : id === "2dias"
                    ? dayRange?.[0] === currentDay && dayRange?.[1] === Math.min(currentDay + 1, nDays - 1)
                  : id === "semana"
                    ? dayRange?.[0] === minDay && dayRange?.[1] === Math.min(4, nDays - 1)
                    : id === "2sem"
                      ? dayRange?.[0] === minDay && dayRange?.[1] === Math.min(9, nDays - 1)
                      : dayRange?.[0] === minDay && dayRange?.[1] === Math.min(19, nDays - 1);
            return (
              <button key={id} onClick={() => setPreset(id)} style={btnStyle(active)}>
                {label}
              </button>
            );
          })}
        </div>

        {/* Export button */}
        {isSingleDay && (
          <button
            type="button"
            disabled={dayRange![0] <= minDay}
            onClick={() => {
              const next = Math.max(minDay, dayRange![0] - 1);
              setCurrentDay(next);
              setDayRange([next, next]);
              setRangeFrom(String(next));
              setRangeTo(String(next));
            }}
            style={{ ...inputStyle, cursor: dayRange![0] <= minDay ? "not-allowed" : "pointer", padding: "5px 10px" }}
          >
            ‹ Dia anterior
          </button>
        )}
        <button
          onClick={() => {
            setCurrentDay(todayDay);
            setDayRange([todayDay, todayDay]);
            setRangeFrom(String(todayDay));
            setRangeTo(String(todayDay));
          }}
          style={{ ...inputStyle, cursor: "pointer", padding: "5px 14px", fontWeight: 600 }}
        >
          Hoje
        </button>
        {isSingleDay && (
          <button
            type="button"
            disabled={dayRange![0] >= nDays - 1}
            onClick={() => {
              const next = Math.min(nDays - 1, dayRange![0] + 1);
              setCurrentDay(next);
              setDayRange([next, next]);
              setRangeFrom(String(next));
              setRangeTo(String(next));
            }}
            style={{ ...inputStyle, cursor: dayRange![0] >= nDays - 1 ? "not-allowed" : "pointer", padding: "5px 10px" }}
          >
            Dia seguinte ›
          </button>
        )}
        <button
          onClick={() => score && exportGantt(
            segments,
            lots,
            score,
            workdays,
            dayRange,
            capacityLookup,
            hasCapacityData,
            fallbackDayCapacity,
          )}
          style={{
            ...inputStyle,
            cursor: "pointer",
            padding: "5px 14px",
            fontWeight: 500,
            background: T.blue + "18",
            border: `1px solid ${T.blue}44`,
            color: T.blue,
          }}
        >
          Exportar CSV
        </button>
        <button
          onClick={() => setPlansOpen(true)}
          style={{
            ...inputStyle,
            cursor: "pointer",
            padding: "5px 14px",
            fontWeight: 600,
            background: T.elevated,
          }}
        >
          Planos
        </button>
        {isSingleDay && (
          <div style={{ display: "flex", border: `1px solid ${T.border}`, borderRadius: 8, background: T.card, overflow: "hidden" }}>
            {shiftOptions.map((shift) => (
              <button key={shift.id} onClick={() => setShiftFocus(shift.id)} style={btnStyle(shiftFocus === shift.id)}>
                {shift.label}
              </button>
            ))}
          </div>
        )}
        <details style={{ marginLeft: "auto" }}>
          <summary style={{ cursor: "pointer", color: T.tertiary, fontSize: 10 }}>Intervalo personalizado</summary>
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 6 }}>
            <span style={{ fontSize: 10, color: T.tertiary }}>Dia</span>
            <input value={rangeFrom} onChange={(e) => setRangeFrom(e.target.value)} style={smallInputStyle} />
            <span style={{ fontSize: 10, color: T.tertiary }}>até</span>
            <input value={rangeTo} onChange={(e) => setRangeTo(e.target.value)} style={smallInputStyle} />
            <button type="button" onClick={applyCustomRange} style={{ ...inputStyle, cursor: "pointer", padding: "4px 8px" }}>Aplicar</button>
          </div>
        </details>
      </div>

      {/* Utilization bars */}
      <Card style={{ padding: 16 }}>
        <div className="gantt-utilization-grid" style={{ display: "flex", gap: 16 }}>
          {displayedMachines.map((m) => {
            const u = utilization[m] || 0;
            const c = u > 95 ? T.red : u > 85 ? T.orange : u > 70 ? T.blue : T.green;
            return (
              <div key={m} style={{ flex: 1 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 11, color: T.secondary }}>{m}</span>
                  <span style={{ fontSize: 11, color: c, fontWeight: 600, fontFamily: T.mono }}>{u}%</span>
                </div>
                <ProgressBar value={u} color={c} height={3} />
              </div>
            );
          })}
        </div>
      </Card>

      {view === "gantt" && (
        <div style={{ display: "flex", gap: 16, flexWrap: "wrap", color: T.tertiary, fontSize: 10 }}>
          <span><b style={{ color: T.tertiary }}>▧</b> fim de semana/feriado</span>
          <span><b style={{ color: T.red }}>▧</b> avaria ou manutenção de máquina</span>
          <span><b style={{ color: T.orange }}>▧</b> ferramenta indisponível</span>
          <span><b style={{ color: T.teal }}>▧</b> operadores indisponíveis</span>
          <span><b style={{ color: T.blue }}>▧</b> ensaio</span>
          <span>As cores sólidas identificam ferramentas; a faixa inicial é setup.</span>
        </div>
      )}

      {view === "gantt" ? (
        <Card style={{ padding: 0, overflow: "hidden", position: "relative" }}>
          {/* Single-day navigator */}
          {isSingleDay && (() => {
            const d = dayRange![0];
            const navPrev = () => { const n = Math.max(minDay, d - 1); setDayRange([n, n]); setRangeFrom(String(n)); setRangeTo(String(n)); };
            const navNext = () => { const n = Math.min(nDays - 1, d + 1); setDayRange([n, n]); setRangeFrom(String(n)); setRangeTo(String(n)); };
            return (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 16,
                  padding: "10px 24px",
                  borderBottom: `1px solid ${T.border}`,
                  background: T.card,
                }}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "ArrowLeft" && d > minDay) navPrev();
                  if (e.key === "ArrowRight" && d < nDays - 1) navNext();
                }}
              >
                <button
                  onClick={navPrev}
                  disabled={d <= minDay}
                  style={{
                    background: "none",
                    border: `1px solid ${T.border}`,
                    borderRadius: 6,
                    color: d <= minDay ? T.tertiary : T.primary,
                    cursor: d <= minDay ? "default" : "pointer",
                    padding: "4px 10px",
                    fontSize: 14,
                    fontFamily: "inherit",
                    opacity: d <= minDay ? 0.4 : 1,
                  }}
                >
                  ‹
                </button>
                <div style={{ textAlign: "center", minWidth: 200 }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: T.primary }}>
                    Dia {d}{d >= 0 && workdays[d] ? ` — ${fmtDate(workdays[d]).short}` : d < 0 ? " (Buffer)" : ""}
                  </div>
                  <div style={{ fontSize: 11, color: T.tertiary }}>
                    {d >= 0 && workdays[d] ? fmtDate(workdays[d]).dow : ""}
                    {" · "}{d - minDay + 1}/{nDays - minDay}
                  </div>
                </div>
                <button
                  onClick={navNext}
                  disabled={d >= nDays - 1}
                  style={{
                    background: "none",
                    border: `1px solid ${T.border}`,
                    borderRadius: 6,
                    color: d >= nDays - 1 ? T.tertiary : T.primary,
                    cursor: d >= nDays - 1 ? "default" : "pointer",
                    padding: "4px 10px",
                    fontSize: 14,
                    fontFamily: "inherit",
                    opacity: d >= nDays - 1 ? 0.4 : 1,
                  }}
                >
                  ›
                </button>
              </div>
            );
          })()}

          <div style={{ display: "grid", gridTemplateColumns: `${MACHINE_COL_W}px minmax(0, 1fr)`, minWidth: 0 }}>
            <div style={{ background: T.card, borderRight: `1px solid ${T.border}`, zIndex: 40 }}>
              <div
                style={{
                  height: GANTT_HEADER_H,
                  boxSizing: "border-box",
                  padding: "8px 16px",
                  fontSize: 11,
                  color: T.tertiary,
                  borderBottom: `1px solid ${T.border}`,
                  background: T.card,
                  fontWeight: 700,
                }}
              >
                Máquina
              </div>
              {resourceRowHeight > 0 && (
                <div
                  style={{
                    height: resourceRowHeight,
                    boxSizing: "border-box",
                    padding: "7px 12px",
                    display: "flex",
                    flexDirection: "column",
                    justifyContent: "center",
                    gap: 2,
                    fontSize: 10,
                    color: T.secondary,
                    borderBottom: `1px solid ${T.border}`,
                    background: T.elevated,
                    fontWeight: 700,
                  }}
                >
                  <span>Recursos</span>
                  <span style={{ color: T.tertiary, fontWeight: 500, fontSize: 9 }}>
                    indisponíveis
                  </span>
                </div>
              )}
              {displayedMachines.map((m) => {
                const inactive = config?.machines?.[m]?.active === false;
                const laneH = isSingleDay
                  ? SINGLE_BAR_PAD + SINGLE_BAR_H + SINGLE_BAR_PAD
                  : LANE_H;
                return (
                  <div
                    key={`fixed-${m}`}
                    style={{
                      height: laneH,
                      boxSizing: "border-box",
                      padding: "0 16px",
                      display: "flex",
                      alignItems: "center",
                      fontSize: 12,
                      fontWeight: 600,
                      color: T.primary,
                      fontFamily: T.mono,
                      background: inactive ? T.elevated : T.card,
                      borderBottom: `1px solid ${T.border}`,
                      opacity: inactive ? 0.65 : 1,
                      boxShadow: `2px 0 0 ${T.border}`,
                    }}
                  >
                    {m}{inactive ? " · inativa" : ""}
                  </div>
                );
              })}
            </div>

            <div style={{ overflowX: "auto", minWidth: 0 }}>
          {/* Timeline header */}
          <div
            style={{
              display: "flex",
              height: GANTT_HEADER_H,
              boxSizing: "border-box",
              borderBottom: `1px solid ${T.border}`,
              position: "sticky",
              top: 0,
              background: T.card,
              zIndex: 20,
            }}
          >
            {isSingleDay ? (
              /* Hour ticks for single-day */
              (() => {
                const ticks = Array.from({ length: Math.ceil(timelineCap / 60) + 1 }, (_, i) => {
                  const min = Math.min(timelineEnd, timelineStart + i * 60);
                  return { min, label: fmtMin(min) };
                });
                return (
                  <div style={{ position: "relative", minWidth: timelineWidth, height: GANTT_HEADER_H - 1 }}>
                    {ticks.map((tick) => {
                      const x = ((tick.min - timelineStart) / timelineCap) * timelineWidth;
                      const boundaryShift = shiftFocus === "all"
                        ? configuredShifts.slice(1).find((shift) => shift.start_min === tick.min)
                        : undefined;
                      return (
                        <div
                          key={tick.min}
                          style={{
                            position: "absolute",
                            left: x,
                            top: 0,
                            height: "100%",
                            display: "flex",
                            alignItems: "center",
                            borderLeft: boundaryShift
                              ? `1.5px solid ${T.orange}55`
                              : `1px solid ${T.border}`,
                          }}
                        >
                          <span style={{
                            fontSize: 9,
                            color: boundaryShift ? T.orange : T.tertiary,
                            fontFamily: T.mono,
                            marginLeft: 4,
                            whiteSpace: "nowrap",
                          }}>
                            {tick.label}
                            {boundaryShift ? ` (turno ${boundaryShift.id})` : ""}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                );
              })()
            ) : (
              /* Day columns for multi-day */
              visibleDays.map((i) => {
                const dt = i >= 0 && workdays[i] ? fmtDate(workdays[i]) : null;
                const isHoliday = holidayDays.has(i);
                return (
                  <div
                    key={i}
                    onClick={() => { setDayRange([i, i]); setRangeFrom(String(i)); setRangeTo(String(i)); }}
                    title="Clica para ver detalhe do dia"
                    style={{
                      width: dayW,
                      height: GANTT_HEADER_H - 1,
                      boxSizing: "border-box",
                      flexShrink: 0,
                      padding: "6px 0",
                      textAlign: "center",
                      borderRight: `1px solid ${T.border}`,
                      cursor: "pointer",
                      transition: "background 0.15s",
                      backgroundColor: isHoliday ? HOLIDAY_BACKGROUND : "transparent",
                      backgroundImage: isHoliday ? HOLIDAY_PATTERN : undefined,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = `${T.blue}12`)}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = isHoliday ? HOLIDAY_BACKGROUND : "transparent")}
                  >
                    <div style={{ fontSize: 10, color: i < 0 ? T.orange : T.secondary, fontFamily: T.mono }}>{dt?.short ?? `D${i}`}</div>
                    <div style={{ fontSize: 9, color: T.tertiary, fontFamily: T.mono }}>
                      {dt ? `D${i} · ${dt.dow}` : i < 0 ? "Buffer" : ""}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Machine lanes */}
          {(() => {
            return (
              <>
                {resourceRowHeight > 0 && (
                  <div
                    style={{
                      position: "relative",
                      height: resourceRowHeight,
                      minWidth: timelineWidth,
                      boxSizing: "border-box",
                      borderBottom: `1px solid ${T.border}`,
                      background: T.elevated,
                    }}
                  >
                    {positionedResourceOverlays.map((overlay) => {
                      const color = overlay.category === "Ensaio"
                        ? T.blue
                        : overlay.kind === "machine" ? T.red : overlay.kind === "operator" ? T.teal : T.orange;
                      return (
                      <div
                        key={`${overlay.kind}-${overlay.resource_id}-${overlay.day_idx}-${overlay.start_min ?? ""}-${overlay.end_min ?? ""}`}
                        data-testid="resource-availability-overlay"
                        data-resource-kind={overlay.kind}
                        title={`${overlay.label}${overlay.reason ? ` · ${overlay.reason}` : ""} · ${fmtMin(overlay.start_min ?? timelineStart)}–${fmtMin(overlay.end_min ?? timelineEnd)}`}
                        aria-label={`${overlay.label}${overlay.reason ? ` · ${overlay.reason}` : ""}`}
                        style={{
                          position: "absolute",
                          left: overlay.left,
                          top: 5 + overlay.level * 22,
                          width: overlay.width,
                          height: 18,
                          boxSizing: "border-box",
                          borderRadius: 4,
                          border: `1px solid ${color}66`,
                          background: `${color}14`,
                          backgroundImage: `repeating-linear-gradient(-45deg, transparent, transparent 5px, ${color}24 5px, ${color}24 10px)`,
                          color,
                          fontFamily: T.mono,
                          fontSize: 9,
                          fontWeight: 700,
                          lineHeight: "16px",
                          padding: "0 6px",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {overlay.display_label}
                      </div>
                    );})}
                  </div>
                )}
                {displayedMachines.map((m) => {
              const machineSegs = visibleSegs.filter((s) => s.machine_id === m);
              const machineOverlays = visibleOverlays.filter((o) => o.machine_id === m);
              const inactive = config?.machines?.[m]?.active === false;
              const laneH = isSingleDay
                ? SINGLE_BAR_PAD + SINGLE_BAR_H + SINGLE_BAR_PAD
                : LANE_H;

              return (
                <div
                  key={m}
                  data-testid="machine-timeline-lane"
                  data-machine-id={m}
                  style={{ display: "flex", height: laneH, boxSizing: "border-box", borderBottom: `1px solid ${T.border}`, background: inactive ? T.elevated : "transparent", opacity: inactive ? 0.65 : 1 }}
                >
                  <div
                    onDragOver={(event) => { if (dragSegment && !isHistoricalPlacement(placementReasons[dragSegment.lot_id])) event.preventDefault(); }}
                    onDrop={(event) => {
                      if (!dragSegment || isHistoricalPlacement(placementReasons[dragSegment.lot_id])) return;
                      event.preventDefault();
                      const draggedLot = lotById.get(dragSegment.lot_id);
                      const compatibleMachines = draggedLot
                        ? [draggedLot.machine_id, draggedLot.alt_machine_id].filter(Boolean)
                        : [];
                      if (!draggedLot || !compatibleMachines.includes(m)) {
                        setMoveError(`O lote ${dragSegment.lot_id} não pode trabalhar na máquina ${m}. Nenhuma alteração foi feita.`);
                        setDragSegment(null);
                        return;
                      }
                      const rect = event.currentTarget.getBoundingClientRect();
                      const x = Math.max(0, Math.min(rect.width - 1, event.clientX - rect.left));
                      const columnWidth = isSingleDay ? rect.width : dayW;
                      const targetDay = isSingleDay
                        ? dayRange![0]
                        : Math.max(0, rangeOffset + Math.floor(x / columnWidth));
                      const within = isSingleDay ? x : x % columnWidth;
                      const targetStartMin = Math.max(
                        timelineStart,
                        Math.min(
                          timelineEnd - 1,
                          timelineStart + Math.round((within / columnWidth) * timelineCap / 15) * 15,
                        ),
                      );
                      setMoveError(null);
                      setMoveRequest({ segment: dragSegment, targetDay, targetStartMin, targetMachine: m });
                      setDragSegment(null);
                    }}
                    style={{ position: "relative", height: "100%", flex: 1, minWidth: timelineWidth }}
                  >
                    {isSingleDay ? (
                      /* Hour grid lines for single-day */
                      Array.from({ length: Math.ceil(timelineCap / 60) + 1 }, (_, i) => {
                        const min = Math.min(timelineEnd, timelineStart + i * 60);
                        const x = ((min - timelineStart) / timelineCap) * timelineWidth;
                        const isBoundary = shiftFocus === "all" && shiftBoundaries.includes(min);
                        return (
                          <div
                            key={`h${i}`}
                            style={{
                              position: "absolute",
                              left: x,
                              top: 0,
                              bottom: 0,
                              width: isBoundary ? 1.5 : 0.5,
                              background: isBoundary ? `${T.orange}33` : T.border,
                            }}
                          />
                        );
                      })
                    ) : (
                      /* Day grid lines + shift separators for multi-day */
                      <>
                        {visibleDays.map((_, idx) => (
                          <div
                            key={`g${idx}`}
                            style={{
                              position: "absolute",
                              left: idx * dayW,
                              top: 0,
                              bottom: 0,
                              width: 0.5,
                              background: T.border,
                            }}
                          />
                        ))}
                        {visibleDays.flatMap((_, idx) => shiftBoundaries.map((boundary) => (
                          <div
                            key={`s${idx}-${boundary}`}
                            style={{
                              position: "absolute",
                              left: idx * dayW + ((boundary - timelineStart) / timelineCap) * dayW,
                              top: 0,
                              bottom: 0,
                              width: 0.5,
                              background: T.border,
                              borderLeft: `1px dashed ${T.border}`,
                            }}
                          />
                        )))}
                      </>
                    )}
                    {/* Availability overlays */}
                    {machineOverlays.map((overlay) => {
                      const rawStart = overlay.start_min ?? timelineStart;
                      const rawEnd = overlay.end_min ?? timelineEnd;
                      if (rawEnd <= timelineStart || rawStart >= timelineEnd) return null;
                      const blockStart = Math.max(timelineStart, rawStart);
                      const blockEnd = Math.min(timelineEnd, rawEnd);
                      const baseLeft = isSingleDay ? 0 : (overlay.day_idx - rangeOffset) * dayW;
                      const scale = isSingleDay ? timelineWidth : dayW;
                      const left = baseLeft + ((blockStart - timelineStart) / timelineCap) * scale;
                      const width = Math.max(2, ((blockEnd - blockStart) / timelineCap) * scale);
                      return (
                        <div
                          key={`${overlay.kind}-${overlay.machine_id}-${overlay.day_idx}-${overlay.start_min ?? ""}-${overlay.end_min ?? ""}`}
                          data-testid="machine-availability-overlay"
                          data-overlay-kind={overlay.kind}
                          title={`${overlay.label}${overlay.reason ? ` · ${overlay.reason}` : ""} · ${fmtMin(blockStart)}–${fmtMin(blockEnd)}`}
                          style={{
                            position: "absolute",
                            left,
                            top: 0,
                            width,
                            bottom: 0,
                            zIndex: 0,
                            pointerEvents: "none",
                            ...ganttOverlayAppearance(overlay),
                          }}
                        />
                      );
                    })}
                    {/* Segments */}
                    {machineSegs.map((s) => {
                      const lot = lotById.get(s.lot_id);
                      const lotQty = s.lot_qty || lot?.qty || s.qty;
                      const visibleStart = Math.max(timelineStart, s.start_min);
                      const visibleEnd = Math.min(timelineEnd, s.end_min);
                      if (visibleEnd <= visibleStart) return null;
                      const left = isSingleDay
                        ? ((visibleStart - timelineStart) / timelineCap) * timelineWidth
                        : (s.day_idx - rangeOffset) * dayW + ((visibleStart - timelineStart) / timelineCap) * dayW;
                      const width = isSingleDay
                        ? Math.max(((visibleEnd - visibleStart) / timelineCap) * timelineWidth, 40)
                        : Math.max(((visibleEnd - visibleStart) / timelineCap) * dayW, 3);
                      const col = toolColor(s.tool_id);
                      const top = isSingleDay ? SINGLE_BAR_PAD : 10;
                      const barH = isSingleDay ? SINGLE_BAR_H : 40;
                      const setupOnly = isSetupOnlySegment(s);
                      const productionDueDay = s.production_due_day ?? s.edd;
                      const productionDueIso = isoAtDay(workdays, productionDueDay);
                      const productionDueLabel = `D${productionDueDay}${productionDueIso ? ` · ${fmtDate(productionDueIso).short}` : ""}`;
                      const segmentTitle = setupOnly
                        ? `${s.tool_id} | Preparação | ${s.setup_min.toFixed(0)} min setup | ${fmtMin(s.start_min)}–${fmtMin(s.end_min)} | Prazo produção ${productionDueLabel}${s.twin_outputs ? " | Twin" : ""}`
                        : `${s.tool_id} | ${controllingReferenceLabel(s)} | Segmento: ${s.qty.toLocaleString()} pç | Lote: ${lotQty.toLocaleString()} pç | Eco: ${(s.eco_lot_effective ?? lot?.eco_lot_effective ?? 0).toLocaleString()} | ${fmtMin(s.start_min)}–${fmtMin(s.end_min)} | Prazo produção ${productionDueLabel}${s.twin_outputs ? " | Twin" : ""}`;
                      const placementTitle = placementReasons[s.lot_id]?.kind === "manual"
                        ? " | Hora manual"
                        : placementReasons[s.lot_id]?.kind === "historical" ? " | Plano passado" : "";
                      return (
                        <div
                          key={`${s.lot_id}-${s.day_idx}-${s.start_min}`}
                          title={`${segmentTitle}${placementTitle}`}
                          draggable={!isHistoricalPlacement(placementReasons[s.lot_id])}
                          onDragStart={(event) => {
                            if (isHistoricalPlacement(placementReasons[s.lot_id])) {
                              event.preventDefault();
                              return;
                            }
                            setDragSegment(s);
                            event.dataTransfer.effectAllowed = "move";
                            event.dataTransfer.setData("text/plain", s.lot_id);
                          }}
                          onDragEnd={() => setDragSegment(null)}
                          onClick={() => setSel(s)}
                          style={{
                            position: "absolute",
                            left,
                            top,
                            width,
                            height: barH,
                            background: setupOnly ? `${T.orange}12` : `${col}18`,
                            zIndex: 2,
                            borderRadius: 5,
                            cursor: "pointer",
                            border: setupOnly ? `1px dashed ${T.orange}88` : `1px solid ${col}55`,
                            transition: "all 0.15s",
                            borderLeft: s.is_continuation ? `2px dashed ${col}66` : undefined,
                            overflow: "hidden",
                          }}
                        >
                          {/* Setup overlay — behind text */}
                          {s.setup_min > 0 && (
                            <div
                              style={{
                                position: "absolute",
                                left: 0,
                                top: 0,
                                bottom: 0,
                                zIndex: 0,
                                width: Math.max((s.setup_min / (s.end_min - s.start_min)) * width, 1.5),
                                background: `${col}30`,
                                backgroundImage: `repeating-linear-gradient(-45deg, transparent, transparent 3px, ${col}15 3px, ${col}15 6px)`,
                                borderRight: `1px dashed ${col}44`,
                              }}
                            />
                          )}
                          {/* Text content — above setup */}
                          {isSingleDay ? (
                            <div style={{
                              position: "relative",
                              zIndex: 1,
                              display: "flex",
                              flexDirection: "column",
                              gap: 1,
                              padding: "6px 8px",
                              overflow: "hidden",
                              height: "100%",
                              justifyContent: "center",
                            }}>
                              <span style={{ fontSize: 10, color: `${col}dd`, fontWeight: 700, fontFamily: T.mono, lineHeight: 1.3 }}>
                                {setupOnly ? "Preparação" : segmentReferenceLabel(s)}
                                {s.setup_min > 0 ? ` ⚙${s.setup_min.toFixed(0)}m` : ""}
                              </span>
                              {width > 50 && (
                                <span style={{
                                  fontSize: 9,
                                  color: T.secondary,
                                  lineHeight: 1.3,
                                  whiteSpace: "nowrap",
                                  overflow: "hidden",
                                  textOverflow: "ellipsis",
                                  maxWidth: width - 16,
                                }}>
                                  {setupOnly
                                    ? `${s.tool_id} · sem produção neste bloco`
                                    : s.twin_outputs
                                    ? s.twin_outputs.map(([, sku, qty]: [string, string, number]) => `${sku}: ${qty.toLocaleString()}`).join(" + ")
                                    : `Segmento ${s.qty.toLocaleString()} · Lote ${lotQty.toLocaleString()} pç`}
                                </span>
                              )}
                              {width > 100 && (
                                <span style={{ fontSize: 8, color: T.tertiary, lineHeight: 1.3 }}>
                                  {setupOnly ? "setup planeado" : `${s.prod_min.toFixed(0)} min de produção`}
                                </span>
                              )}
                            </div>
                          ) : (
                            width > 28 && (
                              <div style={{
                                position: "relative",
                                zIndex: 1,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                width: "100%",
                                height: "100%",
                              }}>
                                <span style={{ fontSize: 8, color: `${col}cc`, fontWeight: 600, fontFamily: T.mono }}>
                                  {setupOnly ? "Setup" : width > 55 ? segmentReferenceLabel(s) : s.tool_id}
                                </span>
                              </div>
                            )
                          )}
                          {/* Twin badge */}
                          {s.twin_outputs && (
                            <span
                              style={{
                                position: "absolute",
                                top: 1,
                                right: 2,
                                zIndex: 2,
                                fontSize: isSingleDay ? 9 : 7,
                                fontWeight: 700,
                                color: `${col}cc`,
                                background: `${col}22`,
                                borderRadius: 3,
                                padding: "0 2px",
                              }}
                            >
                              T
                            </span>
                          )}
                        </div>
                      );
                    })}
                    {/* Customer, production and material milestones */}
                    {(() => {
                      const customerDays = new Set<number>();
                      const productionDueDays = new Set<number>();
                      const materialReleaseDays = new Set<number>();
                      machineSegs.forEach((s) => {
                        const customer = s.customer_delivery_day ?? s.delivery_day ?? s.original_edd ?? s.edd;
                        const due = s.production_due_day ?? s.edd;
                        customerDays.add(customer);
                        if (due !== customer) productionDueDays.add(due);
                        if (s.material_release_day != null) materialReleaseDays.add(s.material_release_day);
                      });
                      if (isSingleDay) {
                        const labels: Array<{ text: string; color: string }> = [];
                        if (customerDays.has(dayRange![0])) {
                          labels.push({ text: "ENTREGA CLIENTE", color: T.red });
                        }
                        if (productionDueDays.has(dayRange![0])) {
                          labels.push({ text: "ENVIO SUB. / PRAZO PRODUÇÃO", color: T.orange });
                        }
                        if (materialReleaseDays.has(dayRange![0])) {
                          labels.push({ text: "LIBERTAÇÃO MATERIAL", color: T.green });
                        }
                        return labels.length ? (
                          <div style={{
                            position: "absolute",
                            right: 4,
                            top: 2,
                            zIndex: 20,
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "flex-end",
                            gap: 1,
                          }}>
                            {labels.map((label) => (
                              <span key={label.text} style={{ fontSize: 8, color: label.color, fontWeight: 700 }}>
                                {label.text}
                              </span>
                            ))}
                          </div>
                        ) : null;
                      }
                      const marker = (day: number, kind: string, color: string, offset: number, style: "dashed" | "dotted") => (
                          <div
                            key={`${kind}-${day}`}
                            title={`${kind} · D${day}`}
                            style={{
                              position: "absolute",
                              left: (day - rangeOffset) * dayW + dayW / 2 + offset,
                              top: 0,
                              bottom: 0,
                              width: 0,
                              borderLeft: `1px ${style} ${color}88`,
                            }}
                          />
                      );
                      const visible = (day: number) => day >= rangeOffset && day < rangeOffset + visibleDays.length;
                      return (
                        <>
                          {[...customerDays].filter(visible).map((day) => marker(day, "Entrega cliente", T.red, -2, "dashed"))}
                          {[...productionDueDays].filter(visible).map((day) => marker(day, "Envio sub. / prazo produção", T.orange, 0, "dashed"))}
                          {[...materialReleaseDays].filter(visible).map((day) => marker(day, "Libertação material", T.green, 2, "dotted"))}
                        </>
                      );
                    })()}
                  </div>
                </div>
                );
                })}
              </>
            );
          })()}
            </div>
          </div>
        </Card>
      ) : (
        /* Table view */
        <DataTable
          rows={visibleSegs}
          columns={tableColumns}
          rowKey={(segment) => `${segment.lot_id}-${segment.day_idx}-${segment.start_min}-${segment.machine_id}`}
          searchPlaceholder="Pesquisar na tabela…"
          emptyTitle="Nenhuma produção neste período"
          emptyDetail="Escolhe outro dia, remove os filtros ou consulta o plano completo."
          onRowClick={setSel}
          initialSort={{ id: "date", direction: "asc" }}
          toolbar={isSingleDay ? (
            <div style={{ display: "flex", alignItems: "center", gap: 6, color: T.secondary, fontSize: 10 }}>
              <button
                type="button"
                disabled={dayRange![0] <= minDay}
                onClick={() => setSingleDay(dayRange![0] - 1)}
                style={{ ...inputStyle, width: "auto", cursor: dayRange![0] <= minDay ? "default" : "pointer", padding: "5px 9px" }}
              >
                ‹ Dia anterior
              </button>
              <span style={{ fontFamily: T.mono }}>
                Dia {dayRange![0]}{workdays[dayRange![0]] ? ` · ${fmtDate(workdays[dayRange![0]]).short}` : ""}
              </span>
              <button
                type="button"
                onClick={() => setSingleDay(todayDay)}
                disabled={dayRange![0] === todayDay}
                style={{ ...inputStyle, width: "auto", cursor: dayRange![0] === todayDay ? "default" : "pointer", padding: "5px 9px", fontWeight: 600 }}
              >
                Hoje
              </button>
              <button
                type="button"
                disabled={dayRange![0] >= nDays - 1}
                onClick={() => setSingleDay(dayRange![0] + 1)}
                style={{ ...inputStyle, width: "auto", cursor: dayRange![0] >= nDays - 1 ? "default" : "pointer", padding: "5px 9px" }}
              >
                Dia seguinte ›
              </button>
            </div>
          ) : undefined}
        />
      )}

      {/* Day detail panel (shown below Gantt when single-day) */}
      {isSingleDay && view === "gantt" && dayDetail && dayDetail.totalSegs > 0 && (
        <Card style={{ padding: 20 }}>
          {/* Summary row */}
          <div style={{ display: "flex", gap: 16, marginBottom: 16, fontSize: 12, color: T.secondary }}>
            <span>{dayDetail.totalSegs} segmentos</span>
            <span style={{ color: T.border }}>|</span>
            <span style={{ color: dayDetail.allProductionDue.length > 0 ? T.orange : T.secondary }}>
              {dayDetail.allProductionDue.length} prazo{dayDetail.allProductionDue.length !== 1 ? "s" : ""} de produção
            </span>
            <span style={{ color: T.border }}>|</span>
            <span>
              {Math.round(dayDetail.machineDetails.reduce((a, m) => a + m.util, 0) / dayDetail.machineDetails.length)}% utilização média
            </span>
          </div>

          {/* Per-machine breakdown */}
          {dayDetail.machineDetails.map((md) => (
            <div key={md.mid} style={{ borderBottom: `1px solid ${T.border}`, paddingBottom: 14, marginBottom: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: T.mono, minWidth: 56 }}>
                  {md.mid}
                </span>
                <span style={{
                  fontSize: 11,
                  fontWeight: 600,
                  fontFamily: T.mono,
                  color: md.util > 95 ? T.red : md.util > 85 ? T.orange : md.util > 70 ? T.blue : T.green,
                }}>
                  {md.util}%
                </span>
                <div style={{ flex: 1, height: 3, background: T.elevated, borderRadius: 2, overflow: "hidden" }}>
                  <div style={{
                    width: `${Math.min(md.util, 100)}%`,
                    height: "100%",
                    background: md.util > 95 ? T.red : md.util > 85 ? T.orange : md.util > 70 ? T.blue : T.green,
                    borderRadius: 2,
                  }} />
                </div>
                <span style={{ fontSize: 11, color: T.tertiary, fontFamily: T.mono }}>
                  {md.totalPcs.toLocaleString()} pç
                </span>
              </div>

              {md.tools.map((toolId) => {
                const toolSegs = md.segs.filter((s) => s.tool_id === toolId);
                const toolSetup = toolSegs.reduce((total, s) => total + s.setup_min, 0);
                const isCont = toolSegs.every((s) => s.is_continuation);
                return (
                  <div key={toolId} style={{ marginLeft: 16, marginBottom: 6 }}>
                    <div style={{ fontSize: 12, color: toolColor(toolId), fontWeight: 500, marginBottom: 2 }}>
                      {toolId}
                      {toolSetup > 0
                        ? ` (setup ${toolSetup.toFixed(0)}min)`
                        : isCont
                          ? " (sem setup — continuação)"
                          : ""}
                    </div>
                    {toolSegs.map((s, si) => {
                      const lotQty = s.lot_qty || lotById.get(s.lot_id)?.qty || s.qty;
                      const setupOnly = isSetupOnlySegment(s);
                      return (
                        <div key={si} style={{ fontSize: 11, color: T.secondary, marginLeft: 8, lineHeight: 1.6 }}>
                          {setupOnly
                            ? `→ Preparação ${s.setup_min.toFixed(0)} min · ${s.tool_id} · sem produção neste bloco`
                            : `→ Segmento ${s.qty.toLocaleString()} pç · Lote ${lotQty.toLocaleString()} pç (${controllingReferenceLabel(s)})`}
                          {s.twin_outputs && (
                            <span style={{
                              fontSize: 9,
                              fontWeight: 700,
                              color: T.blue,
                              background: `${T.blue}15`,
                              borderRadius: 3,
                              padding: "0 3px",
                              marginLeft: 4,
                            }}>
                              T
                            </span>
                          )}
                          {s.twin_outputs && (
                            <div style={{ marginLeft: 12, fontSize: 10, color: T.tertiary }}>
                              {s.twin_outputs.map(([, sku, qty]: [string, string, number], i: number) => (
                                <div key={i}>↳ {sku}: {qty.toLocaleString()} pç{qty === 0 ? " (sem produção)" : ""}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              })}

              {md.productionDueHere.length > 0 && (
                <div style={{ fontSize: 11, color: T.orange, marginLeft: 16, marginTop: 4 }}>
                  ⚠ {md.productionDueHere.length} prazo{md.productionDueHere.length !== 1 ? "s" : ""} de produção hoje
                </div>
              )}
            </div>
          ))}

          {/* Logic summary */}
          <div style={{ marginTop: 8, padding: "10px 12px", background: T.elevated, borderRadius: 8, fontSize: 11, color: T.secondary, lineHeight: 1.6 }}>
            <span style={{ fontWeight: 600, color: T.tertiary }}>Lógica: </span>
            {buildDayLogic(segments!.filter((s) => s.day_idx === dayRange![0]), dayRange![0])}
          </div>
        </Card>
      )}

      <PlanSimulatorSection
        currentDay={dayRange?.[0] ?? currentDay}
        workdays={workdays}
        open={simulatorOpen}
        onToggle={() => setSimulatorOpen((value) => !value)}
        onApplied={handleSimulationApplied}
      />

      {/* Segment detail modal */}
      {sel && (
        <Modal
          title={isSetupOnlySegment(sel) ? "Preparação" : "Segmento"}
          onClose={() => setSel(null)}
          width={
            (sel.twin_outputs?.length ?? 0) > 1
            || (sel.output_milestones?.length ?? lotById.get(sel.lot_id)?.output_milestones?.length ?? 0) > 1
              ? 860
              : 400
          }
        >
          {(() => {
            const selectedLot = lotById.get(sel.lot_id);
            const selectedLotQty = sel.lot_qty || selectedLot?.qty || sel.qty;
            const selectedIsSetupOnly = isSetupOnlySegment(sel);
            const blockerLabels: Record<string, string> = {
              blocked_by_jit_floor: "libertação simulada de matéria-prima (compatibilidade)",
              blocked_by_material_release: "primeiro dia permitido pela libertação simulada de matéria-prima",
              blocked_by_machine_busy: "máquina ocupada ou indisponível",
              blocked_by_tool_busy: "ferramenta ocupada ou indisponível",
              blocked_by_setup_crew: "equipa de setup ocupada",
              blocked_by_operator_capacity: "capacidade de operadores insuficiente",
              blocked_by_holiday: "dia não útil",
              blocked_by_inactive_machine: "máquina inativa",
              blocked_by_priority_higher_risk_lot: "referência com rutura mais prioritária",
              blocked_by_intervening_tool_change:
                "outra ferramenta ocupa a máquina antes da continuação",
              blocked_by_run_setup_sequence: "setup da campanha ainda não realizado",
              blocked_by_delivery_regression: "antecipação pioraria uma entrega",
              left_shift_available: "há espaço anterior a rever pelo planeador",
            };
            const blockers = (sel.left_shift_blockers ?? []).map((code) => blockerLabels[code] ?? code);
            const placementExplanation = placementReasonText(placementReasons[sel.lot_id]);
            // Why this block runs on a different machine from the tool's
            // neighbouring uses (backend explanation of the final plan).
            const machineChange = gateReport?.improvement?.tool_transfers?.items.find(
              (item) => item.lot_ids.includes(sel.lot_id) && item.from_machine === sel.machine_id,
            );
            const fmtDay = (day: number | null | undefined) => {
              if (day == null) return "-";
              const iso = isoAtDay(workdays, day);
              return `Dia ${day}${iso ? ` (${fmtDate(iso).short})` : ""}`;
            };
            const outputMilestones = sel.output_milestones ?? selectedLot?.output_milestones ?? [];
            const hasOutputBreakdown = outputMilestones.length > 1;
            const demandOutputs = outputMilestones.filter((output) => !output.is_coproduced_surplus);
            const constraintOutputs = demandOutputs.length ? demandOutputs : outputMilestones;
            const jointProductionDue = sel.production_due_day
              ?? selectedLot?.production_due_day
              ?? (constraintOutputs.length
                ? Math.min(...constraintOutputs.map((output) => output.production_due_day))
                : sel.edd);
            const jointMaterialRelease = sel.material_release_day
              ?? selectedLot?.material_release_day
              ?? (constraintOutputs.length
                ? Math.min(...constraintOutputs.map((output) => output.material_release_day))
                : null);
            const dueControllingSkus = constraintOutputs
              .filter((output) => output.production_due_day === jointProductionDue)
              .map((output) => output.sku);
            const releaseControllingSkus = constraintOutputs
              .filter((output) => output.material_release_day === jointMaterialRelease)
              .map((output) => output.sku);
            const joinSkus = (skus: string[], fallback: string) => skus.length ? skus.join(" + ") : fallback;
            const materialReferenceLabel = sel.material_reference_kind === "subcontract_dispatch"
              ? "envio para subcontratação"
              : sel.material_reference_kind === "mixed"
                ? "marco mais restritivo dos outputs"
                : "entrega ao cliente";
            const mainRows: [string, unknown][] = [
              ["Tipo", selectedIsSetupOnly ? "Preparação sem produção neste bloco" : "Produção"],
              ["Máquina", sel.machine_id],
              ["Dia", `${sel.day_idx}${workdays[sel.day_idx] ? ` (${fmtDate(workdays[sel.day_idx]).short})` : ""}`],
              ["Turno", sel.shift],
              ["Ferramenta", sel.tool_id],
              ["Referência controladora", sel.sku],
              ...(sel.twin_outputs
                ? [["Referências gémeas", segmentReferenceLabel(sel)] as [string, unknown]]
                : []),
              ["Quantidade segmento", selectedIsSetupOnly ? "-" : sel.qty],
              ["Quantidade lote", selectedLotQty],
              ["Início", fmtMin(sel.start_min)],
              ["Fim", fmtMin(sel.end_min)],
              ...(hasOutputBreakdown
                ? [
                    ["Janela conjunta de produção", `${fmtDay(jointMaterialRelease)} → ${fmtDay(jointProductionDue)}`] as [string, unknown],
                    ["Material comum libertado por", `${joinSkus(releaseControllingSkus, "outputs gémeos")} · libertação ${fmtDay(jointMaterialRelease)}`] as [string, unknown],
                    ["Prazo limitado por", `${joinSkus(dueControllingSkus, sel.sku)} · produzir até ${fmtDay(jointProductionDue)}`] as [string, unknown],
                  ]
                : [
                    ["Entrega ao cliente", fmtDay(sel.customer_delivery_day ?? sel.delivery_day ?? sel.original_edd ?? sel.edd)] as [string, unknown],
                    ["Envio planeado para subcontratação", fmtDay(sel.subcontract_dispatch_day)] as [string, unknown],
                    ...(sel.latest_subcontract_dispatch_day != null
                      && sel.latest_subcontract_dispatch_day !== sel.subcontract_dispatch_day
                      ? [["Último envio possível", fmtDay(sel.latest_subcontract_dispatch_day)] as [string, unknown]]
                      : []),
                    ["Prazo de produção", fmtDay(jointProductionDue)] as [string, unknown],
                    ["Alvo interno", fmtDay(sel.internal_target_day ?? sel.internal_deadline)] as [string, unknown],
                    ["Referência da janela de material", `${fmtDay(sel.material_reference_day)} · ${materialReferenceLabel}`] as [string, unknown],
                    ["Libertação simulada de material", fmtDay(jointMaterialRelease)] as [string, unknown],
                  ]),
              ["Início após libertação", sel.release_delay_workdays ? `${sel.release_delay_workdays} dia(s) útil(eis) depois` : "no primeiro dia permitido"],
              ["Prioridade cliente/ref.", sel.planning_priority ?? selectedLot?.planning_priority ?? 0],
              ["Aviso económico", sel.economic_warning ?? selectedLot?.economic_warning ?? "-"],
              ["Porque não começou antes", placementExplanation ?? (blockers.length ? blockers.join("; ") : "Não foi comprovado um impedimento anterior neste plano.")],
              ...(machineChange
                ? [["Mudança de máquina", `${machineChange.from_machine} → ${machineChange.to_machine}: ${machineChange.summary}`] as [string, unknown]]
                : []),
            ];
            const technicalRows: [string, unknown][] = [
              ["Quantidade campanha", sel.run_qty ? `${sel.run_qty.toLocaleString()} pç` : "-"],
              ["Lotes na campanha", sel.run_lot_count || 1],
              ["Setup segmento", `${sel.setup_min.toFixed(1)} min`],
              ["Setup campanha", `${(sel.run_setup_min ?? sel.setup_min).toFixed(1)} min`],
              ["Produção", selectedIsSetupOnly ? "Sem produção neste bloco" : `${sel.prod_min.toFixed(1)} min`],
              ["Janela começo", fmtDay(sel.target_start_day)],
              ["Eco lot ISOP", sel.eco_lot_isop ?? selectedLot?.eco_lot_isop ?? "-"],
              ["Eco lot efetivo", sel.eco_lot_effective ?? selectedLot?.eco_lot_effective ?? "-"],
              ["Regra campanha", sel.min_campaign_qty || sel.min_campaign_prod_min ? `${sel.min_campaign_qty ?? "-"} pç / ${sel.min_campaign_prod_min ?? "-"} min / ${sel.max_group_gap_days ?? 0} dias` : "-"],
              ["Subcontratação", sel.subcontract_company_id ? `${sel.subcontract_company_id} · lead ${sel.subcontract_lead_time_days ?? 0}d · buffer ${sel.subcontract_buffer_days ?? 0}d` : "-"],
              ...outputMilestones.map((output, index): [string, unknown] => [
                `Marco output ${index + 1}`,
                `${output.sku}${output.sku === sel.sku ? " (controla prazo)" : ""} · entrega ${fmtDay(output.customer_delivery_day)} · ${output.is_subcontracted ? `envio sub. ${fmtDay(output.subcontract_dispatch_day)}${output.latest_subcontract_dispatch_day !== output.subcontract_dispatch_day ? ` · último envio ${fmtDay(output.latest_subcontract_dispatch_day)}` : ""}` : `prazo produção ${fmtDay(output.production_due_day)}`} · libertação ${fmtDay(output.material_release_day)}`,
              ]),
              ["Lote", sel.lot_id],
              ["Continuação", sel.is_continuation ? "Sim" : "Não"],
              ["Produção gémea", sel.twin_outputs ? "Sim" : "Não"],
              ...(sel.twin_outputs
                ? sel.twin_outputs.map(([, sku, qty]: [string, string, number], i: number): [string, unknown] => [
                    `  Referência gémea ${i + 1}`,
                    `${qty.toLocaleString()} pç (${sku})`,
                  ])
                : []),
            ];
            const renderRows = (rows: [string, unknown][]) => rows.map(([key, value]) => (
              <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: 16, padding: "9px 0", borderBottom: `1px solid ${T.border}` }}>
                <span style={{ fontSize: 12, color: T.secondary }}>{key}</span>
                <span style={{ fontSize: 12, color: T.primary, fontWeight: 500, fontFamily: T.mono, textAlign: "right" }}>{String(value)}</span>
              </div>
            ));
            return (
              <div>
                <div style={{ color: T.tertiary, fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" }}>
                  Informação principal
                </div>
                {renderRows(mainRows)}
                {hasOutputBreakdown && (
                  <div style={{ marginTop: 20 }}>
                    <div style={{ color: T.tertiary, fontSize: 10, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>
                      Datas por referência
                    </div>
                    <div style={{ overflowX: "auto" }}>
                      <table aria-label="Datas por referência" style={{ width: "100%", minWidth: 760, borderCollapse: "collapse", tableLayout: "fixed" }}>
                        <thead>
                          <tr>
                            {["Referência", "Entrega ISOP", "Envio sub.", "Produzir até", "Alvo interno", "Referência material", "Libertação se isolada"].map((label, index) => (
                              <th
                                key={label}
                                style={{ width: index === 0 ? 160 : undefined, padding: "7px 8px", borderBottom: `1px solid ${T.border}`, color: T.tertiary, fontSize: 10, fontWeight: 650, textAlign: "left", verticalAlign: "bottom" }}
                              >
                                {label}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {outputMilestones.map((output) => {
                            const contributesToJointWindow = constraintOutputs.includes(output);
                            const constraints = [
                              contributesToJointWindow && output.production_due_day === jointProductionDue ? "limita o prazo" : null,
                              contributesToJointWindow && output.material_release_day === jointMaterialRelease ? "liberta o material comum" : null,
                              output.is_coproduced_surplus ? "stock coproduzido" : null,
                            ].filter(Boolean).join(" · ");
                            const outputMaterialLabel = output.material_reference_kind === "subcontract_dispatch"
                              ? "envio sub."
                              : "entrega";
                            return (
                              <tr key={output.op_id}>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, verticalAlign: "top" }}>
                                  <div style={{ color: T.primary, fontFamily: T.mono, fontSize: 11, fontWeight: 650, overflowWrap: "anywhere" }}>{output.sku}</div>
                                  {constraints && <div style={{ color: T.tertiary, fontSize: 9, marginTop: 3 }}>{constraints}</div>}
                                </td>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, color: T.primary, fontFamily: T.mono, fontSize: 10, verticalAlign: "top" }}>{fmtDay(output.customer_delivery_day)}</td>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, color: T.primary, fontFamily: T.mono, fontSize: 10, verticalAlign: "top" }}>{fmtDay(output.subcontract_dispatch_day)}</td>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, color: T.primary, fontFamily: T.mono, fontSize: 10, verticalAlign: "top" }}>{fmtDay(output.production_due_day)}</td>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, color: T.primary, fontFamily: T.mono, fontSize: 10, verticalAlign: "top" }}>{fmtDay(output.internal_target_day)}</td>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, color: T.primary, fontFamily: T.mono, fontSize: 10, verticalAlign: "top" }}>
                                  {fmtDay(output.material_reference_day)}
                                  <div style={{ color: T.tertiary, fontFamily: T.sans, fontSize: 9, marginTop: 3 }}>{outputMaterialLabel}</div>
                                </td>
                                <td style={{ padding: "9px 8px", borderBottom: `1px solid ${T.border}`, color: T.primary, fontFamily: T.mono, fontSize: 10, verticalAlign: "top" }}>{fmtDay(output.material_release_day)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
                {selectedLot && !selectedIsSetupOnly && !isHistoricalPlacement(placementReasons[sel.lot_id]) && (
                  <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                    <button
                      onClick={() => {
                        setMoveRequest({ segment: sel, targetDay: Math.min(nDays - 1, sel.day_idx + 1) });
                        setSel(null);
                      }}
                      style={{ ...inputStyle, color: T.blue, borderColor: `${T.blue}55`, cursor: "pointer", fontFamily: "inherit", fontWeight: 600 }}
                    >
                      Mover p/ dia seguinte
                    </button>
                    <button
                      onClick={() => {
                        setMoveRequest({ segment: sel, targetDay: sel.day_idx });
                        setSel(null);
                      }}
                      style={{ ...inputStyle, cursor: "pointer", fontFamily: "inherit" }}
                    >
                      Mover para dia…
                    </button>
                  </div>
                )}
                <details style={{ marginTop: 14 }}>
                  <summary style={{ cursor: "pointer", color: T.secondary, fontSize: 12, fontWeight: 600 }}>
                    Detalhes técnicos
                  </summary>
                  <div style={{ marginTop: 6 }}>{renderRows(technicalRows)}</div>
                </details>
              </div>
            );
          })()}
        </Modal>
      )}
      {plansOpen && <PlansDrawer onClose={() => setPlansOpen(false)} />}
      {moveRequest && lotById.get(moveRequest.segment.lot_id) && (
        <MoveLotModal
          segment={moveRequest.segment}
          lot={lotById.get(moveRequest.segment.lot_id)!}
          workdays={workdays}
          initialTargetDay={moveRequest.targetDay}
          initialTargetStartMin={moveRequest.targetStartMin}
          initialTargetMachine={moveRequest.targetMachine}
          onClose={() => setMoveRequest(null)}
          onApplied={() => {
            setMoveRequest(null);
            setSel(null);
          }}
        />
      )}
    </div>
  );
}

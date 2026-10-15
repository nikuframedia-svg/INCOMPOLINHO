import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { FactoryConfig, SetupOverride, ShiftConfig, SkuPlanningRule, SubcontractsResponse } from "../api/types";

/**
 * Configuração: one page-wide list of pending plan-input changes (decisão de
 * 16/10/2026). Every edit is added here instead of being saved at once; one
 * «Aplicar» sends everything in a single replan job (`config_updates`).
 * The list survives page switches (and a reload, via sessionStorage) and is
 * dropped when the active ISOP changes.
 */

export type UnavailabilityKind = "machine" | "tool" | "operator";
export type UnavailabilityCategory = "Avaria" | "Manutenção" | "Ensaio" | "Outra";
export type UnavailabilityForm = {
  kind: UnavailabilityKind;
  resource: string;
  operatorKey: string;
  start_at: string;
  end_at: string;
  category: UnavailabilityCategory;
  count: number;
  reason: string;
};

export type ToolDraft = { setup_hours?: number; alt?: string | null };
export type TwinDraft = { tool_id: string; sku_a: string; sku_b: string };
export type SubcontractsBody = Pick<SubcontractsResponse, "companies" | "sku_subcontracts">;

export type DraftChange =
  | { kind: "machine_add"; machine: { id: string; group: string; active: boolean } }
  | { kind: "machine_oee"; machine: string; value: number | null }
  | { kind: "machine_group"; machine: string; value: string }
  | { kind: "machine_active"; machine: string; value: boolean }
  | { kind: "tool_update"; tool: string; value: ToolDraft }
  | { kind: "shifts"; value: ShiftConfig[] }
  | { kind: "operators"; key: string; value: number }
  | { kind: "setup_crews"; group: string; value: number }
  | { kind: "unavailability_add"; key: string; form: UnavailabilityForm }
  | { kind: "unavailability_update"; entryId: string; form: UnavailabilityForm }
  | { kind: "unavailability_remove"; entryId: string }
  | { kind: "holiday_add"; dates: string[] }
  | { kind: "holiday_remove"; dates: string[] }
  | { kind: "extra_day_add"; date: string }
  | { kind: "extra_day_remove"; date: string }
  | { kind: "setup_override_set"; value: SetupOverride }
  | { kind: "setup_override_remove"; sku: string; machine: string }
  | { kind: "twin_add"; value: TwinDraft }
  | { kind: "twin_remove"; tool_id: string }
  | { kind: "sku_planning"; sku: string; rule: SkuPlanningRule | null }
  | { kind: "subcontracts"; body: SubcontractsBody }
  | { kind: "config_param"; key: string; value: unknown }
  | { kind: "preset"; name: string };

export type DraftItem = DraftChange & { id: string; label: string };

/** What buildConfigUpdates needs from the saved configuration (full-replacement keys). */
export type DraftBase = Pick<FactoryConfig, "setup_crews_by_group" | "setup_overrides">;

const range = (dates: string[]) => `${dates[0] ?? ""}..${dates[dates.length - 1] ?? ""}`;

/** Stable id of the line a change belongs to: a newer change to the same target replaces it. */
export function draftId(change: DraftChange): string {
  switch (change.kind) {
    case "machine_add": return `machine_add:${change.machine.id}`;
    case "machine_oee":
    case "machine_group":
    case "machine_active": return `${change.kind}:${change.machine}`;
    case "tool_update": return `tool:${change.tool}`;
    case "shifts": return "shifts";
    case "operators": return `operators:${change.key}`;
    case "setup_crews": return `setup_crews:${change.group}`;
    case "unavailability_add": return `unavailability_add:${change.key}`;
    case "unavailability_update": return `unavailability_update:${change.entryId}`;
    case "unavailability_remove": return `unavailability_remove:${change.entryId}`;
    case "holiday_add":
    case "holiday_remove": return `holiday:${range(change.dates)}`;
    case "extra_day_add":
    case "extra_day_remove": return `extra_day:${change.date}`;
    case "setup_override_set": return `setup_override:${change.value.sku}|${change.value.machine}`;
    case "setup_override_remove": return `setup_override:${change.sku}|${change.machine}`;
    case "twin_add": return `twin:${change.value.tool_id}`;
    case "twin_remove": return `twin:${change.tool_id}`;
    case "sku_planning": return `sku_planning:${change.sku}`;
    case "subcontracts": return "subcontracts";
    case "config_param": return `config_param:${change.key}`;
    case "preset": return "preset";
  }
}

const number = (value: number) => value.toLocaleString("pt-PT");

/** "2026-12-24" → "24/12/2026"; anything else is shown as is. */
export function dateLabel(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : iso;
}

function dateTimeLabel(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(value);
  return match ? `${match[3]}/${match[2]}/${match[1]} ${match[4]}` : value;
}

function datesLabel(dates: string[]): string {
  if (dates.length <= 1) return dateLabel(dates[0] ?? "");
  return `${dateLabel(dates[0])} a ${dateLabel(dates[dates.length - 1])}`;
}

export function groupLabel(group: string): string {
  return group === "Medias" ? "Médias" : group;
}

/** Resource of an unavailability in plain words ("PRM031", "Grandes A · 2 pessoas"). */
export function unavailabilityResource(form: UnavailabilityForm): string {
  if (form.kind === "operator") {
    return `${form.operatorKey} · ${form.count} pessoa${form.count === 1 ? "" : "s"}`;
  }
  return form.resource;
}

function unavailabilitySummary(form: UnavailabilityForm): string {
  const end = form.end_at ? dateTimeLabel(form.end_at) : "sem previsão";
  const reason = form.reason.trim();
  return `${unavailabilityResource(form)} · ${dateTimeLabel(form.start_at)} → ${end} · ${form.category}${reason ? ` · ${reason}` : ""}`;
}

const SKU_RULE_LABELS: Record<keyof SkuPlanningRule, (value: number) => string> = {
  eco_lot: (v) => `lote económico ${number(v)} pç`,
  start_buffer_days: (v) => `começar ${number(v)} dia(s) antes`,
  finish_buffer_days: (v) => `acabar ${number(v)} dia(s) antes`,
  min_campaign_qty: (v) => `campanha mínima ${number(v)} pç`,
  min_campaign_prod_min: (v) => `campanha mínima ${number(v)} min`,
  max_group_gap_days: (v) => `juntar prazos até ${number(v)} dia(s)`,
  planning_priority: (v) => `prioridade ${number(v)}`,
};

/** One plain pt-PT line for a pending change. */
export function describeChange(change: DraftChange): string {
  switch (change.kind) {
    case "machine_add":
      return `Nova máquina ${change.machine.id} (${groupLabel(change.machine.group)})`;
    case "machine_oee":
      return `${change.machine}: OEE ${change.value === null ? "valor base" : number(change.value)}`;
    case "machine_group":
      return `${change.machine}: grupo ${groupLabel(change.value)}`;
    case "machine_active":
      return change.value
        ? `${change.machine}: ativar`
        : `${change.machine}: desativar (deixa de receber produção)`;
    case "tool_update": {
      const parts: string[] = [];
      if (change.value.setup_hours !== undefined) parts.push(`setup ${number(change.value.setup_hours)} h`);
      if (change.value.alt !== undefined) parts.push(`alternativa ${change.value.alt ?? "nenhuma"}`);
      return `Ferramenta ${change.tool}: ${parts.join(" · ")}`;
    }
    case "shifts":
      return "Turnos alterados";
    case "operators":
      return `Operadores ${change.key}: ${number(change.value)}`;
    case "setup_crews":
      return `Equipas de setup ${groupLabel(change.group)}: ${number(change.value)}`;
    case "unavailability_add":
      return `Nova indisponibilidade: ${unavailabilitySummary(change.form)}`;
    case "unavailability_update":
      return `Indisponibilidade editada: ${unavailabilitySummary(change.form)}`;
    case "unavailability_remove":
      return "Remover indisponibilidade";
    case "holiday_add":
      return `Dia${change.dates.length === 1 ? "" : "s"} sem produção: ${datesLabel(change.dates)}`;
    case "holiday_remove":
      return `Reabrir ${datesLabel(change.dates)}`;
    case "extra_day_add":
      return `Dia extra de produção: ${dateLabel(change.date)}`;
    case "extra_day_remove":
      return `Fechar dia extra ${dateLabel(change.date)}`;
    case "setup_override_set":
      return `Setup de ${change.value.sku} em ${change.value.machine}: ${number(change.value.hours)} h`;
    case "setup_override_remove":
      return `Remover exceção de setup de ${change.sku} em ${change.machine}`;
    case "twin_add":
      return `Gémeas ${change.value.sku_a} + ${change.value.sku_b} (ferramenta ${change.value.tool_id})`;
    case "twin_remove":
      return `Remover gémeas da ferramenta ${change.tool_id}`;
    case "sku_planning": {
      if (change.rule === null) return `${change.sku}: repor valores do ISOP`;
      const parts = (Object.entries(change.rule) as [keyof SkuPlanningRule, number | undefined][])
        .filter(([, value]) => typeof value === "number")
        .map(([key, value]) => SKU_RULE_LABELS[key]?.(value as number) ?? `${key} ${value}`);
      return `${change.sku}: ${parts.join(" · ") || "sem correções"}`;
    }
    case "subcontracts":
      return `Subcontratações: ${Object.keys(change.body.sku_subcontracts).length} referência(s)`;
    case "config_param":
      return `Parâmetro ${change.key}: ${String(change.value)}`;
    case "preset":
      return `Predefinição «${change.name}»`;
  }
}

export function unavailabilityPayload(form: UnavailabilityForm, id?: string): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    ...(id ? { id } : {}),
    kind: form.kind,
    start_at: form.start_at,
    end_at: form.end_at,
    category: form.category,
    reason: form.reason,
  };
  if (form.kind === "operator") {
    const parts = form.operatorKey.trim().split(/\s+/);
    payload.shift = parts.pop() ?? "";
    payload.group = parts.join(" ");
    payload.count = form.count;
  } else {
    payload.resource = form.resource;
  }
  return payload;
}

/** Ordered add/remove sets: a later change to the same value wins. */
function orderedSets() {
  const additions = new Set<string>();
  const removals = new Set<string>();
  return {
    add: (value: string) => { additions.add(value); removals.delete(value); },
    remove: (value: string) => { removals.add(value); additions.delete(value); },
    additions: () => [...additions].sort(),
    removals: () => [...removals].sort(),
  };
}

/**
 * The `config_updates` body of one replan job for every pending change.
 * Keys follow the backend contract (backend/api/replan.py); full-replacement
 * keys (setup crews, setup exceptions) are merged onto `base`.
 */
export function buildConfigUpdates(items: readonly DraftItem[], base: DraftBase): Record<string, unknown> {
  const updates: Record<string, unknown> = {};
  const machineAdditions: Array<{ id: string; group: string; active: boolean }> = [];
  const machineOee: Record<string, number | null> = {};
  const machineGroups: Record<string, string> = {};
  const machineActive: Record<string, boolean> = {};
  const toolUpdates: Record<string, ToolDraft> = {};
  const operators: Record<string, number> = {};
  const crews: Record<string, number> = {};
  const unavailabilityAdditions: Record<string, unknown>[] = [];
  const unavailabilityUpdates = new Map<string, Record<string, unknown>>();
  const unavailabilityRemovals: string[] = [];
  const holidays = orderedSets();
  const extraDays = orderedSets();
  const twins = orderedSets();
  const twinAdditions = new Map<string, TwinDraft>();
  const skuPlanning: Record<string, SkuPlanningRule | null> = {};
  const params: Record<string, unknown> = {};
  let setupOverrides: SetupOverride[] | null = null;
  let hasHolidays = false;
  let hasExtraDays = false;
  let hasTwins = false;

  for (const item of items) {
    switch (item.kind) {
      case "machine_add": machineAdditions.push({ ...item.machine }); break;
      case "machine_oee": machineOee[item.machine] = item.value; break;
      case "machine_group": machineGroups[item.machine] = item.value; break;
      case "machine_active": machineActive[item.machine] = item.value; break;
      case "tool_update": toolUpdates[item.tool] = { ...toolUpdates[item.tool], ...item.value }; break;
      case "shifts": updates.shifts = item.value.map((shift) => ({ ...shift })); break;
      case "operators": operators[item.key] = item.value; break;
      case "setup_crews": crews[item.group] = item.value; break;
      case "unavailability_add": unavailabilityAdditions.push(unavailabilityPayload(item.form)); break;
      case "unavailability_update":
        unavailabilityUpdates.set(item.entryId, unavailabilityPayload(item.form, item.entryId));
        break;
      case "unavailability_remove": unavailabilityRemovals.push(item.entryId); break;
      case "holiday_add": hasHolidays = true; item.dates.forEach(holidays.add); break;
      case "holiday_remove": hasHolidays = true; item.dates.forEach(holidays.remove); break;
      case "extra_day_add": hasExtraDays = true; extraDays.add(item.date); break;
      case "extra_day_remove": hasExtraDays = true; extraDays.remove(item.date); break;
      case "setup_override_set":
      case "setup_override_remove": {
        const current: SetupOverride[] = setupOverrides ?? base.setup_overrides.map((entry) => ({ ...entry }));
        const sku = item.kind === "setup_override_set" ? item.value.sku : item.sku;
        const machine = item.kind === "setup_override_set" ? item.value.machine : item.machine;
        const next = current.filter((entry) => entry.sku !== sku || entry.machine !== machine);
        if (item.kind === "setup_override_set") next.push({ ...item.value });
        setupOverrides = next;
        break;
      }
      case "twin_add": hasTwins = true; twins.add(item.value.tool_id); twinAdditions.set(item.value.tool_id, { ...item.value }); break;
      case "twin_remove": hasTwins = true; twins.remove(item.tool_id); break;
      case "sku_planning": skuPlanning[item.sku] = item.rule === null ? null : { ...item.rule }; break;
      case "subcontracts": updates.subcontracts = structuredClone(item.body); break;
      case "config_param": params[item.key] = item.value; break;
      case "preset": updates.preset = item.name; break;
    }
  }

  const removedUnavailability = new Set(unavailabilityRemovals);
  const editedUnavailability = [...unavailabilityUpdates.entries()]
    .filter(([id]) => !removedUnavailability.has(id))
    .map(([, payload]) => payload);
  const nonEmpty = (key: string, value: Record<string, unknown> | unknown[]) => {
    if (Array.isArray(value) ? value.length : Object.keys(value).length) updates[key] = value;
  };
  nonEmpty("machine_additions", machineAdditions);
  nonEmpty("machine_oee", machineOee);
  nonEmpty("machine_groups", machineGroups);
  nonEmpty("machine_active", machineActive);
  nonEmpty("tool_updates", toolUpdates);
  nonEmpty("operators", operators);
  if (Object.keys(crews).length) updates.setup_crews_by_group = { ...base.setup_crews_by_group, ...crews };
  nonEmpty("unavailability_additions", unavailabilityAdditions);
  nonEmpty("unavailability_updates", editedUnavailability);
  nonEmpty("unavailability_removals", unavailabilityRemovals);
  if (hasHolidays) {
    nonEmpty("holiday_additions", holidays.additions());
    nonEmpty("holiday_removals", holidays.removals());
  }
  if (hasExtraDays) {
    nonEmpty("extra_day_additions", extraDays.additions());
    nonEmpty("extra_day_removals", extraDays.removals());
  }
  if (setupOverrides) updates.setup_overrides = setupOverrides;
  if (hasTwins) {
    nonEmpty("twin_additions", twins.additions().map((toolId) => twinAdditions.get(toolId)!));
    nonEmpty("twin_removals", twins.removals());
  }
  nonEmpty("sku_planning", skuPlanning);
  nonEmpty("config_params", params);
  return updates;
}

interface ConfigDraftState {
  items: DraftItem[];
  count: number;
  /** Dataset the list was prepared for; another dataset drops it. */
  datasetId: string | null;
  /** True from «Aplicar» until the job is applied, refused or cancelled. */
  applying: boolean;
  applyingJobId: string | null;
  applyingItemIds: string[];
  seq: number;

  /** Add a change or replace the pending change to the same target. No-op while applying. */
  upsert: (change: DraftChange, label?: string) => void;
  remove: (id: string) => void;
  discard: () => void;
  nextKey: () => string;
  lines: () => { id: string; text: string }[];
  buildConfigUpdates: (base: DraftBase) => Record<string, unknown>;
  /** Keep the list for this dataset; drop it when the dataset changed. */
  syncDataset: (datasetId: string) => void;
  beginApply: () => DraftItem[];
  setApplyingJob: (jobId: string) => void;
  /** Ends the apply: the applied lines leave the list, a refused apply keeps them. */
  finishApply: (applied: boolean) => void;
}

const withItems = (items: DraftItem[]) => ({ items, count: items.length });

const IDLE = { applying: false, applyingJobId: null, applyingItemIds: [] as string[] };

export const useConfigDraftStore = create<ConfigDraftState>()(persist((set, get) => ({
  items: [],
  count: 0,
  datasetId: null,
  ...IDLE,
  seq: 0,

  upsert: (change, label) => {
    if (get().applying) return;
    const id = draftId(change);
    const item = { ...change, id, label: label ?? describeChange(change) } as DraftItem;
    const items = get().items;
    const index = items.findIndex((candidate) => candidate.id === id);
    set(withItems(index < 0 ? [...items, item] : items.map((candidate, at) => at === index ? item : candidate)));
  },
  remove: (id) => {
    if (get().applying) return;
    set(withItems(get().items.filter((item) => item.id !== id)));
  },
  discard: () => set({ ...withItems([]), ...IDLE }),
  nextKey: () => {
    const seq = get().seq + 1;
    set({ seq });
    return `n${seq}`;
  },
  lines: () => get().items.map((item) => ({ id: item.id, text: item.label })),
  buildConfigUpdates: (base) => buildConfigUpdates(get().items, base),
  syncDataset: (datasetId) => {
    const current = get().datasetId;
    if (current === datasetId) return;
    if (current !== null) set({ ...withItems([]), ...IDLE });
    set({ datasetId });
  },
  beginApply: () => {
    const items = get().items;
    set({ applying: true, applyingJobId: null, applyingItemIds: items.map((item) => item.id) });
    return items;
  },
  setApplyingJob: (jobId) => set({ applyingJobId: jobId }),
  finishApply: (applied) => {
    const done = new Set(get().applyingItemIds);
    set({
      ...(applied ? withItems(get().items.filter((item) => !done.has(item.id))) : {}),
      ...IDLE,
    });
  },
}), {
  name: "pp1ConfigDraft",
  version: 1,
  storage: createJSONStorage(() => sessionStorage),
  partialize: (state) => ({
    items: state.items,
    count: state.count,
    datasetId: state.datasetId,
    applying: state.applying,
    applyingJobId: state.applyingJobId,
    applyingItemIds: state.applyingItemIds,
    seq: state.seq,
  }),
}));

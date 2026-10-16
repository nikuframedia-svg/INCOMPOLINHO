import type { MasterCatalog } from "../api/types";
import type { DraftItem } from "../stores/useConfigDraftStore";

/**
 * Configuração: what deactivating a machine or changing a tool's alternative
 * does to the references, from the catalog plus every pending change together
 * (e.g. PRM042 and MAE054 deactivated in the same list).
 */
export type ConfigImpact = {
  /** Line text with the impact, by draft item id (only for lines that have one). */
  lines: Map<string, string>;
  /** References with no active allowed machine after the changes that had one before. */
  orphanCount: number;
};

type Catalog = Pick<MasterCatalog, "machines" | "tools" | "references">;
type State = { active: Map<string, boolean>; alt: Map<string, string | null> };

const MAX_LISTED = 3;

function refsPhrase(ids: string[], verb: [string, string]): string {
  const one = ids.length === 1;
  return `${ids.length} referência${one ? "" : "s"} ${one ? verb[0] : verb[1]}`;
}

function listed(ids: string[]): string {
  return `${ids.slice(0, MAX_LISTED).join(", ")}${ids.length > MAX_LISTED ? ", …" : ""}`;
}

const orphanText = (ids: string[]) => `${refsPhrase(ids, ["fica", "ficam"])} sem máquina (${listed(ids)})`;

export function configImpact(items: readonly DraftItem[], catalog: Catalog | null): ConfigImpact {
  const lines = new Map<string, string>();
  if (!catalog) return { lines, orphanCount: 0 };

  const toolById = new Map(catalog.tools.map((tool) => [tool.id, tool]));
  const refs = catalog.references
    .filter((ref) => ref.active)
    .map((ref) => ({ id: ref.id, tool: ref.tool, primary: ref.machine || toolById.get(ref.tool)?.primary || "" }));

  const before: State = {
    active: new Map(catalog.machines.map((machine) => [machine.id, machine.active])),
    alt: new Map(catalog.tools.map((tool) => [tool.id, tool.alt])),
  };
  const after: State = { active: new Map(before.active), alt: new Map(before.alt) };
  for (const item of items) {
    if (item.kind === "machine_active") after.active.set(item.machine, item.value);
    else if (item.kind === "machine_add") after.active.set(item.machine.id, item.machine.active);
    else if (item.kind === "tool_update" && item.value.alt !== undefined) after.alt.set(item.tool, item.value.alt);
  }

  const allowed = (ref: (typeof refs)[number], state: State) => {
    const alt = state.alt.get(ref.tool) ?? null;
    return [ref.primary, alt].filter((machine, at, all): machine is string =>
      Boolean(machine) && all.indexOf(machine) === at);
  };
  // A machine the catalog does not know is not reported as inactive.
  const isActive = (machine: string, state: State) => state.active.get(machine) ?? true;
  const activeMachines = (ref: (typeof refs)[number], state: State) =>
    allowed(ref, state).filter((machine) => isActive(machine, state));

  for (const item of items) {
    if (item.kind === "machine_active" && !item.value) {
      const affected = refs.filter((ref) => allowed(ref, after).includes(item.machine));
      const orphans = affected.filter((ref) => activeMachines(ref, after).length === 0).map((ref) => ref.id);
      if (orphans.length) {
        lines.set(item.id, `${item.machine}: desativar — ${orphanText(orphans)}`);
        continue;
      }
      const targets = [...new Set(affected
        .filter((ref) => ref.primary === item.machine)
        .flatMap((ref) => activeMachines(ref, after)))].sort();
      if (targets.length) lines.set(item.id, `${item.machine}: desativar — o trabalho passa para ${targets.join(", ")}`);
    } else if (item.kind === "tool_update" && item.value.alt !== undefined) {
      const toolRefs = refs.filter((ref) => ref.tool === item.tool);
      if (!toolRefs.length) continue;
      const orphans = toolRefs.filter((ref) => activeMachines(ref, after).length === 0).map((ref) => ref.id);
      if (orphans.length) {
        lines.set(item.id, `${item.label} — ${orphanText(orphans)}`);
      } else if (item.value.alt === null) {
        const machines = [...new Set(toolRefs.flatMap((ref) => activeMachines(ref, after)))].sort();
        lines.set(item.id, `${item.label} — ${refsPhrase(toolRefs.map((ref) => ref.id), ["fica", "ficam"])} só na ${machines.join(", ")}`);
      }
    }
  }

  const orphanCount = new Set(refs
    .filter((ref) => activeMachines(ref, after).length === 0 && activeMachines(ref, before).length > 0)
    .map((ref) => ref.id)).size;
  return { lines, orphanCount };
}

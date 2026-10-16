import assert from "node:assert/strict";
import test from "node:test";

import type { MasterCatalog } from "../src/api/types.ts";
import { configImpact } from "../src/lib/configImpact.ts";
import type { DraftItem } from "../src/stores/useConfigDraftStore.ts";

const machine = (id: string, active = true) => ({ id, source: "both" as const, active, group: "Grandes", oee: null });
const tool = (id: string, primary: string, alt: string | null) => ({
  id, source: "both" as const, active: true, primary, alt, setup_hours: 0.5,
});
const ref = (id: string, toolId: string, machineId: string) => ({
  id, source: "isop" as const, active: true, client: "C", machine: machineId, tool: toolId, has_override: false,
});

const catalog: Pick<MasterCatalog, "machines" | "tools" | "references"> = {
  machines: [machine("PRM019"), machine("PRM039"), machine("PRM042"), machine("MAE054")],
  tools: [tool("T1", "PRM042", "PRM039"), tool("T2", "PRM042", "MAE054"), tool("BFP080", "PRM019", "PRM039")],
  references: [
    ref("R1", "T1", "PRM042"),
    ref("R2", "T2", "PRM042"),
    ref("R3", "T2", "PRM042"),
    ref("R4", "T2", "PRM042"),
    ref("R5", "T2", "PRM042"),
    ref("B1", "BFP080", "PRM019"),
  ],
};

const off = (id: string): DraftItem => ({
  kind: "machine_active", machine: id, value: false, id: `machine_active:${id}`, label: `${id}: desativar (deixa de receber produção)`,
});
const alt = (toolId: string, value: string | null): DraftItem => ({
  kind: "tool_update", tool: toolId, value: { alt: value }, id: `tool:${toolId}`,
  label: `Ferramenta ${toolId}: alternativa ${value ?? "nenhuma"}`,
});

test("desativar uma máquina com alternativas ativas diz para onde vai o trabalho", () => {
  const impact = configImpact([off("PRM042")], catalog);
  assert.equal(impact.lines.get("machine_active:PRM042"), "PRM042: desativar — o trabalho passa para MAE054, PRM039");
  assert.equal(impact.orphanCount, 0);
});

test("desativar duas máquinas juntas deixa referências sem máquina (até 3 e …)", () => {
  const impact = configImpact([off("PRM042"), off("MAE054")], catalog);
  const text = "4 referências ficam sem máquina (R2, R3, R4, …)";
  assert.equal(impact.lines.get("machine_active:PRM042"), `PRM042: desativar — ${text}`);
  assert.equal(impact.lines.get("machine_active:MAE054"), `MAE054: desativar — ${text}`);
  assert.equal(impact.orphanCount, 4);
});

test("retirar a alternativa de uma ferramenta: fica só na primária ou sem máquina", () => {
  assert.equal(
    configImpact([alt("BFP080", null)], catalog).lines.get("tool:BFP080"),
    "Ferramenta BFP080: alternativa nenhuma — 1 referência fica só na PRM019",
  );
  const impact = configImpact([off("PRM019"), alt("BFP080", null)], catalog);
  assert.equal(impact.lines.get("tool:BFP080"), "Ferramenta BFP080: alternativa nenhuma — 1 referência fica sem máquina (B1)");
  assert.equal(impact.orphanCount, 1);
});

test("sem catálogo ou sem efeito não altera a linha", () => {
  assert.equal(configImpact([off("PRM042")], null).lines.size, 0);
  assert.equal(configImpact([alt("T1", "PRM019")], catalog).lines.size, 0);
  assert.equal(configImpact([off("PRM039")], catalog).lines.size, 0);
});

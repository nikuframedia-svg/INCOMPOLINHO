// Configuração: one page-wide list of pending changes (decisão de 16/10/2026).
import { afterEach, describe, expect, it } from "vitest";
import {
  buildConfigUpdates,
  describeChange,
  useConfigDraftStore,
  type DraftBase,
} from "../src/stores/useConfigDraftStore";

const base: DraftBase = {
  setup_crews_by_group: { Grandes: 1, Medias: 1 },
  setup_overrides: [{ sku: "A", machine: "M1", hours: 1 }],
};

const store = () => useConfigDraftStore.getState();

afterEach(() => {
  store().discard();
  useConfigDraftStore.setState({ datasetId: null });
});

describe("lista de alterações por aplicar", () => {
  it("acrescenta uma linha por alteração e substitui a do mesmo alvo", () => {
    store().upsert({ kind: "machine_add", machine: { id: "PRM050", group: "Grandes", active: true } });
    store().upsert({ kind: "machine_add", machine: { id: "PRM051", group: "Medias", active: true } });
    store().upsert({ kind: "machine_oee", machine: "PRM031", value: 0.7 });
    store().upsert({ kind: "machine_oee", machine: "PRM031", value: 0.75 });

    expect(store().count).toBe(3);
    expect(store().lines().map((line) => line.text)).toEqual([
      "Nova máquina PRM050 (Grandes)",
      "Nova máquina PRM051 (Médias)",
      "PRM031: OEE 0,75",
    ]);
  });

  it("retira uma linha pelo id e descarta tudo", () => {
    store().upsert({ kind: "holiday_add", dates: ["2026-12-24"] });
    store().upsert({ kind: "operators", key: "Grandes A", value: 4 });
    const [first] = store().lines();
    store().remove(first.id);
    expect(store().lines().map((line) => line.text)).toEqual(["Operadores Grandes A: 4"]);
    store().discard();
    expect(store().count).toBe(0);
  });

  it("constrói um único config_updates com todas as chaves do contrato", () => {
    const s = store();
    s.upsert({ kind: "machine_add", machine: { id: "PRM050", group: "Grandes", active: true } });
    s.upsert({ kind: "machine_oee", machine: "PRM031", value: null });
    s.upsert({ kind: "machine_group", machine: "PRM031", value: "Medias" });
    s.upsert({ kind: "machine_active", machine: "PRM020", value: false });
    s.upsert({ kind: "tool_update", tool: "T1", value: { setup_hours: 1, alt: null } });
    s.upsert({ kind: "shifts", value: [{ id: "A", label: "Manhã", start_min: 420, end_min: 930, duration_min: 510 }] });
    s.upsert({ kind: "operators", key: "Grandes A", value: 4 });
    s.upsert({ kind: "setup_crews", group: "Grandes", value: 2 });
    s.upsert({ kind: "holiday_add", dates: ["2026-12-24", "2026-12-25"] });
    s.upsert({ kind: "holiday_remove", dates: ["2026-12-08"] });
    s.upsert({ kind: "extra_day_add", date: "2026-11-07" });
    s.upsert({ kind: "extra_day_remove", date: "2026-10-31" });
    s.upsert({ kind: "setup_override_set", value: { sku: "B", machine: "M2", hours: 2 } });
    s.upsert({ kind: "setup_override_remove", sku: "A", machine: "M1" });
    s.upsert({ kind: "twin_add", value: { tool_id: "T9", sku_a: "X", sku_b: "Y" } });
    s.upsert({ kind: "twin_remove", tool_id: "T8" });
    s.upsert({ kind: "sku_planning", sku: "X", rule: { eco_lot: 5000 } });
    s.upsert({ kind: "sku_planning", sku: "Y", rule: null });
    s.upsert({ kind: "subcontracts", body: { companies: [], sku_subcontracts: {} } });
    s.upsert({ kind: "config_param", key: "max_edd_gap", value: 8 });
    s.upsert({ kind: "preset", name: "equilibrado" });
    const key = s.nextKey();
    s.upsert({ kind: "unavailability_add", key, form: {
      kind: "operator", resource: "", operatorKey: "Grandes A", start_at: "2026-10-20T07:00",
      end_at: "2026-10-20T15:30", category: "Outra", count: 1, reason: "Formação",
    } });
    s.upsert({ kind: "unavailability_update", entryId: "u1", form: {
      kind: "machine", resource: "PRM031", operatorKey: "", start_at: "2026-10-20T07:00",
      end_at: "", category: "Avaria", count: 1, reason: "",
    } });
    s.upsert({ kind: "unavailability_update", entryId: "u2", form: {
      kind: "tool", resource: "T1", operatorKey: "", start_at: "2026-10-20T07:00",
      end_at: "2026-10-21T07:00", category: "Manutenção", count: 1, reason: "",
    } });
    s.upsert({ kind: "unavailability_remove", entryId: "u2" });

    expect(store().buildConfigUpdates(base)).toEqual({
      machine_additions: [{ id: "PRM050", group: "Grandes", active: true }],
      machine_oee: { PRM031: null },
      machine_groups: { PRM031: "Medias" },
      machine_active: { PRM020: false },
      tool_updates: { T1: { setup_hours: 1, alt: null } },
      shifts: [{ id: "A", label: "Manhã", start_min: 420, end_min: 930, duration_min: 510 }],
      operators: { "Grandes A": 4 },
      setup_crews_by_group: { Grandes: 2, Medias: 1 },
      holiday_additions: ["2026-12-24", "2026-12-25"],
      holiday_removals: ["2026-12-08"],
      extra_day_additions: ["2026-11-07"],
      extra_day_removals: ["2026-10-31"],
      setup_overrides: [{ sku: "B", machine: "M2", hours: 2 }],
      twin_additions: [{ tool_id: "T9", sku_a: "X", sku_b: "Y" }],
      twin_removals: ["T8"],
      sku_planning: { X: { eco_lot: 5000 }, Y: null },
      subcontracts: { companies: [], sku_subcontracts: {} },
      config_params: { max_edd_gap: 8 },
      preset: "equilibrado",
      unavailability_additions: [{
        kind: "operator", start_at: "2026-10-20T07:00", end_at: "2026-10-20T15:30",
        category: "Outra", reason: "Formação", shift: "A", group: "Grandes", count: 1,
      }],
      unavailability_updates: [{
        id: "u1", kind: "machine", resource: "PRM031", start_at: "2026-10-20T07:00",
        end_at: "", category: "Avaria", reason: "",
      }],
      unavailability_removals: ["u2"],
    });
  });

  it("um intervalo reaberto depois de fechado vence na ordem em que foi pedido", () => {
    const updates = buildConfigUpdates([
      { kind: "holiday_add", dates: ["2026-08-03", "2026-08-04", "2026-08-05"], id: "a", label: "" },
      { kind: "holiday_remove", dates: ["2026-08-04"], id: "b", label: "" },
    ], base);
    expect(updates).toEqual({
      holiday_additions: ["2026-08-03", "2026-08-05"],
      holiday_removals: ["2026-08-04"],
    });
  });

  it("descreve cada alteração numa linha simples em português", () => {
    expect(describeChange({ kind: "holiday_add", dates: ["2026-08-03", "2026-08-14"] }))
      .toBe("Dias sem produção: 03/08/2026 a 14/08/2026");
    expect(describeChange({ kind: "machine_active", machine: "PRM031", value: false }))
      .toBe("PRM031: desativar (deixa de receber produção)");
    expect(describeChange({ kind: "sku_planning", sku: "X", rule: { eco_lot: 5000, start_buffer_days: 2 } }))
      .toBe("X: lote económico 5000 pç · começar 2 dia(s) antes");
    expect(describeChange({ kind: "twin_add", value: { tool_id: "T9", sku_a: "X", sku_b: "Y" } }))
      .toBe("Gémeas X + Y (ferramenta T9)");
  });

  it("bloqueia alterações enquanto aplica e só retira as linhas aplicadas", () => {
    store().upsert({ kind: "operators", key: "Grandes A", value: 4 });
    const applying = store().beginApply();
    expect(applying).toHaveLength(1);
    store().upsert({ kind: "operators", key: "Medias A", value: 2 });
    store().remove(applying[0].id);
    expect(store().count).toBe(1);

    store().finishApply(false);
    expect(store().count).toBe(1);
    expect(store().applying).toBe(false);

    store().beginApply();
    store().setApplyingJob("job-1");
    expect(store().applyingJobId).toBe("job-1");
    store().finishApply(true);
    expect(store().count).toBe(0);
    expect(store().applyingJobId).toBeNull();
  });

  it("descarta a lista quando o ISOP ativo muda", () => {
    store().syncDataset("d1");
    store().upsert({ kind: "operators", key: "Grandes A", value: 4 });
    store().syncDataset("d1");
    expect(store().count).toBe(1);
    store().syncDataset("d2");
    expect(store().count).toBe(0);
    expect(store().datasetId).toBe("d2");
  });

  it("guarda a lista na sessão do browser", () => {
    store().upsert({ kind: "operators", key: "Grandes A", value: 4 });
    const saved = JSON.parse(sessionStorage.getItem("pp1ConfigDraft") ?? "{}");
    expect(saved.state.items[0]).toMatchObject({ id: "operators:Grandes A", value: 4 });
  });
});

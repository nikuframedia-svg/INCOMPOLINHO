import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BlockedDaysResponse, CapacityResponse, FactoryConfig, Score, Segment } from "../src/api/types";
import { useDataStore } from "../src/stores/useDataStore";

const endpointMocks = vi.hoisted(() => ({
  getWorkdays: vi.fn(),
  getBlockedDays: vi.fn(),
  getToday: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return {
    ...actual,
    ...endpointMocks,
  };
});

import { GanttPage } from "../src/pages/GanttPage";

const config = {
  day_capacity_min: 960,
  shifts: [
    { id: "A", label: "Manhã", start_min: 420, end_min: 900, duration_min: 480 },
    { id: "C", label: "Noite", start_min: 900, end_min: 1380, duration_min: 480 },
  ],
  machines: {
    M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
    M2: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
  },
  tools: {
    T1: { primary: "M1", alt: null, setup_hours: 0.5 },
    BFP079: { primary: "M1", alt: "M2", setup_hours: 1 },
  },
} as FactoryConfig;

const score = {
  otd: 100,
  otd_d: 100,
  tardy_count: 0,
  setups: 1,
  earliness_avg_days: 0,
  utilization_avg: 0,
  utilization_balance: 0,
  weighted_score: 0,
} satisfies Score;

const segment = {
  lot_id: "L1",
  run_id: "R1",
  machine_id: "M1",
  tool_id: "T1",
  day_idx: 0,
  start_min: 420,
  end_min: 480,
  shift: "A",
  qty: 10,
  prod_min: 45,
  setup_min: 15,
  is_continuation: false,
  edd: 0,
  sku: "SKU1",
  twin_outputs: null,
} satisfies Segment;

function capacityWith(capMin: number): CapacityResponse {
  return {
    granularity: "day",
    items: [{
      machine_id: "M1",
      bucket: "0",
      label: "16-Mar",
      date_from: "2026-03-16",
      date_to: "2026-03-16",
      day_indices: [0],
      cap_min: capMin,
      setup_min: 15,
      prod_min: 45,
      load_min: 60,
      util_pct: capMin > 0 ? (60 / capMin) * 100 : 0,
      overload: false,
      n_setups: 1,
    }],
    operators: [],
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  useDataStore.getState().clear();
});

function renderGantt(
  capacity = capacityWith(120),
  blocked: BlockedDaysResponse = {
    workdays: ["2026-03-16", "2026-03-17"],
    holidays: [],
    machine_blocks: [],
    tool_blocks: [],
    machine_intervals: [],
    tool_intervals: [],
    inactive_machines: [],
  },
  renderedSegments: Segment[] = [segment],
  workdays = ["2026-03-16", "2026-03-17"],
) {
  endpointMocks.getWorkdays.mockResolvedValue(workdays);
  endpointMocks.getBlockedDays.mockResolvedValue(blocked);
  endpointMocks.getToday.mockResolvedValue({ today_idx: 0, date: "2026-03-16" });
  useDataStore.setState({
    segments: renderedSegments,
    lots: [],
    score,
    config,
    capacity,
    workdays,
    blockedDays: blocked,
    gateReport: null,
    activeMutations: [],
  });
  return render(<GanttPage />);
}

describe("GanttPage", () => {
  it("identifica a hora manual sem repetir bloqueios antigos", async () => {
    renderGantt(undefined, undefined, [{
      ...segment, left_shift_blockers: ["blocked_by_setup_crew|obsolete"],
    }]);
    act(() => useDataStore.setState({ placementReasons: {
      L1: { kind: "manual", machine_id: "M1", start_at: "2026-03-16T15:30", reason: "teste", historical: true },
    } }));
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));
    fireEvent.click((await screen.findAllByText("SKU1"))[0]);

    expect(screen.getByText(/Início da produção fixado manualmente em M1, 2026-03-16 15:30/)).toBeTruthy();
    expect(screen.getByText(/Motivo: teste/)).toBeTruthy();
    expect(screen.queryByText(/obsolete/)).toBeNull();
  });

  it("distingue histórico preservado de uma restrição física atual", async () => {
    renderGantt(undefined, undefined, [{ ...segment, left_shift_blockers: [] }]);
    act(() => useDataStore.setState({ placementReasons: { L1: { kind: "historical" } } }));
    expect(document.querySelector('[title*="Plano passado"]')?.getAttribute("draggable")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));
    fireEvent.click((await screen.findAllByText("SKU1"))[0]);

    expect(screen.getByText(/Plano passado; execução não confirmada na aplicação/)).toBeTruthy();
  });

  it("explica porque um bloco ficou noutra máquina", async () => {
    const moved = { ...segment, machine_id: "M2", tool_id: "BFP079", sku: "1064169X100" } satisfies Segment;
    renderGantt(undefined, undefined, [moved]);
    const gateReport = {
      status: "best_effort",
      apply_decision: "approval_required",
      requires_approval: true,
      approval_reasons: [],
      hard_gate_passed: true,
      physical_gate_passed: true,
      coverage_gate_passed: true,
      delivery_gate_passed: false,
      subcontract_dispatch_gate_passed: true,
      jit_window_gate_passed: true,
      robustness_gate_passed: null,
      material_gate_passed: true,
      metrics: {},
      violations: [],
      late_detail: [],
      jit_window_detail: [],
      setup_overlap_detail: [],
      proposals: [],
      improvement: {
        contract_version: 1,
        status: "completed",
        moves_accepted: 0,
        accepted_by_scope: {},
        tool_transfers: {
          remaining: 1,
          omitted: 0,
          items: [{
            key: "BFP079:L1:M2->M1",
            tool_id: "BFP079",
            kind: "split",
            from_machine: "M2",
            to_machine: "M1",
            day_idx: 0,
            lot_ids: ["L1"],
            duration_ratio: 1.5,
            reason: "would_delay",
            details: ["lote L1 acabaria no dia 3"],
            summary: "manter na M1 atrasaria: lote L1 acabaria no dia 3 (na M1 a produção demora 1,5× mais)",
          }],
        },
      },
    } as unknown as NonNullable<ReturnType<typeof useDataStore.getState>["gateReport"]>;
    act(() => useDataStore.setState({ gateReport }));

    expect(await screen.findByText("Transferências de ferramenta mantidas (1)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));
    fireEvent.click((await screen.findAllByText("1064169X100"))[0]);

    expect(screen.getByText("Mudança de máquina")).toBeTruthy();
    expect(screen.getByText(/M2 → M1: manter na M1 atrasaria/)).toBeTruthy();
  });

  it("mostra a data e o número operacional em cada dia da linha temporal", async () => {
    const workdays = Array.from({ length: 64 }, (_, index) => {
      const date = new Date(Date.UTC(2026, 8, 8 + index));
      return date.toISOString().slice(0, 10);
    });
    const view = renderGantt(
      undefined,
      undefined,
      [{ ...segment, lot_id: "L63", run_id: "R63", day_idx: 63, edd: 63, production_due_day: 63 }],
      workdays,
    );

    expect(await screen.findByText("08-Set")).toBeTruthy();
    expect(screen.getByText("D0 · Ter")).toBeTruthy();
    expect(screen.getByText("10-Nov")).toBeTruthy();
    expect(screen.getByText("D63 · Ter")).toBeTruthy();
    expect(view.container.querySelector('[title*="Prazo produção D63 · 10-Nov"]')).toBeTruthy();
  });

  it("usa o rótulo Gantt e turnos vindos da configuração", async () => {
    renderGantt();

    expect(await screen.findByRole("button", { name: "Gantt" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "1 Dia" }));

    expect(screen.getByRole("button", { name: "Turnos A+C" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "C · Noite" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Turno B" })).toBeNull();
  });

  it("mantém navegação diária na vista de tabela", async () => {
    renderGantt();

    await screen.findByRole("button", { name: "Gantt" });
    fireEvent.click(screen.getByRole("button", { name: "1 Dia" }));
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));

    expect(screen.getAllByRole("button", { name: "Dia seguinte ›" }).length).toBeGreaterThan(0);
    expect(screen.getByText(/Dia 0 · 16-Mar/)).toBeTruthy();
  });

  it("filtra e identifica ambas as referências de um ciclo gémeo", async () => {
    const twinSegment = {
      ...segment,
      sku: "SKU-A",
      twin_outputs: [
        ["OPA", "SKU-A", 10],
        ["OPB", "SKU-B", 10],
      ],
    } satisfies Segment;
    renderGantt(undefined, undefined, [twinSegment]);

    await screen.findByRole("button", { name: "Gantt" });
    fireEvent.change(screen.getByRole("textbox", { name: "Pesquisar no plano" }), {
      target: { value: "SKU-B" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));

    expect(await screen.findByText("SKU-A + SKU-B (controla: SKU-A)")).toBeTruthy();
  });

  it("pesquisa a segunda referência pelos marcos de um plano compatível", async () => {
    const compatibleTwinSegment = {
      ...segment,
      sku: "SKU-A",
      twin_outputs: null,
      output_milestones: [
        {
          op_id: "OPA",
          sku: "SKU-A",
          qty: 10,
          is_subcontracted: false,
          customer_delivery_day: 3,
          production_due_day: 3,
          internal_target_day: 3,
          material_reference_day: 3,
          material_reference_kind: "customer_delivery",
          material_release_day: 0,
        },
        {
          op_id: "OPB",
          sku: "SKU-B",
          qty: 10,
          is_subcontracted: false,
          customer_delivery_day: 3,
          production_due_day: 3,
          internal_target_day: 3,
          material_reference_day: 3,
          material_reference_kind: "customer_delivery",
          material_release_day: 0,
        },
      ],
    } satisfies Segment;
    renderGantt(undefined, undefined, [compatibleTwinSegment]);

    await screen.findByRole("button", { name: "Gantt" });
    fireEvent.change(screen.getByRole("textbox", { name: "Pesquisar no plano" }), {
      target: { value: "SKU-B" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));

    expect(await screen.findByText("SKU-A")).toBeTruthy();
  });

  it("separa a entrega ISOP da janela conjunta num lote gémeo", async () => {
    const workdays = Array.from({ length: 15 }, (_, index) => {
      const date = new Date(Date.UTC(2026, 8, 8 + index));
      return date.toISOString().slice(0, 10);
    });
    const twinSegment = {
      ...segment,
      lot_id: "LOT_TWIN_BFP125_7",
      tool_id: "BFP125",
      sku: "1413147X070",
      day_idx: 0,
      customer_delivery_day: 7,
      production_due_day: 7,
      internal_target_day: 7,
      material_reference_day: 7,
      material_reference_kind: "customer_delivery",
      material_release_day: 0,
      twin_outputs: [
        ["OPA", "1403150X050", 6400],
        ["OPB", "1413147X070", 6400],
      ],
      output_milestones: [
        {
          op_id: "OPA",
          sku: "1403150X050",
          qty: 6400,
          is_subcontracted: false,
          customer_delivery_day: 10,
          production_due_day: 10,
          internal_target_day: 10,
          material_reference_day: 10,
          material_reference_kind: "customer_delivery",
          material_release_day: 3,
        },
        {
          op_id: "OPB",
          sku: "1413147X070",
          qty: 6400,
          is_subcontracted: false,
          customer_delivery_day: 7,
          production_due_day: 7,
          internal_target_day: 7,
          material_reference_day: 7,
          material_reference_kind: "customer_delivery",
          material_release_day: 0,
        },
      ],
    } satisfies Segment;
    renderGantt(undefined, undefined, [twinSegment], workdays);

    await screen.findByRole("button", { name: "Gantt" });
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));
    fireEvent.click(await screen.findByText("1403150X050 + 1413147X070 (controla: 1413147X070)"));

    expect(screen.getByText("Janela conjunta de produção")).toBeTruthy();
    expect(screen.getByText("Dia 0 (08-Set) → Dia 7 (15-Set)")).toBeTruthy();
    expect(screen.getByText("Material comum libertado por")).toBeTruthy();
    expect(screen.getByText("Libertação se isolada")).toBeTruthy();
    expect(screen.queryByText("Referência da janela de material")).toBeNull();
    const milestones = screen.getByRole("table", { name: "Datas por referência" });
    const laterOutput = within(milestones).getByRole("row", { name: /1403150X050/ });
    const controllingOutput = within(milestones).getByRole("row", { name: /1413147X070/ });
    expect(within(laterOutput).queryByText("liberta o material comum")).toBeNull();
    expect(within(laterOutput).getAllByText("Dia 10 (18-Set)")).toHaveLength(4);
    expect(within(controllingOutput).getByText(/limita o prazo/)).toBeTruthy();
    expect(within(controllingOutput).getByText(/liberta o material comum/)).toBeTruthy();
    expect(within(controllingOutput).getAllByText("Dia 7 (15-Set)")).toHaveLength(4);
  });

  it("separa os envios de cada output num lote gémeo subcontratado", async () => {
    const workdays = Array.from({ length: 15 }, (_, index) => {
      const date = new Date(Date.UTC(2026, 8, 8 + index));
      return date.toISOString().slice(0, 10);
    });
    const twinSegment = {
      ...segment,
      lot_id: "LOT_TWIN_BFP178_10",
      tool_id: "BFP178",
      sku: "2185094X110.10",
      customer_delivery_day: 10,
      subcontract_dispatch_day: 3,
      production_due_day: 3,
      internal_target_day: 3,
      material_reference_day: 3,
      material_reference_kind: "subcontract_dispatch",
      material_release_day: -4,
      twin_outputs: [
        ["OPA", "2100373X120.10", 28000],
        ["OPB", "2185094X110.10", 28000],
      ],
      output_milestones: [
        {
          op_id: "OPA",
          sku: "2100373X120.10",
          qty: 28000,
          is_subcontracted: true,
          customer_delivery_day: 14,
          subcontract_dispatch_day: 7,
          production_due_day: 7,
          internal_target_day: 7,
          material_reference_day: 7,
          material_reference_kind: "subcontract_dispatch",
          material_release_day: 0,
        },
        {
          op_id: "OPB",
          sku: "2185094X110.10",
          qty: 28000,
          is_subcontracted: true,
          customer_delivery_day: 10,
          subcontract_dispatch_day: 3,
          production_due_day: 3,
          internal_target_day: 3,
          material_reference_day: 3,
          material_reference_kind: "subcontract_dispatch",
          material_release_day: -4,
        },
      ],
    } satisfies Segment;
    renderGantt(undefined, undefined, [twinSegment], workdays);

    await screen.findByRole("button", { name: "Gantt" });
    fireEvent.click(screen.getByRole("button", { name: "Tabela" }));
    fireEvent.click(await screen.findByText("2100373X120.10 + 2185094X110.10 (controla: 2185094X110.10)"));

    expect(screen.getByText("Dia -4 (04-Set) → Dia 3 (11-Set)")).toBeTruthy();
    expect(screen.queryByText("Referência da janela de material")).toBeNull();
    const milestones = screen.getByRole("table", { name: "Datas por referência" });
    const laterOutput = within(milestones).getByRole("row", { name: /2100373X120\.10/ });
    const controllingOutput = within(milestones).getByRole("row", { name: /2185094X110\.10/ });
    expect(within(laterOutput).queryByText("liberta o material comum")).toBeNull();
    expect(within(laterOutput).getAllByText("Dia 7 (15-Set)")).toHaveLength(4);
    expect(within(controllingOutput).getByText(/limita o prazo/)).toBeTruthy();
    expect(within(controllingOutput).getByText(/liberta o material comum/)).toBeTruthy();
    expect(within(controllingOutput).getAllByText("Dia 3 (11-Set)")).toHaveLength(4);
  });

  it("calcula a ocupação com a capacidade diária real", async () => {
    renderGantt(capacityWith(120));

    expect(await screen.findByText("50%")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "1 Dia" }));

    expect(screen.getByText("50% utilização média")).toBeTruthy();
  });

  it("mostra ocupação 0 quando a capacidade real do dia é 0", async () => {
    renderGantt(capacityWith(0));

    expect((await screen.findAllByText("0%")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "1 Dia" }));

    expect(screen.getByText("0% utilização média")).toBeTruthy();
  });

  it("mostra indisponibilidade de ferramenta fora das lanes das máquinas", async () => {
    const { container } = renderGantt(capacityWith(120), {
      workdays: ["2026-03-16", "2026-03-17"],
      holidays: [],
      machine_blocks: [],
      tool_blocks: [{ tool_id: "BFP079", day_idx: 1, date: "2026-03-17" }],
      machine_intervals: [],
      tool_intervals: [{
        tool_id: "BFP079",
        start_day: 1,
        start_min: 420,
        end_day: 1,
        end_min: 900,
        category: "Avaria",
        reason: "Manutenção",
        start_at: "2026-03-17T07:00:00",
        end_at: "2026-03-17T15:00:00",
      }],
      inactive_machines: [],
    });

    expect(await screen.findByText("Recursos")).toBeTruthy();
    expect(screen.getByText("BFP079")).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="resource-availability-overlay"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-testid="machine-availability-overlay"]')).toHaveLength(0);
  });

  it("continua a marcar indisponibilidade de máquina na lane da máquina", async () => {
    const { container } = renderGantt(capacityWith(120), {
      workdays: ["2026-03-16", "2026-03-17"],
      holidays: [],
      machine_blocks: [],
      tool_blocks: [],
      machine_intervals: [{
        machine_id: "M1",
        start_day: 1,
        start_min: 420,
        end_day: 1,
        end_min: 900,
        category: "Avaria",
        reason: "Manutenção",
        start_at: "2026-03-17T07:00:00",
        end_at: "2026-03-17T15:00:00",
      }],
      tool_intervals: [],
      inactive_machines: [],
    });

    await screen.findByRole("button", { name: "Gantt" });
    expect(container.querySelectorAll('[data-testid="machine-availability-overlay"]')).toHaveLength(1);
    expect(container.querySelectorAll('[data-testid="resource-availability-overlay"]')).toHaveLength(1);
    expect(container.querySelector('[data-testid="resource-availability-overlay"]')?.textContent).toContain("M1");
  });

  it("mostra ferramentas, máquinas e ausências de operadores na mesma faixa", async () => {
    const { container } = renderGantt(capacityWith(120), {
      workdays: ["2026-03-16", "2026-03-17"],
      holidays: [],
      machine_blocks: [],
      tool_blocks: [],
      machine_intervals: [{
        machine_id: "M1", start_day: 1, start_min: 420, end_day: 1, end_min: 900,
        category: "Manutenção", reason: "Revisão", start_at: "2026-03-17T07:00:00",
        end_at: "2026-03-17T15:00:00",
      }],
      tool_intervals: [{
        tool_id: "BFP079", start_day: 1, start_min: 420, end_day: 1, end_min: 900,
        category: "Avaria", reason: "Reparação", start_at: "2026-03-17T07:00:00",
        end_at: "2026-03-17T15:00:00",
      }],
      operator_intervals: [{
        id: "absence-1", group: "Grandes", shift: "A", count: 3,
        start_day: 1, start_min: 420, end_day: 1, end_min: 900,
        category: "Outra", reason: "doença", start_at: "2026-03-17T07:00:00",
        end_at: "2026-03-17T15:00:00",
      }, {
        id: "absence-2", group: "Grandes", shift: "A", count: 1,
        start_day: 1, start_min: 420, end_day: 1, end_min: 900,
        category: "Outra", reason: "férias", start_at: "2026-03-17T07:00:00",
        end_at: "2026-03-17T15:00:00",
      }],
      inactive_machines: [],
    });

    expect(await screen.findByText("Recursos")).toBeTruthy();
    const marks = container.querySelectorAll<HTMLElement>('[data-testid="resource-availability-overlay"]');
    expect(marks).toHaveLength(4);
    expect([...marks].map((mark) => mark.textContent)).toEqual(expect.arrayContaining([
      "BFP079", "M1", "A -3 · Grandes", "A -1 · Grandes",
    ]));
    expect([...marks].find((mark) => mark.textContent === "A -3 · Grandes")?.title).toContain("doença");
    expect(container.querySelectorAll('[data-testid="machine-availability-overlay"]')).toHaveLength(1);
  });

  it("mantém o fim de semana visível quando pesquisa uma referência", async () => {
    const weekend: BlockedDaysResponse = {
      workdays: ["2026-03-20", "2026-03-21"],
      holidays: [{ day_idx: 1, date: "2026-03-21" }],
      machine_blocks: [],
      tool_blocks: [],
      machine_intervals: [],
      tool_intervals: [],
      inactive_machines: [],
    };
    const { container } = renderGantt(capacityWith(120), weekend, undefined, weekend.workdays);

    await screen.findByRole("button", { name: "Gantt" });
    expect(container.querySelectorAll('[data-overlay-kind="holiday"]')).toHaveLength(2);

    fireEvent.change(screen.getByRole("textbox", { name: "Pesquisar no plano" }), {
      target: { value: "SKU1" },
    });

    const holidayOverlays = container.querySelectorAll<HTMLElement>('[data-overlay-kind="holiday"]');
    expect(holidayOverlays).toHaveLength(2);
    expect(holidayOverlays[0].style.backgroundImage).toContain("repeating-linear-gradient");
  });

  it("mostra apenas a lane escolhida sem perder o fim de semana", async () => {
    const weekend: BlockedDaysResponse = {
      workdays: ["2026-03-20", "2026-03-21"],
      holidays: [{ day_idx: 1, date: "2026-03-21" }],
      machine_blocks: [],
      tool_blocks: [],
      machine_intervals: [],
      tool_intervals: [],
      inactive_machines: [],
    };
    const { container } = renderGantt(capacityWith(120), weekend, undefined, weekend.workdays);

    await screen.findByRole("button", { name: "Gantt" });
    fireEvent.change(screen.getByRole("combobox", { name: "Filtrar o plano por máquina" }), {
      target: { value: "M1" },
    });

    const lanes = container.querySelectorAll<HTMLElement>('[data-testid="machine-timeline-lane"]');
    expect(lanes).toHaveLength(1);
    expect(lanes[0].dataset.machineId).toBe("M1");
    expect(container.querySelectorAll('[data-overlay-kind="holiday"]')).toHaveLength(1);
  });

  it("atualiza datas e bloqueios quando o calendário central é renovado", async () => {
    const { container } = renderGantt();
    await screen.findByText("16-Mar");

    const refreshed: BlockedDaysResponse = {
      workdays: ["2026-03-18", "2026-03-19"],
      holidays: [{ day_idx: 1, date: "2026-03-19" }],
      machine_blocks: [],
      tool_blocks: [],
      machine_intervals: [],
      tool_intervals: [],
      inactive_machines: [],
    };
    act(() => {
      useDataStore.setState({
        workdays: refreshed.workdays,
        blockedDays: refreshed,
      });
    });

    expect(await screen.findByText("18-Mar")).toBeTruthy();
    expect(container.querySelectorAll('[data-overlay-kind="holiday"]')).toHaveLength(2);
  });
});

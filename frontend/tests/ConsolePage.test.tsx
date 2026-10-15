import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ConsoleData, GateReport, Score } from "../src/api/types";
import { useAppStore } from "../src/stores/useAppStore";
import { useDataStore } from "../src/stores/useDataStore";

const endpointMocks = vi.hoisted(() => ({
	  getToday: vi.fn(),
	  getWorkdays: vi.fn(),
	  getConsole: vi.fn(),
  getHealth: vi.fn(),
  getTrust: vi.fn(),
  getPlanView: vi.fn(),
  getScore: vi.fn(),
  getGateReport: vi.fn(),
  getSegments: vi.fn(),
  getLots: vi.fn(),
  getConfig: vi.fn(),
  getLearning: vi.fn(),
  canRevert: vi.fn(),
  getActiveMutations: vi.fn(),
  getManualEdits: vi.fn(),
  recalculate: vi.fn(),
  releaseManualEdits: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return {
    ...actual,
    ...endpointMocks,
  };
});

vi.mock("../src/components/Sidebar", () => ({ Sidebar: () => <aside /> }));
vi.mock("../src/components/ChatPanel", () => ({ ChatPanel: () => <aside>Chat</aside> }));
vi.mock("../src/components/ui/UploadZone", () => ({ UploadZone: () => <div>Upload</div> }));
vi.mock("../src/pages/GanttPage", () => ({ GanttPage: () => <div>Plano page</div> }));
vi.mock("../src/pages/RiskPage", () => ({ RiskPage: () => <div>Risco page</div> }));
vi.mock("../src/pages/ConfigPage", () => ({ ConfigPage: () => <div>Config page</div> }));
vi.mock("../src/pages/DeliveriesPage", () => ({ DeliveriesPage: () => <div>Entregas page</div> }));
vi.mock("../src/pages/JournalPage", () => ({ JournalPage: () => <div>Journal page</div> }));
vi.mock("../src/pages/RulesPage", () => ({ RulesPage: () => <div>Regras page</div> }));
vi.mock("../src/pages/CapacityPage", () => ({ CapacityPage: () => <div>Capacidade page</div> }));

import { Shell } from "../src/components/Shell";
import { ConsolePage } from "../src/pages/ConsolePage";

const score: Score = {
  otd: 99.4,
  otd_d: 97.1,
  tardy_count: 1,
  setups: 2,
  earliness_avg_days: 1,
  utilization_avg: 80,
  utilization_balance: 90,
  weighted_score: 95,
};

const consoleData = {
  date: "2026-03-05",
  state: { color: "green", phrase: "2 máquinas a produzir. Sem problemas." },
  actions: [],
  machines: [
    {
      machine_id: "M1",
      group: "Grandes",
      utilization_pct: 78,
      current_tool: "T1",
      current_sku: "SKU1",
      runs: [],
      next_setup_at: null,
      current_state: "producing",
      eta_current: null,
      total_pcs: 1200,
    },
  ],
  setups_today: [
    {
      time: "08:00",
      start_min: 480,
      shift: "A",
      machine: "M1",
      from_tool: "T0",
      to_tool: "T1",
      sku: "SKU1",
      duration_min: 30,
      already_mounted: false,
    },
  ],
  top_risks: [],
  expedition: [
    { client: "ACME", ready: 1, partial: 1, not_ready: 0, total: 2 },
  ],
  tomorrow: {
    date: "2026-03-06",
    setups: [
      {
        time: "07:30",
        start_min: 450,
        shift: "A",
        machine: "M3",
        from_tool: "T4",
        to_tool: "T5",
        sku: "SKU5",
        duration_min: 45,
        already_mounted: false,
      },
    ],
    operators: [
      { shift: "A", group: "Grandes", required: 4, available: 3, deficit: 1 },
    ],
    expeditions_summary: "2 (ACME ×2)",
    problems: ["Falta 1 operador Grandes turno A"],
    ok: false,
  },
  summary: [
    { text: "Qui, 2026-03-05", color: "default" },
    { text: "Expedição: 2 encomendas, todas prontas.", color: "green" },
  ],
  operational_summary: {
    production_by_group: [
      { group: "Grandes", machines: ["M1"], count: 1 },
    ],
    setups_by_group_shift: [
      { group: "Grandes", shift: "A", count: 1 },
    ],
    average_utilization_pct: 78,
    unavailable: { machines: [], tools: [], operators: [] },
    trials: [],
    expedition: { ready: 1, partial: 1, not_ready: 0 },
  },
  day_overview: {
    today: { unavailable_count: 0, trial_count: 0 },
    tomorrow: { setups_count: 1, operator_deficit: 1, problems_count: 1 },
  },
} as ConsoleData;

function mockConsoleEndpoints() {
  endpointMocks.getToday.mockResolvedValue({ today_idx: 0, date: "2026-03-05" });
  endpointMocks.getWorkdays.mockResolvedValue(["2026-03-05", "2026-03-06", "2026-03-07"]);
  endpointMocks.getConsole.mockResolvedValue(consoleData);
}

function mockShellEndpoints() {
  mockConsoleEndpoints();
  endpointMocks.getHealth.mockResolvedValue({
    has_data: true,
    dataset: {
      id: "dataset-1",
      filename: "plano.xlsx",
      uploaded_at: "2026-03-05T08:00:00",
      n_ops: 12,
      n_segments: 34,
      trust_score: 100,
      trust_gate: "ok",
      otd: 99.4,
      tardy_count: 1,
    },
    copilot: { available: false, reason: "Teste" },
  });
  endpointMocks.getTrust.mockResolvedValue({
    score: 100,
    gate: "ok",
    n_ops: 12,
    n_issues: 0,
    dimensions: [],
  });
  endpointMocks.getScore.mockResolvedValue(score);
  endpointMocks.getPlanView.mockResolvedValue({
    plan_revision: 1,
    dataset: { id: "dataset-1", filename: "plano.xlsx", trust_score: 100, trust_gate: "full_auto" },
    dataset_id: "dataset-1", active_mutations: [], manual_edits: [], can_revert: false, learning: null,
    score,
    gate_report: null,
    segments: [],
    lots: [],
    config: {},
    capacity: {},
    workdays: ["2026-03-05", "2026-03-06", "2026-03-07"],
    blocked_days: {
      workdays: ["2026-03-05", "2026-03-06", "2026-03-07"],
      holidays: [],
      machine_blocks: [],
      tool_blocks: [],
      machine_intervals: [],
      tool_intervals: [],
      inactive_machines: [],
    },
  });
  endpointMocks.getGateReport.mockResolvedValue(null);
  endpointMocks.getSegments.mockResolvedValue([]);
  endpointMocks.getLots.mockResolvedValue([]);
  endpointMocks.getConfig.mockResolvedValue({});
  endpointMocks.getLearning.mockResolvedValue(null);
  endpointMocks.canRevert.mockResolvedValue({ can_revert: false });
  endpointMocks.getActiveMutations.mockResolvedValue({ active: false, mutations: [] });
  endpointMocks.getManualEdits.mockResolvedValue({ active: false, edits: [], can_revert: false });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  sessionStorage.clear();
  localStorage.clear();
  useAppStore.setState({
    activePage: "console",
    chatOpen: false,
    hasData: false,
    isUploading: false,
    trustScore: null,
    trustGate: null,
    dataset: null,
  });
  useDataStore.getState().clear();
});

describe("ConsolePage", () => {
  it("destaca recursos indisponíveis e mantém os grupos vazios neutros", async () => {
    mockConsoleEndpoints();
    endpointMocks.getConsole.mockResolvedValue({
      ...consoleData,
      day_overview: { ...consoleData.day_overview, today: { unavailable_count: 1, trial_count: 0 } },
      operational_summary: {
        ...consoleData.operational_summary,
        unavailable: {
          machines: [{ resource: "PRM039", category: "Manutenção", reason: "Avaria" }],
          tools: [],
          operators: [],
        },
      },
    } as ConsoleData);

    render(<ConsolePage />);

    const region = await screen.findByRole("region", { name: "Recursos indisponíveis" });
    expect(region.style.borderLeft).toContain("rgb(194, 65, 12)");
    expect(within(region).getByText("Máquinas: PRM039").style.fontWeight).toBe("700");
    expect(within(region).getByText("Ferramentas: nenhuma").style.fontWeight).toBe("400");
    expect(screen.getByText("Indisp. 1").style.fontWeight).toBe("700");
  });

  it("retira o destaque ao mudar para um dia sem indisponibilidades", async () => {
    mockConsoleEndpoints();
    endpointMocks.getConsole.mockImplementation((day: number) => Promise.resolve(day === 0 ? {
      ...consoleData,
      operational_summary: {
        ...consoleData.operational_summary,
        unavailable: {
          machines: [],
          tools: [{ resource: "BFP079", category: "Avaria", reason: "" }],
          operators: [{ group: "Grandes", shift: "A", count: 3, reason: "Ausência" }],
        },
      },
    } as ConsoleData : consoleData));

    render(<ConsolePage />);

    const region = await screen.findByRole("region", { name: "Recursos indisponíveis" });
    expect(within(region).getByText("Ferramentas: BFP079").style.fontWeight).toBe("700");
    expect(within(region).getByText("Pessoas: Grandes A: 3").style.fontWeight).toBe("700");
    fireEvent.change(screen.getByLabelText("Escolher data"), { target: { value: "2026-03-06" } });
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Recursos indisponíveis" })).getByText("Ferramentas: nenhuma")).toBeTruthy());
    expect(screen.getByRole("region", { name: "Recursos indisponíveis" }).style.borderLeft).toContain("transparent");
    expect(screen.getByText("Indisp. 0").style.fontWeight).toBe("");
  });

  it("mostra os riscos pela ordem do servidor com estado em linguagem simples", async () => {
    mockConsoleEndpoints();
    endpointMocks.getConsole.mockResolvedValue({
      ...consoleData,
      top_risks: [
        {
          lot_id: "late", sku: "SKU-LATE", machine_id: "PRM042", planned_machine_id: "PRM042",
          risk_level: "critical", risk_score: 1, edd: 5, slack: -2, slack_days: -2,
          production_day: 3, status: "late", cause: "operator", binding_constraint: "operator",
        },
        {
          lot_id: "limit", sku: "SKU-LIMIT", machine_id: "PRM031", planned_machine_id: "PRM031",
          risk_level: "critical", risk_score: 0.9, edd: 2, slack: 0, slack_days: 0,
          production_day: 1, status: "at_limit", cause: null, binding_constraint: "capacity",
        },
        {
          lot_id: "short", sku: "SKU-SHORT", machine_id: "PRM043", planned_machine_id: "PRM043",
          risk_level: "high", risk_score: 0.5, edd: 1, slack: 1, slack_days: 1,
          production_day: 0, status: "short_slack", cause: null, binding_constraint: "crew",
        },
      ],
    } as ConsoleData);

    render(<ConsolePage />);

    expect(await screen.findByText("Lotes em risco")).toBeTruthy();
    const skus = screen.getAllByText(/^SKU-(LATE|LIMIT|SHORT)$/).map((node) => node.textContent);
    expect(skus).toEqual(["SKU-LATE", "SKU-LIMIT", "SKU-SHORT"]);
    expect(screen.getByText("PRM042 · SKU-LATE · Atrasado · falta de operadores no turno")).toBeTruthy();
    expect(screen.getByText("PRM031 · SKU-LIMIT · No limite")).toBeTruthy();
    expect(screen.getByText("PRM043 · SKU-SHORT · Folga curta")).toBeTruthy();
    expect(screen.getByText(/acaba 2 dias depois do prazo de produção/)).toBeTruthy();
    expect(screen.getByText(/acaba no último dia do prazo de produção/)).toBeTruthy();
    expect(screen.getByText(/1 dia de folga/)).toBeTruthy();
    const text0 = document.body.textContent ?? "";
    expect(text0).not.toMatch(/\(s\)/);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/equipa|capacidade|margem/i);
  });

  it("lista encomendas atrasadas; um plano antigo com produções longas já não mostra esse cartão", async () => {
    mockConsoleEndpoints();
    useDataStore.setState({
      gateReport: {
        metrics: { orders_total: 709, orders_on_time: 701, orders_late: 8, order_otd: 98.9 },
        late_order_detail: [
          { client: "JOAO DEUS", sku: "JDE002", machine_id: "PRM042", order_qty: 5000, covered_qty: 2000, shortfall_qty: 3000, due_day: 26, ready_day: 29, late_days: 3 },
          { client: "FAURECIA", sku: "FAU001", order_qty: 800, covered_qty: 0, shortfall_qty: 800, due_day: 27, ready_day: 28, late_days: 1 },
          { client: "HANON", sku: "HAN010", order_qty: 1200, covered_qty: 0, shortfall_qty: 1200, due_day: 30, ready_day: null, late_days: null },
        ],
        long_production_detail: [
          { lot_id: "LOT_JDE002", sku: "JDE002", machine_id: "PRM042", workdays: 5, limit_workdays: 4, excess_workdays: 1, days: [26, 27, 28, 29, 30], consecutive_days: [26, 27, 28, 29, 30] },
          { lot_id: "LOT_TP", sku: "TP042173", machine_id: "PRM042", workdays: 5, limit_workdays: 4, excess_workdays: 1, days: [33, 34, 35, 36, 37, 40, 41], consecutive_days: [33, 34, 35, 36, 37] },
        ],
      } as unknown as GateReport,
    });

    render(<ConsolePage />);

    expect(await screen.findByText("Encomendas atrasadas")).toBeTruthy();
    const rows = screen.getAllByTestId("late-order-row");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("JOAO DEUS")).toBeTruthy();
    expect(within(rows[0]).getByText("PRM042")).toBeTruthy();
    expect(rows[0].textContent).toMatch(/No dia de entrega faltam 3\s?000 de 5\s?000 pç · Entrega: dia 26 · Pronta: dia 29/);
    expect(within(rows[0]).getByText("3 dias de atraso")).toBeTruthy();
    expect(within(rows[1]).getByText("1 dia de atraso")).toBeTruthy();
    expect(within(rows[2]).getByText("não fica completa no plano")).toBeTruthy();
    expect(rows[2].textContent).not.toMatch(/Pronta/);
    expect(screen.getByText("Encomendas que não ficam prontas até ao dia de entrega")).toBeTruthy();
    expect(screen.getByText("8")).toBeTruthy();
    // 3 rows shown out of 8 late orders: the rest comes from the total, not the list length.
    expect(screen.getByText("e mais 5 encomendas atrasadas")).toBeTruthy();

    // A fábrica retirou o limite de dias seguidos (09/10/2026).
    expect(screen.queryByText("Produções longas")).toBeNull();
    expect(screen.queryAllByTestId("long-production-row")).toHaveLength(0);
    expect(document.body.textContent ?? "").not.toMatch(/dias seguidos/);
    expect(document.body.textContent ?? "").not.toMatch(/\(s\)/);
  });

  it("e mais N usa o total de encomendas atrasadas mesmo com a lista cortada", async () => {
    mockConsoleEndpoints();
    const detail = Array.from({ length: 50 }, (_, index) => ({
      client: `C${index}`, sku: `S${index}`, order_qty: 10, covered_qty: 0, shortfall_qty: 10,
      due_day: 5, ready_day: 6, late_days: 1,
    }));
    useDataStore.setState({
      gateReport: {
        metrics: { orders_total: 300, orders_on_time: 180, orders_late: 120, order_otd: 60 },
        late_order_detail: detail,
      } as unknown as GateReport,
    });

    render(<ConsolePage />);

    expect(await screen.findByText("Encomendas atrasadas")).toBeTruthy();
    expect(screen.getAllByTestId("late-order-row")).toHaveLength(10);
    expect(screen.getByText("e mais 110 encomendas atrasadas")).toBeTruthy();
  });

  it("e mais 1 encomenda atrasada no singular", async () => {
    mockConsoleEndpoints();
    const detail = Array.from({ length: 11 }, (_, index) => ({
      client: `C${index}`, sku: `S${index}`, order_qty: 10, covered_qty: 0, shortfall_qty: 10,
      due_day: 5, ready_day: 6, late_days: 1,
    }));
    useDataStore.setState({
      gateReport: {
        metrics: { orders_late: 11 },
        late_order_detail: detail,
      } as unknown as GateReport,
    });

    render(<ConsolePage />);

    expect(await screen.findByText("Encomendas atrasadas")).toBeTruthy();
    expect(screen.getByText("e mais 1 encomenda atrasada")).toBeTruthy();
  });

  it("plano antigo sem os campos novos mostra — e não falha", async () => {
    mockConsoleEndpoints();
    useDataStore.setState({
      gateReport: { metrics: { tardy_count: 2 }, late_detail: [] } as unknown as GateReport,
    });

    render(<ConsolePage />);

    expect(await screen.findByText("Encomendas atrasadas")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.queryByText("Produções longas")).toBeNull();
    expect(screen.queryAllByTestId("late-order-row")).toHaveLength(0);
  });

  it("funde operação no resumo e move amanhã para Setups e Expedições", async () => {
    mockConsoleEndpoints();

    render(<ConsolePage />);

    expect(await screen.findByText("Resumo do Dia")).toBeTruthy();
    expect(screen.getByText("PRODUÇÃO:")).toBeTruthy();
    expect(screen.getByText("SETUPS:")).toBeTruthy();
    expect(screen.getByText("RISCOS:")).toBeTruthy();
    expect(screen.getByText(/Ocupação média/)).toBeTruthy();
    expect(screen.getByText("Expedições")).toBeTruthy();
    expect(screen.getAllByText("Turno A").length).toBeGreaterThan(0);
    expect(screen.getByText("M3")).toBeTruthy();
    expect(screen.getByText("2 (ACME ×2)")).toBeTruthy();
    expect(screen.queryByText("Preparação de amanhã")).toBeNull();
    expect(screen.queryByText("Expedição")).toBeNull();
    expect(screen.queryByText(/Sem problemas/i)).toBeNull();
	  });

  it("permite escolher o dia clicando na data", async () => {
    mockConsoleEndpoints();

    render(<ConsolePage />);

    const picker = await screen.findByLabelText("Escolher data");
    fireEvent.change(picker, { target: { value: "2026-03-06" } });

    await waitFor(() => {
      expect(endpointMocks.getConsole).toHaveBeenLastCalledWith(1);
    });
    expect(JSON.parse(sessionStorage.getItem("pp1ConsoleDay") ?? "null")).toMatchObject({
      today: "2026-03-05", date: "2026-03-06", day: 1,
    });
    expect(localStorage.getItem("pp1ConsoleLastDay")).toBeNull();
  });
});

describe("ConsolePage — dia de abertura", () => {
  // Uso de 12/10/2026: aberto no domingo 11/10, continuava a abrir no domingo.
  const octoberDays = ["2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13"];
  const sundayChoice = {
    today: "2026-10-11", local: "2026-10-11", date: "2026-10-11", day: 2,
  };

  function mockMonday() {
    mockConsoleEndpoints();
    endpointMocks.getToday.mockResolvedValue({ today_idx: 3, date: "2026-10-12" });
    endpointMocks.getWorkdays.mockResolvedValue(octoberDays);
    endpointMocks.getConsole.mockImplementation((day: number) => Promise.resolve({
      ...consoleData, date: octoberDays[day],
    } as ConsoleData));
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  it("abre no hoje do servidor mesmo com domingo guardado por versões antigas", async () => {
    vi.setSystemTime(new Date(2026, 9, 12, 11, 21));
    localStorage.setItem("pp1ConsoleLastDay", "2");
    sessionStorage.setItem("pp1ConsoleDay", JSON.stringify(sundayChoice));
    mockMonday();

    render(<ConsolePage />);

    expect(await screen.findByDisplayValue("2026-10-12")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Hoje" }) as HTMLButtonElement).disabled).toBe(true);
    expect(endpointMocks.getConsole).toHaveBeenCalledWith(3);
    expect(endpointMocks.getConsole).not.toHaveBeenCalledWith(2);
    expect(localStorage.getItem("pp1ConsoleLastDay")).toBeNull();
  });

  it("valores guardados inválidos são ignorados", async () => {
    vi.setSystemTime(new Date(2026, 9, 12, 9, 0));
    sessionStorage.setItem("pp1ConsoleDay", "2");
    mockMonday();

    render(<ConsolePage />);

    expect(await screen.findByDisplayValue("2026-10-12")).toBeTruthy();
    expect(endpointMocks.getConsole).toHaveBeenCalledWith(3);
  });

  it("mantém o dia escolhido à mão na mesma sessão do separador e Hoje volta ao dia de hoje", async () => {
    vi.setSystemTime(new Date(2026, 9, 12, 9, 0));
    mockMonday();

    const first = render(<ConsolePage />);
    fireEvent.change(await screen.findByLabelText("Escolher data"), { target: { value: "2026-10-13" } });
    expect(await screen.findByDisplayValue("2026-10-13")).toBeTruthy();
    first.unmount();

    // Recarregar a página no mesmo separador mantém a escolha.
    endpointMocks.getConsole.mockClear();
    render(<ConsolePage />);
    expect(await screen.findByDisplayValue("2026-10-13")).toBeTruthy();
    expect(endpointMocks.getConsole).not.toHaveBeenCalledWith(3);
    expect(screen.getByText("Dia 4")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Hoje" }));
    expect(await screen.findByDisplayValue("2026-10-12")).toBeTruthy();
    expect(sessionStorage.getItem("pp1ConsoleDay")).toBeNull();
  });

  it("a escolha de ontem não passa para hoje, mesmo no mesmo separador", async () => {
    vi.setSystemTime(new Date(2026, 9, 11, 22, 0));
    mockConsoleEndpoints();
    endpointMocks.getToday.mockResolvedValue({ today_idx: 2, date: "2026-10-11" });
    endpointMocks.getWorkdays.mockResolvedValue(octoberDays);
    endpointMocks.getConsole.mockImplementation((day: number) => Promise.resolve({
      ...consoleData, date: octoberDays[day],
    } as ConsoleData));

    render(<ConsolePage />);
    fireEvent.change(await screen.findByLabelText("Escolher data"), { target: { value: "2026-10-09" } });
    expect(await screen.findByDisplayValue("2026-10-09")).toBeTruthy();

    // O separador fica aberto durante a noite; na segunda-feira volta a ficar visível.
    vi.setSystemTime(new Date(2026, 9, 12, 7, 30));
    endpointMocks.getToday.mockResolvedValue({ today_idx: 3, date: "2026-10-12" });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(await screen.findByDisplayValue("2026-10-12")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Hoje" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Shell", () => {
  // Decisão de 15/10/2026: lotes fixados à mão visíveis, cada um com «Soltar»;
  // «Recalcular» só apaga as alterações manuais depois de confirmar.
  function mockPinnedPlan() {
    mockShellEndpoints();
    endpointMocks.getPlanView.mockResolvedValue({
      plan_revision: 1,
      dataset: { id: "dataset-1", filename: "plano.xlsx", trust_score: 100, trust_gate: "full_auto" },
      dataset_id: "dataset-1", active_mutations: [], can_revert: false, learning: null,
      score, gate_report: null, segments: [], config: {}, capacity: {},
      lots: [{ id: "LOT_JTE001_PRM043_6800016767A.10_57", sku: "6800016767A.10", op_id: "OP1",
        machine_id: "PRM043", twin_outputs: null }],
      manual_edits: [{ id: "e1", created_at: "2026-10-15T12:30:00Z", lot_id: "LOT_JTE001_PRM043_6800016767A.10_57",
        source_days: [0], target_day: 1, target_start_min: 525, target_machine: "PRM043", delivery_risk_confirmed: false }],
      workdays: ["2026-03-05", "2026-03-06", "2026-03-07"],
      blocked_days: { workdays: ["2026-03-05", "2026-03-06", "2026-03-07"], holidays: [], machine_blocks: [],
        tool_blocks: [], machine_intervals: [], tool_intervals: [], inactive_machines: [] },
    });
  }

  it("mostra cada lote fixado à mão pela referência e solta-o", async () => {
    mockPinnedPlan();
    endpointMocks.releaseManualEdits.mockResolvedValue({ status: "ok", released: ["LOT_JTE001_PRM043_6800016767A.10_57"] });
    render(<Shell />);
    expect(await screen.findByText("1 lote fixado à mão")).toBeTruthy();
    expect(screen.getByText("Referência 6800016767A.10 (PRM043) → 06/03 08:45")).toBeTruthy();
    expect(screen.queryByText(/LOT_JTE001/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Soltar" }));
    await waitFor(() => expect(endpointMocks.releaseManualEdits).toHaveBeenCalled());
    expect(endpointMocks.releaseManualEdits.mock.calls[0][0]).toEqual(["LOT_JTE001_PRM043_6800016767A.10_57"]);
  });

  it("Recalcular com alterações manuais pede confirmação antes de as apagar", async () => {
    mockPinnedPlan();
    render(<Shell />);
    await screen.findByText("1 lote fixado à mão");
    fireEvent.click(screen.getByRole("button", { name: /Recalcular plano/ }));
    await waitFor(() => expect(endpointMocks.getToday).toHaveBeenCalled());
    // Sem confirmação (o diálogo devolve «não» fora do ConfirmProvider) nada é apagado.
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(endpointMocks.recalculate).not.toHaveBeenCalled();
  });

  it("carrega automaticamente o plano persistido mesmo com outro dataset em cache", async () => {
    sessionStorage.setItem("pp1ActiveDatasetId", "dataset-antigo");
    mockShellEndpoints();

    render(<Shell />);

    expect(await screen.findByText("Resumo do Dia")).toBeTruthy();
    expect(screen.queryByText("Upload")).toBeNull();
    expect(sessionStorage.getItem("pp1ActiveDatasetId")).toBe("dataset-1");
    expect(useAppStore.getState().dataset?.filename).toBe("plano.xlsx");
  });

  it("abre Entregas a partir dos KPIs e guarda o foco em sessionStorage", async () => {
    mockShellEndpoints();

    render(<Shell />);

    fireEvent.click(await screen.findByRole("button", { name: /Encomendas a tempo/i }));

    await waitFor(() => {
      expect(useAppStore.getState().activePage).toBe("deliveries");
    });
    expect(JSON.parse(sessionStorage.getItem("pp1DeliveriesFocus") ?? "{}")).toMatchObject({
      page: "deliveries",
      view: "order",
      metric: "otd",
      source: "shell-kpi",
    });
    expect(screen.getByText("Entregas page")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Cumprimento diário/i }));

    expect(JSON.parse(sessionStorage.getItem("pp1DeliveriesFocus") ?? "{}")).toMatchObject({
      metric: "otd_d",
    });
  });

  it("mostra Encomendas a tempo em destaque e Lotes no prazo como detalhe", async () => {
    mockShellEndpoints();
    const planView = await endpointMocks.getPlanView();
    endpointMocks.getPlanView.mockResolvedValue({
      ...planView,
      gate_report: { metrics: { orders_total: 709, orders_on_time: 701, orders_late: 8, order_otd: 98.9 } },
    });

    render(<Shell />);

    const orders = await screen.findByRole("button", { name: /Encomendas a tempo/i });
    await waitFor(() => expect(orders.textContent).toContain("98.9%"));
    expect(screen.getByRole("button", { name: /Lotes no prazo/i }).textContent).toContain("99.4%");
    expect(screen.getByRole("button", { name: /Cumprimento diário/i }).textContent).toContain("97.1%");
    expect(screen.queryByText(/Entregas a tempo/)).toBeNull();
  });

  it("mostra no topo o aviso de plano calculado com regras de material antigas", async () => {
    mockShellEndpoints();
    const planView = await endpointMocks.getPlanView();
    const notice = "Este plano foi calculado antes de o material passar a ser libertado por entrega. "
      + "Para aplicar as regras por entrega é preciso usar «Recalcular plano»; até lá, o plano "
      + "mantém-se como foi guardado.";
    endpointMocks.getPlanView.mockResolvedValue({ ...planView, plan_notices: [notice] });

    render(<Shell />);

    const banner = await screen.findByRole("status", { name: "Aviso sobre o plano ativo" });
    expect(within(banner).getByText("Aviso do plano")).toBeTruthy();
    expect(banner.textContent).toContain("«Recalcular plano»");
    expect(useDataStore.getState().planNotices).toEqual([notice]);
  });

  it("mostra no topo o aviso de plano feito com um ISOP de um dia anterior", async () => {
    mockShellEndpoints();
    const planView = await endpointMocks.getPlanView();
    const notice = "O plano usa o ISOP de 09/10. Os dias anteriores a hoje são considerados já "
      + "produzidos. Carregue o ISOP de hoje para atualizar o plano.";
    endpointMocks.getPlanView.mockResolvedValue({ ...planView, plan_notices: [notice] });

    render(<Shell />);

    const banner = await screen.findByRole("status", { name: "Aviso sobre o plano ativo" });
    expect(within(banner).getByText("Aviso do plano")).toBeTruthy();
    expect(within(banner).getByText(notice)).toBeTruthy();
  });

  it("sem avisos do plano não mostra a faixa", async () => {
    mockShellEndpoints();

    render(<Shell />);

    await waitFor(() => expect(useDataStore.getState().planRevision).toBe(1));
    expect(screen.queryByRole("status", { name: "Aviso sobre o plano ativo" })).toBeNull();
    expect(useDataStore.getState().planNotices).toEqual([]);
  });

  it("plano antigo sem métricas de encomendas mostra — no cabeçalho", async () => {
    mockShellEndpoints();

    render(<Shell />);

    const orders = await screen.findByRole("button", { name: /Encomendas a tempo/i });
    expect(orders.textContent).toContain("—");
    expect(screen.getByRole("button", { name: /Lotes no prazo/i }).textContent).toContain("99.4%");
  });
});

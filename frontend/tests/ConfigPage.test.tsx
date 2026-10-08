import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import type { EOp, FactoryConfig, MasterCatalog } from "../src/api/types";

const endpointMocks = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getOps: vi.fn(),
  getCatalog: vi.fn(),
  updateConfig: vi.fn(),
  startReplan: vi.fn(),
  getReplan: vi.fn(),
  getReplans: vi.fn().mockResolvedValue({ jobs: [] }),
  applyReplan: vi.fn(),
  cancelReplan: vi.fn(),
  getTrust: vi.fn().mockResolvedValue(null),
  getPlanView: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return {
    ...actual,
    ...endpointMocks,
  };
});

import { ConfigPage } from "../src/pages/ConfigPage";
import { ConfirmProvider } from "../src/components/ui/ConfirmProvider";
import { useDataStore } from "../src/stores/useDataStore";

const config: FactoryConfig = {
  plan_revision: 1,
  name: "Nikufra",
  site: "Fábrica",
  timezone: "Europe/Lisbon",
  shifts: [
    { id: "A", label: "Turno A", start_min: 360, end_min: 840, duration_min: 480 },
  ],
  day_capacity_min: 960,
  machines: {},
  tools: {},
  twins: [],
  operators: {},
  holidays: [],
  extra_workdays: [],
  unavailability: { machines: [], tools: [], operators: [] },
  setup_overrides: [],
  setup_families: {},
  earliness_policy: "jit",
  material_release_days: 5,
  early_window_enforcement: "soft",
  oee_default: 0.8,
  subcontract_skus: [],
  sku_planning_rules: {},
  subcontract_companies: [],
  sku_subcontracts: {},
  setup_crews: 1,
  setup_crews_by_group: {},
  jit_enabled: true,
  jit_buffer_pct: 0,
  jit_threshold: 0,
  jit_max_retries: 1,
  jit_earliness_target: 5,
  max_run_days: 4,
  max_edd_gap: 0,
  max_edd_span: 0,
  edd_swap_tolerance: 0,
  edd_assign_threshold: 0,
  campaign_window: 0,
  urgency_threshold: 0,
  interleave_enabled: false,
  auto_buffer: false,
  vns_enabled: false,
  vns_max_iter: 0,
  compact_enabled: false,
  weight_earliness: 0,
  weight_setups: 0,
  weight_balance: 0,
  eco_lot_mode: "soft",
};

const catalog: MasterCatalog = {
  source_policy: { active: "ISOP", persistent: "Configuração" },
  machines: [],
  tools: [],
  references: [],
};

const ops: EOp[] = [
  {
    id: "T1_M1_SKU1",
    sku: "SKU1",
    client: "Cliente A",
    designation: "Peça ativa",
    machine: "M1",
    tool: "T1",
    alt_machine: null,
    pcs_hour: 100,
    setup_hours: 0.5,
    eco_lot: 100,
    eco_lot_isop: 100,
    eco_lot_effective: 100,
    stock: 0,
    oee: 0.8,
    backlog: 0,
    operators: 1,
    demand: [0, 25],
    active: true,
  },
  {
    id: "inactive::CF589MMA1A02.20",
    sku: "CF589MMA1A02.20",
    client: "",
    designation: "Histórico",
    machine: "",
    tool: "",
    alt_machine: null,
    pcs_hour: 0,
    setup_hours: 0,
    eco_lot: 0,
    eco_lot_isop: 0,
    eco_lot_effective: 0,
    stock: 0,
    oee: 0.8,
    backlog: 0,
    operators: 0,
    demand: [],
    active: false,
    subcontract_company_id: "SUBCONTRATO",
    subcontract_lead_time_days: 5,
  },
];

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  endpointMocks.getReplans.mockResolvedValue({ jobs: [] });
  useDataStore.getState().clear();
});

describe("Configuração", () => {
  function configureJobs() {
    endpointMocks.getConfig.mockResolvedValue({ ...config, tools: { T1: { primary: "M1", alt: null, setup_hours: 0.5 } } });
    endpointMocks.getOps.mockResolvedValue([ops[0]]);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.getPlanView.mockResolvedValue({ dataset_id: "d1", plan_revision: 2, config, score: {}, gate_report: {},
      lots: [], segments: [], workdays: [], blocked_days: {}, capacity: {}, learning: null,
      active_mutations: [], manual_edits: [], can_revert: false });
    return { id: "job", status: "ready", base_revision: 1, dataset_id: "d1", reason: "Tools", warnings: [], message: "Ready", created_at: new Date().toISOString(),
      result: { score: { otd: 100 }, gate_report: { status: "applicable", apply_decision: "auto_applicable" }, n_segments: 1 } };
  }

  it("resumes a ready job under StrictMode cleanup and setup", async () => {
    const job = configureJobs();
    endpointMocks.getReplans.mockResolvedValue({ jobs: [job] });
    render(<StrictMode><ConfigPage /></StrictMode>);
    expect(await screen.findByRole("button", { name: "Aplicar e guardar" })).toBeTruthy();
    expect(endpointMocks.getReplans).toHaveBeenCalledTimes(2);
  });

  it("ignores ready polls arriving while cancellation is pending", async () => {
    const job = configureJobs();
    endpointMocks.getReplans.mockResolvedValue({ jobs: [{ ...job, status: "running" }] });
    let poll!: (value: unknown) => void;
    let cancel!: (value: unknown) => void;
    endpointMocks.getReplan.mockReturnValue(new Promise((resolve) => { poll = resolve; }));
    endpointMocks.cancelReplan.mockReturnValue(new Promise((resolve) => { cancel = resolve; }));
    render(<ConfigPage />);
    const cancelButton = await screen.findByRole("button", { name: "Cancelar pedido" });
    vi.useFakeTimers();
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    // The initial poll timer was created before fake timers, so use the pending mock explicitly after its first read.
    vi.useRealTimers();
    await waitFor(() => expect(endpointMocks.getReplan).toHaveBeenCalled());
    fireEvent.click(cancelButton);
    await act(async () => { poll({ job }); });
    expect(screen.queryByRole("button", { name: "Aplicar e guardar" })).toBeNull();
    await act(async () => { cancel({ job: { ...job, status: "cancelled" } }); });
    expect(screen.queryByRole("button", { name: "Aplicar e guardar" })).toBeNull();
    expect(screen.getByText(/Pedido cancelado/)).toBeTruthy();
  });

  it("recovers a ready candidate after cancellation fails without an unhandled rejection", async () => {
    const job = configureJobs();
    endpointMocks.getReplans.mockResolvedValue({ jobs: [job] });
    endpointMocks.cancelReplan.mockRejectedValue(new Error("offline"));
    endpointMocks.getReplan.mockResolvedValue({ job });
    render(<ConfigPage />);
    await screen.findByRole("button", { name: "Aplicar e guardar" });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar mudança" }));
    await waitFor(() => expect(endpointMocks.getReplan).toHaveBeenCalledWith("job"));
    await waitFor(() => expect(screen.getByRole<HTMLButtonElement>("button", { name: "Aplicar e guardar" }).disabled).toBe(false));
  });

  it("identifica a pesquisa parcial no candidato recuperado sem bloquear a aplicação", async () => {
    const job = configureJobs();
    endpointMocks.getReplans.mockResolvedValue({ jobs: [{ ...job, result: {
      ...job.result, gate_report: { ...job.result.gate_report, improvement: {
        contract_version: 1, status: "partial", stop_reason: "search_limit",
        moves_accepted: 0, accepted_by_scope: {},
      } },
    } }] });
    render(<ConfigPage />);
    expect(await screen.findByText(/a melhoria automática parou antes de rever todas as hipóteses/)).toBeTruthy();
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Aplicar e guardar" }).disabled).toBe(false);
  });

  it("preserves tool edits made after the submitted candidate became ready", async () => {
    const job = configureJobs();
    endpointMocks.startReplan.mockResolvedValue({ job });
    endpointMocks.applyReplan.mockResolvedValue({ job: { ...job, status: "completed" } });
    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
    const apply = await screen.findByRole("button", { name: "Aplicar e guardar" });
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "2" } });
    fireEvent.click(apply);
    await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith("job", undefined, 1));
    await waitFor(() => expect(screen.getByRole<HTMLButtonElement>("button", { name: "Guardar alterações" }).disabled).toBe(false));
    expect(screen.getByRole<HTMLInputElement>("spinbutton").value).toBe("2");
  });

  it("removes the pending candidate when a lost cancellation response is recovered as cancelled", async () => {
    const job = configureJobs();
    endpointMocks.getReplans.mockResolvedValue({ jobs: [job] });
    endpointMocks.cancelReplan.mockRejectedValue(new Error("timeout"));
    endpointMocks.getReplan.mockResolvedValue({ job: { ...job, status: "cancelled" } });
    render(<ConfigPage />);
    await screen.findByRole("button", { name: "Aplicar e guardar" });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar mudança" }));
    await screen.findByText(/Pedido cancelado/);
    expect(screen.queryByRole("button", { name: "Aplicar e guardar" })).toBeNull();
  });

  it("wraps only the unavailability toolbar and preserves intentional table scrolling", async () => {
    configureJobs();
    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    expect(screen.getByTestId("unavailability-toolbar").style.flexWrap).toBe("wrap");
    expect(screen.getByRole<HTMLSelectElement>("combobox", { name: "Ordenar indisponibilidades" }).style.maxWidth).toBe("100%");
  });

  it.each(["blocked", "approval_required", "auto_applicable"])(
    "respeita a decisão %s ao repor o setup de uma ferramenta para 1 hora",
    async (decision) => {
      endpointMocks.getConfig.mockResolvedValue({
        ...config,
        tools: { T1: { primary: "M1", alt: null, setup_hours: 0.5 } },
      });
      endpointMocks.getOps.mockResolvedValue([ops[0]]);
      endpointMocks.getCatalog.mockResolvedValue(catalog);
      endpointMocks.startReplan.mockResolvedValue({ job: {
        id: "setup-job", status: "ready", progress: 100, warnings: [],
        message: "O candidato ainda contém 1 interrupção de campanha.",
        result: {
          score: { otd: 96.5, tardy_count: 9 }, n_segments: 755,
          gate_report: {
            status: decision === "blocked" ? "operational_sequence_blocked" : "best_effort",
            apply_decision: decision,
            requires_approval: decision === "approval_required",
          },
        },
      } });
      render(<ConfigPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
      fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
      const apply = await screen.findByRole<HTMLButtonElement>("button", {
        name: decision === "blocked" ? "Não aplicável ao plano" : "Aplicar e guardar",
      });
      expect(endpointMocks.startReplan).toHaveBeenCalledWith({
        reason: "Ferramentas alteradas",
        config_updates: { tool_updates: { T1: { setup_hours: 1 } } },
        expected_revision: 1,
      });
      expect(apply.disabled).toBe(decision === "blocked");
      if (decision === "blocked") {
        expect(screen.queryByText("Alterações prontas para aplicar")).toBeNull();
        expect(screen.getByText("Resultado do cenário calculado")).toBeTruthy();
        fireEvent.click(apply);
        expect(endpointMocks.applyReplan).not.toHaveBeenCalled();
      }
    },
  );

  it("pede confirmação e justificação antes de aplicar um candidato com exceções", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      tools: { T1: { primary: "M1", alt: null, setup_hours: 0.5 } },
    });
    endpointMocks.getOps.mockResolvedValue([ops[0]]);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockResolvedValue({ job: {
      id: "approval-job", status: "ready", progress: 100, warnings: ["Rever sequência"], base_revision: 1,
      message: "Candidato pronto",
      result: {
        score: { otd: 96.5, tardy_count: 9 }, n_segments: 755,
        gate_report: {
          status: "best_effort",
          apply_decision: "approval_required",
          requires_approval: true,
          approval_reasons: ["Existe 1 interrupção de campanha evitável."],
        },
      },
    } });
    endpointMocks.applyReplan.mockReturnValue(new Promise(() => undefined));

    render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
    fireEvent.click(await screen.findByRole("button", { name: "Aplicar e guardar" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Aplicar plano com exceções?")).toBeTruthy();
    expect(dialog.textContent).toContain("Existe 1 interrupção de campanha evitável.");
    expect(dialog.textContent).toContain("Lotes no prazo: 96.5%");
    expect(dialog.textContent).toContain("Lotes atrasados: 9");
    expect(endpointMocks.applyReplan).not.toHaveBeenCalled();

    const confirmApply = within(dialog).getByRole<HTMLButtonElement>("button", { name: "Confirmar e aplicar" });
    expect(confirmApply.disabled).toBe(true);
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: "Impacto revisto e aceite pelo planeador." },
    });
    fireEvent.click(confirmApply);

    await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith(
      "approval-job",
      { reason: "Impacto revisto e aceite pelo planeador.", author: "planeador" },
      1,
    ));
  });

  it("mostra fase e tempo e mantém o polling após três falhas transitórias", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      tools: { T1: { primary: "M1", alt: null, setup_hours: 0.5 } },
    });
    endpointMocks.getOps.mockResolvedValue([ops[0]]);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockResolvedValue({ job: {
      id: "slow-job", status: "running", phase: "optimizing", progress: 35, warnings: [],
      message: "A procurar o melhor plano completo", result: null,
    } });
    endpointMocks.getReplan
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockResolvedValueOnce({ job: {
        id: "slow-job", status: "ready", phase: "ready", progress: 100, warnings: [],
        message: "Candidato pronto",
        result: {
          score: { otd: 100, tardy_count: 0 }, n_segments: 1,
          gate_report: { status: "applicable", apply_decision: "auto_applicable", requires_approval: false, approval_reasons: [] },
        },
      } });

    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));
    await act(async () => { await Promise.resolve(); });

    const activeStatus = screen.getByRole("status");
    expect(activeStatus.getAttribute("aria-live")).toBe("polite");
    expect(activeStatus.textContent).toContain("Fase atual: A procurar o melhor plano completo");
    expect(activeStatus.textContent).toContain("Tempo decorrido: 0 s");
    expect(activeStatus.textContent).not.toContain("35%");

    await act(async () => { await vi.advanceTimersByTimeAsync(7000); });
    expect(endpointMocks.getReplan).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status").textContent).toContain("Nova tentativa 3 de 3");
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "A recalcular…" }).disabled).toBe(true);

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(endpointMocks.getReplan).toHaveBeenCalledTimes(4);
    expect(screen.getByText("Alterações prontas para aplicar")).toBeTruthy();
  });

  it("mantém as definições acessíveis e recupera quando o catálogo falha", async () => {
    endpointMocks.getConfig.mockResolvedValue(config);
    endpointMocks.getOps.mockResolvedValue([]);
    endpointMocks.getCatalog
      .mockRejectedValueOnce(new Error("Not Found"))
      .mockResolvedValueOnce(catalog);

    render(<ConfigPage />);

    expect((await screen.findByRole("status")).textContent).toContain(
      "Podes continuar a consultar e alterar as restantes definições.",
    );
    expect(screen.getByText("Adicionar máquina")).toBeTruthy();
    expect(screen.queryByText("Error: Not Found")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));

    await waitFor(() => {
      expect(screen.queryByRole("status")).toBeNull();
    });
    expect(endpointMocks.getCatalog).toHaveBeenCalledTimes(2);
  });

  it("torna os dados ISOP acessíveis em modo read-only", async () => {
    endpointMocks.getConfig.mockResolvedValue(config);
    endpointMocks.getOps.mockResolvedValue(ops);
    endpointMocks.getCatalog.mockResolvedValue(catalog);

    render(<ConfigPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Administração / Avançado" }));
    expect(screen.queryByRole("button", { name: "Estado atual" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ver dados ISOP" }));

    expect(screen.getByText(/Consulta read-only dos dados recebidos do ISOP/)).toBeTruthy();
    expect(screen.getByRole("searchbox", { name: "Pesquisar dados ISOP" })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Ordenar dados ISOP" })).toBeTruthy();
    expect(screen.getByText("CF589MMA1A02.20")).toBeTruthy();
    expect(screen.getByText("Configuração")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Aplicar/ })).toBeNull();
  });

  it("mostra ferramentas que existem apenas no ISOP e permite pesquisar pelo artigo", async () => {
    const isopOnlyOps: EOp[] = [
      {
        ...ops[0],
        id: "VUL146_PRM039_8718658056.20",
        sku: "8718658056.20",
        client: "BOSCH-TERM",
        designation: "Artigo ISOP",
        machine: "PRM039",
        tool: "VUL146",
      },
    ];
    const isopOnlyCatalog: MasterCatalog = {
      ...catalog,
      tools: [
        { id: "VUL146", source: "isop", active: true, primary: "PRM039", alt: null, setup_hours: 0.5 },
      ],
      references: [
        {
          id: "8718658056.20",
          source: "isop",
          active: true,
          client: "BOSCH-TERM",
          machine: "PRM039",
          tool: "VUL146",
          has_override: false,
        },
      ],
    };

    endpointMocks.getConfig.mockResolvedValue(config);
    endpointMocks.getOps.mockResolvedValue(isopOnlyOps);
    endpointMocks.getCatalog.mockResolvedValue(isopOnlyCatalog);

    render(<ConfigPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByPlaceholderText(/Pesquisar ferramenta/), {
      target: { value: "8718658056.20" },
    });

    expect(screen.getByText("VUL146")).toBeTruthy();
    expect(screen.getByText("8718658056.20")).toBeTruthy();
    expect(screen.getByText("PRM039")).toBeTruthy();
  });

  it("mostra a máquina principal do ISOP quando a configuração só define o setup", async () => {
    const hanConfig: FactoryConfig = {
      ...config,
      machines: {
        PRM043: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
      },
      tools: {
        HAN002: { primary: "", alt: null, setup_hours: 0.5 },
      },
    };
    const hanOp: EOp = {
      ...ops[0],
      id: "HAN002_PRM043_13497858X130",
      sku: "13497858X130",
      machine: "PRM043",
      tool: "HAN002",
    };
    const hanCatalog: MasterCatalog = {
      ...catalog,
      tools: [{
        id: "HAN002",
        source: "both",
        active: true,
        primary: "PRM043",
        primary_source: "isop",
        observed_machines: ["PRM043"],
        alt: null,
        setup_hours: 0.5,
      }],
    };

    endpointMocks.getConfig.mockResolvedValue(hanConfig);
    endpointMocks.getOps.mockResolvedValue([hanOp]);
    endpointMocks.getCatalog.mockResolvedValue(hanCatalog);

    render(<ConfigPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByPlaceholderText(/Pesquisar ferramenta/), {
      target: { value: "HAN002" },
    });

    expect(screen.getByText("HAN002")).toBeTruthy();
    expect(screen.getByText("PRM043")).toBeTruthy();
    expect(screen.getByText("ISOP")).toBeTruthy();
    expect(screen.queryByText("Sem dados no ISOP atual")).toBeNull();
  });

  it("calcula a duração dos turnos com horas normais e meia-noite", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      shifts: [
        { id: "A", label: "Manhã", start_min: 420, end_min: 930, duration_min: 510 },
        { id: "B", label: "Tarde", start_min: 930, end_min: 1440, duration_min: 510 },
      ],
    });
    endpointMocks.getOps.mockResolvedValue([]);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.updateConfig.mockResolvedValue({ status: "ok", score: {}, score_previous: {}, plan_revision: 2 });

    render(<ConfigPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Turnos" }));
    const timeInputs = screen.getAllByDisplayValue(/\d{2}:\d{2}/);
    const turnoBFim = timeInputs[3] as HTMLInputElement;

    fireEvent.change(turnoBFim, { target: { value: "23:50" } });

    expect(screen.getByText("500")).toBeTruthy();
    expect(screen.queryByText("1940")).toBeNull();
  });

  it("mantém o rascunho de indisponibilidade quando guardar falha", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      machines: {
        M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
      },
    });
    endpointMocks.getOps.mockResolvedValue(ops);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockRejectedValue(new Error("disco indisponível"));

    render(<ConfigPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    fireEvent.change(screen.getByLabelText("Máquina"), { target: { value: "M1" } });
    fireEvent.change(screen.getByLabelText("Início exato"), {
      target: { value: "2026-09-14T08:00" },
    });
    fireEvent.change(screen.getByLabelText(/Fim exato/), {
      target: { value: "2026-09-14T10:00" },
    });
    fireEvent.change(screen.getByLabelText("Motivo (opcional)"), {
      target: { value: "Teste de persistência" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao rascunho" }));

    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("Nova")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));

    await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledWith({
      reason: "Indisponibilidades alteradas",
      expected_revision: 1,
      config_updates: {
        unavailability_additions: [{
          kind: "machine",
          resource: "M1",
          start_at: "2026-09-14T08:00",
          end_at: "2026-09-14T10:00",
          category: "Avaria",
          reason: "Teste de persistência",
        }],
      },
    }));
    expect(screen.getAllByText("M1").length).toBeGreaterThan(0);
    expect(screen.getByText("2026-09-14T08:00 → 2026-09-14T10:00")).toBeTruthy();
    expect(screen.getByText("Teste de persistência")).toBeTruthy();
    expect(screen.getByText("1 nova(s) · 0 editada(s) · 0 a remover")).toBeTruthy();
  });

  it("resume a indisponibilidade com período, categoria e motivo antes de aplicar", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      machines: {
        M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
      },
    });
    endpointMocks.getOps.mockResolvedValue(ops);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockResolvedValue({ job: {
      id: "availability-job", status: "ready", progress: 100, warnings: [],
      message: "Candidato pronto",
      result: {
        score: { otd: 100, tardy_count: 0 }, n_segments: 1,
        gate_report: { status: "applicable", apply_decision: "auto_applicable", requires_approval: false, approval_reasons: [] },
      },
    } });

    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    fireEvent.change(screen.getByLabelText("Máquina"), { target: { value: "M1" } });
    fireEvent.change(screen.getByLabelText("Início exato"), { target: { value: "2026-09-14T08:00" } });
    fireEvent.change(screen.getByLabelText(/Fim exato/), { target: { value: "2026-09-14T10:00" } });
    fireEvent.change(screen.getByLabelText("Motivo (opcional)"), { target: { value: "Reparação preventiva" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao rascunho" }));
    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));

    expect(await screen.findByText(
      "Nova indisponibilidade: M1 · 2026-09-14T08:00 -> 2026-09-14T10:00 · Categoria: Avaria · Motivo: Reparação preventiva",
    )).toBeTruthy();
  });

  it("só recalcula depois de guardar uma remoção de indisponibilidade", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      machines: {
        M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
      },
      unavailability: {
        machines: [{
          id: "stop-1",
          resource: "M1",
          start_at: "2026-09-14T08:00+01:00",
          end_at: "2026-09-14T10:00+01:00",
          category: "Manutenção",
          reason: "Teste",
        }],
        tools: [],
        operators: [],
      },
    });
    endpointMocks.getOps.mockResolvedValue(ops);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockResolvedValue({
      status: "queued",
      job: {
        id: "job-remove",
        status: "ready",
        progress: 100,
        message: "Candidato pronto",
        warnings: [],
        result: {
          score: { otd: 100, tardy_count: 0 },
          gate_report: { status: "applicable", requires_approval: false },
          n_segments: 1,
        },
      },
    });

    render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);

    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    expect(screen.getByTestId("unavailability-table-scroll").style.overflowX).toBe("auto");
    const removeButton = screen.getByRole("button", { name: "Remover indisponibilidade M1" });
    expect(removeButton.style.minWidth).toBe("44px");
    expect(removeButton.style.minHeight).toBe("44px");
    fireEvent.click(removeButton);
    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("A remover")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));

    await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledWith({
      reason: "Indisponibilidades alteradas",
      expected_revision: 1,
      config_updates: { unavailability_removals: ["stop-1"] },
    }));
    expect(await screen.findByText("Alterações prontas para aplicar")).toBeTruthy();
  });

  it("edita várias indisponibilidades e envia um único recálculo", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      machines: { M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null } },
      unavailability: {
        machines: [{
          id: "stop-1", resource: "M1",
          start_at: "2026-09-14T08:00+01:00", end_at: "2026-09-14T10:00+01:00",
          category: "Manutenção", reason: "Teste",
        }],
        tools: [], operators: [],
      },
    });
    endpointMocks.getOps.mockResolvedValue(ops);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockResolvedValue({ job: {
      id: "job-edit", status: "ready", progress: 100, warnings: [], message: "Candidato pronto",
      result: { score: { otd: 100, tardy_count: 0 }, n_segments: 1,
        gate_report: { status: "applicable", apply_decision: "auto_applicable", requires_approval: false } },
    } });

    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    fireEvent.click(screen.getByRole("button", { name: "Editar indisponibilidade M1" }));
    expect(screen.getByLabelText<HTMLInputElement>("Início exato").value).toBe("2026-09-14T08:00");
    fireEvent.change(screen.getByLabelText(/Fim exato/), { target: { value: "2026-09-14T12:00" } });
    fireEvent.change(screen.getByLabelText("Motivo (opcional)"), { target: { value: "Prolongada" } });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar rascunho" }));
    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("Editada")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Máquina"), { target: { value: "M1" } });
    fireEvent.change(screen.getByLabelText("Início exato"), { target: { value: "2026-09-16T08:00" } });
    fireEvent.change(screen.getByLabelText(/Fim exato/), { target: { value: "2026-09-16T09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar ao rascunho" }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar alterações" }));

    await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledTimes(1));
    expect(endpointMocks.startReplan).toHaveBeenCalledWith({
      reason: "Indisponibilidades alteradas",
      expected_revision: 1,
      config_updates: {
        unavailability_updates: [{
          id: "stop-1", kind: "machine", resource: "M1",
          start_at: "2026-09-14T08:00", end_at: "2026-09-14T12:00",
          category: "Manutenção", reason: "Prolongada",
        }],
        unavailability_additions: [{
          kind: "machine", resource: "M1",
          start_at: "2026-09-16T08:00", end_at: "2026-09-16T09:00",
          category: "Manutenção", reason: "",
        }],
      },
    });
  });
});

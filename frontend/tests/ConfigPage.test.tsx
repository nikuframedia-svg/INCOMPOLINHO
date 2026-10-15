import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
import { useConfigDraftStore } from "../src/stores/useConfigDraftStore";
import { useAppStore } from "../src/stores/useAppStore";
import { Sidebar } from "../src/components/Sidebar";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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

beforeEach(() => {
  endpointMocks.getPlanView.mockResolvedValue({ dataset_id: "d1", plan_revision: 2, config, score: {}, gate_report: {},
    lots: [], segments: [], workdays: [], blocked_days: {}, capacity: {}, learning: null,
    active_mutations: [], manual_edits: [], can_revert: false });
});

afterEach(() => {
  cleanup();
  useConfigDraftStore.getState().discard();
  useAppStore.setState({ accessMode: "edit" });
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

  it("põe a alteração na lista e aplica sozinho quando o candidato fica pronto", async () => {
    const job = configureJobs();
    endpointMocks.startReplan.mockResolvedValue({ job });
    endpointMocks.applyReplan.mockResolvedValue({ job: { ...job, status: "completed" } });
    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });

    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("1 alteração por aplicar")).toBeTruthy();
    expect(screen.getByText("Ferramenta T1: setup 1 h")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

    await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith("job", undefined, 1));
    expect(endpointMocks.startReplan).toHaveBeenCalledWith({
      reason: "Ferramenta T1: setup 1 h",
      config_updates: { tool_updates: { T1: { setup_hours: 1 } } },
      expected_revision: 1,
    });
    await waitFor(() => expect(screen.queryByText("1 alteração por aplicar")).toBeNull());
    expect(screen.queryByRole("button", { name: "Aplicar e guardar" })).toBeNull();
    expect(useConfigDraftStore.getState().count).toBe(0);
  });

  it("shows a failed re-plan in plain Portuguese, never the raw English error", async () => {
    const job = configureJobs();
    endpointMocks.getReplans.mockResolvedValue({ jobs: [{ ...job, status: "running" }] });
    endpointMocks.getReplan.mockResolvedValue({ job: {
      ...job, status: "failed", result: null, code: "planning_timeout",
      message: "Tempo de cálculo esgotado sem um plano válido",
      error: "Planning deadline expired; candidate not committed.",
    } });
    render(<ConfigPage />);
    expect(await screen.findByText(/Tempo de cálculo esgotado sem um plano válido/, {}, { timeout: 4000 })).toBeTruthy();
    expect(screen.queryByText(/deadline expired/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Aplicar e guardar" })).toBeNull();
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

  function stageToolSetup(job: Record<string, unknown>) {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      tools: { T1: { primary: "M1", alt: null, setup_hours: 0.5 } },
    });
    endpointMocks.getOps.mockResolvedValue([ops[0]]);
    endpointMocks.getCatalog.mockResolvedValue(catalog);
    endpointMocks.startReplan.mockResolvedValue({ job });
  }

  it.each(["blocked", "approval_required", "auto_applicable"])(
    "respeita a decisão %s ao repor o setup de uma ferramenta para 1 hora",
    async (decision) => {
      stageToolSetup({
        id: "setup-job", status: "ready", progress: 100, warnings: [], base_revision: 1,
        message: "O candidato ainda contém 1 interrupção de campanha.",
        causes: decision === "blocked" ? ["A PRM031 fica sem capacidade na semana 43."] : [],
        result: {
          score: { otd: 96.5, tardy_count: 9 }, n_segments: 755,
          gate_report: {
            status: decision === "blocked" ? "operational_sequence_blocked" : "best_effort",
            apply_decision: decision,
            requires_approval: decision === "approval_required",
          },
        },
      });
      endpointMocks.applyReplan.mockResolvedValue({ job: { id: "setup-job", status: "completed", warnings: [] } });
      render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
      fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
      fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
      fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

      await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledWith({
        reason: "Ferramenta T1: setup 1 h",
        config_updates: { tool_updates: { T1: { setup_hours: 1 } } },
        expected_revision: 1,
      }));
      // There is never a review card to click for a candidate from the list.
      expect(screen.queryByRole("button", { name: "Aplicar e guardar" })).toBeNull();
      if (decision === "blocked") {
        expect(await screen.findByText(/O candidato ainda contém 1 interrupção de campanha/)).toBeTruthy();
        expect(screen.getByText("A PRM031 fica sem capacidade na semana 43.")).toBeTruthy();
        expect(endpointMocks.applyReplan).not.toHaveBeenCalled();
        expect(endpointMocks.cancelReplan).toHaveBeenCalledWith("setup-job");
        // The list stays so the planner can correct it.
        expect(screen.getByText("Ferramenta T1: setup 1 h")).toBeTruthy();
        expect(useConfigDraftStore.getState().applying).toBe(false);
      } else if (decision === "approval_required") {
        expect(await screen.findByRole("dialog")).toBeTruthy();
        expect(endpointMocks.applyReplan).not.toHaveBeenCalled();
      } else {
        await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith("setup-job", undefined, 1));
        expect(screen.queryByRole("dialog")).toBeNull();
      }
    },
  );

  it("pede a justificação uma vez antes de aplicar um candidato com exceções", async () => {
    stageToolSetup({
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
    });
    endpointMocks.applyReplan.mockReturnValue(new Promise(() => undefined));

    render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

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

  it("recusar a justificação não aplica nada e mantém a lista", async () => {
    stageToolSetup({
      id: "approval-job", status: "ready", progress: 100, warnings: [], base_revision: 1,
      message: "Candidato pronto",
      result: {
        score: { otd: 96.5, tardy_count: 9 }, n_segments: 755,
        gate_report: { status: "best_effort", apply_decision: "approval_required", requires_approval: true },
      },
    });
    render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Cancelar/ }));

    expect(await screen.findByText(/Alterações não aplicadas/)).toBeTruthy();
    expect(endpointMocks.applyReplan).not.toHaveBeenCalled();
    expect(endpointMocks.cancelReplan).toHaveBeenCalledWith("approval-job");
    expect(screen.getByText("Ferramenta T1: setup 1 h")).toBeTruthy();
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Aplicar" }).disabled).toBe(false);
  });

  it("mostra fase e tempo, bloqueia a edição e mantém o polling após três falhas transitórias", async () => {
    stageToolSetup({
      id: "slow-job", status: "running", phase: "optimizing", progress: 35, warnings: [],
      message: "A procurar o melhor plano completo", result: null,
    });
    endpointMocks.getReplan
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockResolvedValueOnce({ job: {
        id: "slow-job", status: "ready", phase: "ready", progress: 100, warnings: [], base_revision: 1,
        message: "Candidato pronto",
        result: {
          score: { otd: 100, tardy_count: 0 }, n_segments: 1,
          gate_report: { status: "applicable", apply_decision: "auto_applicable", requires_approval: false, approval_reasons: [] },
        },
      } });
    endpointMocks.applyReplan.mockResolvedValue({ job: { id: "slow-job", status: "completed", warnings: [] } });

    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ferramentas e artigos" }));
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "1" } });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    await act(async () => { await Promise.resolve(); });

    const activeStatus = screen.getByRole("status");
    expect(activeStatus.getAttribute("aria-live")).toBe("polite");
    expect(activeStatus.textContent).toContain("Fase atual: A procurar o melhor plano completo");
    expect(activeStatus.textContent).toContain("Tempo decorrido: 0 s");
    expect(activeStatus.textContent).not.toContain("35%");
    expect(screen.getByRole<HTMLInputElement>("spinbutton").disabled).toBe(true);

    await act(async () => { await vi.advanceTimersByTimeAsync(7000); });
    expect(endpointMocks.getReplan).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status").textContent).toContain("Nova tentativa 3 de 3");
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "A aplicar…" }).disabled).toBe(true);

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(endpointMocks.getReplan).toHaveBeenCalledTimes(4);
    expect(endpointMocks.applyReplan).toHaveBeenCalledWith("slow-job", undefined, 1);
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

  it("mantém a lista de indisponibilidades quando aplicar falha", async () => {
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
    fireEvent.click(screen.getByRole("button", { name: "Adicionar à lista" }));

    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("Nova")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

    await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledWith(expect.objectContaining({
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
    })));
    expect(await screen.findByText("Erro: disco indisponível")).toBeTruthy();
    expect(screen.getAllByText("M1").length).toBeGreaterThan(0);
    expect(screen.getByText("2026-09-14T08:00 → 2026-09-14T10:00")).toBeTruthy();
    expect(screen.getByText("Teste de persistência")).toBeTruthy();
    expect(screen.getByText("1 alteração por aplicar")).toBeTruthy();
  });

  it("descreve a indisponibilidade com período, categoria e motivo na lista", async () => {
    endpointMocks.getConfig.mockResolvedValue({
      ...config,
      machines: {
        M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null },
      },
    });
    endpointMocks.getOps.mockResolvedValue(ops);
    endpointMocks.getCatalog.mockResolvedValue(catalog);

    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    fireEvent.change(screen.getByLabelText("Máquina"), { target: { value: "M1" } });
    fireEvent.change(screen.getByLabelText("Início exato"), { target: { value: "2026-09-14T08:00" } });
    fireEvent.change(screen.getByLabelText(/Fim exato/), { target: { value: "2026-09-14T10:00" } });
    fireEvent.change(screen.getByLabelText("Motivo (opcional)"), { target: { value: "Reparação preventiva" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar à lista" }));

    expect(screen.getByText(
      "Nova indisponibilidade: M1 · 14/09/2026 08:00 → 14/09/2026 10:00 · Avaria · Reparação preventiva",
    )).toBeTruthy();
    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
  });

  it("só recalcula depois de Aplicar uma remoção de indisponibilidade", async () => {
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
        base_revision: 1,
        result: {
          score: { otd: 100, tardy_count: 0 },
          gate_report: { status: "applicable", requires_approval: false },
          n_segments: 1,
        },
      },
    });
    endpointMocks.applyReplan.mockResolvedValue({ job: { id: "job-remove", status: "completed", warnings: [] } });

    render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);

    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    expect(screen.getByTestId("unavailability-table-scroll").style.overflowX).toBe("auto");
    const removeButton = screen.getByRole("button", { name: "Remover indisponibilidade M1" });
    expect(removeButton.style.minWidth).toBe("44px");
    expect(removeButton.style.minHeight).toBe("44px");
    fireEvent.click(removeButton);
    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("A remover")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

    await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledWith(expect.objectContaining({
      expected_revision: 1,
      config_updates: { unavailability_removals: ["stop-1"] },
    })));
    await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith("job-remove", undefined, 1));
    expect(screen.queryByText("Alterações prontas para aplicar")).toBeNull();
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
      id: "job-edit", status: "ready", progress: 100, warnings: [], message: "Candidato pronto", base_revision: 1,
      result: { score: { otd: 100, tardy_count: 0 }, n_segments: 1,
        gate_report: { status: "applicable", apply_decision: "auto_applicable", requires_approval: false } },
    } });
    endpointMocks.applyReplan.mockResolvedValue({ job: { id: "job-edit", status: "completed", warnings: [] } });

    render(<ConfigPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Indisponibilidades" }));
    fireEvent.click(screen.getByRole("button", { name: "Editar indisponibilidade M1" }));
    expect(screen.getByLabelText<HTMLInputElement>("Início exato").value).toBe("2026-09-14T08:00");
    fireEvent.change(screen.getByLabelText(/Fim exato/), { target: { value: "2026-09-14T12:00" } });
    fireEvent.change(screen.getByLabelText("Motivo (opcional)"), { target: { value: "Prolongada" } });
    fireEvent.click(screen.getByRole("button", { name: "Atualizar na lista" }));
    expect(endpointMocks.startReplan).not.toHaveBeenCalled();
    expect(screen.getByText("Editada")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Máquina"), { target: { value: "M1" } });
    fireEvent.change(screen.getByLabelText("Início exato"), { target: { value: "2026-09-16T08:00" } });
    fireEvent.change(screen.getByLabelText(/Fim exato/), { target: { value: "2026-09-16T09:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar à lista" }));
    expect(screen.getByText("2 alterações por aplicar")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

    await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledTimes(1));
    expect(endpointMocks.startReplan).toHaveBeenCalledWith({
      reason: "2 alterações de configuração",
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

  describe("uma só lista para toda a página (16/10/2026)", () => {
    const factory: FactoryConfig = {
      ...config,
      machines: { M1: { group: "Grandes", active: true, day_capacity_min: null, oee: null } },
      operators: { "Grandes A": 3 },
      setup_crews_by_group: { Grandes: 1, Medias: 1 },
    };

    function readyJob(requiresApproval: boolean) {
      return {
        id: "list-job", status: "ready", progress: 100, warnings: [], base_revision: 1,
        message: "Candidato pronto", created_at: new Date().toISOString(),
        result: {
          score: { otd: 100, tardy_count: 0, setups: 10 }, n_segments: 1,
          gate_report: {
            status: requiresApproval ? "best_effort" : "applicable",
            apply_decision: requiresApproval ? "approval_required" : "auto_applicable",
            requires_approval: requiresApproval,
            approval_reasons: requiresApproval ? ["delivery_risk"] : [],
          },
        },
      };
    }

    it.each([false, true])(
      "2 máquinas + retirar 1 + feriado + gémea + equipas → um só pedido e aplica (aprovação: %s)",
      async (requiresApproval) => {
        endpointMocks.getConfig.mockResolvedValue(factory);
        endpointMocks.getOps.mockResolvedValue([ops[0]]);
        endpointMocks.getCatalog.mockResolvedValue(catalog);
        endpointMocks.startReplan.mockResolvedValue({ job: readyJob(requiresApproval) });
        endpointMocks.applyReplan.mockResolvedValue({ job: { ...readyJob(requiresApproval), status: "completed" } });

        render(<ConfirmProvider><ConfigPage /></ConfirmProvider>);
        // Máquinas (open by default): two additions, then one is taken out of the list.
        const machineId = await screen.findByPlaceholderText("Ex.: PRM044");
        fireEvent.change(machineId, { target: { value: "prm050" } });
        fireEvent.click(screen.getByRole("button", { name: "Adicionar à lista" }));
        fireEvent.change(machineId, { target: { value: "PRM051" } });
        fireEvent.click(screen.getByRole("button", { name: "Adicionar à lista" }));
        fireEvent.click(screen.getByRole("button", { name: "Retirar: Nova máquina PRM051 (Grandes)" }));

        // Calendário: one closed day.
        fireEvent.click(screen.getByRole("button", { name: "Calendário" }));
        fireEvent.change(document.querySelector<HTMLInputElement>('input[type="date"]')!, { target: { value: "2026-12-24" } });
        fireEvent.click(screen.getByRole("button", { name: "Adicionar dia" }));

        // Gémeas.
        fireEvent.click(screen.getByRole("button", { name: "Ferramentas e artigos" }));
        fireEvent.click(screen.getByRole("button", { name: "Gémeas" }));
        fireEvent.click(screen.getByRole("button", { name: "+ Adicionar" }));
        fireEvent.change(screen.getByLabelText("Ferramenta"), { target: { value: "T1" } });
        fireEvent.change(screen.getByLabelText("Referência A"), { target: { value: "SKU1" } });
        fireEvent.change(screen.getByLabelText("Referência B"), { target: { value: "SKU2" } });
        fireEvent.click(screen.getByRole("button", { name: "Adicionar à lista" }));

        // Equipas de setup.
        fireEvent.click(screen.getByRole("button", { name: "Fábrica" }));
        fireEvent.click(screen.getByRole("button", { name: "Operadores" }));
        fireEvent.change(screen.getByLabelText("Grandes"), { target: { value: "2" } });

        expect(screen.getByText("4 alterações por aplicar")).toBeTruthy();
        expect(screen.getByText("Dia sem produção: 24/12/2026")).toBeTruthy();
        expect(screen.getByText("Gémeas SKU1 + SKU2 (ferramenta T1)")).toBeTruthy();
        expect(endpointMocks.startReplan).not.toHaveBeenCalled();

        fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));

        await waitFor(() => expect(endpointMocks.startReplan).toHaveBeenCalledTimes(1));
        expect(endpointMocks.startReplan).toHaveBeenCalledWith({
          reason: "4 alterações de configuração",
          expected_revision: 1,
          config_updates: {
            machine_additions: [{ id: "PRM050", group: "Grandes", active: true }],
            holiday_additions: ["2026-12-24"],
            twin_additions: [{ tool_id: "T1", sku_a: "SKU1", sku_b: "SKU2" }],
            setup_crews_by_group: { Grandes: 2, Medias: 1 },
          },
        });

        if (requiresApproval) {
          const dialog = await screen.findByRole("dialog");
          expect(endpointMocks.applyReplan).not.toHaveBeenCalled();
          fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Natal acordado" } });
          fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar e aplicar" }));
          await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith(
            "list-job", { reason: "Natal acordado", author: "planeador" }, 1,
          ));
        } else {
          await waitFor(() => expect(endpointMocks.applyReplan).toHaveBeenCalledWith("list-job", undefined, 1));
          expect(screen.queryByRole("dialog")).toBeNull();
        }
        await waitFor(() => expect(screen.queryByText("4 alterações por aplicar")).toBeNull());
        expect(useConfigDraftStore.getState().count).toBe(0);
        expect(endpointMocks.startReplan).toHaveBeenCalledTimes(1);
      },
    );

    it("a lista sobrevive à troca de página e conta no menu lateral", async () => {
      endpointMocks.getConfig.mockResolvedValue(factory);
      endpointMocks.getOps.mockResolvedValue([ops[0]]);
      endpointMocks.getCatalog.mockResolvedValue(catalog);

      const first = render(<ConfigPage />);
      fireEvent.click(await screen.findByRole("button", { name: "Operadores" }));
      fireEvent.change(screen.getByLabelText("Operadores Grandes A"), { target: { value: "5" } });
      expect(screen.getByText("Operadores Grandes A: 5")).toBeTruthy();
      first.unmount();

      render(<Sidebar />);
      expect(screen.getByTitle("1 alteração por aplicar").textContent).toBe("1");
      cleanup();

      render(<ConfigPage />);
      expect(await screen.findByText("Operadores Grandes A: 5")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Operadores" }));
      expect(screen.getByLabelText<HTMLInputElement>("Operadores Grandes A").value).toBe("5");
      fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
      expect(screen.queryByText("Operadores Grandes A: 5")).toBeNull();
      expect(screen.getByLabelText<HTMLInputElement>("Operadores Grandes A").value).toBe("3");
    });

    it("em modo de consulta não deixa editar nem aplicar", async () => {
      endpointMocks.getConfig.mockResolvedValue(factory);
      endpointMocks.getOps.mockResolvedValue([ops[0]]);
      endpointMocks.getCatalog.mockResolvedValue(catalog);
      useConfigDraftStore.getState().upsert({ kind: "operators", key: "Grandes A", value: 5 });
      useAppStore.setState({ accessMode: "view" });

      render(<ConfigPage />);
      expect(await screen.findByText("Operadores Grandes A: 5")).toBeTruthy();
      expect(screen.getByRole<HTMLButtonElement>("button", { name: "Aplicar" }).disabled).toBe(true);
      expect(screen.getByPlaceholderText<HTMLInputElement>("Ex.: PRM044").disabled).toBe(true);
      fireEvent.click(screen.getByRole("button", { name: "Operadores" }));
      expect(screen.getByLabelText<HTMLInputElement>("Operadores Grandes A").disabled).toBe(true);
    });

    it("a Configuração não chama nenhum endpoint de escrita direta das entradas do plano", () => {
      const source = readFileSync(resolve(__dirname, "../src/pages/ConfigPage.tsx"), "utf8");
      const endpointImport = /import\s*\{([^}]*)\}\s*from\s*"\.\.\/api\/endpoints"/.exec(source)?.[1] ?? "";
      const imported = endpointImport.split(",").map((name) => name.trim()).filter(Boolean);
      const directWrites = [
        "updateOperators", "addHoliday", "removeHoliday", "addHolidayRange", "removeHolidayRange",
        "addExtraWorkday", "removeExtraWorkday", "addTwin", "removeTwin", "replaceSetupOverrides",
        "updateConfig", "applyPreset", "updateSkuPlanning", "resetSkuPlanning", "updateSubcontracts",
        "editMachine", "addMachine", "editTool", "addTool", "addUnavailability", "removeUnavailability",
      ];
      expect(imported).toContain("startReplan");
      expect(imported.filter((name) => directWrites.includes(name))).toEqual([]);
    });
  });
});

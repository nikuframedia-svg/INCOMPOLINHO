import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { GateReport } from "../src/api/types";
import { GateReportCard } from "../src/components/GateReportCard";

afterEach(cleanup);

function report(status: string): GateReport {
  return {
    status: "applicable", apply_decision: "auto_applicable", requires_approval: false,
    approval_reasons: [], hard_gate_passed: true, physical_gate_passed: true,
    coverage_gate_passed: true, delivery_gate_passed: true,
    subcontract_dispatch_gate_passed: true, jit_window_gate_passed: true,
    material_gate_passed: true,
    metrics: {}, violations: [], late_detail: [], jit_window_detail: [],
    setup_overlap_detail: [], proposals: [], improvement: {
      contract_version: 1, status, stop_reason: "search_limit",
      moves_accepted: 0, accepted_by_scope: {},
    },
  };
}

describe("estado da pesquisa de melhorias", () => {
  it.each([true, false])("mostra pesquisa parcial sem transferências listadas (ativo=%s)", (activePlan) => {
    render(<GateReportCard gate={report("partial")} activePlan={activePlan} />);
    expect(screen.getByText(/A melhoria automática parou antes de rever todas as hipóteses/)).toBeTruthy();
    expect(screen.queryByText("Conflito físico")).toBeNull();
    expect(screen.queryByText("Resultado calculado · não aplicável")).toBeNull();
  });

  it.each(["completed", "not_evaluated"])("não inventa pesquisa parcial quando o estado é %s", (status) => {
    render(<GateReportCard gate={report(status)} />);
    expect(screen.queryByText(/A melhoria automática parou/)).toBeNull();
  });
});

describe("robustez apenas informativa", () => {
  it("não mostra a robustez como limite a cumprir, mesmo em revisões antigas", () => {
    const gate = report("completed");
    gate.robustness_gate_passed = false;
    gate.metrics = {
      tardy_count: 2, robustness_model_version: 4, robustness_evaluated_samples: 100,
      robustness_success_probability_pct: 80, robustness_threshold_pct: 95,
    };
    render(<GateReportCard gate={gate} />);
    expect(screen.queryByText(/robustez/i)).toBeNull();
    expect(screen.queryByText(/80% \/ 95%/)).toBeNull();
    expect(screen.getByText("2 lotes acabam depois do prazo de produção.")).toBeTruthy();
    expect(screen.getByText(/lotes em atraso 2/)).toBeTruthy();
  });
});

function infeasibleReport(): GateReport {
  const gate = report("completed");
  gate.status = "best_effort";
  gate.apply_decision = "approval_required";
  gate.requires_approval = true;
  gate.approval_reasons = ["delivery_risk", "long_production"];
  gate.solver_status = "strict_infeasible_best_effort";
  gate.metrics = {
    tardy_count: 9, otd: 95.2, otd_d: 99.1, long_productions: 1,
    orders_total: 709, orders_on_time: 701, orders_late: 8, order_otd: 98.9,
  };
  gate.long_production_detail = [{
    lot_id: "LOT_JDE002_PRM042_TP042173-0060-1_33", sku: "TP042173-0060-1", machine_id: "PRM042",
    workdays: 5, limit_workdays: 4, excess_workdays: 1, days: [26, 27, 28, 29, 30],
    consecutive_days: [26, 27, 28, 29, 30],
  }];
  gate.feasibility = {
    solver_status: "strict_infeasible_best_effort", strict_solver_status: "proven_infeasible",
    strict_feasible: false, jit_window_workdays: 5, minimum_required_window_workdays_lower_bound: 8,
    binding_constraints: [
      { resource_type: "machine", resource_id: "PRM042", from_day: 26, to_day: 33, demand_min: 9000,
        capacity_min: 5268, deficit_min: 3732, affected_lots: [], affected_ops: [], affected_qty: 0 },
      { resource_type: "machine", resource_id: "PRM042", from_day: 23, to_day: 33, demand_min: 9000,
        capacity_min: 5939, deficit_min: 3061, affected_lots: [], affected_ops: [], affected_qty: 0 },
    ],
    interventions: [],
  };
  gate.proposals = [{
    id: "overtime-PRM042", description: "Horas extra na PRM042", expected_impact: "Recupera atrasos",
    before: { tardy_count: 9 }, after_target: { tardy_count: 0 },
  } as unknown as GateReport["proposals"][number]];
  return gate;
}

/** Visible text with the collapsed "Detalhes técnicos" block taken out. */
function textOutsideTechnical(container: HTMLElement): string {
  const clone = container.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-testid="gate-technical"]').forEach((node) => node.remove());
  return clone.textContent ?? "";
}

describe("resumo em linguagem simples", () => {
  it("mostra primeiro um resumo curto com encomendas, capacidade e produções longas", () => {
    render(<GateReportCard gate={infeasibleReport()} />);
    const summary = screen.getByTestId("gate-summary");
    const lines = summary.querySelectorAll("p");
    expect(lines.length).toBeGreaterThanOrEqual(2);
    expect(lines.length).toBeLessThanOrEqual(4);
    expect(summary.textContent).toContain("8 de 709 encomendas ficam atrasadas.");
    expect(summary.textContent).toContain("PRM042 cerca de 62 h");
    expect(summary.textContent).toContain("TP042173-0060-1 na PRM042, 5 dias seguidos (o limite é 4)");
  });

  it("não soma janelas sobrepostas do mesmo recurso", () => {
    render(<GateReportCard gate={infeasibleReport()} />);
    const summary = screen.getByTestId("gate-summary").textContent ?? "";
    // 3732 + 3061 min = ~113 h would double count the same minutes.
    expect(summary).not.toContain("113 h");
    expect(summary.match(/PRM042 cerca de/g)).toHaveLength(1);
  });

  it("guarda o vocabulário técnico dentro de Detalhes técnicos, fechado por omissão", () => {
    const { container } = render(<GateReportCard gate={infeasibleReport()} />);
    const technical = screen.getByTestId("gate-technical") as HTMLDetailsElement;
    expect(technical.open).toBe(false);
    expect(technical.querySelector("summary")?.textContent).toBe("Detalhes técnicos");
    expect(technical.textContent).toContain("strict_infeasible_best_effort");
    expect(technical.textContent).toContain("D26–D33");
    expect(technical.textContent).toContain("tardy_count: 9 → 0");

    const outside = textOutsideTechnical(container);
    for (const raw of [
      "strict_infeasible", "Solver", "delivery_risk", "long_production", "tardy_count",
      "binding", "défice", "D26", "machine PRM042",
    ]) {
      expect(outside).not.toContain(raw);
    }
  });

  it("relatórios antigos sem métricas de encomendas falam em lotes", () => {
    const gate = infeasibleReport();
    gate.metrics = { tardy_count: 1 };
    render(<GateReportCard gate={gate} />);
    const summary = screen.getByTestId("gate-summary").textContent ?? "";
    expect(summary).toContain("1 lote acaba depois do prazo de produção.");
    expect(summary).not.toContain("encomenda");
    expect(screen.getByTestId("gate-technical").textContent).toContain("encomendas em atraso —");
  });
});

describe("linhas de detalhe sem abreviaturas", () => {
  it("escreve dias úteis por extenso e com singular/plural", () => {
    const gate = report("completed");
    gate.jit_window_detail = [{
      lot_id: "L1", sku: "SKU1", machine_id: "PRM019", start_day: 3, material_reference_day: 9, excess_workdays: 2,
    } as unknown as GateReport["jit_window_detail"][number]];
    gate.subcontract_dispatch_detail = [{
      lot_id: "L2", op_id: "O2", sku: "SKU2", qty: 10, customer_delivery_day: 20,
      subcontract_dispatch_day: 15, completion_day: 16, late_workdays: 1,
    } as unknown as NonNullable<GateReport["subcontract_dispatch_detail"]>[number]];
    const { container } = render(<GateReportCard gate={gate} />);
    const text = container.textContent ?? "";
    expect(text).toContain("2 dias úteis antes do permitido");
    expect(text).toContain("1 dia útil de atraso");
    expect(text).not.toMatch(/\d+du\b/);
    expect(text).not.toContain("excesso");
  });

  it("ações sugeridas e transferências mantidas ficam dentro de Detalhes técnicos", () => {
    const gate = infeasibleReport();
    gate.proposals = [{
      id: "p1", description: "Horas extra na PRM042", expected_impact: "Recupera atrasos",
      affected_machines: ["PRM042"], affected_skus: ["SKU1"],
    } as unknown as GateReport["proposals"][number]];
    gate.improvement = {
      contract_version: 1, status: "completed", stop_reason: "no_admissible_improvement",
      moves_accepted: 0, accepted_by_scope: {},
      tool_transfers: { remaining: 1, items: [{
        key: "k1", tool_id: "BFP183", from_machine: "PRM039", to_machine: "PRM031", day_idx: 15,
        summary: "não avaliada neste cálculo",
      }] },
    } as unknown as GateReport["improvement"];
    const { container } = render(<GateReportCard gate={gate} />);
    const technical = screen.getByTestId("gate-technical");
    expect(technical.textContent).toContain("Ver ações sugeridas (1)");
    expect(technical.textContent).toContain("Referências SKU1");
    expect(technical.textContent).toContain("Transferências de ferramenta mantidas (1)");
    const outside = textOutsideTechnical(container);
    expect(outside).not.toContain("ações sugeridas");
    expect(outside).not.toContain("Transferências de ferramenta");
    expect(container.textContent).not.toContain("SKUs");
  });
});

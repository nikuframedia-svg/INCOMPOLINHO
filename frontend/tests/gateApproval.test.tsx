import { describe, expect, it } from "vitest";
import type { GateReport } from "../src/api/types";
import {
  approvalImpactMessage,
  approvalReasonLabel,
  BACKEND_APPROVAL_REASONS,
  capacityShortfalls,
  gateSummaryLines,
  isLegacyRobustnessReason,
} from "../src/lib/gateApproval";

const RAW_CODE = /\b[a-z]+(?:_[a-z]+)+\b/;

function gate(overrides: Partial<GateReport> = {}): GateReport {
  return {
    status: "best_effort", apply_decision: "approval_required", requires_approval: true,
    approval_reasons: ["delivery_risk"], hard_gate_passed: true, physical_gate_passed: true,
    coverage_gate_passed: true, delivery_gate_passed: false, subcontract_dispatch_gate_passed: true,
    jit_window_gate_passed: true, material_gate_passed: true, metrics: {}, violations: [],
    late_detail: [], jit_window_detail: [], setup_overlap_detail: [], proposals: [],
    ...overrides,
  };
}

const constraint = (resource_type: string, resource_id: string, from_day: number, deficit_min: number) => ({
  resource_type, resource_id, from_day, to_day: 33, demand_min: 0, capacity_min: 0, deficit_min,
  affected_lots: [], affected_ops: [], affected_qty: 0,
});

describe("dicionário único dos motivos de aprovação", () => {
  it.each(BACKEND_APPROVAL_REASONS)("%s tem um rótulo simples", (code) => {
    const label = approvalReasonLabel(code);
    expect(label).not.toBe(code);
    expect(label).not.toMatch(RAW_CODE);
    expect(label.length).toBeGreaterThan(10);
  });

  it("cobre exatamente os 7 motivos do backend", () => {
    expect([...BACKEND_APPROVAL_REASONS].sort()).toEqual([
      "delivery_risk", "jit_window_blocked", "long_production", "material_release_blocked",
      "operational_sequence_review", "operator_capacity_shortage", "subcontract_dispatch_risk",
    ]);
  });

  it("marca os motivos antigos de robustez como critério antigo", () => {
    for (const code of ["robustness_not_evaluated", "robustness_below_threshold"]) {
      expect(isLegacyRobustnessReason(code)).toBe(true);
      expect(approvalReasonLabel(code)).toContain("critério antigo");
    }
  });

  it("nunca devolve um código desconhecido em bruto", () => {
    expect(approvalReasonLabel("motivo_novo_do_servidor")).toBe("existe uma exceção de planeamento a rever");
  });
});

describe("mensagem de impacto", () => {
  it("fala em encomendas quando o relatório as traz", () => {
    const message = approvalImpactMessage(gate({ metrics: { tardy_count: 9, orders_late: 8, orders_total: 709 } }));
    expect(message).toContain("Impacto previsto: 8 encomendas ficam atrasadas.");
    const impact = message.split("\n").find((line) => line.startsWith("Impacto previsto:")) ?? "";
    expect(impact).toBe("Impacto previsto: 8 encomendas ficam atrasadas.");
  });

  it("singular e zero encomendas", () => {
    expect(approvalImpactMessage(gate({ metrics: { orders_late: 1 } }))).toContain("1 encomenda fica atrasada.");
    expect(approvalImpactMessage(gate({ metrics: { tardy_count: 0, orders_late: 0 } })))
      .toContain("Impacto previsto: nenhuma encomenda fica atrasada.");
  });

  it("lotes atrasados sem encomendas atrasadas: diz as duas coisas, sem se contradizer", () => {
    const message = approvalImpactMessage(gate({ metrics: { tardy_count: 3, orders_late: 0, orders_total: 709 } }));
    expect(message).toContain("Requer decisão do planeador por: há lotes que acabam depois do prazo de produção.");
    expect(message).toContain(
      "Impacto previsto: nenhuma encomenda fica atrasada; 3 lotes acabam depois do prazo de produção.",
    );
    expect(approvalImpactMessage(gate({ metrics: { tardy_count: 1, orders_late: 0 } })))
      .toContain("nenhuma encomenda fica atrasada; 1 lote acaba depois do prazo de produção.");
    expect(gateSummaryLines(gate({ metrics: { tardy_count: 3, orders_late: 0, orders_total: 709 } })))
      .toEqual(["Nenhuma encomenda fica atrasada; 3 lotes acabam depois do prazo de produção."]);
    expect(gateSummaryLines(gate({ metrics: { tardy_count: 0, orders_late: 0, orders_total: 709 } })))
      .toEqual(["Todas as 709 encomendas ficam prontas a tempo."]);
  });

  it("diz que o plano proposto pode ser executado, sem falar em candidato", () => {
    const message = approvalImpactMessage(gate({ metrics: { orders_late: 0 } }));
    expect(message.split("\n")[0]).toBe(
      "O plano proposto pode ser executado: respeita máquinas, ferramentas, equipas, calendário e material.",
    );
    expect(message).not.toMatch(/candidato/i);
  });

  it("só pede justificação quando o diálogo tem campo de texto", () => {
    const withText = approvalImpactMessage(gate());
    expect(withText.split("\n").at(-1)).toBe("Indica uma justificação para aplicar este plano.");
    const confirmOnly = approvalImpactMessage(gate(), "confirm");
    expect(confirmOnly.split("\n").at(-1)).toBe("Confirma para aplicar este plano.");
    expect(confirmOnly).not.toMatch(/justifica/i);
  });

  it("relatórios antigos sem encomendas falam em lotes", () => {
    expect(approvalImpactMessage(gate({ metrics: { tardy_count: 5 } })))
      .toContain("Impacto previsto: 5 lotes acabam depois do prazo de produção.");
    expect(approvalImpactMessage(gate({ metrics: { tardy_count: 1 } })))
      .toContain("Impacto previsto: 1 lote acaba depois do prazo de produção.");
  });

  it("lista as produções longas em palavras simples", () => {
    const message = approvalImpactMessage(gate({
      approval_reasons: ["long_production"],
      long_production_detail: [{
        lot_id: "L1", sku: "TP042173-0060-1", machine_id: "PRM042", workdays: 5, limit_workdays: 4,
        excess_workdays: 1, days: [26, 27, 28, 29, 30], consecutive_days: [26, 27, 28, 29, 30],
      }],
    }));
    expect(message).toContain("Produções longas: TP042173-0060-1 na PRM042, 5 dias seguidos (o limite é 4).");
    expect(message).not.toContain("::");
    expect(message).toContain("Requer decisão do planeador por: há produções seguidas acima do limite de dias.");
  });

  it("não mostra códigos em bruto nem robustez", () => {
    const message = approvalImpactMessage(gate({
      approval_reasons: [...BACKEND_APPROVAL_REASONS, "robustness_not_evaluated"],
      metrics: { tardy_count: 2, orders_late: 1 },
    }));
    expect(message).not.toMatch(RAW_CODE);
    expect(message).not.toMatch(/robustez/i);
  });
});

describe("resumo do relatório", () => {
  it("usa o maior défice por recurso e não soma janelas sobrepostas", () => {
    const report = gate({
      feasibility: {
        solver_status: "x", strict_solver_status: "x", strict_feasible: false, jit_window_workdays: 5,
        minimum_required_window_workdays_lower_bound: null, interventions: [],
        binding_constraints: [
          constraint("machine", "PRM042", 23, 3061),
          constraint("machine", "PRM042", 26, 3732),
          constraint("tool", "T1", 20, 300),
          constraint("machine", "PRM019", 10, 20),
        ],
      },
    });
    expect(capacityShortfalls(report)).toEqual([
      { resource: "PRM042", deficitMin: 3732 },
      { resource: "ferramenta T1", deficitMin: 300 },
      { resource: "PRM019", deficitMin: 20 },
    ]);
    expect(gateSummaryLines(report)).toContain(
      "Falta capacidade para cumprir todos os prazos: PRM042 cerca de 62 h, ferramenta T1 cerca de 5 h, PRM019 menos de 1 h.",
    );
  });

  it("tem no máximo 4 frases e nenhuma com códigos", () => {
    const lines = gateSummaryLines(gate({
      metrics: {
        orders_late: 2, orders_total: 10, long_productions: 3, missing_lots: 1,
        subcontract_dispatch_misses: 2, early_window_violations: 4,
      },
    }));
    expect(lines.length).toBeLessThanOrEqual(4);
    for (const line of lines) expect(line).not.toMatch(RAW_CODE);
  });

  it("sem métricas não inventa frases", () => {
    expect(gateSummaryLines(gate())).toEqual([]);
  });
});

describe("motivos já escritos pelo servidor", () => {
  it("mostra texto já escrito tal como vem, mas nunca um código", () => {
    expect(approvalReasonLabel("Existe 1 interrupção de campanha evitável."))
      .toBe("Existe 1 interrupção de campanha evitável.");
    expect(approvalReasonLabel("novo_codigo")).toBe("existe uma exceção de planeamento a rever");
  });
});

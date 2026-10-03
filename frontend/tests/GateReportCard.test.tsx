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
    robustness_gate_passed: true, material_gate_passed: true,
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
    expect(screen.getByText(/melhoria parcialmente verificada/)).toBeTruthy();
    expect(screen.queryByText("Conflito físico")).toBeNull();
    expect(screen.queryByText("Resultado calculado · não aplicável")).toBeNull();
  });

  it.each(["completed", "not_evaluated"])("não inventa pesquisa parcial quando o estado é %s", (status) => {
    render(<GateReportCard gate={report(status)} />);
    expect(screen.queryByText(/melhoria parcialmente verificada/)).toBeNull();
  });
});

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PlanSummary } from "../src/api/types";

const endpointMocks = vi.hoisted(() => ({
  getPlans: vi.fn(),
  restorePlan: vi.fn(),
  savePlan: vi.fn(),
  deletePlan: vi.fn(),
}));

vi.mock("../src/api/endpoints", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/endpoints")>();
  return { ...actual, ...endpointMocks };
});

import { PlansDrawer } from "../src/components/PlansDrawer";

function plan(id: string, name: string, createdAt: string, extra: Partial<PlanSummary> = {}): PlanSummary {
  return {
    id, created_at: createdAt, name, source: "auto", origin: "ISOP_ Nikufra_13.10.xlsx",
    note: "manual:9f8e7d6c5b4a", is_auto: true, otd: 100, otd_d: 100, tardy_count: 0,
    setups: 12, gate_status: "applicable", ...extra,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PlansDrawer", () => {
  // Decisão de 15/10/2026: cada versão diz o que mudou, à hora de Lisboa,
  // a mais recente primeiro; nunca ids internos.
  it("mostra o nome de cada versão e a hora de Lisboa, sem ids internos", async () => {
    endpointMocks.getPlans.mockResolvedValue({
      plans: [
        plan("p3", "Desfeito: Movido Referência 6800016767A.10 (PRM043) → 03/12 08:45", "2026-10-15 13:40:00"),
        plan("p2", "Movido Referência 6800016767A.10 (PRM043) → 03/12 08:45", "2026-10-15 13:33:00"),
        plan("p1", "Feriado 07/12 adicionado", "2026-10-15 07:05:00"),
        plan("p0", "Plano aprovado", "2026-10-14 16:00:00", { source: "user", is_auto: false, note: "Turno A" }),
      ],
    });
    render(<PlansDrawer onClose={() => undefined} />);

    const names = await screen.findAllByText(/Movido Referência|Feriado 07\/12|Plano aprovado/);
    expect(names.map((node) => node.textContent)).toEqual([
      "Desfeito: Movido Referência 6800016767A.10 (PRM043) → 03/12 08:45",
      "Movido Referência 6800016767A.10 (PRM043) → 03/12 08:45",
      "Feriado 07/12 adicionado",
      "Plano aprovado",
    ]);
    // The store keeps UTC; Lisbon is UTC+1 in October (summer time).
    expect(screen.getByText(/14:33/)).toBeTruthy();
    expect(screen.getByText(/08:05/)).toBeTruthy();
    expect(screen.queryByText(/manual:9f8e7d6c5b4a/)).toBeNull();
    expect(screen.getByText("Turno A")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Repor" })).toHaveLength(4);
  });
});

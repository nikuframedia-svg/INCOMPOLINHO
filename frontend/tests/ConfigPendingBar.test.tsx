import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ConfigPendingBar } from "../src/components/ConfigPendingBar";

const noop = () => {};

afterEach(cleanup);

describe("ConfigPendingBar", () => {
  it("avisa quando há referências que ficam sem máquina ativa", () => {
    render(
      <ConfigPendingBar
        lines={[{ id: "a", text: "PRM042: desativar — 2 referências ficam sem máquina (R1, R2)" }]}
        orphanCount={2}
        busy={false}
        disabled={false}
        onRemove={noop}
        onApply={noop}
        onDiscard={noop}
      />,
    );
    expect(screen.getByRole("alert").textContent).toBe("Atenção: 2 referências ficam sem máquina ativa e passam a atrasadas.");
    expect(screen.getByText("PRM042: desativar — 2 referências ficam sem máquina (R1, R2)")).toBeTruthy();
  });

  it("não avisa quando nenhuma referência fica sem máquina", () => {
    render(
      <ConfigPendingBar lines={[{ id: "a", text: "x" }]} busy={false} disabled={false} onRemove={noop} onApply={noop} onDiscard={noop} />,
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

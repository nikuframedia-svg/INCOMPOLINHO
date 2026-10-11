import { describe, expect, it } from "vitest";
import { isRawErrorText, jobFailureText } from "../src/lib/jobFailure";

describe("jobFailureText", () => {
  it("keeps the backend's Portuguese explanation", () => {
    expect(jobFailureText({ code: "invalid_plan", error: "O plano não cumpre as regras. Detalhe: conflito na PRM031." }, "x"))
      .toBe("O plano não cumpre as regras. Detalhe: conflito na PRM031.");
  });

  it("never shows the raw English deadline text, translating the code instead", () => {
    const text = jobFailureText({
      code: "planning_timeout",
      message: "Tempo de cálculo esgotado sem um plano válido",
      error: "Planning deadline expired; candidate not committed.",
    }, "x");
    expect(text).not.toMatch(/deadline|committed/i);
    expect(text).toMatch(/Tempo de cálculo esgotado/);
    expect(text).toMatch(/não foram alterados/);
  });

  it("falls back to the job message, then to the caller's text, for old jobs without a code", () => {
    expect(jobFailureText({ message: "Tempo de planeamento esgotado", error: "Planning deadline expired; candidate not committed." }, "x"))
      .toBe("Tempo de planeamento esgotado");
    expect(jobFailureText({ error: "KeyError: 'PRM031'" }, "O replaneamento falhou.")).toBe("O replaneamento falhou.");
  });

  it("recognises raw runtime text", () => {
    expect(isRawErrorText("Planning deadline expired; candidate not committed.")).toBe(true);
    expect(isRawErrorText("'NoneType' object has no attribute 'segments'")).toBe(true);
    expect(isRawErrorText("Não foi possível obter um plano válido")).toBe(false);
  });

  it("numa verificação de movimento não fala em configuração", () => {
    for (const code of ["planning_timeout", "invalid_plan", "blocked", "internal_error", "interrupted"]) {
      const text = jobFailureText({ code }, "x", "move");
      expect(text).toMatch(/O plano não foi alterado\./);
      expect(text).not.toMatch(/configuração|alteração/);
    }
    expect(jobFailureText({ code: "invalid_plan" }, "x")).toMatch(/O plano e a configuração não foram alterados\./);
  });

  it("produção já iniciada: não fala em conflitos físicos", () => {
    const text = jobFailureText({ code: "history_protected" }, "x");
    expect(text).toMatch(/produção já iniciada/);
    expect(text).toMatch(/O plano e a configuração não foram alterados\./);
    expect(text).not.toMatch(/conflitos físicos/);
  });

  it("interrompido: diz o que aconteceu e usa a palavra replaneamento", () => {
    expect(jobFailureText({ code: "interrupted" }, "x")).toBe(
      "O replaneamento foi interrompido (o servidor reiniciou ou o cálculo parou). O plano e a configuração não foram alterados. Pode iniciar novamente.",
    );
  });

  it("não deita fora texto português só por conter a palavra None", () => {
    expect(isRawErrorText("Referência None Plus sem material libertado")).toBe(false);
    expect(isRawErrorText("value is None")).toBe(true);
  });
});

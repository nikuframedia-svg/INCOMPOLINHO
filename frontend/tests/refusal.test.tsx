// One refusal format (decisão de 15/10/2026): causes travel with the error and
// no screen shows a refusal in a raw browser alert.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";
import { ApiError } from "../src/api/client";
import { RefusalError, causesOf, refusalCauses } from "../src/lib/refusal";

it("reads causes from an API refusal, a job refusal and nothing else", () => {
  expect(refusalCauses(new ApiError(400, "Plano inválido: 1 conflito.", {
    message: "Plano inválido: 1 conflito.", causes: ["Causa A.", 3, "", "Causa B."],
  }))).toEqual(["Causa A.", "Causa B."]);
  expect(refusalCauses(new ApiError(400, "texto simples", "texto simples"))).toEqual([]);
  expect(refusalCauses(new RefusalError("Falhou", ["Causa C."]))).toEqual(["Causa C."]);
  expect(refusalCauses(new Error("x"))).toEqual([]);
  expect(causesOf({ causes: "não é lista" })).toEqual([]);
});

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

it("no screen uses a browser alert for errors", () => {
  const offenders = sources(join(process.cwd(), "src"))
    .filter((path) => /(^|[^.\w])alert\(|window\.alert\(/.test(readFileSync(path, "utf8")));
  expect(offenders).toEqual([]);
});

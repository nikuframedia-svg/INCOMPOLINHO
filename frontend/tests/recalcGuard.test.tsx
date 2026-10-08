// "Recalcular" with an ISOP older than today warns first (decision of 07/10/2026).
import { expect, it } from "vitest";
import { staleIsopWarning } from "../src/lib/recalcGuard";

it("warns when today is after the ISOP's first day", () => {
  const warning = staleIsopWarning({ today_idx: 3, date: "2026-10-10" }, "2026-10-07");
  expect(warning).toContain("começa a 07/10, antes de hoje");
  expect(warning).toContain("carregar o ISOP de hoje");
});

it("does not warn for today's ISOP or without information", () => {
  expect(staleIsopWarning({ today_idx: 0, date: "2026-10-07" }, "2026-10-07")).toBeNull();
  expect(staleIsopWarning(null, "2026-10-07")).toBeNull();
  expect(staleIsopWarning({ today_idx: 2, date: "2026-10-09" }, undefined)).toBeNull();
});

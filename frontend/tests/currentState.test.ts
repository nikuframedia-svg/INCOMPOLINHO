import assert from "node:assert/strict";
import test from "node:test";

import {
  currentStateForStatus,
  isCurrentStateReady,
} from "../src/lib/currentState.ts";

test("setup e ensaio exigem ferramenta e hora prevista", () => {
  assert.equal(isCurrentStateReady({
    machine_id: "M1",
    status: "setup",
    expected_end: "2026-07-24T10:00",
  }), false);
  assert.equal(isCurrentStateReady({
    machine_id: "M1",
    status: "trial",
    tool_id: "T1",
    expected_end: "2026-07-24T10:00",
  }), true);
});

test("produção exige referência, ferramenta, quantidade positiva e hora prevista", () => {
  assert.equal(isCurrentStateReady({
    machine_id: "M1",
    status: "producing",
    sku: "SKU1",
    tool_id: "T1",
    remaining_qty: 0,
    expected_end: "2026-07-24T10:00",
  }), false);
  assert.equal(isCurrentStateReady({
    machine_id: "M1",
    status: "producing",
    sku: "SKU1",
    tool_id: "T1",
    remaining_qty: 20,
    expected_end: "2026-07-24T10:00",
  }), true);
});

test("mudar o estado remove campos que deixaram de ser aplicáveis", () => {
  const producing = {
    machine_id: "M1",
    status: "producing" as const,
    sku: "SKU1",
    tool_id: "T1",
    remaining_qty: 20,
    expected_end: "2026-07-24T10:00",
  };

  assert.deepEqual(currentStateForStatus(producing, "idle"), {
    machine_id: "M1",
    status: "idle",
    note: "",
  });
  assert.deepEqual(currentStateForStatus(producing, "setup"), {
    machine_id: "M1",
    status: "setup",
    note: "",
    tool_id: "T1",
    expected_end: "2026-07-24T10:00",
  });
});

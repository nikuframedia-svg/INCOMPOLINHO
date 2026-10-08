import assert from "node:assert/strict";
import test from "node:test";

import type { Lot, Segment } from "../src/api/types.ts";
import { analyseJitWindow } from "../src/lib/jitAnalysis.ts";

const workdays = Array.from({ length: 20 }, (_, offset) => {
  const value = new Date("2026-09-07T00:00:00Z");
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
});

function lot(overrides: Partial<Lot> = {}): Lot {
  return {
    id: "L1",
    op_id: "OP1",
    tool_id: "T1",
    machine_id: "M1",
    alt_machine_id: null,
    qty: 100,
    prod_min: 60,
    setup_min: 0,
    edd: 7,
    is_twin: false,
    sku: "SUB",
    twin_outputs: null,
    ...overrides,
  };
}

function segment(day: number): Segment {
  return {
    lot_id: "L1",
    run_id: "R1",
    machine_id: "M1",
    tool_id: "T1",
    day_idx: day,
    start_min: 420,
    end_min: 480,
    shift: "A",
    qty: 100,
    prod_min: 60,
    setup_min: 0,
    is_continuation: false,
    edd: 7,
    sku: "SUB",
    twin_outputs: null,
  };
}

test("subcontract analysis uses the backend dispatch-anchored release", () => {
  const analysis = analyseJitWindow(
    [segment(0)],
    [lot({
      customer_delivery_day: 14,
      production_due_day: 7,
      subcontract_dispatch_day: 7,
      material_reference_day: 7,
      material_reference_kind: "subcontract_dispatch",
      material_release_day: 0,
      is_subcontracted: true,
    })],
    workdays,
    null,
  );

  assert.equal(analysis.violations.length, 0);
});

test("an explicit backend release wins over a client-side derived date", () => {
  const analysis = analyseJitWindow(
    [segment(1)],
    [lot({
      customer_delivery_day: 14,
      material_reference_day: 7,
      material_reference_kind: "subcontract_dispatch",
      material_release_day: 2,
    })],
    workdays,
    null,
  );

  assert.equal(analysis.violations.length, 1);
  assert.equal(analysis.violations[0].earliest_allowed_start_day, 2);
  assert.equal(analysis.violations[0].material_reference_day, 7);
  assert.equal(analysis.violations[0].customer_delivery_day, 14);
});

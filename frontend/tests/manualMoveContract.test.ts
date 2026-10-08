import assert from "node:assert/strict";
import test from "node:test";

import {
  getManualMoveApplyError,
  normalizeManualMoveJob,
  normalizeManualMoveResponse,
} from "../src/lib/manualMoveContract.ts";

const delta = {
  otd_before: 100,
  otd_after: 100,
  otd_d_before: 100,
  otd_d_after: 100,
  setups_before: 2,
  setups_after: 2,
  earliness_before: 1,
  earliness_after: 1,
  tardy_before: 0,
  tardy_after: 0,
};

test("normaliza listas opcionais sem bloquear a página", () => {
  const response = normalizeManualMoveResponse({
    contract_version: 2,
    status: "preview",
    lot_id: "LOT-1",
    source_days: [0],
    target_day: 1,
    target_start_min: 420,
    target_machine: "M1",
    score: {},
    score_previous: {},
    delta,
    gate_report: {
      status: "applicable",
      apply_decision: "auto_applicable",
      requires_approval: false,
      approval_reasons: [],
      hard_gate_passed: true,
      physical_gate_passed: true,
      coverage_gate_passed: true,
      delivery_gate_passed: true,
      jit_window_gate_passed: true,
      robustness_gate_passed: null,
      material_gate_passed: true,
      metrics: {},
      violations: [],
      late_detail: [],
    },
    requires_confirmation: false,
    time_ms: 10,
  });

  assert.deepEqual(response.gate_report.jit_window_detail, []);
  assert.deepEqual(response.gate_report.setup_overlap_detail, []);
  assert.deepEqual(response.gate_report.proposals, []);
  assert.equal(response.gate_report.feasibility, null);
});

test("bloqueia uma resposta antiga antes de permitir aplicar", () => {
  assert.throws(
    () => normalizeManualMoveResponse({
      status: "preview",
      lot_id: "LOT-1",
      target_day: 1,
      target_machine: "M1",
      delta,
    }),
    /servidor está desatualizado/i,
  );
});

test("normaliza fases e cancelamento dos trabalhos de movimento", () => {
  const job = normalizeManualMoveJob({
    id: "job-1",
    created_at: "2026-07-27T10:00:00Z",
    updated_at: "2026-07-27T10:00:01Z",
    status: "cancelled",
    phase: "cancelled",
    progress: 135,
    message: "Verificação cancelada",
    dataset_id: "dataset-1",
    base_revision: 3,
    error: null,
    result: null,
  });

  assert.equal(job.status, "cancelled");
  assert.equal(job.phase, "cancelled");
  assert.equal(job.progress, 100);
  assert.equal(job.result, null);
});

test("preserva a causa física de um movimento rejeitado", () => {
  const job = normalizeManualMoveJob({
    id: "job-physical",
    status: "failed",
    phase: "failed",
    error: "Capacidade de operadores insuficiente",
    result: null,
    gate_report: {
      status: "invalid_physics",
      apply_decision: "blocked",
      requires_approval: false,
      physical_gate_passed: false,
      coverage_gate_passed: true,
      metrics: { operator_capacity_violations: 1 },
      violations: [{ kind: "operator_capacity", message: "3 operadores para 2 disponíveis" }],
    },
  });

  assert.equal(job.gate_report?.violations[0]?.kind, "operator_capacity");
});

test("rejeita estados desconhecidos dos trabalhos de movimento", () => {
  assert.throws(
    () => normalizeManualMoveJob({
      id: "job-2",
      status: "misterioso",
      result: null,
    }),
    /estado de verificação inválido/i,
  );
});

test("explica o que falta antes de aplicar um movimento com exceções", () => {
  assert.match(
    getManualMoveApplyError({
      requiresConfirmation: true,
      confirmed: false,
      reason: "",
    }) ?? "",
    /confirma.*exceções/i,
  );
  assert.match(
    getManualMoveApplyError({
      requiresConfirmation: true,
      confirmed: true,
      reason: "   ",
    }) ?? "",
    /motivo da alteração/i,
  );
  assert.equal(
    getManualMoveApplyError({
      requiresConfirmation: true,
      confirmed: true,
      reason: "Prioridade do cliente",
    }),
    null,
  );
});

test("não exige confirmação nem motivo quando o movimento não tem exceções", () => {
  assert.equal(
    getManualMoveApplyError({
      requiresConfirmation: false,
      confirmed: false,
      reason: "",
    }),
    null,
  );
});

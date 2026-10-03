// Real UI acceptance runs are restricted to the isolated instance.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");

const base = "http://127.0.0.1:53970";
const mode = process.argv[2] ?? "smoke";
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const report = { mode, screenshots: [], apiLatencyMs: [] };
page.on("pageerror", (error) => errors.push(String(error)));
page.setDefaultTimeout(15_000);

async function screenshot(name) {
  const path = `/tmp/incompolinho-corrections-${name}.png`;
  await page.screenshot({ path, fullPage: true });
  report.screenshots.push(path);
}

async function saveAndApply() {
  const started = page.waitForResponse((r) => r.url().endsWith("/replan-jobs") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Guardar alterações", exact: true }).click();
  const response = await started;
  const content = await response.json();
  assert.equal(response.status(), 200, JSON.stringify(content));
  const jobId = content.job.id;
  const apply = page.getByRole("button", { name: "Aplicar e guardar", exact: true });
  await apply.waitFor({ timeout: 75_000 });
  assert.equal(await apply.isEnabled(), true, await page.locator("body").innerText());
  const preview = await (await page.request.get(`${base}/api/data/replan-jobs/${jobId}`)).json();
  const applied = page.waitForResponse((r) => r.url().endsWith(`/replan-jobs/${jobId}/apply`));
  await apply.click();
  if (preview.job.result.gate_report.requires_approval) {
    await page.getByLabel("Justificação obrigatória").fill("Verificação isolada das ausências");
    await page.getByRole("button", { name: "Confirmar e aplicar", exact: true }).click();
  }
  const committed = await applied;
  assert.equal(committed.status(), 200, await committed.text());
  await apply.waitFor({ state: "detached" });
  await page.waitForTimeout(500);
  return (await page.request.get(`${base}/api/data/plan-view`)).json();
}

async function uploadValid(path) {
  await page.getByRole("button", { name: "Trocar ISOP", exact: true }).click();
  await page.getByLabel("Ficheiro ISOP").setInputFiles(path);
  const start = Date.now();
  for (;;) {
    const text = await page.locator("body").innerText();
    if (text.includes("Plano atualizado.") || text.includes("O novo plano foi carregado.")) break;
    const confirm = page.getByRole("button", { name: "Atualizar plano", exact: true });
    if (await confirm.isVisible() && await confirm.isEnabled()) await confirm.click();
    assert.ok(!text.includes("Não foi possível concluir"), text);
    assert.ok(Date.now() - start < 90_000, text);
    await page.waitForTimeout(500);
  }
  await page.getByText("Configuração", { exact: true }).first().click();
  await page.getByLabel("OEE da máquina PRM039").waitFor();
}

function productionPeaks(view) {
  const peaks = { A: 0, B: 0 };
  const dates = view.workdays ?? view.calendar?.workdays;
  // The fixture contains four references, each requiring one operator.
  for (let day = 0; day < 7; day += 1) {
    for (const [shift, lo, hi] of [["A", 420, 930], ["B", 930, 1440]]) {
      const events = view.segments.flatMap((s) => {
        if (s.day_idx !== day || s.prod_min <= 0) return [];
        const start = Math.max(lo, s.start_min + s.setup_min);
        const end = Math.min(hi, s.end_min);
        return start < end ? [[start, 1], [end, -1]] : [];
      }).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      let count = 0;
      for (const [, delta] of events) {
        count += delta;
        peaks[shift] = Math.max(peaks[shift], count);
      }
    }
  }
  return { ...peaks, dates };
}

try {
  await page.goto(base);
  await page.getByText("Configuração", { exact: true }).first().click();
  await page.getByLabel("OEE da máquina PRM039").waitFor();
  if (mode === "oee") {
    const before = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    report.before = { revision: before.plan_revision, dataset: before.dataset_id };
    await page.getByLabel("OEE da máquina PRM039").fill("0.44");
    const started = page.waitForResponse((r) => r.url().endsWith("/replan-jobs") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Guardar alterações", exact: true }).click();
    const response = await started;
    assert.equal(response.status(), 200);
    report.started = await response.json();
    const startedAt = Date.now();
    for (;;) {
      const message = await page.locator("body").innerText();
      if (message.includes("Aplicar e guardar") || message.includes("Não aplicável ao plano")) break;
      assert.ok(Date.now() - startedAt < 75_000, message);
      const now = performance.now();
      const health = await page.request.get(`${base}/api/copilot/health`);
      assert.equal(health.status(), 200);
      report.apiLatencyMs.push(performance.now() - now);
      await page.waitForTimeout(1200);
    }
    report.previewSeconds = (Date.now() - startedAt) / 1000;
    const jobId = report.started.job.id;
    report.preview = await (await page.request.get(`${base}/api/data/replan-jobs/${jobId}`)).json();
    await screenshot("oee-preview-desktop");
    assert.equal(await page.getByRole("button", { name: "Aplicar e guardar", exact: true }).isEnabled(), true);
    await page.getByRole("button", { name: "Aplicar e guardar", exact: true }).click();
    const confirmation = page.getByLabel("Justificação obrigatória");
    if (report.preview.job.result.gate_report.requires_approval) {
      await confirmation.fill("Teste de regressão na instância isolada");
    }
    const applied = page.waitForResponse((r) => r.url().endsWith(`/replan-jobs/${jobId}/apply`));
    if (report.preview.job.result.gate_report.requires_approval) {
      await page.getByRole("button", { name: "Confirmar e aplicar", exact: true }).click();
    }
    const committed = await applied;
    report.application = await committed.json();
    assert.equal(committed.status(), 200, JSON.stringify(report.application));
    await page.getByRole("button", { name: "Aplicar e guardar", exact: true }).waitFor({ state: "detached" });
    await page.waitForTimeout(500);
    report.after = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    assert.equal(report.after.dataset_id, before.dataset_id);
    assert.equal(report.after.plan_revision, before.plan_revision + 1);
    assert.equal(report.after.config.machines.PRM039.oee, 0.44);
    await page.reload();
    await page.getByText("Configuração", { exact: true }).first().click();
    await page.getByLabel("OEE da máquina PRM039").waitFor();
    assert.equal(await page.getByLabel("OEE da máquina PRM039").inputValue(), "0.44");
    await screenshot("oee-applied-desktop");
  } else if (mode === "robustness") {
    const before = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    await page.getByText("Plano", { exact: true }).first().click();
    await page.getByRole("button", { name: /^Simular alterações/ }).click();
    await page.locator("select").filter({ has: page.locator('option[value="intensive"]') }).selectOption("intensive");
    let starts = 0;
    await page.route("**/api/data/robustness-runs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      starts += 1;
      await new Promise((resolve) => setTimeout(resolve, 700));
      return route.continue();
    });
    const started = page.waitForResponse((r) => r.url().endsWith("/robustness-runs") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Executar", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "A aguardar…", exact: true }).isDisabled(), true);
    const startResponse = await started;
    const job = (await startResponse.json()).job;
    assert.equal(starts, 1);
    let releasePoll;
    let sawPoll;
    const waiting = new Promise((resolve) => { sawPoll = resolve; });
    const release = new Promise((resolve) => { releasePoll = resolve; });
    await page.route(`**/api/data/robustness-runs/${job.id}`, async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      sawPoll();
      await release;
      return route.fulfill({ response });
    });
    await waiting;
    const cancelled = page.waitForResponse((r) => r.url().endsWith(`/robustness-runs/${job.id}/cancel`));
    await page.getByRole("button", { name: "Cancelar", exact: true }).click();
    const cancelledResponse = await cancelled;
    assert.equal(cancelledResponse.status(), 200);
    releasePoll();
    await page.getByRole("button", { name: "Executar", exact: true }).waitFor();
    await page.waitForTimeout(1000);
    assert.equal(await page.getByRole("button", { name: "Executar", exact: true }).isEnabled(), true);
    const terminal = (await (await page.request.get(`${base}/api/data/robustness-runs/${job.id}`)).json()).job;
    assert.ok(["cancelled", "completed"].includes(terminal.status), JSON.stringify(terminal));
    await page.getByRole("button", { name: "Consulta", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "Executar", exact: true }).isDisabled(), true);
    assert.deepEqual(await (await page.request.get(`${base}/api/data/plan-view`)).json(), before);
    report.checks = ["pending POST disables start", "late poll cannot revive cancelled/completed job", "Consulta cannot start", "plan unchanged"];
    report.terminal = terminal.status;
    await screenshot("robustness-cancel-late-poll");
  } else if (mode === "simulator") {
    const before = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    await page.getByText("Plano", { exact: true }).first().click();
    await page.getByRole("button", { name: /^Simular alterações/ }).click();
    await page.getByText("Outras simulações e promessas", { exact: true }).click();
    await page.getByRole("button", { name: "+ Adicionar alteração", exact: true }).click();
    const panel = page.locator("#plan-simulator-content");
    await panel.locator("select").filter({ has: page.locator('option[value="demand_change"]') }).selectOption("demand_change");
    await panel.locator("select").filter({ has: page.getByRole("option", { name: "SKU", exact: true }) }).first().selectOption("AUDIT-SKU-0");
    await page.getByPlaceholder("Factor (1.0=igual)").fill("1.1");
    const calculated = page.waitForResponse((r) => r.url().endsWith("/simulate") && r.request().method() === "POST", { timeout: 75_000 });
    await page.getByRole("button", { name: "Simular", exact: true }).click();
    const candidateResponse = await calculated;
    const candidate = await candidateResponse.json();
    assert.equal(candidateResponse.status(), 200, JSON.stringify(candidate));
    assert.ok(candidate.candidate_id);
    await page.getByLabel("Nome para guardar o cenário").fill("AUDIT exact preview");
    const saved = page.waitForResponse((r) => r.url().endsWith("/scenarios") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Guardar cenário", exact: true }).click();
    const stored = await saved;
    assert.equal(stored.status(), 200, await stored.text());
    assert.equal(stored.request().postDataJSON().candidate_id, candidate.candidate_id);
    assert.deepEqual(await (await page.request.get(`${base}/api/data/plan-view`)).json(), before);
    await screenshot("simulator-saved-exact-preview");
    await page.getByPlaceholder("Factor (1.0=igual)").fill("1.2");
    await page.getByRole("button", { name: "Guardar cenário", exact: true }).waitFor({ state: "detached" });
    await page.getByText("Preview Gantt do cenário", { exact: true }).waitFor({ state: "detached" });
    await page.getByLabel("SKU da promessa").selectOption("AUDIT-SKU-1");
    await page.getByPlaceholder("Entrega cliente (dia)").fill("6");
    const promises = [];
    for (const qty of [10, 20]) {
      await page.getByPlaceholder("Quantidade", { exact: true }).fill(String(qty));
      await page.getByRole("button", { name: "Aplicar ao Gantt", exact: true }).waitFor({ state: "detached" });
      const verified = page.waitForResponse((r) => r.url().endsWith("/ctp") && r.request().method() === "POST", { timeout: 75_000 });
      await page.getByRole("button", { name: "Verificar", exact: true }).click();
      const response = await verified;
      const promise = await response.json();
      assert.equal(response.status(), 200, JSON.stringify(promise));
      assert.equal(promise.qty_requested, qty);
      assert.equal(promise.feasible, true, JSON.stringify(promise));
      promises.push(promise);
      await page.getByRole("button", { name: "Aplicar ao Gantt", exact: true }).waitFor();
    }
    assert.notEqual(promises[0].candidate_id, promises[1].candidate_id);
    await screenshot("ctp-verified-edited-quantity");
    let dropped = false;
    const successfulBodies = [];
    await page.route("**/api/data/ctp-apply", async (route) => {
      const response = await route.fetch();
      if (response.status() === 200) {
        successfulBodies.push(route.request().postDataJSON());
        if (!dropped) {
          dropped = true;
          return route.fulfill({ status: 503, json: { detail: "Simulated lost response after commit" } });
        }
      }
      return route.fulfill({ response });
    });
    await page.getByRole("button", { name: "Aplicar ao Gantt", exact: true }).click();
    const waitStart = Date.now();
    while (!dropped) {
      const approval = page.getByRole("button", { name: "Aprovar e aplicar", exact: true });
      if (await approval.isVisible()) {
        await page.getByLabel("Justificação", { exact: true }).fill("Teste isolado de recuperação de confirmação");
        await approval.click();
      }
      assert.ok(Date.now() - waitStart < 25_000, await page.locator("body").innerText());
      await page.waitForTimeout(200);
    }
    await page.getByText(/Simulated lost response after commit/).waitFor();
    const recovered = page.waitForResponse((r) => r.url().endsWith("/ctp-apply") && r.status() === 200);
    await page.getByRole("button", { name: "Aplicar ao Gantt", exact: true }).click();
    await recovered;
    await page.getByRole("button", { name: "Aplicar ao Gantt", exact: true }).waitFor({ state: "detached" });
    const after = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    assert.equal(after.plan_revision, before.plan_revision + 1);
    assert.equal(successfulBodies.length, 2);
    assert.equal(successfulBodies[0].request_id, successfulBodies[1].request_id);
    assert.ok(successfulBodies[0].request_id);
    assert.equal(successfulBodies[1].candidate_id, promises[1].candidate_id);
    assert.equal(after.score.hard_violations, 0);
    assert.equal(after.score.missing_qty, 0);
    report.checks = ["save consumes exact preview", "editing discards scenario", "editing discards CTP", "CTP applies verified quantity", "lost HTTP confirmation replays same receipt once"];
    report.after = { revision: after.plan_revision, dataset: after.dataset_id };
    report.promises = promises;
    await screenshot("ctp-applied-once-after-lost-response");
  } else if (mode === "operators") {
    await uploadValid("/tmp/incompolinho-audit-operators.xlsx");
    const before = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    assert.equal(Math.max(productionPeaks(before).A, productionPeaks(before).B), 4);
    await page.getByRole("button", { name: "Indisponibilidades", exact: true }).first().click();
    for (const shift of ["A", "B"]) {
      await page.getByLabel(/^Tipo/).selectOption("operator");
      await page.getByLabel("Equipa/turno").selectOption(`Grandes ${shift}`);
      await page.getByLabel("Pessoas ausentes").fill("3");
      await page.getByLabel("Início exato").fill("2026-10-19T00:00");
      await page.getByLabel("Fim exato").fill("2026-10-25T23:59");
      await page.getByLabel("Motivo (opcional)").fill(`AUDIT-ABSENCE-${shift}`);
      await page.getByRole("button", { name: "Adicionar ao rascunho", exact: true }).click();
    }
    const constrained = await saveAndApply();
    const limits = productionPeaks(constrained);
    assert.ok(limits.A <= 3 && limits.B <= 2, JSON.stringify(limits));
    assert.equal(constrained.score.hard_violations, 0);
    assert.equal(constrained.score.missing_qty, 0);
    await screenshot("operators-constrained");
    await page.setViewportSize({ width: 390, height: 1000 });
    await page.getByLabel(/^Tipo/).selectOption("operator");
    await screenshot("operators-mobile-form");
    for (const label of ["Tipo", "Equipa/turno", "Pessoas ausentes", "Início exato", "Fim exato", "Motivo (opcional)"]) {
      const rect = await page.getByLabel(new RegExp(`^${label.replaceAll(/[()]/g, "\\$&")}`)).boundingBox();
      assert.ok(rect.x >= 0 && rect.x + rect.width <= 390, `${label}: ${JSON.stringify(rect)}`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    for (const shift of ["A", "B"]) {
      const row = page.getByRole("row").filter({ hasText: `AUDIT-ABSENCE-${shift}` });
      await row.getByRole("button", { name: /^Remover indisponibilidade/ }).click();
    }
    const released = await saveAndApply();
    assert.equal(Math.max(productionPeaks(released).A, productionPeaks(released).B), 4);
    assert.equal(released.config.unavailability.operators.some((entry) => entry.reason.startsWith("AUDIT-ABSENCE")), false);
    assert.equal(released.score.hard_violations, 0);
    assert.equal(released.score.missing_qty, 0);
    await page.reload();
    await page.getByText("Configuração", { exact: true }).first().click();
    await page.getByLabel("OEE da máquina PRM039").waitFor();
    assert.deepEqual(await (await page.request.get(`${base}/api/data/plan-view`)).json(), released);
    await screenshot("operators-released");
    report.peaks = { before: productionPeaks(before), constrained: limits, released: productionPeaks(released) };
    report.revisions = [before.plan_revision, constrained.plan_revision, released.plan_revision];
  } else if (mode === "network") {
    const before = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    await page.route("**/api/data/plan-view", (route) => route.fulfill({ status: 503, json: { detail: "Test network failure" } }));
    await page.getByRole("button", { name: "Atualizar dados", exact: true }).click();
    await page.getByText("Não foi possível atualizar", { exact: true }).waitFor();
    assert.equal(await page.getByLabel("OEE da máquina PRM039").inputValue(), "0.44");
    await screenshot("network-refresh-failure");
    await page.unroute("**/api/data/plan-view");
    await page.getByRole("button", { name: "Atualizar dados", exact: true }).click();
    await page.getByText("Dados atualizados", { exact: true }).waitFor();
    let attempts = 0;
    await page.route("**/api/data/replan-jobs", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      attempts += 1;
      await route.fulfill({ status: 409, json: { detail: { code: "stale_revision", message: "Teste de conflito de revisão", current_revision: before.plan_revision + 1 } } });
    });
    await page.getByLabel("OEE da máquina PRM039").fill("0.45");
    await page.getByRole("button", { name: "Guardar alterações", exact: true }).click();
    await page.getByText(/Teste de conflito de revisão/).waitFor();
    assert.equal(await page.getByLabel("OEE da máquina PRM039").inputValue(), "0.45");
    assert.equal(attempts, 1);
    await screenshot("network-conflict-preserves-draft");
    await page.reload();
    await page.getByRole("button", { name: "Consulta", exact: true }).click();
    await page.getByText("Configuração", { exact: true }).first().click();
    await page.getByLabel("OEE da máquina PRM039").waitFor();
    await page.getByLabel("OEE da máquina PRM039").fill("0.45");
    const save = page.getByRole("button", { name: "Guardar alterações", exact: true });
    if (await save.isEnabled()) await save.click();
    await page.waitForTimeout(400);
    assert.equal(attempts, 1, "Consulta must not send a second write request");
    await screenshot("consulta-disabled-writes");
    const after = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    assert.deepEqual(after, before);
    report.checks = ["failed refresh preserves snapshot", "successful refresh acknowledged", "409 retains draft without retry", "Consulta cannot write", "live isolated plan unchanged"];
  } else if (mode === "upload") {
    const before = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    await page.getByRole("button", { name: "Trocar ISOP", exact: true }).click();
    await page.getByLabel("Ficheiro ISOP").setInputFiles("/tmp/incompolinho-audit-invalid.xlsx");
    await page.getByRole("button", { name: "Escolher outro ISOP", exact: true }).waitFor({ timeout: 90_000 });
    assert.match(await page.locator("body").innerText(), /N6/);
    assert.deepEqual(await (await page.request.get(`${base}/api/data/plan-view`)).json(), before);
    await screenshot("invalid-import-preserves-plan");
    await page.getByRole("button", { name: "Escolher outro ISOP", exact: true }).click();
    await page.getByLabel("Ficheiro ISOP").setInputFiles("/tmp/incompolinho-audit-valid.xlsx");
    const start = Date.now();
    for (;;) {
      const text = await page.locator("body").innerText();
      if (text.includes("Plano atualizado.") || text.includes("O novo plano foi carregado.")) break;
      const confirm = page.getByRole("button", { name: "Atualizar plano", exact: true });
      if (await confirm.isVisible() && await confirm.isEnabled()) await confirm.click();
      assert.ok(!text.includes("Não foi possível concluir"), text);
      assert.ok(Date.now() - start < 90_000, text);
      await page.waitForTimeout(500);
    }
    const after = await (await page.request.get(`${base}/api/data/plan-view`)).json();
    assert.notEqual(after.dataset_id, before.dataset_id);
    assert.equal(after.dataset.filename, "incompolinho-audit-valid.xlsx");
    assert.equal(after.score.missing_qty, 0);
    assert.equal(after.score.hard_violations, 0);
    report.after = { dataset: after.dataset_id, revision: after.plan_revision, segments: after.segments.length };
    await screenshot("valid-import-applied");
  } else {
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const name of ["Hoje", "Plano", "Carga e capacidade", "Entregas", "Risco", "Configuração"]) {
        const nav = page.getByText(name, { exact: true }).first();
        await nav.click();
        const ready = {
          "Hoje": () => page.getByLabel("Escolher data"),
          "Plano": () => page.getByText("PRM031", { exact: true }).filter({ visible: true }).first(),
          "Carga e capacidade": () => page.getByText("PRM031", { exact: true }).filter({ visible: true }).first(),
          "Entregas": () => page.getByRole("button", { name: "So rupturas", exact: true }),
          "Risco": () => page.getByText("PRM031", { exact: true }).filter({ visible: true }).first(),
          "Configuração": () => page.getByLabel("OEE da máquina PRM039"),
        };
        await ready[name]().waitFor({ state: "visible" });
        await page.getByText("A carregar...", { exact: true }).waitFor({ state: "detached" });
        await page.waitForTimeout(150);
        await screenshot(`smoke-${width}-${name.replaceAll(/[^a-zA-Z]/g, "_")}`);
      }
    }
  }
  assert.deepEqual(errors, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = String(error);
  report.body = (await page.locator("body").innerText()).slice(-10_000);
  await screenshot(`${mode}-failure`);
  process.exitCode = 1;
} finally {
  report.errors = errors;
  await writeFile(`/tmp/incompolinho-corrections-browser-${mode}.json`, JSON.stringify(report));
  console.log(JSON.stringify({ mode, status: report.status, error: report.error, seconds: report.previewSeconds }));
  await browser.close();
}

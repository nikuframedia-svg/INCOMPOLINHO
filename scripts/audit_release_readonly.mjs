// Publication acceptance: block every API write, including accidental UI actions.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const [baseArgument, prefix] = process.argv.slice(2);
assert.ok(baseArgument && prefix, "Expected app URL and absolute artifact prefix");
const base = baseArgument.replace(/\/+$/, "");
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(30_000);
const report = { base, screenshots: [], errors: [], blockedWrites: [], apiFailures: [] };
page.on("pageerror", (error) => report.errors.push(String(error)));
page.on("response", (response) => {
  if (response.url().includes("/api/") && response.status() >= 400) {
    report.apiFailures.push({ url: response.url(), status: response.status() });
  }
});
await page.route("**/api/**", async (route) => {
  if (!["GET", "HEAD", "OPTIONS"].includes(route.request().method())) {
    report.blockedWrites.push(route.request().url());
    await route.abort();
  } else await route.continue();
});
async function snapshot() {
  const response = await page.request.get(`${base}/api/data/plan-view`);
  assert.equal(response.status(), 200);
  return response.json();
}
try {
  const before = await snapshot();
  const machineId = before.segments[0]?.machine_id;
  assert.ok(machineId, "Expected an allocated production for this navigation check");
  await page.goto(base);
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const name of ["Hoje", "Plano", "Carga e capacidade", "Entregas", "Risco", "Configuração"]) {
      await page.getByText(name, { exact: true }).first().click();
      const ready = {
        "Hoje": () => page.getByLabel("Escolher data"),
        "Plano": () => page.getByText(machineId, { exact: true }).filter({ visible: true }).first(),
        "Carga e capacidade": () => page.getByText(machineId, { exact: true }).filter({ visible: true }).first(),
        "Entregas": () => page.getByRole("button", { name: "So rupturas", exact: true }),
        "Risco": () => page.getByText(machineId, { exact: true }).filter({ visible: true }).first(),
        "Configuração": () => page.getByLabel(`OEE da máquina ${machineId}`),
      };
      await ready[name]().waitFor({ state: "visible" });
      await page.getByText("A carregar...", { exact: true }).waitFor({ state: "detached" });
      const path = `${prefix}-${width}-${name.replaceAll(/[^a-zA-Z]/g, "_")}.png`;
      await page.screenshot({ path, fullPage: true });
      report.screenshots.push(path);
    }
  }
  const after = await snapshot();
  for (const key of ["dataset_id", "plan_revision", "segments", "lots", "config", "score", "active_mutations", "manual_edits"]) {
    assert.deepEqual(after[key], before[key], key);
  }
  report.identity = { dataset: after.dataset_id, revision: after.plan_revision, segments: after.segments.length };
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.blockedWrites, []);
  assert.deepEqual(report.apiFailures, []);
  report.status = "passed";
} catch (error) {
  report.status = "failed";
  report.error = String(error);
  report.body = (await page.locator("body").innerText()).slice(-10_000);
  await page.screenshot({ path: `${prefix}-failure.png`, fullPage: true });
  process.exitCode = 1;
} finally {
  await writeFile(`${prefix}.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: report.status, error: report.error, identity: report.identity,
    errors: report.errors, apiFailures: report.apiFailures, blockedWrites: report.blockedWrites }));
  await browser.close();
}

// Read-only browser acceptance with deliberate network/proxy failures.
import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const [baseArgument, prefix, onlyCase] = process.argv.slice(2);
assert.ok(baseArgument && prefix, "Expected app URL and artifact prefix");
const base = baseArgument.replace(/\/+$/, "");
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH });
const report = { base, cases: [], errors: [], blockedWrites: [] };
const cases = [
  { name: "risk_network", path: "/api/data/risk", failures: 2, page: "Risco" },
  { name: "config_proxy", path: "/api/data/catalog", failures: 2, page: "Configuração", status: 503 },
  { name: "today_network", path: "/api/console", failures: 2, page: "Hoje" },
  { name: "exhausted", path: "/api/data/risk", failures: Infinity, page: "Risco" },
  { name: "unmounted", path: "/api/data/risk", failures: 2, page: "Risco" },
].filter(item => !onlyCase || item.name === onlyCase);
assert.ok(cases.length, "Unknown case");

async function snapshot(request) {
  const response = await request.get(`${base}/api/data/plan-view`);
  assert.equal(response.status(), 200);
  return response.json();
}

try {
  for (const width of onlyCase ? [1440] : [1440, 390]) {
    for (const scenario of cases) {
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      await context.addInitScript((mode) => localStorage.setItem("pp1AccessMode", mode), width === 390 ? "view" : "edit");
      const page = await context.newPage();
      page.setDefaultTimeout(8000);
      const result = { name: scenario.name, width, attempts: [], injectedFailures: 0, networkFailures: [] };
      const injected = new WeakSet();
      report.cases.push(result);
      page.on("pageerror", error => report.errors.push(String(error)));
      page.on("requestfailed", request => result.networkFailures.push({
        url: request.url(), error: request.failure(), injected: injected.has(request),
      }));
      await page.route("**/api/**", async route => {
        const request = route.request();
        if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
          report.blockedWrites.push(request.url());
          return route.abort();
        }
        if (new URL(request.url()).pathname !== scenario.path) return route.continue();
        result.attempts.push({ at: Date.now(), headers: request.headers() });
        if (result.injectedFailures >= scenario.failures) return route.continue();
        result.injectedFailures++;
        if (scenario.status) return route.fulfill({ status: scenario.status, contentType: "text/html", body: "<html>Proxy temporarily unavailable</html>" });
        injected.add(request);
        return route.abort("internetdisconnected");
      });
      try {
        const before = await snapshot(page.request);
        const machine = before.segments[0].machine_id;
        await page.goto(base);
        await page.getByTitle(before.dataset.filename, { exact: true }).filter({ visible: true }).first().waitFor();
        await page.getByText(scenario.page, { exact: true }).first().click();
        if (scenario.name === "unmounted") {
          await page.waitForFunction(() => performance.getEntriesByType("resource").some(entry => entry.name.endsWith("/api/data/risk")));
          await page.getByText("Plano", { exact: true }).first().click();
          await page.getByText(machine, { exact: true }).filter({ visible: true }).first().waitFor();
          await page.waitForTimeout(700);
          assert.equal(await page.getByText(/Não foi possível ligar/).count(), 0);
          await page.getByText("Risco", { exact: true }).first().click();
        }
        if (scenario.name === "exhausted") {
          await page.getByText("Error: Não foi possível ligar ao servidor. Tenta novamente dentro de instantes.", { exact: true }).waitFor();
          assert.equal(await page.getByText(/A restabelecer ligação/).count(), 0);
          const count = result.attempts.length;
          assert.ok(count >= 3 && count <= 6, `Unbounded read retry: ${count}`);
          await page.waitForTimeout(800);
          assert.equal(result.attempts.length, count);
        } else if (scenario.page === "Configuração") {
          await page.getByLabel(`OEE da máquina ${machine}`).waitFor();
        } else if (scenario.page === "Hoje") {
          await page.getByLabel("Escolher data").waitFor();
        } else {
          await page.getByText(machine, { exact: true }).filter({ visible: true }).first().waitFor();
        }
        assert.ok(result.injectedFailures >= Math.min(2, scenario.failures), "Fault injection not exercised");
        if (scenario.name !== "exhausted") {
          assert.equal(await page.getByText(/Não foi possível ligar|temporariamente indisponível/).count(), 0);
        }
        for (const attempt of result.attempts) {
          assert.equal(attempt.headers["x-dataset-id"], before.dataset_id);
          assert.equal(attempt.headers["x-plan-revision"], String(before.plan_revision));
          assert.equal(attempt.headers["x-access-mode"], width === 390 ? "view" : "edit");
        }
        const after = await snapshot(page.request);
        for (const key of ["dataset_id", "plan_revision", "segments", "lots", "config", "score", "active_mutations", "manual_edits"]) {
          assert.deepEqual(after[key], before[key], key);
        }
        result.screenshot = `${prefix}-${width}-${scenario.name}.png`;
        await page.screenshot({ path: result.screenshot, fullPage: true });
        result.identity = { dataset: after.dataset_id, revision: after.plan_revision };
        result.status = "passed";
      } catch (error) {
        result.status = "failed";
        result.error = String(error);
        result.body = (await page.locator("body").innerText()).slice(-10_000);
        await page.screenshot({ path: `${prefix}-${width}-${scenario.name}-failure.png`, fullPage: true });
        process.exitCode = 1;
      } finally {
        await context.close();
      }
    }
  }
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.blockedWrites, []);
} catch (error) {
  report.error = String(error);
  process.exitCode = 1;
} finally {
  await browser.close();
  report.status = process.exitCode ? "failed" : "passed";
  await writeFile(`${prefix}.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: report.status, error: report.error, cases: report.cases.map(({ name, width, status, error, injectedFailures, attempts, networkFailures }) => ({ name, width, status, error, injectedFailures, attempts: attempts.length, unexpectedNetworkFailures: networkFailures.filter(failure => !failure.injected) })),
    errors: report.errors, blockedWrites: report.blockedWrites }));
}

// Real frontend recalculation and exact-candidate persistence, private only.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const [runtime, prefix, mode] = process.argv.slice(2);
assert.ok(runtime?.startsWith('/tmp/incompolinho-full-horizon-runtime-'));
const base = 'http://127.0.0.1:54267';
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH});
const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Europe/Lisbon'});
page.setDefaultTimeout(90_000);
const report = {status:'running',errors:[],screenshots:[]};
page.on('pageerror',error=>report.errors.push(String(error)));
async function view() {
  const response = await page.request.get(`${base}/api/data/plan-view`);
  assert.equal(response.status(),200);
  return response.json();
}
async function screenshot(stage) {
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    const path = `${prefix}-${stage}-${width}.png`;
    await page.screenshot({path,fullPage:true});
    report.screenshots.push(path);
  }
  await page.setViewportSize({width:1440,height:1000});
}
try {
  const before = await view();
  assert.equal(before.dataset_id,'6d55d4d1d9094833aebdf62d89297d52');
  await page.goto(base);
  await page.getByText('Plano',{exact:true}).first().click();
  await page.getByRole('button',{name:'Tudo',exact:true}).click();
  if(mode !== 'restart') {
    await screenshot('before');
    const started = performance.now();
    const pending = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/api/data/recalculate'));
    await page.getByRole('button',{name:'Recalcular plano',exact:true}).click();
    const response = await pending;
    report.preview_seconds = (performance.now()-started)/1000;
    if(response.status()===409) {
      const detail = (await response.json()).detail;
      assert.ok(detail.candidate_id,JSON.stringify(detail));
      assert.equal(detail.gate_report.apply_decision,'approval_required');
      assert.deepEqual((await view()).segments,before.segments);
      const applying = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/api/data/recalculate'));
      await page.getByRole('dialog').getByRole('button',{name:'Aplicar plano',exact:true}).click();
      const applied = await applying;
      assert.equal(applied.status(),200,await applied.text());
      assert.equal(applied.request().postDataJSON().candidate_id,detail.candidate_id);
      report.candidate_id = detail.candidate_id;
    } else assert.equal(response.status(),200,await response.text());
    await page.getByText(/Plano recalculado/).filter({visible:true}).first().waitFor();
  }
  const after = await view();
  const proof = JSON.parse(await readFile(`${runtime}/candidate-proof.json`));
  assert.equal(proof.calls,1);
  const durable = await (await page.request.get(`${base}/api/__full_horizon_proof__`)).json();
  assert.deepEqual(durable.segments,proof.segments);
  assert.deepEqual(durable.lots,proof.lots);
  const raw = await (await page.request.get(`${base}/api/data/segments`)).json();
  assert.deepEqual(raw,proof.segments);
  assert.equal(after.plan_revision,92);
  assert.equal(durable.engine_data.plan_anchors[0].lot_id,'LOT_TWIN_BFP083_15');
  const first = [...raw].filter(s=>s.prod_min>0 && s.lot_id==='LOT_BFP082_PRM019_1092262X100_0')
    .sort((a,b)=>a.day_idx-b.day_idx || a.start_min-b.start_min)[0];
  assert.equal(first.day_idx,0);
  report.bfp082 = {day:first.day_idx,production_start:first.start_min+first.setup_min};
  await page.getByLabel('Pesquisar no plano').fill('BFP082');
  const range = page.locator('details').filter({has:page.locator('summary',{hasText:'Intervalo personalizado'})});
  await range.locator('summary').click();
  await range.locator('input').nth(0).fill('0');
  await range.locator('input').nth(1).fill('8');
  await range.getByRole('button',{name:'Aplicar',exact:true}).click();
  await screenshot(mode==='restart'?'restart':'after');
  await page.reload();
  assert.deepEqual((await view()).segments,after.segments);
  assert.deepEqual(report.errors,[]);
  report.status='passed';report.revision=after.plan_revision;
} catch(error) {
  report.status='failed';report.error=String(error);report.stack=error.stack;
  report.body=(await page.locator('body').innerText()).slice(-8000);
  await screenshot('failure');process.exitCode=1;
} finally {
  await writeFile(`${prefix}${mode==='restart'?'-restart':''}.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
  await browser.close();
}

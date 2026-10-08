// Actual UI recalculate, approval and reload, restricted to a private fixture.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const [name, runtime, prefix] = process.argv.slice(2);
const readOnly = process.argv[5] === '--read-only';
assert.ok(name && runtime && prefix);
assert.ok(runtime.startsWith('/tmp/incompolinho-named-flow-'));
const base = 'http://127.0.0.1:54254';
const fixture = JSON.parse(await readFile(new URL('../tests/fixtures/planning_opportunities_2026-09-17.json', import.meta.url)));
const expected = fixture.cases[name]?.expected;
assert.ok(expected);
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH});
const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Europe/Lisbon'});
page.setDefaultTimeout(75_000);
await page.clock.setFixedTime(new Date(fixture.clock));
const report = {case:name,status:'running',errors:[],failures:[],expectedConfirmations:[],screenshots:[]};
page.on('pageerror', error => report.errors.push(String(error)));
page.on('response', response => {
  if(response.url().includes('/api/') && response.status() >= 400) report.failures.push([response.url(),response.status()]);
});
async function view() {
  const response = await page.request.get(`${base}/api/data/plan-view`);
  assert.equal(response.status(),200);
  const value = await response.json();
  assert.equal(value.dataset_id,name,'Never mutate another dataset');
  return value;
}
async function shots(stage) {
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    const path = `${prefix}-${stage}-${width}.png`;
    await page.screenshot({path,fullPage:true});
    report.screenshots.push(path);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.getByRole('button',{name:'Tabela',exact:true}).click();
  const tablePath = `${prefix}-${stage}-table-1440.png`;
  await page.screenshot({path:tablePath,fullPage:true});
  report.screenshots.push(tablePath);
  await page.getByRole('button',{name:'Gantt',exact:true}).click();
}
function verify(value) {
  if(expected.sku) {
    const rows = value.segments.filter(s => s.prod_min > 0 && s.sku === expected.sku)
      .sort((a,b) => a.day_idx-b.day_idx || a.start_min-b.start_min);
    assert.ok(rows.length);
    assert.deepEqual([rows[0].day_idx, rows[0].start_min+rows[0].setup_min],
      [expected.first_day,expected.production_start]);
    if(expected.complete_day !== undefined) {
      assert.ok(rows.every(s => s.day_idx === expected.complete_day));
      for(let i=1;i<rows.length;i++) assert.equal(rows[i].start_min,rows[i-1].end_min);
    }
  } else {
    const byTool = new Map();
    for(const s of [...value.segments].sort((a,b)=>a.day_idx-b.day_idx || a.start_min-b.start_min)) {
      if(!byTool.has(s.tool_id)) byTool.set(s.tool_id,[]);
      byTool.get(s.tool_id).push(s.machine_id);
    }
    const transfers = [...byTool.values()].reduce((total,machines)=>total+
      machines.slice(1).filter((mid,i)=>mid!==machines[i]).length,0);
    assert.equal(transfers,expected.transfers);
    assert.ok(value.segments.filter(s=>s.setup_min>0).length <= expected.max_setups);
  }
}
try {
  if(readOnly) {
    const previous = JSON.parse(await readFile(`${prefix}.json`));
    assert.equal(previous.status,'passed');
    const recovered = await view();
    assert.equal(recovered.plan_revision,previous.revision);
    assert.deepEqual(recovered.segments,previous.segments);
    assert.deepEqual(recovered.lots,previous.lots);
    verify(recovered);
    const proof = JSON.parse(await readFile(`${runtime}/candidate-proof.json`));
    const raw = await page.request.get(`${base}/api/data/segments`);
    assert.equal(raw.status(),200);
    assert.deepEqual(await raw.json(),proof.segments);
    const durable = await (await page.request.get(`${base}/api/__named-proof__`)).json();
    assert.deepEqual(durable.payload.segments,proof.segments);
    assert.deepEqual(durable.payload.lots,proof.lots);
    await page.goto(base);
    await page.getByText('Plano',{exact:true}).first().click();
    await page.getByRole('button',{name:'Tudo',exact:true}).click();
    await shots('restart');
    assert.deepEqual(report.errors,[]);
    assert.deepEqual(report.failures,[]);
    report.status='passed';
    report.revision=recovered.plan_revision;
  } else {
  const before = await view();
  assert.equal(before.plan_revision,1);
  await page.goto(base);
  await page.getByText('Plano',{exact:true}).first().click();
  await page.getByRole('button',{name:'Tudo',exact:true}).click();
  await shots('before');
  const started = performance.now();
  const responsePromise = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/api/data/recalculate'));
  await page.getByRole('button',{name:'Recalcular plano',exact:true}).click();
  const first = await responsePromise;
  report.preview_seconds = (performance.now()-started)/1000;
  if(first.status()===409) {
    const detail = (await first.json()).detail;
    assert.equal(detail.gate_report.requires_approval,true);
    assert.ok(detail.candidate_id);
    assert.equal(detail.dataset_id,name);
    assert.equal(detail.base_revision,1);
    assert.deepEqual((await view()).segments,before.segments);
    report.expectedConfirmations.push([first.url(),409]);
    const appliedPromise = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/api/data/recalculate'));
    await page.getByRole('dialog').getByRole('button',{name:'Aplicar plano',exact:true}).click();
    const applied = await appliedPromise;
    assert.equal(applied.status(),200,await applied.text());
    assert.equal(applied.request().postDataJSON().candidate_id,detail.candidate_id);
    report.candidate_id = detail.candidate_id;
  } else assert.equal(first.status(),200,await first.text());
  await page.getByText(/Plano recalculado/).filter({visible:true}).first().waitFor();
  const accepted = await view();
  assert.equal(accepted.plan_revision,2);
  verify(accepted);
  const proof = JSON.parse(await readFile(`${runtime}/candidate-proof.json`));
  assert.equal(proof.calls,1);
  assert.deepEqual(accepted.lots,proof.lots);
  const raw = await page.request.get(`${base}/api/data/segments`);
  assert.equal(raw.status(),200);
  assert.deepEqual(await raw.json(),proof.segments);
  for(const [actual,planned] of accepted.segments.map((s,i)=>[s,proof.segments[i]])) {
    // Live explanations update only diagnostics; raw and durable equality is checked above/below.
    const diagnostics = ['left_shift_blockers','material_release_day','release_delay_workdays'];
    for(const key of Object.keys(planned).filter(key=>!diagnostics.includes(key)))
      assert.deepEqual(actual[key],planned[key],key);
  }
  const durableResponse = await page.request.get(`${base}/api/__named-proof__`);
  assert.equal(durableResponse.status(),200);
  const durable = await durableResponse.json();
  assert.deepEqual(durable.payload.lots,proof.lots);
  assert.deepEqual(durable.payload.segments,proof.segments);
  if(report.candidate_id) assert.equal(durable.payload.approvals.at(-1).candidate_id,report.candidate_id);
  await shots('after');
  await page.reload();
  const reloaded = await view();
  assert.deepEqual(reloaded.segments,accepted.segments);
  assert.deepEqual(reloaded.lots,accepted.lots);
  verify(reloaded);
  assert.deepEqual(report.errors,[]);
  assert.deepEqual(report.failures,report.expectedConfirmations);
  report.status='passed';
  report.revision=accepted.plan_revision;
  report.segments=accepted.segments;
  report.lots=accepted.lots;
  }
} catch(error) {
  report.status='failed'; report.error=String(error); report.stack=error.stack;
  report.body=(await page.locator('body').innerText()).slice(-9000);
  await shots('failure'); process.exitCode=1;
} finally {
  await writeFile(`${prefix}${readOnly?'-restart':''}.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({case:name,status:report.status,error:report.error,seconds:report.preview_seconds,
    errors:report.errors,failures:report.failures,revision:report.revision}));
  await browser.close();
}

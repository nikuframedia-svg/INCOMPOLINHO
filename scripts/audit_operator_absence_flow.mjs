// Mutating acceptance run: only the dedicated isolated backend may be used.
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';

const {chromium} = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const [base = 'http://127.0.0.1:54254', prefix = '/tmp/incompolinho-operator-flow-browser',
  proofPath = '/tmp/incompolinho-operator-flow-proof.json'] = process.argv.slice(2);
assert.equal(new URL(base).origin, 'http://127.0.0.1:54254');
const fixture = JSON.parse(await readFile(new URL('../tests/fixtures/operator_absence_2026-09-21.json', import.meta.url)));
const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH});
const page = await browser.newPage({viewport:{width:1440, height:1000}, timezoneId:'Europe/Lisbon'});
page.setDefaultTimeout(75_000);
await page.clock.setFixedTime(new Date(fixture.clock));
const report = {status:'running', errors:[], failures:[], expectedConfirmations:[], stages:[], screenshots:[]};
page.on('pageerror', error => report.errors.push(String(error)));
page.on('response', r => {if(r.url().includes('/api/') && r.status() >= 400) report.failures.push([r.url(), r.status()]);});
await page.route('**/api/**', async route => {
  assert.equal(new URL(route.request().url()).origin, new URL(base).origin);
  await route.continue();
});

async function view() {
  const response = await page.request.get(`${base}/api/data/plan-view`);
  assert.equal(response.status(), 200);
  const value = await response.json();
  assert.equal(value.dataset_id, fixture.id, 'Never mutate production');
  return value;
}
async function shot(name) {
  const path = `${prefix}-${name}.png`;
  await page.screenshot({path, fullPage:true});
  report.screenshots.push(path);
}
function physical(value) {
  return value.segments.map(s => Object.fromEntries(['lot_id','run_id','machine_id','tool_id','day_idx',
    'start_min','end_min','qty','prod_min','setup_min','twin_outputs'].map(k => [k,s[k]])));
}
function peaks(value) {
  const answer = {A:0, B:0};
  for(const day of [4,5,6,7,8,9,10]) for(const [shift,left,right] of [['A',420,930],['B',930,1440]]) {
    const events = new Map();
    for(const s of value.segments) {
      if(s.day_idx !== day || s.prod_min <= 0) continue;
      const start = Math.max(s.production_start_min ?? s.start_min + s.setup_min,left), end = Math.min(s.end_min,right);
      if(start >= end) continue;
      events.set(start,(events.get(start) ?? 0)+1);
      events.set(end,(events.get(end) ?? 0)-1);
    }
    let count=0;
    for(const minute of [...events.keys()].sort((a,b)=>a-b)) {
      count += events.get(minute);
      answer[shift] = Math.max(answer[shift],count);
    }
  }
  return answer;
}
async function checkStage(name, expectedAbsences, limits) {
  const value = await view();
  assert.equal(value.config.unavailability.operators.length, expectedAbsences);
  assert.equal(value.segments.reduce((n,s)=>n+s.qty,0), fixture.demand.qty_per_machine * 4);
  const concurrent = peaks(value);
  assert.ok(concurrent.A <= limits.A, JSON.stringify(concurrent));
  assert.ok(concurrent.B <= limits.B, JSON.stringify(concurrent));
  report.stages.push({name,revision:value.plan_revision,peaks:concurrent,value});
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    await shot(`${name}-${width}`);
  }
  await page.setViewportSize({width:1440,height:1000});
  return value;
}
async function applyDraft(name) {
  const before = await view();
  const responsePromise = page.waitForResponse(r => r.request().method()==='POST' && r.url().endsWith('/api/data/replan-jobs'));
  await page.getByRole('button',{name:'Guardar altera\u00e7\u00f5es',exact:true}).click();
  const posted = await responsePromise;
  assert.equal(posted.status(),200,await posted.text());
  const jobId = (await posted.json()).job.id;
  await page.getByRole('button',{name:'Aplicar e guardar',exact:true}).waitFor();
  assert.deepEqual(physical(await view()),physical(before));
  const response = await page.request.get(`${base}/api/data/replan-jobs/${jobId}`);
  const job = (await response.json()).job;
  assert.equal(job.status,'ready',JSON.stringify(job));
  assert.equal(job.result.gate_report.physical_gate_passed,true);
  assert.equal(job.result.gate_report.coverage_gate_passed,true);
  const appliedPromise = page.waitForResponse(r => r.request().method()==='POST' && r.url().endsWith(`/replan-jobs/${jobId}/apply`));
  await page.getByRole('button',{name:'Aplicar e guardar',exact:true}).click();
  if(job.result.gate_report.requires_approval) {
    await page.getByRole('dialog').getByLabel('Justifica\u00e7\u00e3o obrigat\u00f3ria').fill('Ensaio isolado de capacidade, aplicacao e remocao de operadores.');
    await page.getByRole('dialog').getByRole('button',{name:'Confirmar e aplicar',exact:true}).click();
  }
  const applied = await appliedPromise;
  assert.equal(applied.status(),200,await applied.text());
  await page.getByRole('button',{name:'Aplicar e guardar',exact:true}).waitFor({state:'detached'});
  const after = await view();
  assert.equal(after.plan_revision,before.plan_revision+1);
  report.stages.push({name:`${name}-job`,jobId,job});
  console.log(JSON.stringify({name,jobId,revision:after.plan_revision,peaks:peaks(after)}));
}

try {
  const before = await view();
  assert.equal(before.config.unavailability.operators.length,0);
  assert.deepEqual(peaks(before),{A:4,B:4});
  await page.goto(base);
  await page.getByText('Configura\u00e7\u00e3o',{exact:true}).first().click();
  await page.getByRole('button',{name:'Indisponibilidades',exact:true}).first().click();
  for(const shift of ['A','B']) {
    await page.getByLabel(/^Tipo/).selectOption('operator');
    await page.getByLabel(/^Equipa\/turno/).selectOption(`Grandes ${shift}`);
    await page.getByLabel('Pessoas ausentes',{exact:true}).fill('3');
    await page.getByLabel(/^Categoria/).selectOption('Outra');
    await page.getByLabel('In\u00edcio exato',{exact:true}).fill('2026-09-21T00:01');
    await page.getByLabel('Fim exato',{exact:true}).fill('2026-09-27T23:59');
    await page.getByRole('button',{name:'Adicionar ao rascunho',exact:true}).click();
  }
  assert.deepEqual(physical(await view()),physical(before));
  await applyDraft('add-both');
  const restricted = await checkStage('restricted',2,{A:3,B:2});
  assert.deepEqual(peaks(restricted),{A:3,B:2});
  await page.getByRole('button',{name:/^Remover indisponibilidade Grandes A/}).click();
  await applyDraft('remove-A');
  const onlyB = await checkStage('only-B',1,{A:4,B:2});
  assert.equal(peaks(onlyB).A,4);
  await page.getByRole('button',{name:/^Remover indisponibilidade Grandes B/}).click();
  await applyDraft('remove-B');
  const released = await checkStage('released',0,{A:4,B:4});
  assert.equal(Math.max(...Object.values(peaks(released))),4);
  await page.reload();
  assert.deepEqual(physical(await view()),physical(released));
  const recalculated = page.waitForResponse(r => r.request().method()==='POST' && r.url().endsWith('/api/data/recalculate'));
  await page.getByRole('button',{name:'Recalcular plano',exact:true}).click();
  const firstResponse = await recalculated;
  if(firstResponse.status()===409) {
    const detail = (await firstResponse.json()).detail;
    assert.equal(detail.gate_report.requires_approval,true);
    assert.equal(detail.dataset_id,fixture.id);
    assert.equal(detail.base_revision,released.plan_revision);
    assert.ok(detail.candidate_id && detail.candidate_fingerprint);
    assert.deepEqual(physical(await view()),physical(released));
    report.expectedConfirmations.push([firstResponse.url(),409]);
    const confirmed = page.waitForResponse(r => r.request().method()==='POST' && r.url().endsWith('/api/data/recalculate'));
    const confirmation = page.getByRole('dialog');
    await confirmation.getByRole('button',{name:'Aplicar plano',exact:true}).click();
    const applied = await confirmed;
    assert.equal(applied.status(),200,await applied.text());
    assert.equal(applied.request().postDataJSON().candidate_id,detail.candidate_id);
    const proof = JSON.parse(await readFile(proofPath));
    const accepted = await view();
    assert.equal(proof.calls,1,'Approval must not run compaction again');
    assert.deepEqual(physical(accepted),physical({segments:proof.segments}));
    assert.deepEqual(accepted.lots,proof.lots);
    const durableResponse = await page.request.get(`${base}/api/__operator-proof__`);
    assert.equal(durableResponse.status(),200);
    const durable = await durableResponse.json();
    assert.equal(durable.payload.approvals.at(-1).candidate_id,detail.candidate_id);
    assert.equal(durable.runtime.plan_revision,accepted.plan_revision);
  } else assert.equal(firstResponse.status(),200,await firstResponse.text());
  await page.getByText(/Plano recalculado/).filter({visible:true}).first().waitFor();
  const afterRecalculation = await checkStage('recalculated',0,{A:4,B:4});
  assert.ok(afterRecalculation.plan_revision > released.plan_revision);
  assert.equal(Math.max(...Object.values(peaks(afterRecalculation))),4);
  assert.deepEqual(report.errors,[]);
  assert.deepEqual(report.failures,report.expectedConfirmations);
  report.status='passed';
} catch(error) {
  report.status='failed'; report.error=String(error);report.stack=error.stack;
  report.body=(await page.locator('body').innerText()).slice(-9000);
  await shot('failure');process.exitCode=1;
} finally {
  await writeFile(`${prefix}.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({status:report.status,error:report.error,errors:report.errors,failures:report.failures}));
  await browser.close();
}

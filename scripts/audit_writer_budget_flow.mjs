// Real configuration UI with interrupted apply, retry, durable late reply and reload.
import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
const {chromium} = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');
const base = 'http://127.0.0.1:54254';
const prefix = process.argv[2] ?? '/tmp/incompolinho-writer-ui';
const readOnly = process.argv.includes('--read-only');
const browser = await chromium.launch({headless:true,executablePath:process.env.PLAYWRIGHT_CHROMIUM_PATH});
const page = await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Europe/Lisbon'});
page.setDefaultTimeout(75_000);
await page.clock.setFixedTime(new Date('2026-09-17T07:00:00+01:00'));
const report = {status:'running',errors:[],failures:[],stages:[],screenshots:[]};
page.on('pageerror',error=>report.errors.push(String(error)));
page.on('response',r=>{if(r.url().includes('/api/') && r.status()>=400)report.failures.push([r.url(),r.status()]);});
async function get(path) {
  const response = await page.request.get(`${base}${path}`);
  assert.equal(response.status(),200);
  return response.json();
}
async function view() {
  const value = await get('/api/data/plan-view');
  assert.equal(value.dataset_id,'bfp082_initial_priority','Never mutate production');
  return value;
}
async function arm(mode) {
  const response = await page.request.post(`${base}/api/__writer-fault__`,{data:{mode}});
  assert.equal(response.status(),200);
}
async function shots(stage) {
  for(const width of [1440,390]) {
    await page.setViewportSize({width,height:1000});
    const path = `${prefix}-${stage}-${width}.png`;
    await page.screenshot({path,fullPage:true});
    report.screenshots.push(path);
  }
  await page.setViewportSize({width:1440,height:1000});
}
try {
  if(readOnly) {
    const previous = JSON.parse(await readFile(`${prefix}.json`));
    assert.equal(previous.status,'passed');
    const value = await view();
    const proof = await get('/api/__writer-proof__');
    assert.equal(value.plan_revision,2);
    assert.deepEqual(proof.runtime,previous.durable.runtime);
    assert.equal(proof.payload_sha,previous.durable.payload_sha);
    assert.equal(proof.config_sha,previous.durable.config_sha);
    assert.deepEqual(proof.pending,[]);
    assert.equal(value.config.machines.PRM019.oee,0.8);
    const raw = await get('/api/data/segments');
    assert.deepEqual(raw,proof.payload.segments);
    await page.goto(base);
    await page.getByText('Configura\u00e7\u00e3o',{exact:true}).first().click();
    await page.getByLabel('OEE da m\u00e1quina PRM019',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('OEE da m\u00e1quina PRM019',{exact:true}).inputValue(),'0.8');
    await shots('restart');
    assert.deepEqual(report.errors,[]);
    assert.deepEqual(report.failures,[]);
    report.status='passed';report.revision=value.plan_revision;
  } else {
  const before = await view();
  assert.equal(before.plan_revision,1);
  const durableBefore = await get('/api/__writer-proof__');
  await page.goto(base);
  await page.getByText('Configura\u00e7\u00e3o',{exact:true}).first().click();
  await page.getByLabel('OEE da m\u00e1quina PRM019',{exact:true}).fill('0.8');
  const started = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/api/data/replan-jobs'));
  await page.getByRole('button',{name:'Guardar altera\u00e7\u00f5es',exact:true}).click();
  const posted = await started;
  assert.equal(posted.status(),200,await posted.text());
  const jobId = (await posted.json()).job.id;
  await page.getByRole('button',{name:'Aplicar e guardar',exact:true}).waitFor();
  const job = (await get(`/api/data/replan-jobs/${jobId}`)).job;
  assert.equal(job.status,'ready',JSON.stringify(job));
  assert.notEqual(job.result.gate_report.apply_decision,'blocked');
  const candidate = (await get(`/api/__writer-proof__?job_id=${jobId}`)).candidate;
  assert.ok(candidate);

  async function apply(mode,expectedStatus) {
    await arm(mode);
    const startedAt = performance.now();
    const promise = page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith(`/replan-jobs/${jobId}/apply`));
    await page.getByRole('button',{name:'Aplicar e guardar',exact:true}).click();
    if(job.result.gate_report.requires_approval) {
      await page.getByRole('dialog').getByLabel('Justifica\u00e7\u00e3o obrigat\u00f3ria').fill('Ensaio privado de interrupcao e gravacao recuperavel.');
      await page.getByRole('dialog').getByRole('button',{name:'Confirmar e aplicar',exact:true}).click();
    }
    const response = await promise;
    const body = await response.json();
    assert.equal(response.status(),expectedStatus,JSON.stringify(body));
    report.stages.push({mode,status:response.status(),seconds:(performance.now()-startedAt)/1000,body});
    return response;
  }
  for(const mode of ['timeout','cancel','file_timeout']) {
    const response = await apply(mode,mode==='cancel'?409:504);
    assert.equal((await response.json()).detail.code,mode==='cancel'?'planning_cancelled':'planning_timeout');
    await page.getByText(/Erro:.*plano ativo nao foi alterado/).filter({visible:true}).first().waitFor();
    const unchanged = await view();
    assert.deepEqual(unchanged.segments,before.segments);
    assert.deepEqual(unchanged.config,before.config);
    assert.equal(unchanged.plan_revision,1);
    const proof = await get('/api/__writer-proof__');
    assert.equal(proof.fault.hits,1);
    assert.deepEqual(proof.runtime,durableBefore.runtime);
    assert.equal(proof.payload_sha,durableBefore.payload_sha);
    assert.equal(proof.config_sha,durableBefore.config_sha);
    assert.deepEqual(proof.pending,[]);
    assert.equal((await get(`/api/data/replan-jobs/${jobId}`)).job.status,'ready');
    await shots(mode);
  }
  const applied = await apply('late_ack',200);
  await page.getByRole('button',{name:'Aplicar e guardar',exact:true}).waitFor({state:'detached'});
  const after = await view();
  assert.equal(after.plan_revision,2);
  assert.equal(after.config.machines.PRM019.oee,0.8);
  const proof = await get('/api/__writer-proof__');
  assert.equal(proof.fault.hits,1);
  report.durable = Object.fromEntries(['runtime','payload_sha','config_sha'].map(key=>[key,proof[key]]));
  assert.equal(proof.runtime.plan_revision,2);
  assert.equal(proof.payload.config.machines.PRM019.oee,0.8);
  assert.deepEqual(proof.payload.segments,candidate.segments);
  assert.deepEqual(proof.payload.lots,candidate.lots);
  assert.deepEqual(proof.payload.lots,after.lots);
  assert.deepEqual(proof.pending,[]);
  const repeated = await page.request.post(applied.url(),{data:applied.request().postDataJSON()});
  assert.equal(repeated.status(),200,await repeated.text());
  assert.deepEqual(await repeated.json(),await applied.json());
  assert.deepEqual((await get('/api/__writer-proof__')).runtime,proof.runtime);
  await page.reload();
  assert.deepEqual((await view()).segments,after.segments);
  await page.getByText('Configura\u00e7\u00e3o',{exact:true}).first().click();
  await page.getByLabel('OEE da m\u00e1quina PRM019',{exact:true}).waitFor();
  assert.equal(await page.getByLabel('OEE da m\u00e1quina PRM019',{exact:true}).inputValue(),'0.8');
  await shots('saved');
  assert.deepEqual(report.errors,[]);
  assert.equal(report.failures.length,3);
  report.status='passed';
  report.revision=after.plan_revision;
  }
} catch(error) {
  report.status='failed';report.error=String(error);report.stack=error.stack;
  report.body=(await page.locator('body').innerText()).slice(-9000);
  await shots('failure');process.exitCode=1;
} finally {
  await writeFile(`${prefix}${readOnly?'-restart':''}.json`,JSON.stringify(report,null,2));
  console.log(JSON.stringify({status:report.status,error:report.error,revision:report.revision,stages:report.stages.map(({mode,status,seconds})=>({mode,status,seconds}))}));
  await browser.close();
}

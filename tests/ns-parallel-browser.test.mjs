import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '..');
const origin = 'http://127.0.0.1:8797';
const python = process.env.NS_TEST_PYTHON || '/opt/homebrew/bin/python3';

test('parallel NS admission keeps RH replay pending and displays the current allocation', { timeout: 45000 }, async () => {
  const data = mkdtempSync(join(tmpdir(), 'lean-ns-parallel-browser-'));
  function runPython(source) {
    const result = spawnSync(python, ['-c', source], { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  }
  runPython(`import json,time
from pathlib import Path
from ns_queue.store import QueueStore
s=QueueStore(${JSON.stringify(data)})
s.initialize(json.loads(Path('ns_queue/manifest.json').read_text()),'rh-replay-fixture',{'scope':'server','capHours':20,'rentalStartedAt':time.time()-3*3600,'enforcement':'notify_only'})
s.mutate(lambda x:x.update(status='RUNNING',reason='running',phase='compile',startedAt=time.time(),controllerHeartbeat=time.time(),schedulingMode='parallel_replay',parallelAdmission={'kind':'rh_replay','runId':'rh-replay-fixture','recordedAt':time.time(),'snapshotPath':'rh/parallel-snapshot.json','snapshotSha256':'a'*64,'snapshotBytes':1234,'finalSuccess':False},resourceProfile={'cpus':60,'memoryBytes':220000000000,'mode':'rh_overlap'},rhEvidence={'persisted':False},rh={'id':'rh-replay-fixture','status':'running','phase':'kernel','compile':{'succeeded':175187,'total':175187,'failed':0},'metrics':{}}))`);
  let output = '';
  const server = spawn(python, ['-m', 'ns_queue.web', '--root', data, '--host', '127.0.0.1', '--port', '8797'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  server.stdout.on('data', chunk => { output += chunk; });
  server.stderr.on('data', chunk => { output += chunk; });
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      try { if ((await fetch(origin + '/healthz')).ok) { ready = true; break; } } catch {}
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(ready, output);
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.setDefaultTimeout(5000);
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (['error', 'warning'].includes(message.type())) errors.push(message.text()); });
    page.on('request', request => { if (request.method() !== 'GET') writes.push(request.method() + ' ' + request.url()); });
    await page.goto(origin + '/ns/');
    assert.equal(page.url(), origin + '/ns/');
    assert.match(await page.title(), /Navier/);
    await page.waitForFunction(() => document.querySelector('#status').textContent.includes('验证中'));
    assert.match(await page.locator('#status').innerText(), /并行/);
    assert.match(await page.locator('#banner').innerText(), /RH.*重放.*尚未/);
    assert.match(await page.locator('#rh-status').innerText(), /重放.*待完成/);
    assert.match(await page.locator('#rh-evidence').innerText(), /快照.*最终成功.*尚未/);
    assert.match(await page.locator('body').innerText(), /60 vCPU.*220 GB/);
    assert.doesNotMatch(await page.locator('body').innerText(), /严格串行|250 GB/);
    assert.equal(await page.getByRole('button', { name: /启动|暂停|恢复|管理员/ }).count(), 0);
    assert.equal(await page.locator('nextjs-portal,vite-error-overlay').count(), 0);
    const evidence = '/tmp/lean-ns-parallel-qa';
    mkdirSync(evidence, { recursive: true });
    await page.screenshot({ path: evidence + '/pending-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: evidence + '/pending-mobile.png', fullPage: true });
    await page.goto(origin + '/entry');
    assert.match(await page.title(), /Lean Observatory/);
    await page.waitForFunction(() => document.querySelector('#entry-rh-count').textContent === '175,187 / 175,187');
    assert.equal(await page.locator('#entry-rh-status').innerText(), '内核重放中');
    assert.equal(await page.locator('#entry-ns-status').innerText(), '并行运行中');
    assert.equal(await page.locator('footer,.entry-intro,.entry-utility,.eyebrow').count(), 0);
    await page.screenshot({ path: evidence + '/entry-pending-mobile.png', fullPage: true });
    runPython(`from ns_queue.store import QueueStore
QueueStore(${JSON.stringify(data)}).mutate(lambda x:x['rh'].update(phase='independent'))`);
    await page.waitForFunction(() => document.querySelector('#entry-rh-status').textContent === '运行中');
    await page.getByRole('link', { name: /进入 NS/ }).click();
    await page.waitForURL(origin + '/ns/');
    await page.waitForFunction(() => document.querySelector('#rh-status').textContent.includes('待完成'));
    assert.doesNotMatch(await page.locator('#rh-status').innerText(), /内核重放/);
    assert.match(await page.locator('#banner').innerText(), /RH 最终检查尚未完成/);
    runPython(`import time
from ns_queue.store import QueueStore
def promote(x):
 x['rh'].update(status='completed',phase='persist')
 x['rhEvidence'].update(persisted=True)
 x['resourceProfile'].update(memoryBytes=250000000000,mode='rh_complete')
 x.update(controllerHeartbeat=time.time())
QueueStore(${JSON.stringify(data)}).mutate(promote)`);
    await page.waitForFunction(() => document.querySelector('#resource-limit').textContent.includes('250 GB'));
    assert.match(await page.locator('#rh-evidence').innerText(), /最终.*成功.*归档/);
    assert.doesNotMatch(await page.locator('#rh-status').innerText(), /待完成/);
    assert.equal(await page.locator('#status').innerText(), '验证中');
    await page.screenshot({ path: evidence + '/promoted-mobile.png', fullPage: true });
    await page.goto(origin + '/entry');
    await page.waitForFunction(() => document.querySelector('#entry-ns-status').textContent === '运行中');
    assert.equal(await page.locator('#entry-rh-status').innerText(), '所列检查完成');
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ scope: 'Local parallel admission fixture; no real verification', browser: 'Playwright; Browser plugin not available', viewports: [1440, 390], screenshots: evidence, writes, errors, passed: true }));
  } finally {
    if (browser) await browser.close();
    if (server.exitCode === null && server.signalCode === null) {
      server.kill('SIGTERM');
      await new Promise(resolve => {
        const timeout = setTimeout(() => { server.kill('SIGKILL'); resolve(); }, 2000);
        server.once('exit', () => { clearTimeout(timeout); resolve(); });
      });
    }
    rmSync(data, { recursive: true, force: true });
  }
});

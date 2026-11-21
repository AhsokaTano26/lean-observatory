import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

const root = resolve(import.meta.dirname, '..');
const origin = 'http://127.0.0.1:8796';
const python = process.env.NS_TEST_PYTHON || '/opt/homebrew/bin/python3';
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

test('project entrance shows real RH progress, the queued successor and shared server clock', { timeout: 60000 }, async () => {
  const data = mkdtempSync(join(tmpdir(), 'lean-entry-browser-'));
  function runPython(source) {
    const result = spawnSync(python, ['-c', source], { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  }
  runPython(`import json,time
from pathlib import Path
from ns_queue.store import QueueStore
s=QueueStore(${JSON.stringify(data)})
s.initialize(json.loads(Path('ns_queue/manifest.json').read_text()),'rh-entry-fixture',{'scope':'server','capHours':20,'rentalStartedAt':time.time()-3*3600,'enforcement':'notify_only'})
s.mutate(lambda x:x.update(controllerHeartbeat=time.time(),rh={'id':'rh-entry-fixture','status':'running','phase':'compile','compile':{'succeeded':56985,'total':175187,'failed':0},'metrics':{}}))`);
  let output = '';
  const startServer = () => {
    const child = spawn(python, ['-m', 'ns_queue.web', '--root', data, '--host', '127.0.0.1', '--port', '8796'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { output += chunk; });
    return child;
  };
  let server = startServer();
  let browser;
  async function stopServer() {
    const child = server;
    if (child.exitCode !== null || child.signalCode !== null) return;
    child.kill('SIGTERM');
    await new Promise(resolve => {
      const timeout = setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 2000);
      child.once('exit', () => { clearTimeout(timeout); resolve(); });
    });
  }
  async function ready() {
    for (let attempt = 0; attempt < 60; attempt++) {
      try { if ((await fetch(origin + '/healthz')).ok) return; } catch {}
      await pause(100);
    }
    assert.fail(output);
  }
  try {
    await ready();
    const entrance = await fetch(origin + '/entry').catch(() => null);
    assert.equal(entrance?.status, 200, 'project entrance must be served at /entry');
    browser = await chromium.launch();
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    const errors = [], writes = [], failedResponses = [];
    let outage = false;
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      if (['error', 'warning'].includes(message.type()) && !(outage && /ERR_|network|Failed to load/i.test(message.text()))) errors.push(message.text());
    });
    page.on('request', request => { if (request.method() !== 'GET') writes.push(request.method() + ' ' + request.url()); });
    page.on('response', response => { if (response.status() >= 400) failedResponses.push(response.status() + ' ' + response.url()); });
    await page.goto(origin + '/entry');
    assert.match(await page.title(), /Lean Observatory/);
    await page.getByRole('heading', { name: 'Riemann Hypothesis' }).waitFor();
    await page.getByRole('heading', { name: 'Navier–Stokes Equations' }).waitFor();
    await page.waitForFunction(() => document.querySelector('#entry-rh-count').textContent === '56,985 / 175,187');
    assert.equal(await page.locator('#entry-rh-progress').innerText(), '32.5%');
    assert.equal(await page.locator('#entry-ns-status').innerText(), '排队中');
    assert.match(await page.locator('#entry-budget-cap').innerText(), /20\.00/);
    assert.match(await page.locator('#entry-budget-used').innerText(), /3\.00/);
    assert.match(await page.locator('#entry-budget-remaining').innerText(), /17\.00|16\.99/);
    assert.equal(await page.getByText('计划时长', { exact: true }).count(), 1);
    assert.equal(await page.locator('footer,.entry-intro,.entry-utility,.eyebrow').count(), 0);
    assert.equal(await page.getByRole('link', { name: /进入 RH/ }).getAttribute('href'), '/rh/');
    assert.equal(await page.getByRole('link', { name: /进入 NS/ }).getAttribute('href'), '/ns/');
    assert.equal(await page.getByRole('button', { name: /启动|暂停|恢复|管理员/ }).count(), 0);
    assert.equal(await page.locator('nextjs-portal,vite-error-overlay').count(), 0);
    const evidence = '/tmp/lean-entry-qa';
    mkdirSync(evidence, { recursive: true });
    await page.screenshot({ path: evidence + '/desktop-light.png', fullPage: true });
    await page.getByRole('button', { name: '切换深色主题' }).focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.waitForFunction(() => document.querySelector('#entry-connection').dataset.online === 'true');
    await page.screenshot({ path: evidence + '/desktop-dark.png', fullPage: true });
    for (const [width, height] of [[1280, 800], [768, 1024], [390, 844], [320, 640]]) {
      await page.setViewportSize({ width, height });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `horizontal overflow at ${width}`);
      const smallText = await page.evaluate(() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const findings = [];
        while (walker.nextNode()) {
          const node = walker.currentNode;
          const element = node.parentElement;
          if (!node.textContent.trim() || !element || !element.getClientRects().length) continue;
          const style = getComputedStyle(element);
          if (style.visibility === 'visible' && Number.parseFloat(style.fontSize) < 16) findings.push(node.textContent.trim());
        }
        return findings;
      });
      assert.deepEqual(smallText, [], `small visible text at ${width}`);
      await page.screenshot({ path: evidence + `/viewport-${width}.png`, fullPage: true });
    }
    runPython(`import time
from ns_queue.store import QueueStore
s=QueueStore(${JSON.stringify(data)})
s.mutate(lambda x:(x['rh']['compile'].update(succeeded=56986),x.update(controllerHeartbeat=time.time())))`);
    await page.waitForFunction(() => document.querySelector('#entry-rh-count').textContent === '56,986 / 175,187');
    await pause(2300);
    assert.equal(await page.locator('#entry-rh-count').innerText(), '56,986 / 175,187', 'compile count must not advance without a server update');
    runPython(`import time
from ns_queue.store import QueueStore
QueueStore(${JSON.stringify(data)}).mutate(lambda x:x.update(controllerHeartbeat=time.time()-120))`);
    await page.waitForFunction(() => document.querySelector('#entry-connection').textContent.includes('心跳待更新'));
    await page.screenshot({ path: evidence + '/stale-controller.png', fullPage: true });
    outage = true;
    await stopServer();
    await page.waitForFunction(() => document.querySelector('#entry-connection').textContent.includes('连接中断'));
    assert.equal(await page.locator('#entry-rh-count').innerText(), '56,986 / 175,187');
    server = startServer();
    await ready();
    runPython(`import time
from ns_queue.store import QueueStore
QueueStore(${JSON.stringify(data)}).mutate(lambda x:x.update(controllerHeartbeat=time.time()))`);
    await page.waitForFunction(() => document.querySelector('#entry-connection').dataset.online === 'true', null, { timeout: 15000 });
    outage = false;
    const nsLink = page.getByRole('link', { name: /进入 NS/ });
    await nsLink.focus();
    assert.equal(await nsLink.evaluate(element => element === document.activeElement), true);
    assert.notEqual(await nsLink.evaluate(element => getComputedStyle(element).outlineStyle), 'none');
    await page.keyboard.press('Enter');
    await page.waitForURL(origin + '/ns/');
    await page.getByRole('heading', { name: 'Navier–Stokes', exact: true }).waitFor();
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    assert.deepEqual(failedResponses, []);
    console.log(JSON.stringify({ scope: 'Local fixture only; no build or real verification run', browser: 'Playwright; Browser plugin not available', viewports: [1440, 1280, 768, 390, 320], screenshots: evidence, writes, errors, passed: true }));
  } finally {
    if (browser) await browser.close();
    await stopServer();
    rmSync(data, { recursive: true, force: true });
  }
});

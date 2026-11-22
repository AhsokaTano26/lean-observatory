import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setTimeout as pause } from 'node:timers/promises';
import { chromium } from 'playwright';

const repo = resolve(import.meta.dirname, '..');
const screenshots = '/tmp/lean-static-qa';
const origin = 'http://127.0.0.1:8894';

test('captured results browse offline and serve without application requests', { timeout: 60000 }, async () => {
  const fixture = process.env.STATIC_RESULTS_ROOT ? null : await mkdtemp(resolve(tmpdir(), 'lean-static-results-'));
  const root = fixture ?? resolve(process.env.STATIC_RESULTS_ROOT);
  let browser;
  let server;
  try {
    const snapshot = JSON.parse(await readFile(resolve(repo, 'result_snapshots/2026-11-22/results.json'), 'utf8'));
    if (fixture) {
      for (const name of ['index.html', 'app.css', 'app.js']) {
        await copyFile(resolve(repo, 'static_results', name), resolve(fixture, name));
      }
      await writeFile(resolve(fixture, 'data.js'), 'window.LEAN_OBSERVATORY_RESULTS = ' + JSON.stringify(snapshot) + ';');
      await mkdir(resolve(fixture, 'ns'));
      await copyFile(resolve(repo, 'reports/ns-final-verification.json'), resolve(fixture, 'ns/verification-result.json'));
    }
    assert.ok((await stat(resolve(root, 'index.html')).catch(() => null))?.isFile(), 'expected generated static results index.html');
    await mkdir(screenshots, { recursive: true });
    server = spawn('python3', ['-m', 'http.server', '8894', '--bind', '127.0.0.1', '--directory', root], {
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    let output = '';
    server.stderr.on('data', chunk => { output += chunk; });
    let ready = false;
    for (let attempt = 0; attempt < 50 && server.exitCode === null; attempt++) {
      ready = await fetch(origin + '/index.html').then(response => response.ok).catch(() => false);
      if (ready) break;
      await pause(100);
    }
    assert.ok(ready, output);
    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1440, height: 950 }, colorScheme: 'light' });
    page.setDefaultTimeout(5000);
    const unexpected = [];
    page.on('pageerror', error => unexpected.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' || message.type() === 'warning') unexpected.push(message.text());
    });
    page.on('websocket', socket => unexpected.push(socket.url()));
    page.on('response', response => {
      if (response.status() >= 400) unexpected.push(response.status() + ' ' + response.url());
    });
    await page.route('**/*', route => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET' || ![origin, 'null'].includes(url.origin)
          || ['fetch', 'xhr', 'eventsource'].includes(request.resourceType())) {
        unexpected.push(request.method() + ' ' + request.url());
        return route.abort();
      }
      return route.continue();
    });

    await page.goto(origin + '/index.html');
    assert.match(await page.title(), /Lean Observatory/);
    const results = page.getByRole('region', { name: '项目详情' });
    await results.getByRole('heading', { name: '黎曼猜想' }).waitFor();
    await results.getByText('本机重放已暂停', { exact: true }).waitFor();
    await results.getByText(/175,187/).first().waitFor();
    await results.getByText('5 / 6', { exact: true }).waitFor();
    await results.getByRole('link', { name: /Andrew Sutherland/ }).waitFor();
    await page.screenshot({ path: screenshots + '/desktop-light.png' });

    await page.getByRole('button', { name: '切换深色主题' }).click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.getByRole('navigation', { name: '切换项目' }).getByRole('button', { name: 'NS' }).click();
    await results.getByRole('heading', { name: 'Navier–Stokes', exact: true }).waitFor();
    await results.getByText('机器检查通过', { exact: true }).waitFor();
    await results.getByText('7 / 7', { exact: true }).waitFor();
    await results.getByText(/2,659/).first().waitFor();
    await results.getByText(/人工数学语义复核未进行/).waitFor();

    const search = page.getByRole('searchbox', { name: '搜索日志' });
    const rows = page.locator('#log-rows .log-row');
    const count = await rows.count();
    assert.ok(count > 0 && count <= 300);
    await search.fill('comparator');
    assert.ok(await rows.count() > 0 && await rows.count() < count);
    for (const value of await rows.allTextContents()) assert.match(value, /comparator/i);
    await search.fill('no-log-matches-lean-static-test');
    await page.getByText('没有符合条件的日志', { exact: true }).waitFor();
    assert.equal(await rows.count(), 0);
    await search.clear();
    const logStage = page.getByLabel('日志阶段');
    await logStage.selectOption('independent');
    assert.ok(await rows.count() > 0);
    for (const value of await rows.locator('span').allTextContents()) assert.match(value, /^independent/);
    await logStage.selectOption('');

    const report = page.getByRole('link', { name: '最终验证报告', exact: true });
    assert.equal(await report.getAttribute('href'), './ns/verification-result.json');
    const downloadEvent = page.waitForEvent('download');
    await report.click();
    const download = await downloadEvent;
    const bytes = await readFile(await download.path());
    const expectedReport = snapshot.projects.find(project => project.id === 'ns').downloads
      .find(file => file.path === 'ns/verification-result.json');
    assert.equal(bytes.byteLength, expectedReport.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), expectedReport.sha256);
    assert.equal(JSON.parse(bytes).proofAccepted, false);

    await results.evaluate(element => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({ path: screenshots + '/desktop-dark.png' });
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'overflow at ' + width);
      await results.getByRole('heading', { name: '定理审计' }).evaluate(element => element.scrollIntoView({ block: 'start' }));
      await page.screenshot({ path: screenshots + '/mobile-' + width + '.png' });
    }

    server.kill();
    await once(server, 'exit');
    await page.goto(pathToFileURL(resolve(root, 'index.html')).href);
    await results.getByText('本机重放已暂停', { exact: true }).waitFor();
    const localReport = results.getByRole('link', { name: '完整日志', exact: true });
    assert.match(await localReport.getAttribute('href'), /^\.\/downloads\//);
    assert.deepEqual(unexpected, []);
    console.log('Validated ' + (fixture ? 'portable fixture' : 'generated archive') + ' via HTTP and file://');
  } finally {
    if (browser) await browser.close();
    if (server && server.exitCode === null && server.signalCode === null) {
      server.kill();
      await once(server, 'exit');
    }
    if (fixture) await rm(fixture, { recursive: true, force: true });
  }
});

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

const root=resolve(import.meta.dirname,'..');
test('NS queued page: desktop, mobile, theme, logs, readonly requests and reconnect',async()=>{
 const data=mkdtempSync(join(tmpdir(),'lean-ns-browser-'));
 const python=process.env.NS_TEST_PYTHON||'/opt/homebrew/bin/python3';
 const init=spawnSync(python,['-m','ns_queue.control','--root',data,'init','--budget','0'],{cwd:root,encoding:'utf8'});
 assert.equal(init.status,0,init.stderr);
 const seed=spawnSync(python,['-c',`from ns_queue.store import QueueStore;s=QueueStore(${JSON.stringify(data)});s.log('scheduler','Waiting for RH; NS budget is zero');s.mutate(lambda x:x.update(controllerHeartbeat=__import__('time').time()))`],{cwd:root,encoding:'utf8'});
 assert.equal(seed.status,0,seed.stderr);
 let output='';
 const start=()=>{const child=spawn(python,['-m','ns_queue.web','--root',data,'--host','127.0.0.1','--port','8793'],{cwd:root,stdio:['ignore','pipe','pipe']});child.stdout.on('data',x=>output+=x);child.stderr.on('data',x=>output+=x);return child;};
 let server=start();
 let browser;
 try{
  let ready=false;
  for(let i=0;i<60;i++){try{const r=await fetch('http://127.0.0.1:8793/healthz');if(r.ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,100));}
  assert.ok(ready,output);
  browser=await chromium.launch();const context=await browser.newContext({viewport:{width:1440,height:1100}});const page=await context.newPage();
  const errors=[],writes=[];let expectedOutage=false;
  page.on('pageerror',x=>errors.push(x.message));page.on('console',x=>{if(['error','warning'].includes(x.type())&&!(expectedOutage&&/ERR_|Failed to load resource|network/i.test(x.text())))errors.push(x.text());});
  page.on('request',r=>{if(r.method()!=='GET')writes.push(r.method()+' '+r.url());});
  await page.goto('http://127.0.0.1:8793/ns/');assert.match(await page.title(),/Navier/);
  await page.getByRole('heading',{name:'Navier–Stokes',exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('#status').textContent==='排队中');
  assert.match(await page.locator('#banner').innerText(),/RH 优先/);
  assert.equal(await page.locator('#budget').innerText(),'$0.00');assert.equal(await page.locator('#cost').innerText(),'$0.00');
  assert.equal(await page.getByRole('button',{name:/启动|暂停|恢复|管理员/}).count(),0);
  assert.equal(await page.locator('nextjs-portal,vite-error-overlay').count(),0);
  const evidence='/tmp/lean-observatory-ns-ui-qa';mkdirSync(evidence,{recursive:true});
  await page.screenshot({path:evidence+'/desktop-light.png',fullPage:true});
  await page.getByRole('button',{name:'切换深色主题'}).click();await page.reload();
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  await page.getByRole('searchbox',{name:'筛选',exact:true}).fill('never-match');
  assert.match(await page.locator('#logs').innerText(),/没有匹配日志/);
  await page.getByRole('searchbox',{name:'筛选',exact:true}).fill('');
  await page.screenshot({path:evidence+'/desktop-dark.png',fullPage:true});
  for(const width of [390,320]){
   await page.setViewportSize({width,height:844});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`overflow at ${width}`);
   await page.screenshot({path:evidence+`/mobile-${width}.png`,fullPage:true});
  }
  expectedOutage=true;server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));
  await page.waitForFunction(()=>document.querySelector('#connection').textContent.includes('自动重连'));
  server=start();
  await page.waitForFunction(()=>document.querySelector('#connection').dataset.online==='true',{timeout:15000});
  expectedOutage=false;
  assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({scope:'Local NS queued fixture only',browser:'Playwright; Browser plugin not available',viewports:[1440,390,320],writes,errors,passed:true}));
 }finally{
  if(browser)await browser.close();server.kill('SIGTERM');await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},2000).unref();});rmSync(data,{recursive:true,force:true});
 }
});

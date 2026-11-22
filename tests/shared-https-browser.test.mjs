import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {mkdtempSync,chmodSync,mkdirSync,writeFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve,join} from 'node:path';
import {chromium} from 'playwright';
const root=resolve(import.meta.dirname,'..');
test('Shared HTTPS: root entrance, RH/NS isolation, SSE, assets, downloads and HTTP redirect',{timeout:180000},async()=>{
 const fixture=mkdtempSync(join(tmpdir(),'lean-proxy-'));const env={...process.env,PROXY_FIXTURE_ROOT:fixture};
 const args=['compose','-p','lean-shared-https-test','-f','tests/fixtures/shared-https/compose.yaml'];
 const compose=(more)=>execFileSync('docker',[...args,...more],{cwd:root,env,encoding:'utf8',stdio:['ignore','pipe','pipe']});
 const python=process.env.NS_TEST_PYTHON||'/opt/homebrew/bin/python3';let browser;
 try{
  mkdirSync(join(fixture,'rh/api/state'),{recursive:true});mkdirSync(join(fixture,'rh/assets'),{recursive:true});
  writeFileSync(join(fixture,'rh/index.html'),'<html><title>RH original</title><h1>RH ORIGINAL PAGE</h1><script src="/assets/rh.js"></script></html>');
  writeFileSync(join(fixture,'rh/assets/rh.js'),'window.RH_ORIGINAL=true;');writeFileSync(join(fixture,'rh/api/state/index.html'),'{"project":"RH"}');
  const cert=join(fixture,'certs/live/lean.tano.asia');mkdirSync(cert,{recursive:true});
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',join(cert,'privkey.pem'),'-out',join(cert,'fullchain.pem'),'-subj','/CN=localhost'],{stdio:'ignore'});
  execFileSync(python,['-c',`import importlib.util,json,os,time\nfrom pathlib import Path\nfrom ns_queue.store import QueueStore\nfrom ns_queue.budget import normalize\nr=Path(os.environ['PROXY_FIXTURE_ROOT']);s=QueueStore(r/'data');s.initialize(json.loads(Path('ns_queue/manifest.json').read_text()),'20565ace60c2',{'capHours':0});s.mutate(lambda x:x.update(budget=normalize({'scope':'server','enforcement':'notify_only','capHours':20,'rentalStartedAt':time.time()-10800}),controllerHeartbeat=time.time(),rh={'id':'20565ace60c2','status':'running','phase':'compile','compile':{'succeeded':56985,'total':175187,'failed':0}}));s.log('scheduler','NS waiting for RH');[(p.chmod(0o755 if p.is_dir() else 0o644)) for p in (r/'data').rglob('*')];(r/'data').chmod(0o755)\nspec=importlib.util.spec_from_file_location('p','deploy/ns/activate_proxy.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);(r/'nginx.conf').write_text(m.render(Path('deploy/nginx-tls.conf').read_text()))`],{cwd:root,env});
  chmodSync(join(cert,'privkey.pem'),0o644); // Ephemeral self-signed fixture only; no production keys.
  compose(['run','--rm','validator']);
  compose(['up','-d','--build']);
  browser=await chromium.launch();const context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1440,height:1000}});const page=await context.newPage();const errors=[],writes=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()!=='GET')writes.push(r.method());});
  let ready=false;for(let i=0;i<80;i++){try{const response=await page.request.get('https://127.0.0.1:9444/ns/healthz');const rhResponse=await page.request.get('https://127.0.0.1:9444/rh/');if(response.ok()&&rhResponse.ok()&&(await rhResponse.text()).includes('RH ORIGINAL PAGE')){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,200));}assert.ok(ready);
  const redirect=execFileSync('curl',['-sS','-o','/dev/null','-w','%{redirect_url}','-H','Host: lean.tano.asia','http://127.0.0.1:9080/rh/'],{encoding:'utf8'});assert.equal(redirect,'https://lean.tano.asia/rh/');
  await page.goto('https://127.0.0.1:9444/');await page.waitForFunction(()=>document.querySelector('#entry-rh-count')?.textContent.includes('56,985'));
  const rhLink=page.locator('a[href="/rh/"]').first(),nsLink=page.locator('a[href="/ns/"]').first();assert.ok(await rhLink.count());assert.ok(await nsLink.count());
  await rhLink.click();await page.getByRole('heading',{name:'RH ORIGINAL PAGE'}).waitFor();assert.equal(await page.evaluate(()=>window.RH_ORIGINAL),true);
  const rh=await page.request.get('https://127.0.0.1:9444/api/state/');assert.deepEqual(await rh.json(),{project:'RH'});
  await page.goto('https://127.0.0.1:9444/');await page.locator('a[href="/ns/"]').first().click();await page.waitForFunction(()=>document.querySelector('#connection')?.textContent.includes('SSE 已连接'));
  assert.equal(await page.locator('#status').textContent(),'排队中');assert.match(await page.locator('#budget').textContent(),/20.00/);
  const ns=await page.request.get('https://127.0.0.1:9444/ns/api/state');assert.equal((await ns.json()).queue.status,'QUEUED');
  const report=await page.request.get('https://127.0.0.1:9444/ns/api/report.json');assert.match(report.headers()['content-disposition'],/attachment/);
  const logs=await page.request.get('https://127.0.0.1:9444/ns/api/logs/export');assert.match(await logs.text(),/NS waiting for RH/);
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(JSON.stringify({localNginx:true,routes:['/','/rh/','/ns/'],legacyRhApiUnchanged:true,nsSSE:true,downloads:true,httpRedirect:true,writes,errors}));
 }finally{
  if(browser)await browser.close();try{compose(['down','--timeout','2','--remove-orphans']);}catch{}rmSync(fixture,{recursive:true,force:true});
 }
});

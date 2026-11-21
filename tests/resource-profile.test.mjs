import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
test('Both RH and NS profiles reserve four host vCPUs and use 250 decimal GB without swap',()=>{
 const env={...process.env,WORKER_CPUS:'60',WORKER_CPUSET:'4-63',WORKER_MEMORY:'250000000000',NS_CONTAINER_NAME:'lean-observatory-ns-ns-f9e8bc5b38b6',NS_RUN_ID:'ns-f9e8bc5b38b6',NS_SOURCE_COMMIT:'f9e8bc5b38b6e212696e8a30e3e91517af887bbd'};
 for(const [file,service] of [['compose.yaml','worker'],['compose.ns-worker.yaml','ns-worker']]){
  const config=JSON.parse(execFileSync('docker',['compose','--profile','*','-f',file,'config','--format','json'],{cwd:resolve(import.meta.dirname,'..'),env,encoding:'utf8'}));
  if(service==='ns-worker')assert.equal(config.services['ns-worker'].ports,undefined);
  const s=config.services[service];assert.equal(Number(s.cpus),60);assert.equal(s.cpuset,'4-63');
  assert.equal(Number(s.mem_limit),250000000000);assert.equal(Number(s.memswap_limit),250000000000);
 }
 const web=JSON.parse(execFileSync('docker',['compose','-f','compose.ns.yaml','config','--format','json'],{cwd:resolve(import.meta.dirname,'..'),env,encoding:'utf8'}));
 assert.ok(!web.services.nginx.ports?.length,'NS backend must not publish9443');

});

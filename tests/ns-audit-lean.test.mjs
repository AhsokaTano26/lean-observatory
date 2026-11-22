import test from 'node:test';import assert from 'node:assert/strict';import {execFileSync} from 'node:child_process';import {resolve} from 'node:path';
test('Generated standalone audit diagnostic compiles and reports actual axioms in real Lean',{timeout:120000},()=>{
 const cwd=resolve(import.meta.dirname,'..');const args=['compose','-p','lean-ns-audit-native-test','-f','tests/fixtures/ns-audit/compose.yaml'];
 try{const output=execFileSync('docker',[...args,'run','--rm','lean-audit'],{cwd,encoding:'utf8'});assert.match(output,/"actualLeanExitCode": 0/);assert.match(output,/"diagnosticTargets": 2/);}finally{execFileSync('docker',[...args,'down','--remove-orphans'],{cwd,stdio:'ignore'});}
});

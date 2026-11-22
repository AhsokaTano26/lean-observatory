import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
test('Real restricted Linux supervisor prepares and reopens UID10002 directories without FOWNER',{timeout:120000},()=>{
 const cwd=resolve(import.meta.dirname,'..');const args=['compose','-p','lean-ns-supervisor-test','-f','tests/fixtures/ns-supervisor/compose.yaml'];
 try{const output=execFileSync('docker',[...args,'run','--rm','permissions'],{cwd,encoding:'utf8'});assert.match(output,/restart succeeded without CAP_FOWNER/);}finally{execFileSync('docker',[...args,'down','--remove-orphans'],{cwd,stdio:'ignore'});}
});

test('Real seccomp keeps checker AF_UNIX denial while permitting dependency resolver sockets',{timeout:120000},()=>{
 const cwd=resolve(import.meta.dirname,'..');const args=['compose','-p','lean-ns-socket-test','-f','tests/fixtures/ns-supervisor/compose.yaml'];
 try{const output=execFileSync('docker',[...args,'run','--rm','sockets'],{cwd,encoding:'utf8'});assert.match(output,/inherited filters deny AF_UNIX/);}finally{execFileSync('docker',[...args,'down','--remove-orphans'],{cwd,stdio:'ignore'});}
});

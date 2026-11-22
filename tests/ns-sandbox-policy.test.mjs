import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

test('Real Linux layered sandbox accepts measured guards and rejects missing Landlock or AF_UNIX seccomp', {timeout: 120000}, () => {
  const cwd = resolve(import.meta.dirname, '..');
  const args = ['compose', '-p', 'lean-ns-policy-test', '-f', 'tests/fixtures/ns-sandbox-policy/compose.yaml'];
  try {
    const output = execFileSync('docker', [...args, 'run', '--rm', 'scope'], {
      cwd, encoding: 'utf8', timeout: 110000,
    });
    const evidence = JSON.parse(output.trim().split('\n').at(-1));
    assert.equal(evidence.realLinux, true);
    assert.equal(evidence.realLandlock, true);
    assert.ok(evidence.nativeLandlockAbi >= 4);
    assert.equal(evidence.cases.layered.accepted, true);
    assert.equal(evidence.cases.noLandlock.accepted, false);
    assert.equal(evidence.cases.noLandlock.filesystemWriteDenied, false);
    assert.equal(evidence.cases.noUnixFilter.accepted, false);
    assert.equal(evidence.cases.noUnixFilter.unixSocketDenied, false);
    assert.equal(evidence.cases.noUnixFilter.unixSocketpairDenied, false);
  } finally {
    execFileSync('docker', [...args, 'down', '--remove-orphans'], {cwd, stdio: 'ignore'});
  }
});

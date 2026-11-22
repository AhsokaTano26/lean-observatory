import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';

test('REPLAY with cached v4.33 API adaptation checks real Lean proofs and quotient primitives', {timeout: 120000}, () => {
  const cwd = resolve(import.meta.dirname, '..');
  const args = ['compose', '-p', 'lean-ns-replay-test', '-f', 'tests/fixtures/ns-audit/compose-replay.yaml'];
  try {
    const output = execFileSync('docker', [...args, 'run', '--rm', 'lean-replay'], {cwd, encoding: 'utf8'});
    const evidence = JSON.parse(output.trim().split('\n').at(-1));
    assert.equal(evidence.fixture, true);
    assert.equal(evidence.realLeanReplay, true);
    assert.equal(evidence.runtimeCompatibility, 'v4.33.1 Lean.Environment.replay');
    assert.deepEqual(Object.keys(evidence.cases).sort(), [
      'valid-proof', 'invalid-proof', 'valid-quotient', 'tampered-Quot',
      'tampered-Quot.mk', 'tampered-Quot.lift', 'tampered-Quot.ind', 'missing-export',
    ].sort());
    for (const [name, code] of Object.entries(evidence.cases)) {
      assert.equal(code === 0, name === 'valid-proof' || name === 'valid-quotient', name);
    }
  } finally {
    execFileSync('docker', [...args, 'down', '--remove-orphans'], {cwd, stdio: 'ignore'});
  }
});

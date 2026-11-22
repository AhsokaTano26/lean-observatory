"""Run the production REPLAY template through the cached real Lean kernel.

Export.Parse supplies explicit tiny fixture declarations instead of parsing a real
NS export. Comparator.Compare mirrors only the pinned module's BEq instances.
The sole v4.33.1 API adaptation calls its official Lean.Environment.replay.
Neither fixture replaces kernel checking or asserts NS acceptance.
"""
import json
from pathlib import Path
import subprocess

from ns_queue.ns_worker import REPLAY


TOOLS = '/home/lean/.elan/toolchains/leanprover--lean4---v4.33.1'
ROOT = Path('/sandbox/tmp')

PARSE_FIXTURE = r'''import Lean
-- The cached v4.33.1 Lean umbrella omits this real kernel replay module.
import Lean.Replay
import Std.Data.HashMap

namespace Export

structure ExportedEnv where
  constMap : Std.HashMap Lean.Name Lean.ConstantInfo

private def proofFixture (invalid : Bool) : ExportedEnv := Id.run do
  let p : Lean.Expr := .const `ReplayFixture.p []
  let assumption : Lean.ConstantInfo := .axiomInfo {
    name := `ReplayFixture.p, levelParams := [], type := .sort .zero, isUnsafe := false
  }
  let proof : Lean.ConstantInfo := .thmInfo {
    name := `ReplayFixture.idP, levelParams := [],
    type := .forallE `x p p .default,
    value := if invalid then .sort .zero else .lam `x p (.bvar 0) .default,
    all := [`ReplayFixture.idP]
  }
  return { constMap := ({} : Std.HashMap Lean.Name Lean.ConstantInfo)
    |>.insert assumption.name assumption |>.insert proof.name proof }

private def quotientFixture (tamper : Option Lean.Name) : IO ExportedEnv := do
  Lean.initSearchPath (← Lean.findSysroot)
  let imported ← Lean.importModules #[{ module := `Init }] {}
  let mut constants : Std.HashMap Lean.Name Lean.ConstantInfo := {}
  -- Eq and its constructor are the kernel prerequisites for quotDecl.
  -- All quotient values come from this runtime's actual Init environment.
  for name in [`Eq, `Eq.refl, `Eq.rec, `Quot, `Quot.mk, `Quot.lift, `Quot.ind] do
    let some info := imported.find? name
      | throw <| IO.userError s!"missing canonical fixture declaration: {name}"
    let info ← if tamper == some name then
      match info with
      | .quotInfo value => pure <| .quotInfo {
          value with levelParams := [`ReplayFixture.changedUniverse]
        }
      | _ => throw <| IO.userError "fixture tamper target is not a quotient primitive"
    else pure info
    constants := constants.insert name info
  return { constMap := constants }

def parseStream (stream : IO.FS.Stream) : IO ExportedEnv := do
  match (← stream.getLine).trimAscii.toString with
  | "valid-proof" => return proofFixture false
  | "invalid-proof" => return proofFixture true
  | "valid-quotient" => quotientFixture none
  | "tampered-Quot" => quotientFixture (some `Quot)
  | "tampered-Quot.mk" => quotientFixture (some `Quot.mk)
  | "tampered-Quot.lift" => quotientFixture (some `Quot.lift)
  | "tampered-Quot.ind" => quotientFixture (some `Quot.ind)
  | _ => throw <| IO.userError "unknown export fixture"

end Export
'''

COMPARE_FIXTURE = r'''/-
Test-only module boundary for the pinned Comparator.Compare import.
These four deriving statements are copied from Comparator/Compare.lean at
19e111e2141cf333c7daff0f64c5f24acc91dd2e (Lean FRO, LLC, Apache-2.0;
author Henrik Böving). No comparator or proof-checking implementation is mocked.
-/
import Export.Parse

namespace Comparator.Compare

deriving instance BEq for Lean.QuotKind
deriving instance BEq for Lean.QuotVal
deriving instance BEq for Lean.InductiveVal
deriving instance BEq for Lean.ConstantInfo

end Comparator.Compare
'''


def lean(*arguments):
    # Same private proc mount, toolchain, and checker UID as the audit fixture.
    command = [
        'unshare', '--mount', '--pid', '--fork', '--kill-child=SIGKILL',
        '--mount-proc=/sandbox/proc', 'chroot', '--userspec=10002:10002',
        '/sandbox', '/usr/bin/env', '-i', 'HOME=/tmp', 'LEAN_PATH=/tmp',
        'PATH=' + TOOLS + '/bin:/usr/bin:/bin',
        'LD_LIBRARY_PATH=' + TOOLS + '/lib/lean:' + TOOLS + '/lib',
        TOOLS + '/bin/lean', '--root=/tmp', *arguments,
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    print(result.stdout, end='')
    print(result.stderr, end='')
    return result


def compile_module(relative, source):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    # The root supervisor writes fixtures; the unprivileged checker emits .olean.
    path.parent.chmod(0o777)
    path.write_text(source)
    result = lean('-o', '/tmp/' + str(Path(relative).with_suffix('.olean')),
                  '/tmp/' + relative)
    assert result.returncode == 0, 'real Lean failed to compile fixture module: ' + relative


compile_module('Export/Parse.lean', PARSE_FIXTURE)
compile_module('Comparator/Compare.lean', COMPARE_FIXTURE)
# v4.34 moved the replay API to Kernel.Environment. Adapt only that call for the
# cached v4.33.1 runtime, retaining the same fresh empty environment and real
# native kernel checks. Unwrap its result so the quotient guard reads the same
# kernel environment (including generated quotient primitives) as production.
# The exact production v4.34 template is checked separately.
native_call = 'let checked ← env.toKernelEnv.replay constants'
assert REPLAY.count(native_call) == 1, 'production replay call changed'
local_replay = REPLAY.replace(native_call,
    'let checked ← Lean.Environment.replay constants env\n  let checked := checked.toKernelEnv')
(ROOT / 'Replay.lean').write_text(local_replay)
compiled = lean('/tmp/Replay.lean')
assert compiled.returncode == 0, 'REPLAY template with v4.33.1 API adaptation failed to compile in real Lean'

cases = {}
for flag in ['valid-proof', 'invalid-proof', 'valid-quotient', 'tampered-Quot',
             'tampered-Quot.mk', 'tampered-Quot.lift', 'tampered-Quot.ind']:
    (ROOT / 'export.fixture').write_text(flag + '\n')
    result = lean('--run', '/tmp/Replay.lean', '/tmp/export.fixture')
    output = result.stdout + result.stderr
    cases[flag] = result.returncode
    if flag in {'valid-proof', 'valid-quotient'}:
        assert result.returncode == 0, 'kernel rejected valid fixture: ' + flag
        assert result.stdout.splitlines() == ['NS_KERNEL_OK'], result.stdout
    else:
        assert result.returncode != 0, 'invalid fixture was accepted: ' + flag
        assert 'NS_KERNEL_OK' not in output, 'invalid fixture emitted acceptance: ' + flag
        if flag == 'invalid-proof':
            assert "while replaying declaration 'ReplayFixture.idP'" in output, output
        else:
            assert 'quotient primitive mismatch' in output, output

missing = lean('--run', '/tmp/Replay.lean')
assert missing.returncode != 0, 'empty arguments were accepted'
assert 'missing export' in missing.stdout + missing.stderr
assert 'NS_KERNEL_OK' not in missing.stdout + missing.stderr
cases['missing-export'] = missing.returncode
print(json.dumps({'fixture': True, 'realLeanReplay': True,
                  'runtimeCompatibility': 'v4.33.1 Lean.Environment.replay', 'cases': cases}))

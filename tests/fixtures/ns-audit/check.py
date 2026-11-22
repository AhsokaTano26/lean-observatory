"""Exercise the generated diagnostic command against a real cached Lean runtime.

The tiny True theorems are test fixtures; no NS proof acceptance is asserted.
The production v4.34.0-rc2 helper is additionally checked against the real project.
"""
import json,subprocess
from pathlib import Path
from ns_queue.ns_worker import audit_script,load_manifest,parse_audit
names=load_manifest()['theorems'];generated=audit_script(names)
fixture='import Lean\nnamespace NavierStokes.Comparator\n'
for name in names:
    fixture+='theorem '+name.rsplit('.',1)[1]+' : True := Eq.mp (propext (Iff.rfl : True ↔ True)) True.intro\n'
fixture+='end NavierStokes.Comparator\n'+generated[generated.index('run_cmd do'):]
tools='/home/lean/.elan/toolchains/leanprover--lean4---v4.33.1'
if Path('/sandbox').exists():
    path=Path('/sandbox/tmp/AuditDiagnosticFixture.lean');path.write_text(fixture)
    cmd=['unshare','--mount','--pid','--fork','--kill-child=SIGKILL','--mount-proc=/sandbox/proc',
        'chroot','--userspec=10002:10002','/sandbox','/usr/bin/env','-i','HOME=/tmp',
        'LD_LIBRARY_PATH='+tools+'/lib/lean:'+tools+'/lib',tools+'/bin/lean','/tmp/AuditDiagnosticFixture.lean']
else:
    path=Path('/tmp/AuditDiagnosticFixture.lean');path.write_text(fixture)
    cmd=[tools+'/bin/lean',str(path)]
result=subprocess.run(cmd,capture_output=True,text=True);print(result.stdout,end='');print(result.stderr,end='')
assert result.returncode==0, 'generated standalone audit command failed in real Lean'
rows=parse_audit(result.stdout,names)
assert all(row['dependencies']==['propext'] for row in rows),rows
print(json.dumps({'fixture':True,'diagnosticTargets':len(rows),'actualLeanExitCode':result.returncode}))

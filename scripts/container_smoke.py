"""Inside worker image only: real pinned Lean + isolation + fresh kernel fixture."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from backend.sandbox import prepare
from backend.store import Store
from backend.runner import CommandRunner

class FixtureRunner(CommandRunner):
    def run(self,*args,**kwargs):
        try: return super().run(*args,**kwargs)
        except Exception:
            record=self.store.raw(self.run_id)['commands'][-1]
            print((self.root/record['logFile']).read_text(),flush=True)
            raise

with tempfile.TemporaryDirectory() as d:
    root=Path(d); store=Store(root/'evidence');run=store.create('real',jobs=2);rid=run['id']
    source=root/'source';source.mkdir()
    (source/'Main.lean').write_text('theorem smoke : True := True.intro\n')
    project=prepare('/sandbox',rid,source)
    runner=FixtureRunner(store,rid)
    version=runner.run(['lean','-j1','--version'],project,'dependencies',sandbox=True)
    assert 'version 4.33.1' in version, version
    runner.run(['lean','-j1','-o','.lake/Main.olean','Main.lean'],project,'compile',sandbox=True)
    runner.run(['env','LEAN_PATH=.lake','leanchecker','--fresh','Main'],project,'replay',sandbox=True,timeout=120)
    probes='''
import os
from pathlib import Path
assert os.getuid()==10002
try: os.rename(os.environ['HOME'],os.environ['HOME']+'-replaced')
except PermissionError: pass
else: raise RuntimeError('Builder could replace HOME entry')
assert os.getenv('ADMIN_TOKEN') is None
import socket
assert not [line for line in Path('/proc/net/route').read_text().splitlines()[1:] if line.strip()]
try: socket.create_connection(('198.51.100.1',80),timeout=.25)
except OSError: pass
else: raise RuntimeError('Offline namespace unexpectedly has an external route')
assert int(next(x for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('CapEff:')).split()[1],16)==0
assert not Path('/data').exists()
assert not Path('/app').exists()
for target in [Path('Main.lean'),Path('/home/lean/.elan/toolchains/leanprover--lean4---v4.33.1/bin/lean')]:
    try:
        f=target.open('ab');f.close()
    except PermissionError: pass
    else: raise RuntimeError('Sandbox write escaped: '+str(target))
Path('.lake/isolation-write-probe').write_text('build output is writable')
print('sandbox isolation passed')
'''
    result=runner.run(['python3','-c',probes],project,'audit',sandbox=True)
    assert 'sandbox isolation passed' in result
    detached = "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',\"import time;f=open('.lake/detached-heartbeat','a');\\nwhile True:f.write('x');f.flush();time.sleep(.05)\"],start_new_session=True);time.sleep(.4)"
    runner.run(['python3','-c',detached],project,'compile',sandbox=True)
    heartbeat=project/'.lake/detached-heartbeat'
    before=heartbeat.read_bytes();time.sleep(.5)
    assert before==heartbeat.read_bytes(),'Detached descendant escaped PID namespace'
    print(json.dumps(dict(pinnedLean=version,kernelFixture='passed',filesystemIsolation='passed',detachedCleanup='passed',proofReproduction='NOT_RUN'),indent=2))
    shutil.rmtree(project.parent)

# Hard-kill a controller while its entire command group is stopped.
with tempfile.TemporaryDirectory() as d:
    root=Path(d); (root/'pid').touch()
    code="""
import sys
from pathlib import Path
from backend.store import Store
from backend.runner import CommandRunner
s=Store(Path(sys.argv[1]));r=s.create('real')
CommandRunner(s,r['id']).run([sys.executable,'-c',"import os,time;open('child.pid','w').write(str(os.getpid()));time.sleep(90)"],Path(sys.argv[1]),'compile')
"""
    process=subprocess.Popen([sys.executable,'-c',code,d],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    deadline=time.time()+10
    while not (root/'child.pid').exists() and time.time()<deadline: time.sleep(.05)
    assert (root/'child.pid').exists()
    store=Store(root); child=int((root/'child.pid').read_text()); group=store.raw()['commands'][-1]['pgid']
    os.killpg(group,19);process.kill();process.communicate(timeout=5)
    deadline=time.time()+8
    while time.time()<deadline:
        stat=Path(f'/proc/{child}/stat')
        if not stat.exists() or stat.read_text().rsplit(')',1)[1].split()[0]=='Z': break
        time.sleep(.1)
    else:
        os.killpg(group,9);raise AssertionError('Stopped child survived parent death')
    print('parent-death guard passed (including stopped process group)')

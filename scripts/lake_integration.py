"""Actual pipeline on a tiny synthetic submission, never the original proof.

Run inside the verification worker image. Uses the unmodified original TOML /
locked manifest, a targeted official Mathlib cache, actual Lake and fresh checker.
"""
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import threading
import time
import tomllib
from backend.model import THEOREMS
from backend.pipeline import Pipeline,Submission
from backend.store import Store


with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);source=root/'input'/'lean';source.mkdir(parents=True)
    fixture=Path('/fixture')
    for name in ['lakefile.toml','lake-manifest.json']:shutil.copy2(fixture/name,source/name)
    (source/'lean-toolchain').write_text('leanprover/lean4:v4.33.1\n')
    src=source/'src';(src/'Lemmata').mkdir(parents=True)
    # Original default targets include globs whose directories must exist even
    # when the tiny fixture contains no modules in that library.
    for library in tomllib.loads((source/'lakefile.toml').read_text()).get('lean_lib',[]):
        for glob in library.get('globs',[]):
            (src/Path(*glob.split('.')[:-1])).mkdir(parents=True,exist_ok=True)
    (src/'Statements.lean').write_text('-- SYNTHETIC FIXTURE ONLY: these propositions are True, not Riemann statements.\n'+'\n'.join('def '+typ+' : Prop := True' for _,typ in THEOREMS)+'\n')
    (src/'Lemmata'/'Fixture.lean').write_text('import Mathlib.Data.Nat.Basic\ntheorem fixtureTrue : True := True.intro\n')
    (src/'Main.lean').write_text('import Statements\nimport Lemmata.Fixture\n'+'\n'.join(f'theorem {name} : {typ} := fixtureTrue' for name,typ in THEOREMS)+'\n')
    archive=root/'tiny.tar.gz'
    with tarfile.open(archive,'w:gz') as out:out.add(source,arcname='lean')
    blob=archive.read_bytes();step=len(blob)//14
    sizes=[]
    for i in range(14):
        data=blob[i*step:(i+1)*step] if i<13 else blob[i*step:]
        (root/f'lean.tar.gz.part{i+1:02}').write_bytes(data);sizes.append(len(data))
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    store=Store(root/'evidence');run=store.create('real',jobs=2)
    store.mutate(run['id'],lambda state:state.update(status='running',startedAt=time.time()))
    specification=Submission(archive_hash=hashlib.sha256(blob).hexdigest(),archive_bytes=len(blob),file_count=3,part_sizes=tuple(sizes),origin=f'http://127.0.0.1:{server.server_port}',min_free_bytes=0,cache_targets=('Mathlib.Data.Nat.Basic',))
    class TransientCompileFixture(Pipeline):
        inject_failure=True
        def execute(self,argv,stage,callback=None):
            if stage=='compile' and self.inject_failure:
                self.inject_failure=False
                # A real child process fails, with unchanged source/configuration.
                # Its actual exit 42 remains in the historical command ledger.
                return self.runner.run(['python3','-c','raise SystemExit(42)'],self.project,stage,sandbox=True)
            return super().execute(argv,stage,callback)
    pipeline=TransientCompileFixture(store,run['id'],submission=specification)
    stopped=threading.Event()
    def monitor():
        while not stopped.wait(5):
            state=store.raw(run['id']);logs=store.logs(run['id'],limit=1)
            print('[fixture] '+state['phase']+' '+(logs[-1]['message'][-200:] if logs else ''),flush=True)
    threading.Thread(target=monitor,daemon=True).start()
    try:
        pipeline.run()
        result=store.raw(run['id'])
        assert result['status']=='failed' and result['phase']=='compile'
        assert result['commands'][-1]['exitCode']==42
        print('[fixture] actual transient compile process exit 42 recorded; explicitly resuming same run',flush=True)
        store.control(run['id'],'resume')
        pipeline.run()
        result=store.raw(run['id'])
        if result['status']!='checks_completed':
            print(json.dumps({k:result[k] for k in ['id','status','phase','error','compile','stages']},ensure_ascii=False,indent=2),flush=True)
            for command in result['commands']:
                if command['exitCode'] not in (None,0):
                    print((pipeline.root/command['logFile']).read_text(errors='replace'),flush=True)
            raise RuntimeError('Tiny Lake pipeline failed: '+str(result['error']))
        assert result['compile']['succeeded']==3
        assert all(s['exitCode']==0 for s in result['stages'])
        assert not result['proofAccepted']
        print(json.dumps({'scope':'SYNTHETIC TRUE PROPOSITIONS ONLY; NOT RIEMANN PROOF','pipeline':'passed','transientCompileFailureExit':42,'sameRunResumed':True,'stages':{s['id']:s['exitCode'] for s in result['stages']},'compiledModules':3,'actualMathlib':result['environment']['actualMathlib'],'commands':[{k:c.get(k) for k in ['argv','exitCode','terminationCause']} for c in result['commands']],'proofReproduction':'NOT_RUN'},ensure_ascii=False,indent=2),flush=True)
    finally:
        stopped.set()
        server.shutdown();server.server_close()
        # The fixture's package/cache outputs are not needed by the real run.
        shutil.rmtree(Path('/sandbox/work')/run['id'],ignore_errors=True)

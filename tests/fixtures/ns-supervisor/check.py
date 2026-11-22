import os,stat,tempfile
from pathlib import Path
from ns_queue import sandbox
assert not (int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:')),16)&(1<<3)), 'test must run without CAP_FOWNER'
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)/'sandbox';(root/'etc').mkdir(parents=True)
    source=Path(temporary)/'source';source.mkdir();(source/'Main.lean').write_text('def x := 1\n')
    for attempt in range(2):
        project=sandbox.prepare(root,source)
        for path,mode in [(project/'.lake',0o755),(root/'work/ns/home-project',0o700),(root/'work/ns/evidence',0o755)]:
            assert path.stat().st_uid==10002 and stat.S_IMODE(path.stat().st_mode)==mode
    print('Restricted supervisor preparation and restart succeeded without CAP_FOWNER')
    from types import SimpleNamespace
    from ns_queue.ns_worker import NSWorker,load_manifest
    cwd=root/'work/ns/new-tools';cwd.mkdir()
    def executor(argv,**kwargs):
        log=kwargs['log_path'];log.parent.mkdir(parents=True,exist_ok=True);log.write_text('filesystem fixture\n')
        return SimpleNamespace(exit_code=0,termination=None,output='fixture')
    worker=NSWorker(Path(temporary)/'data',executor=executor,sandbox_root=root)
    worker.store.initialize(load_manifest(),'20565ace60c2',{'capHours':1})
    worker._beat=lambda:None;worker.stage='dependencies'
    assert worker._command(['true'],cwd=cwd)=='fixture'
    home=root/'work/ns/home-new-tools'
    assert home.stat().st_uid==10002 and stat.S_IMODE(home.stat().st_mode)==0o700

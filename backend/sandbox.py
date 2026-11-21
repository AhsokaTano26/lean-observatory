"""Linux filesystem boundary: build UID cannot access supervisor state or alter tools."""
import os
import shutil
import subprocess
from pathlib import Path

BUILD_UID=10002


def prepare(root, run, original):
    root=Path(root).resolve()
    if os.geteuid()!=0: raise RuntimeError('Sandbox supervisor must have chroot/setuid capabilities')
    resolver=root/'etc/resolv.conf'
    if resolver.is_symlink(): resolver.unlink()
    shutil.copyfile('/etc/resolv.conf',resolver)
    project=root/'work'/run/'project'
    if not project.exists():
        project.parent.mkdir(parents=True,exist_ok=True)
        staging=project.with_name('project.partial')
        if staging.exists(): shutil.rmtree(staging)
        shutil.copytree(original,staging,ignore=shutil.ignore_patterns('.lake'))
        for base,dirs,files in os.walk(staging):
            os.chmod(base,0o755)
            for name in files: os.chmod(Path(base)/name,0o644)
        staging.rename(project)
    lake=project/'.lake';lake.mkdir(exist_ok=True)
    if lake.is_symlink(): raise RuntimeError('Rejected symlink build root')
    if lake.stat().st_mode & 0o777 != 0o755: os.chmod(lake,0o755)
    os.chown(lake,BUILD_UID,BUILD_UID,follow_symlinks=False)
    home=project.parent/'home'
    if not home.exists():
        home.mkdir(mode=0o700)
        os.chown(home,BUILD_UID,BUILD_UID,follow_symlinks=False)
    if home.is_symlink() or not home.is_dir() or home.stat().st_uid!=BUILD_UID:
        raise RuntimeError('Rejected invalid sandbox HOME')
    return project


def command(root, cwd, argv, jobs=1, network=False):
    root=Path(root).resolve();cwd=Path(cwd).resolve()
    if not cwd.is_relative_to(root/'work'): raise ValueError('Sandbox cwd outside work volume')
    # PID1 exit tears down the private namespace, including detached setsid children.
    isolation=['unshare','--mount','--pid','--fork','--kill-child=SIGKILL','--mount-proc='+str(root/'proc')]
    if not network: isolation.append('--net')
    home='/'+str((cwd.parent/'home').relative_to(root))
    return isolation+['chroot','--userspec=10002:10002',str(root),'/usr/bin/env','-i',
            '--chdir=/'+str(cwd.relative_to(root)),
            'HOME='+home,'PATH=/home/lean/.elan/toolchains/leanprover--lean4---v4.33.1/bin:/usr/bin:/bin',
            'LD_LIBRARY_PATH=/home/lean/.elan/toolchains/leanprover--lean4---v4.33.1/lib/lean:/home/lean/.elan/toolchains/leanprover--lean4---v4.33.1/lib',
            'LEAN_NUM_THREADS='+str(jobs),'NO_COLOR=1','TERM=dumb',*argv]

"""Separate chroot, mount/PID/network namespaces and unprivileged source build UID."""
import os
from pathlib import Path
import shutil

BUILD_UID = 10002
TOOLCHAIN = '/home/lean/.elan/toolchains/leanprover--lean4---v4.34.0-rc2'


def prepare(root, original, name='project'):
    root = Path(root).resolve()
    if os.geteuid() != 0: raise RuntimeError('trusted sandbox supervisor requires root for chroot/setuid')
    workspace = root / 'work/ns'; workspace.mkdir(parents=True, exist_ok=True)
    if workspace.is_symlink(): raise ValueError('symlink sandbox work root')
    project = workspace / name
    if not project.exists():
        shutil.copytree(original, project, ignore=shutil.ignore_patterns('.lake'))
        for base, dirs, files in os.walk(project):
            os.chmod(base, 0o755)
            for entry in files: os.chmod(Path(base) / entry, 0o644)
    if project.is_symlink(): raise ValueError('symlink sandbox project')
    for path in [project / '.lake', workspace / ('home-' + name), workspace / 'evidence']:
        path.mkdir(exist_ok=True)
        if path.is_symlink(): raise ValueError('symlink writable sandbox path')
        os.chown(path, BUILD_UID, BUILD_UID); os.chmod(path, 0o700 if 'home-' in path.name else 0o755)
    resolver = root / 'etc/resolv.conf'
    if resolver.is_symlink(): resolver.unlink()
    shutil.copyfile('/etc/resolv.conf', resolver)
    return project


def command(root, cwd, argv, jobs=60, network=False, home=None, environment=None):
    root = Path(root).resolve(); cwd = Path(cwd).resolve()
    if not cwd.is_relative_to(root / 'work/ns'): raise ValueError('sandbox cwd outside NS work root')
    home = Path(home or cwd.parent / ('home-' + cwd.name)).resolve()
    if not home.is_relative_to(root / 'work/ns'): raise ValueError('sandbox HOME outside NS work root')
    isolation = ['unshare', '--mount', '--pid', '--fork', '--kill-child=SIGKILL',
                 '--mount-proc=' + str(root / 'proc')]
    if not network: isolation.append('--net')
    env = {'HOME': '/' + str(home.relative_to(root)),
           'PATH': TOOLCHAIN + '/bin:/usr/local/go/bin:/opt/rust/cargo/bin:/usr/local/bin:/usr/bin:/bin',
           'ELAN_HOME': '/home/lean/.elan', 'RUSTUP_HOME': '/opt/rust/rustup',
           'LD_LIBRARY_PATH': TOOLCHAIN + '/lib/lean:' + TOOLCHAIN + '/lib',
           'LEAN_NUM_THREADS': str(jobs), 'NO_COLOR': '1', 'TERM': 'dumb',
           'PYTHONDONTWRITEBYTECODE': '1'}
    for key, value in (environment or {}).items():
        if key not in {'COMPARATOR_LANDRUN', 'COMPARATOR_LEAN4EXPORT', 'COMPARATOR_NANODA'}:
            raise ValueError('unapproved sandbox environment override')
        env[key] = value
    return isolation + ['chroot', '--userspec=10002:10002', str(root), '/usr/bin/env', '-i',
        '--chdir=/' + str(cwd.relative_to(root)), *[k + '=' + v for k, v in env.items()],
        '/usr/bin/python3', '/opt/ns-queue/child.py', '--exec', *argv]


def freeze(path):
    """Once built, tools become supervisor-owned and cannot be replaced by source commands."""
    path = Path(path).resolve()
    for base, dirs, files in os.walk(path):
        for item in [Path(base), *[Path(base) / name for name in files]]:
            if item.is_symlink():
                if not item.resolve().is_relative_to(path): raise ValueError('tool symlink escapes trusted tree')
                continue
            executable = item.is_dir() or bool(item.stat().st_mode & 0o111)
            os.chown(item, 0, 0); os.chmod(item, 0o755 if executable else 0o644)

"""Exercise the production scope probe with actual Linux isolation and Landlock.

Only this test wrapper installs a tiny deny-write ruleset. Production uses its
pinned Landrun executable; its policy and its warning handling are not mocked.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess

from ns_queue import sandbox_policy as policy


libc = ctypes.CDLL(None, use_errno=True)
abi = libc.syscall(444, 0, 0, 1)
assert abi >= 4, 'real Linux Landlock ABI >= 4 is required for this fixture'

root = Path('/sandbox')
evidence = root / 'work/ns/evidence'
evidence.mkdir(parents=True)
evidence.chmod(0o755)
os.chown(evidence, 10002, 10002)
target = evidence / 'landlock-write-probe'

# -I prevents imports from the project, PYTHONPATH, or the current directory.
# Both scripts are root-owned, read-only inputs in this container's private tmpfs.
child = root / 'tmp/ns-policy-child.py'
child.write_bytes(Path('/app/ns_queue/child.py').read_bytes())
child.chmod(0o644)
runner = root / 'tmp/ns-policy-runner.py'
runner.write_text('''import ctypes, os, sys
if sys.argv[1] == 'landlock':
    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64)]
    libc = ctypes.CDLL(None, use_errno=True)
    # WRITE_FILE | MAKE_REG: no path grants, so fresh file creation/writes fail.
    attr = Ruleset((1 << 1) | (1 << 8))
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'real landlock_create_ruleset failed')
    try:
        if libc.prctl(38, 1, 0, 0, 0) or libc.syscall(446, fd, 0):
            raise OSError(ctypes.get_errno(), 'real landlock_restrict_self failed')
    finally:
        os.close(fd)
exec(compile(''' + repr(policy.SCOPE_PROBE) + ''', '<trusted-scope-probe>', 'exec'), {'__name__': '__main__'})
''')
runner.chmod(0o644)


def run_case(name, *, landlock, unix_filter):
    if target.exists():
        target.unlink()
    # Prove the same UID can write this target without Landlock; a read-only
    # mount or DAC failure must never substitute for the tested restriction.
    baseline = [
        'unshare', '--mount', '--pid', '--fork', '--kill-child=SIGKILL', '--net',
        '--mount-proc=/sandbox/proc', 'chroot', '--userspec=10002:10002', '/sandbox',
        '/usr/bin/python3', '-I', '-c',
        "open('/work/ns/evidence/landlock-write-probe', 'w').write('baseline')",
    ]
    subprocess.run(baseline, stdin=subprocess.DEVNULL, check=True, capture_output=True, text=True, timeout=15)
    assert target.read_text() == 'baseline'
    target.unlink()
    command = [
        'unshare', '--mount', '--pid', '--fork', '--kill-child=SIGKILL', '--net',
        '--mount-proc=/sandbox/proc', 'chroot', '--userspec=10002:10002', '/sandbox',
        '/usr/bin/env', '-i', 'HOME=/tmp', 'PATH=/usr/bin:/bin',
        '/usr/bin/python3', '-I', '/tmp/ns-policy-child.py',
        '--exec' if unix_filter else '--exec-network',
        '/usr/bin/python3', '-I', '/tmp/ns-policy-runner.py',
        'landlock' if landlock else 'no-landlock',
    ]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20)
    print(result.stdout, end='')
    print(result.stderr, end='')
    assert result.returncode == 0, (name, result.returncode, result.stdout, result.stderr)
    markers = [line.split('|', 1)[1] for line in result.stdout.splitlines() if line.startswith('NS_SANDBOX_SCOPE|')]
    assert len(markers) == 1, result.stdout
    measured = json.loads(markers[0])
    try:
        report = policy.validate_probe(result.stdout + result.stderr, abi)
    except ValueError:
        accepted = False
    else:
        assert report['guards'] == measured
        accepted = True
    if name == 'layered':
        assert accepted, measured
    elif name == 'noLandlock':
        assert not measured['filesystemWriteDenied'] and not accepted, measured
    else:
        assert not measured['unixSocketDenied'] and not measured['unixSocketpairDenied'] and not accepted, measured
    return {'accepted': accepted, 'filesystemWriteDenied': measured['filesystemWriteDenied'],
            'unixSocketDenied': measured['unixSocketDenied'], 'unixSocketpairDenied': measured['unixSocketpairDenied']}


cases = {
    'layered': run_case('layered', landlock=True, unix_filter=True),
    'noLandlock': run_case('noLandlock', landlock=False, unix_filter=True),
    'noUnixFilter': run_case('noUnixFilter', landlock=True, unix_filter=False),
}
print(json.dumps({'realLinux': True, 'realLandlock': True, 'nativeLandlockAbi': abi, 'cases': cases}))

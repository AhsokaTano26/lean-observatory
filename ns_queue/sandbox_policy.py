"""Evidence-based compatibility for Landlock ABI 4 with verified outer guards.

The native warning remains in logs and reports. This profile does not claim
ABI 5+ ioctl, signal, UNIX socket or UDP restrictions are supplied by Landlock.
"""
import json
import re

ABI4_WARNING = ('kernel supports Landlock ABI v4, so these default restrictions are not enforced: '
    'device ioctl (ABI v5), pathname UNIX socket connections (ABI v9), UDP bind/connect/send (ABI v10), '
    'abstract UNIX socket and signal scoping (ABI v6)')
_WARNING = re.compile(r'\[landrun:warn\] \d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} ' + re.escape(ABI4_WARNING))
_TRUE_GUARDS = ('pid1SameRoot', 'noSys', 'safeFds', 'filesystemWriteDenied', 'unixSocketDenied',
    'unixSocketpairDenied', 'ipv4TcpDenied', 'ipv4UdpDenied', 'ipv6TcpDenied', 'ipv6UdpDenied',
    'noIpv4Routes', 'userNamespaceDenied')

# Executed by isolated stdlib Python inside the same Landrun/namespace/filter
# path as the real checker. No project imports or executable probe files.
SCOPE_PROBE = r'''
import ctypes, errno, json, os, socket, stat
libc = ctypes.CDLL(None, use_errno=True)
r = {'landlockAbi': libc.syscall(444, 0, 0, 1), 'uid': os.getuid(), 'gid': os.getgid()}
status = dict(line.split(':', 1) for line in open('/proc/self/status') if ':' in line)
r.update(capEff=int(status['CapEff'].strip(), 16), noNewPrivs=int(status['NoNewPrivs']), seccomp=int(status['Seccomp']))
pid1 = dict(line.split(':', 1) for line in open('/proc/1/status') if ':' in line)
r['pid1Uid'] = int(pid1['Uid'].split()[0])
def identity(path):
    s = os.stat(path); return (s.st_dev, s.st_ino)
r['pid1SameRoot'] = identity('/proc/1/root') == identity('/')
r['noSys'] = not os.path.exists('/sys')
r['devices'] = {}
for name in os.listdir('/dev'):
    s = os.stat('/dev/' + name)
    r['devices'][name] = [os.major(s.st_rdev), os.minor(s.st_rdev)] if stat.S_ISCHR(s.st_mode) else 'not-character-device'
r['safeFds'] = True
for name in os.listdir('/proc/self/fd'):
    try: s = os.fstat(int(name))
    except OSError as e:
        if e.errno == errno.EBADF: continue
        raise
    safe = stat.S_ISFIFO(s.st_mode) or (stat.S_ISCHR(s.st_mode) and (os.major(s.st_rdev), os.minor(s.st_rdev)) == (1, 3))
    if not safe: r['safeFds'] = False
r['filesystemWriteDenied'] = False
try:
    with open('/work/ns/evidence/landlock-write-probe', 'w') as f: f.write('escaped')
except PermissionError: r['filesystemWriteDenied'] = True
for key, action in [('unixSocketDenied', lambda: socket.socket(socket.AF_UNIX)),
                    ('unixSocketpairDenied', lambda: socket.socketpair(socket.AF_UNIX))]:
    try:
        made = action()
        for s in made if isinstance(made, tuple) else [made]: s.close()
        r[key] = False
    except OSError as e: r[key] = e.errno in (errno.EPERM, errno.EACCES)
for family, prefix, address in [(socket.AF_INET, 'ipv4', '198.51.100.1'), (socket.AF_INET6, 'ipv6', '2001:db8::1')]:
    for kind, suffix in [(socket.SOCK_STREAM, 'TcpDenied'), (socket.SOCK_DGRAM, 'UdpDenied')]:
        s = None
        try:
            s = socket.socket(family, kind); s.settimeout(1)
            if kind == socket.SOCK_DGRAM: s.sendto(b'', (address, 9))
            else: s.connect((address, 9))
            r[prefix + suffix] = False
        except OSError as e:
            r[prefix + suffix] = e.errno in (errno.EPERM, errno.EACCES, errno.ENETUNREACH, errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT) or (family == socket.AF_INET6 and e.errno == errno.EADDRNOTAVAIL)
        finally:
            if s is not None: s.close()
routes = [line.split() for line in open('/proc/net/route') if line.strip()]
r['noIpv4Routes'] = not routes or (len(routes) == 1 and routes[0][0] == 'Iface' and 'Gateway' in routes[0])
ctypes.set_errno(0)
r['userNamespaceDenied'] = libc.unshare(0x10000000) == -1 and ctypes.get_errno() in (errno.EPERM, errno.EACCES)
print('NS_SANDBOX_SCOPE|' + json.dumps(r, sort_keys=True), flush=True)
'''


def _validate_guards(record, abi):
    if type(abi) is not int or abi < 4 or type(record) is not dict:
        raise ValueError('independent sandbox ABI/record unavailable')
    expected = {'landlockAbi': abi, 'uid': 10002, 'gid': 10002, 'capEff': 0,
                'noNewPrivs': 1, 'seccomp': 2, 'pid1Uid': 10002}
    if any(type(record.get(k)) is not int or record[k] != v for k, v in expected.items()):
        raise ValueError('independent sandbox identity/capability guard failed')
    if any(record.get(k) is not True for k in _TRUE_GUARDS):
        raise ValueError('independent sandbox filesystem/namespace/socket/fd guard failed')
    if record.get('devices') != {'null': [1, 3], 'urandom': [1, 9]}:
        raise ValueError('independent sandbox device exposure changed')


def validate_warnings(output, evidence=None):
    if re.search(r'fake[-_]landrun|unsandboxed|best.effort|kernel rejects', output, re.I):
        raise ValueError('independent sandbox/checker unsafe mode')
    warnings = [line for line in output.splitlines() if '[landrun:warn]' in line.lower()]
    if warnings:
        if type(evidence) is not dict or evidence.get('profile') != 'landlock+namespaces+seccomp':
            raise ValueError('Landlock warning lacks verified compensating guards')
        _validate_guards(evidence.get('guards'), evidence.get('nativeLandlockAbi'))
        if evidence['nativeLandlockAbi'] != 4 or any(not _WARNING.fullmatch(line) for line in warnings):
            raise ValueError('unrecognized Landlock warning')
    return warnings


def validate_probe(output, expected_abi):
    markers = [line.removeprefix('NS_SANDBOX_SCOPE|') for line in output.splitlines()
               if line.startswith('NS_SANDBOX_SCOPE|')]
    if len(markers) != 1: raise ValueError('missing/duplicate independent sandbox evidence')
    record = json.loads(markers[0]); _validate_guards(record, expected_abi)
    report = {'profile': 'landlock+namespaces+seccomp', 'nativeLandlockAbi': expected_abi,
              'guards': record, 'devicePolicy': 'null-and-urandom-only; no-sensitive-inherited-fds',
              'nativeFeatureLimitations': ['ioctl restriction unavailable before ABI 5',
                  'UNIX socket and signal scoping unavailable before ABI 6/9',
                  'UDP restriction unavailable before ABI 10'],
              'limitations': ['ioctl syscall is not disabled; only null/urandom devices and pipe/null inherited fds are exposed',
                  'signal isolation is provided by the private PID namespace, not a per-Landlock-domain signal scope']}
    report['nativeWarnings'] = validate_warnings(output, report)
    return report

#!/usr/bin/python3
"""Parent-death watchdog and Linux seccomp socket constraint, before any source exec."""
import ctypes
import errno
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import time


def identity(pid):
    try:
        if sys.platform.startswith('linux'):
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            if stat[0] == 'Z': return None
            return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + stat[19]
        # Portable tiny-process fixtures can run where macOS denies ps access.
        # The NS worker itself refuses non-Linux execution, so production always
        # uses the boot ID + kernel start-time identity above (including PID reuse).
        os.kill(pid, 0)
        return 'local-fixture-pid:' + str(pid)
    except (OSError, subprocess.SubprocessError): return None


def socket_filter_program(architecture):
    targets = {'x86_64': (0xc000003e, 41, 53), 'aarch64': (0xc00000b7, 198, 199)}
    if architecture not in targets: raise RuntimeError('unsupported seccomp architecture')
    arch, socket_nr, socketpair_nr = targets[architecture]
    return [(0x20,0,0,4), (0x15,1,0,arch), (0x06,0,0,0x80000000),
            (0x20,0,0,0), (0x35,0,1,0x40000000), (0x06,0,0,0x80000000),
            (0x15,1,0,socket_nr), (0x15,0,3,socketpair_nr), (0x20,0,0,16),
            (0x15,0,1,socket.AF_UNIX), (0x06,0,0,0x00050000 | errno.EPERM),
            (0x06,0,0,0x7fff0000)]


def forbid_unix_sockets():
    """Inherited syscall filter closes Comparator's AF_UNIX gap; unsupported means failure."""
    if not sys.platform.startswith('linux'):
        raise RuntimeError('AF_UNIX seccomp requires supported Linux architecture')
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    # audit arch, reject x32/other ABIs, then deny socket(AF_UNIX, ...).
    ins = socket_filter_program(platform.machine())
    array = (Filter * len(ins))(*(Filter(*x) for x in ins))
    prog = Program(len(ins), array); libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) or libc.prctl(22, 2, ctypes.byref(prog), 0, 0):
        raise OSError(ctypes.get_errno(), 'cannot enforce AF_UNIX seccomp')


def main(argv):
    if argv[0] == '--watch':
        parent, parent_id, group, group_id = int(argv[1]), argv[2], int(argv[3]), argv[4]
        while identity(group) == group_id:
            if identity(parent) != parent_id:
                try: os.killpg(group, signal.SIGKILL)
                except ProcessLookupError: pass
                return 0
            time.sleep(.2)
        return 0
    if argv[0] == '--guard':
        parent = int(argv[1]); parent_id = identity(parent); group_id = identity(os.getpid())
        if not parent_id or not group_id or os.getppid() != parent:
            raise RuntimeError('cannot establish command supervision')
        watcher = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--watch',
            str(parent), parent_id, str(os.getpid()), group_id], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            child = subprocess.Popen(argv[2:]); result = child.wait()
            return result if result >= 0 else 128 - result
        finally:
            watcher.terminate(); watcher.wait()
    if os.geteuid() == 0: raise RuntimeError('source commands must never execute as root')
    # Network-enabled dependency preparation needs libcurl's local resolver
    # wakeup socketpair. Offline checks inherit their irreversible filter;
    # invoking this mode underneath a strict check cannot remove that filter.
    if argv[0] == '--exec-network': os.execvp(argv[1], argv[1:])
    forbid_unix_sockets()
    if argv[0] == '--probe-af-unix':
        for factory in [socket.socket, socket.socketpair]:
            try: factory(socket.AF_UNIX)
            except PermissionError: continue
            raise RuntimeError('AF_UNIX socket/socketpair was not denied')
        print('NS_AF_UNIX_DENIED'); return 0
    if argv[0] == '--probe-landlock':
        numbers = {'x86_64': 444, 'aarch64': 444}
        libc = ctypes.CDLL(None, use_errno=True)
        abi = libc.syscall(numbers[platform.machine()], 0, 0, 1)
        if abi < 4: raise RuntimeError('real Landlock ABI >= 4 required; no best-effort fallback')
        print('NS_LANDLOCK_ABI|' + str(abi)); return 0
    if argv[0] == '--landrun':
        # Real upstream landrun, in strict mode. Never substitute fake-landrun.
        executable = '/work/ns/tools/landrun/landrun'
        args = [x for x in argv[1:] if x != '--best-effort']
        os.execv(executable, [executable, *args])
    if argv[0] == '--exec': os.execvp(argv[1], argv[1:])
    raise ValueError('unknown child mode')


if __name__ == '__main__':
    arguments = sys.argv[1:]
    if Path(sys.argv[0]).name == 'comparator-landrun': arguments = ['--landrun', *arguments]
    sys.exit(main(arguments))

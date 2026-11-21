"""Supervise a command group with a watchdog outside that group's stop boundary."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def identity(pid):
    try:
        if sys.platform.startswith('linux'):
            stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            if stat[0]=='Z': return None
            return Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+stat[19]
        os.kill(pid,0)
        value=subprocess.check_output(['ps','-p',str(pid),'-o','lstart='],stderr=subprocess.DEVNULL,text=True).strip()
        return value or None
    except (OSError,subprocess.SubprocessError): return None


def watch(parent, parent_identity, group, group_identity):
    while identity(group)==group_identity:
        if identity(parent)!=parent_identity:
            try: os.killpg(group,signal.SIGKILL)
            except ProcessLookupError: pass
            return
        time.sleep(.25)


def main():
    if sys.argv[1]=='--watch':
        watch(int(sys.argv[2]),sys.argv[3],int(sys.argv[4]),sys.argv[5]); return 0
    parent=int(sys.argv[1]); argv=sys.argv[2:]
    # A stopped command group must not stop its parent-death watchdog.
    parent_id=identity(parent); group_id=identity(os.getpid())
    if not parent_id or not group_id: raise RuntimeError('Cannot establish process identity')
    watcher=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--watch',str(parent),parent_id,str(os.getpid()),group_id],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        if os.getppid()!=parent: raise RuntimeError('Runner exited before supervision started')
        child=subprocess.Popen(argv)
        result=child.wait()
        return result if result>=0 else 128-result
    finally:
        watcher.terminate(); watcher.wait()


if __name__=='__main__': sys.exit(main())

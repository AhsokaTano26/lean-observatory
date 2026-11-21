"""One persistent scheduler process, isolated from the web server."""
import argparse
import fcntl
import math
import os
import signal
import threading
import time
from pathlib import Path
from .store import Store
from .mock import tick, metrics as mock_metrics
from .pipeline import Pipeline
from .metrics import collect, read_host_file
from .readiness import require_online_gate


def sample_loop(store, stop, host_file=None):
    while not stop.is_set():
        s=store.snapshot()
        m=mock_metrics(store.raw(s['id'])) if s['id'] and s['mode']=='mock' else (read_host_file(host_file) if host_file else collect(store.root))
        m.update(runId=s['id'],mode=s['mode'],rate=s['compile']['rate'],completed=s['compile']['succeeded'],observedAt=time.time())
        store.sample(m)
        stop.wait(1 if s['mode']=='mock' else 5)


def work(store, stop=None, interval=1, allow_real=False):
    stop=stop or threading.Event()
    # File lock is released by the OS on crash. Only one scheduler per data volume.
    lock=(store.root/'worker.lock').open('w')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit('已有 Worker 持有该数据卷')
    for s in store.active_runs():
        if s['status'] in ('running','paused'):
            def interrupt(x):
                if x['status'] not in ('running','paused'): return
                observed=time.time()
                for command in x['commands']:
                    if (command.get('status') in (None,'running','paused')
                            and command.get('exitCode') is None and command.get('finishedAt') is None):
                        command.update(status='interrupted',observedStoppedAt=observed,
                                       terminationCause='worker_restart_exit_unknown')
                for stage in x['stages']:
                    if stage['status'] in ('running','paused'):
                        stage.update(status='interrupted',observedStoppedAt=observed,
                                     terminationCause='worker_restart_exit_unknown')
                if x['desired']=='cancelled':
                    x.update(status='cancelled',finishedAt=observed,workerHeartbeat=None)
                    x['compile']['rate']=0
                    return
                x.update(status='interrupted',desired='running',error='Worker 重启；已保存检查点，请显式恢复',workerHeartbeat=None)
                x['compile']['rate']=0
            store.mutate(s['id'],interrupt,'worker_restart')
    sampler=threading.Thread(target=sample_loop,args=(store,stop,os.environ.get('HOST_METRICS')),daemon=True); sampler.start()
    try:
        while not stop.is_set():
            s=next(iter(store.active_runs()),None)
            if not s: stop.wait(interval); continue
            run=s['id']
            if s['desired']=='cancelled':
                store.mutate(run,lambda x:x.update(status='cancelled',finishedAt=time.time()))
                continue
            if s['mode']=='real':
                if not allow_real:
                    store.mutate(run,lambda x:x.update(status='failed',error='Worker 真实验证门禁未启用'))
                    continue
                try: require_online_gate(run)
                except ValueError as error:
                    store.mutate(run,lambda x:x.update(status='failed',error=str(error)))
                    continue
                store.mutate(run,lambda x:x.update(status='running',startedAt=x['startedAt'] or time.time(),workerHeartbeat=time.time()),'worker_claimed')
                Pipeline(store,run).run()
                continue
            previous=s['phase']; previous_status=s['status']
            def advance(x):
                # The user may cancel after the scheduler reads active_runs.
                # Recheck the transactional state before claiming this tick.
                if x['status'] not in ('queued','running','paused') or x['desired']=='cancelled':
                    return
                x.update(startedAt=x['startedAt'] or time.time(),status='paused' if x['desired']=='paused' else 'running',workerHeartbeat=time.time())
                tick(x,interval)
            s=store.mutate(run,advance)
            if s['status']=='running':
                stage=s['phase']; message=f"[MOCK] {stage}: "
                if stage=='compile': message+=f"Built {s['compile']['currentModule']} · {s['compile']['succeeded']:,}/{s['compile']['total']:,}"
                else: message+='模拟阶段推进；不产生真实验证结论'
                store.log(run,'info',message,stage)
            if s['status'] not in ('running','paused'):
                store.log(run,'error' if s['error'] else 'info','[MOCK] '+(s['error'] or ('任务已取消' if s['status']=='cancelled' else '所有模拟检查结束；真实验证未执行')),s['phase'])
            stop.wait(interval)
    finally:
        stop.set(); sampler.join(2); lock.close()


def main():
    p=argparse.ArgumentParser(); p.add_argument('--data',default='.data'); p.add_argument('--interval',type=float,default=1)
    a=p.parse_args()
    stop=threading.Event()
    def terminate(sig, frame):
        stop.set()
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try: work(Store(Path(a.data)),stop=stop,interval=a.interval,allow_real=os.environ.get('ENABLE_REAL')=='1')
    except KeyboardInterrupt: pass


if __name__=='__main__': main()

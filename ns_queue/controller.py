"""Successor controller. RH is observed via GET; only the NS driver can mutate containers."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import tarfile
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from .gates import rh_gate, start_gate, validate_result
from .notify import DEFAULT_WEBHOOK, deliver
from .store import QueueStore


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def atomic_bytes(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    with temporary.open('wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


class RHClient:
    def __init__(self, base='https://lean.tano.asia', timeout=20):
        p = urllib.parse.urlsplit(base)
        if p.scheme != 'https' or p.hostname != 'lean.tano.asia' or p.port not in (None, 443) or p.username or p.password or p.path not in ('', '/'):
            raise ValueError('RH dependency must use the existing CA-verified production URL')
        self.base = base.rstrip('/'); self.timeout = timeout

    def _get(self, path):
        return urllib.request.urlopen(self.base + path, timeout=self.timeout)

    def snapshot(self, run):
        with self._get('/api/state?run=' + urllib.parse.quote(run, safe='')) as response:
            return json.load(response)

    def ledger(self):
        with self._get('/api/runs') as response: return json.load(response)

    def result_bytes(self, run):
        with self._get('/api/artifacts/verification-result.json?run=' + urllib.parse.quote(run, safe='')) as response:
            blob = response.read(64*1024**2 + 1)
        if len(blob) > 64*1024**2: raise ValueError('RH result exceeds evidence limit')
        return blob

    def download_logs(self, run, path):
        with self._get('/api/logs/download?run=' + urllib.parse.quote(run, safe='')) as response, Path(path).open('wb') as out:
            size = 0
            while True:
                chunk = response.read(1024*1024)
                if not chunk: break
                size += len(chunk)
                if size > 20*1024**3: raise ValueError('RH log archive exceeds storage limit')
                out.write(chunk)
            out.flush(); os.fsync(out.fileno())


@contextlib.contextmanager
def controller_lease(root):
    path = Path(root)/'controller.lock'; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise RuntimeError('Another NS controller owns this queue') from error
        try: yield
        finally: fcntl.flock(lock, fcntl.LOCK_UN)


class Controller:
    def __init__(self, store, rh_client, driver, *, webhook=DEFAULT_WEBHOOK, notifier=deliver, clock=time.time):
        self.store=store; self.rh=rh_client; self.driver=driver
        self.webhook=webhook; self.notifier=notifier; self.clock=clock

    def flush_notices(self):
        for item in self.store.outbox():
            if (item.get('nextAttemptAt') or 0) > self.clock(): continue
            try: result=self.notifier(self.webhook,item)
            except Exception as error: result={'status':'retry','error':str(error)[:400]}
            self.store.ack_alert(item['id'],result['status'],result.get('error'))

    def pause(self, reason, message):
        state=self.store.snapshot()
        self.store.mutate(lambda s:s.update(status='PAUSED',reason=reason),'paused')
        self.store.log('scheduler',message,'warning')
        self.store.alert(state['id']+':'+reason,'NS 验证暂停',message,'error' if reason.startswith('rh_') else 'warning',
                         {'project':'NS','run':state['id'],'RH':state['rhRunId'],'reason':reason})
        self.flush_notices()

    def observe_rh(self, state):
        payload=self.rh.snapshot(state['rhRunId']); ledger=self.rh.ledger()
        payload['workerRunning']=self.driver.rh_running()
        run=payload.get('run') or {}
        summary={key:run.get(key) for key in ['id','status','phase','compile','startedAt','finishedAt','error','proofAccepted']}
        summary['workerOnline']=payload.get('workerOnline'); summary['metrics']=payload.get('metrics')
        self.store.mutate(lambda s:s.update(rh=summary,controllerHeartbeat=self.clock()),event=None)
        return payload,ledger,rh_gate(payload,ledger,state['rhRunId'])

    def persist_rh(self, payload):
        state=self.store.snapshot(); existing=state['rhEvidence']
        if existing.get('persisted'):
            for key,hash_key in [('resultPath','resultSha256'),('logsPath','logsSha256')]:
                path=(self.store.root/existing[key]).resolve()
                if not path.is_relative_to(self.store.root) or digest(path)!=existing[hash_key]:
                    raise ValueError('Persisted RH evidence changed')
            return
        run=payload['run']; entry=next(a for a in run['artifacts'] if a['name']=='verification-result.json')
        blob=self.rh.result_bytes(state['rhRunId'])
        if len(blob)!=entry['bytes'] or hashlib.sha256(blob).hexdigest()!=entry['sha256']:
            raise ValueError('RH final report hash or size mismatch')
        report=json.loads(blob); validate_result(report,state['rhRunId'])
        if report['run']['finishedAt']!=run['finishedAt']:
            raise ValueError('RH result belongs to a different completion snapshot')
        directory=self.store.root/'rh-evidence'/state['rhRunId']; directory.mkdir(parents=True,exist_ok=True)
        result=directory/'verification-result.json'; atomic_bytes(result,blob)
        temporary=directory/'logs.tar.gz.partial'; self.rh.download_logs(state['rhRunId'],temporary)
        with tarfile.open(temporary,'r:gz') as archive:
            names=set(archive.getnames())
            required={'events.ndjson','snapshot.json'} | {c['logFile'] for c in run['commands'] if c.get('logFile')}
            if not required<=names: raise ValueError('RH log archive is incomplete')
        logs=directory/'logs.tar.gz'; temporary.replace(logs)
        manifest=dict(persisted=True,runId=state['rhRunId'],persistedAt=self.clock(),
                      resultPath=str(result.relative_to(self.store.root)),resultSha256=digest(result),
                      resultBytes=result.stat().st_size,
                      logsPath=str(logs.relative_to(self.store.root)),logsSha256=digest(logs),logsBytes=logs.stat().st_size)
        atomic_bytes(directory/'manifest.json',json.dumps(manifest,indent=2).encode())
        self.store.mutate(lambda s:s.update(rhEvidence=manifest),'rh_persisted')
        self.store.log('scheduler','RH 全部必要机器检查与完整日志已校验并持久化；数学语义/额外独立内核状态仍单列。')

    def _reconcile(self, state):
        job=self.driver.inspect(state)
        if state.get('startedAt'):
            elapsed=max(0,(state.get('finishedAt') or self.clock())-state['startedAt'])
            self.store.mutate(lambda s:s['budget'].update(estimatedUsd=elapsed/3600*s['budget']['hourlyUsd']),event=None)
            state=self.store.snapshot()
        if job and job.get('running'):
            if hasattr(self.driver,'metrics'):job['resources']=self.driver.metrics(state)
            self.store.mutate(lambda s:s.update(worker=job,controllerHeartbeat=self.clock()),event=None)
            if state['budget']['estimatedUsd']>=state['budget']['capUsd']:
                self.driver.stop(state)
                self.pause('budget','NS 预算额度已到，已停止自己的 NS Worker并保留检查点。服务器仍按小时计费。')
            return
        if state['status']=='STARTING' and job is None:
            # A crash before creation is retried only through the full fresh barrier.
            self.store.mutate(lambda s:s.update(status='QUEUED',reason='recover_launch'),'launch_recovery')
            return
        state=self.store.snapshot()
        if state['status'] in ('COMPLETED','CHECKS_COMPLETED'): return
        if state['status'] in ('PAUSED','FAILED'):
            self.store.alert(state['id']+':'+state.get('reason','ns_failed'),'NS 验证暂停',
                             state.get('error') or 'NS 阶段检查失败；完整日志和检查点已保留。','error',{'run':state['id']})
            self.flush_notices(); return
        self.pause('ns_worker_stopped','NS Worker 已停止，尚未确认完整成功结果；保留阶段检查点等待管理员处理。')

    def tick(self):
        self.flush_notices(); state=self.store.snapshot()
        if not state: return
        self.store.mutate(lambda s:s.update(controllerHeartbeat=self.clock()),event=None)
        if state['status'] in ('RUNNING','STARTING'):
            self._reconcile(state); return
        if state['status'] in ('PAUSED','FAILED') and state.get('execution')=='INCOMPLETE' and state.get('startedAt'):
            self.store.alert(state['id']+':'+state.get('reason','worker_failed'),'NS 验证暂停',
                             state.get('error') or 'NS 阶段未完成；已保留完整日志和检查点。','error',{'run':state['id']})
            self.flush_notices();return
        if state['status']!='QUEUED': return
        try:
            payload,ledger,gate=self.observe_rh(state)
            if gate['decision']=='PAUSE':
                self.pause(gate['reason'],'RH 失败或异常停止；NS 不启动，原 RH 日志与配置保持原样。'); return
            if gate['decision']!='READY':
                self.store.mutate(lambda s:s.update(reason=gate['reason']),event=None); return
            self.persist_rh(payload)
            # Evidence download can take time: do not use an earlier READY decision.
            payload,ledger,gate=self.observe_rh(self.store.snapshot())
            if gate['decision']=='PAUSE':
                self.pause(gate['reason'],'RH 状态在证据归档期间发生异常；NS 不启动。'); return
            if gate['decision']!='READY':
                self.store.mutate(lambda s:s.update(reason=gate['reason']),event=None); return
            state=self.store.snapshot(); resources=self.driver.resources(); resources['rhActive']=False
            start=start_gate(state,resources)
            if not start['allowed']:
                self.pause(start['reason'],'RH 已完成，但 NS '+('额外预算不足（当前为0时不会启动）。服务器仍按小时计费。' if start['reason']=='budget' else '资源启动门禁未满足。')); return
            self.store.mutate(lambda s:s.update(status='STARTING',reason='starting',startedAt=s.get('startedAt') or self.clock()),'starting')
            job=self.driver.launch(self.store.snapshot())
            self.store.mutate(lambda s:s.update(status='RUNNING',reason='running',worker=job),'launched')
            self.store.log('scheduler','NS Worker 已在独立资源与工具链中启动。')
            self.store.alert(state['id']+':started','NS 验证启动','RH 所有必要检查及结果持久化成功，NS 资源与预算门禁通过。','info',{'run':state['id']})
            self.flush_notices()
        except Exception as error:
            current=self.store.snapshot()
            if current.get('status')=='STARTING':
                try: existing=self.driver.inspect(current)
                except Exception: existing=None
                if existing and existing.get('running'):
                    self.store.mutate(lambda s:s.update(status='RUNNING',reason='running',worker=existing),'launch_adopted')
                    self.store.log('scheduler','启动确认中断后发现同一NS容器已运行，已接管；不会重复创建。','warning')
                    return
            # A transient observation failure does not label RH failed or launch NS.
            if isinstance(error,(urllib.error.URLError,TimeoutError,ConnectionError)):
                try: stopped=self.driver.rh_running() is False
                except Exception: stopped=False
                if stopped:
                    self.pause('rh_interrupted','RH API 无法访问且原 RH Worker 已停止；NS 暂停，保留全部日志。'); return
                self.store.mutate(lambda s:s.update(reason='rh_unreachable'),event=None)
                self.store.log('scheduler','RH 状态暂不可确认：'+str(error)[:300],'warning')
            else:
                self.pause('rh_evidence' if not self.store.snapshot()['rhEvidence'].get('persisted') else 'launch_error',str(error)[:700])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--root',required=True); parser.add_argument('--deployment',required=True)
    parser.add_argument('--interval',type=float,default=10); parser.add_argument('--webhook',default=DEFAULT_WEBHOOK)
    args=parser.parse_args()
    from .driver import DockerDriver
    store=QueueStore(args.root); controller=Controller(store,RHClient(),DockerDriver(args.deployment,args.root),webhook=args.webhook)
    controller.driver.rh_barrier=lambda: controller.observe_rh(store.snapshot())[2]['decision']=='READY'
    stop=False
    def terminate(*_):
        nonlocal stop; stop=True
    signal.signal(signal.SIGTERM,terminate); signal.signal(signal.SIGINT,terminate)
    with controller_lease(args.root):
        while not stop:
            controller.tick()
            for _ in range(max(1,int(args.interval*5))):
                if stop: break
                time.sleep(.2)


if __name__=='__main__': main()

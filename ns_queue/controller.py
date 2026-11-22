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
from .admission import dependency_gate, verify_parallel
from .notify import DEFAULT_WEBHOOK, deliver
from .store import QueueStore
from .budget import normalize, runtime_usage


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
        self.store.mutate(lambda s:s.update(status='PAUSED',reason=reason,pausedAt=self.clock()),'paused')
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
        return payload,ledger,dependency_gate(payload,ledger,state)

    def persist_admission(self, payload, ledger):
        state=self.store.snapshot()
        path=self.store.root/'rh-evidence'/state['rhRunId']/'replay-admission.json'
        atomic_bytes(path,json.dumps({'payload':payload,'ledger':ledger},ensure_ascii=False).encode())
        evidence=dict(kind='rh_replay',runId=state['rhRunId'],recordedAt=self.clock(),
            snapshotPath=str(path.relative_to(self.store.root)),snapshotSha256=digest(path),
            snapshotBytes=path.stat().st_size,finalSuccess=False)
        candidate={**state,'parallelAdmission':evidence};verify_parallel(self.store.root,candidate)
        self.store.mutate(lambda s:s.update(parallelAdmission=evidence,
            resourceProfile={'cpus':60,'memoryBytes':220000000000,'mode':'rh_overlap'}),'parallel_admitted')
        self.store.log('scheduler','管理员已授权 RH 内核重放期间并行 NS；编译与公理审计已通过，RH 重放和最终结果仍未完成。')

    def monitor_parallel(self, state):
        """Observe RH while NS runs; only the owned NS container can be stopped."""
        if state.get('schedulingMode')!='parallel_replay' or (state.get('rhEvidence',{}).get('persisted') and
                state.get('resourceProfile',{}).get('mode')!='rh_overlap'):
            return True
        try:
            payload,ledger,gate=self.observe_rh(state)
            if gate['decision']=='PAUSE':
                if state['status'] in ('RUNNING','STARTING'):
                    self.driver.stop(state)
                    self.pause(gate['reason'],'RH 失败或异常停止；已暂停自己的 NS Worker，RH 进程及日志未修改。')
                    return False
                self.store.alert(state['id']+':'+gate['reason'],'RH 验证异常',
                    'RH 失败或异常停止；NS 现有结果与暂停状态保留，RH 日志未修改。','error',{'RH':state['rhRunId']})
                return True
            if gate['decision']=='WAIT' and payload['run'].get('status')!='checks_completed' and state['status'] in ('RUNNING','STARTING'):
                self.driver.stop(state)
                self.pause('rh_overlap_unconfirmed','RH 已不满足内核重放并行条件；NS 暂停并保留检查点。')
                return False
            if rh_gate(payload,ledger,state['rhRunId'])['decision']=='READY':
                self.persist_rh(payload)
                self.driver.promote(self.store.snapshot())
                self.store.mutate(lambda s:s.update(resourceProfile={
                    'cpus':60,'memoryBytes':250000000000,'mode':'dedicated'}),'resources_promoted')
                self.store.log('scheduler','RH 必要检查及最终证据归档完成；NS 内存上限已恢复为 250 GB，原进程继续运行。')
            return True
        except (urllib.error.URLError,TimeoutError,ConnectionError) as error:
            if self.driver.rh_running() is False:
                if state['status'] in ('RUNNING','STARTING'):
                    self.driver.stop(state);self.pause('rh_interrupted','RH API 无法访问且 Worker 已停止；NS 已暂停。');return False
                self.store.alert(state['id']+':rh_interrupted','RH 验证异常',
                    'RH API 无法访问且 Worker 已停止；NS 现有结果与暂停状态保留。','error',{'RH':state['rhRunId']})
                return True
            self.store.log('scheduler','RH 状态暂不可确认，保持现有进程：'+str(error)[:250],'warning')
            return True
        except Exception as error:
            # Retain the overlap limit if final evidence/promotion cannot be confirmed.
            self.store.log('scheduler','RH 最终证据或资源提升待重试：'+str(error)[:400],'warning')
            self.store.alert(state['id']+':rh_final_pending','RH 最终归档待重试',str(error)[:500],'warning',{'run':state['id']})
            return True

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

    def budget_tick(self):
        state=self.store.mutate(lambda s:s.update(budget=normalize(s['budget'],self.clock()),controllerHeartbeat=self.clock()),event=None)
        budget=state['budget']
        if budget['scope']!='server':return True
        remaining=budget['remainingHours']*3600
        key=state['id']+':window:'+str(budget['rentalStartedAt'])+':'+str(budget['capHours'])
        if remaining>0:
            for seconds,label in [(3600,'1小时'),(900,'15分钟')]:
                if remaining<=seconds:
                    self.store.alert(key+':'+str(seconds),'服务器总时限即将到期',
                        '服务器租用窗口剩余不足'+label+'；RH和NS共用总计时。'+('按自动衔接设置继续运行，到期后由管理员判断。' if budget['enforcement']=='notify_only' else '到期暂停NS并保留成果，RH与服务器后续处理由管理员决定。'),
                        'warning',{'remainingHours':round(budget['remainingHours'],4),'deadlineUnix':budget['deadlineAt']})
            self.flush_notices();return True
        if budget['enforcement']=='notify_only':
            self.store.alert(key+':expired','20小时计时已到',
                '服务器20小时计时已到。按管理员要求保持当前调度与运行；由管理员判断何时停止，服务器计费继续。',
                'warning',{'deadlineUnix':budget['deadlineAt'],'mode':'notify_only'})
            self.flush_notices();return True
        job=self.driver.inspect(state)
        if job and job.get('running'):
            self.driver.stop(state)
            self.store.mutate(lambda s:s.update(worker=self.driver.inspect(state)),event=None)
        message='服务器总运行时限已到；NS已停止或禁止启动，日志和成果已保留。RH保持原样，请管理员决定后续处理；服务器计费仍继续。'
        if state['status'] not in ('COMPLETED','CHECKS_COMPLETED'):
            if state.get('reason')!='budget_deadline':self.pause('budget_deadline',message)
        else:
            self.store.alert(state['id']+':budget_deadline','服务器总运行时限已到',message,'warning',{'deadlineUnix':budget['deadlineAt']})
            self.flush_notices()
        return False

    def _reconcile(self, state):
        job=self.driver.inspect(state)
        if state.get('startedAt') and state['budget'].get('scope')!='server':
            elapsed=max(0,(state.get('finishedAt') or self.clock())-state['startedAt'])
            self.store.mutate(lambda s:s.update(budget=runtime_usage(s['budget'],elapsed/3600,self.clock())),event=None)
            state=self.store.snapshot()
        if job and job.get('running'):
            if hasattr(self.driver,'metrics'):job['resources']=self.driver.metrics(state)
            self.store.mutate(lambda s:s.update(worker=job,controllerHeartbeat=self.clock()),event=None)
            if state['budget']['remainingHours']<=0 and state['budget']['enforcement']!='notify_only':
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
        try:
            if not self.budget_tick():
                latest=self.store.snapshot()
                if latest.get('startedAt') and latest.get('schedulingMode')=='parallel_replay':self.monitor_parallel(latest)
                return
        except (ValueError,TypeError,KeyError) as error:
            self.pause('budget','运行时限配置无效，NS不启动：'+str(error));return
        state=self.store.snapshot()
        if state.get('startedAt') and state.get('schedulingMode')=='parallel_replay':
            if not self.monitor_parallel(state):return
            state=self.store.snapshot()
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
            if gate['reason']=='rh_replay_overlap':self.persist_admission(payload,ledger)
            else:self.persist_rh(payload)
            # Evidence download can take time: do not use an earlier READY decision.
            payload,ledger,gate=self.observe_rh(self.store.snapshot())
            if gate['decision']=='PAUSE':
                self.pause(gate['reason'],'RH 状态在证据归档期间发生异常；NS 不启动。'); return
            if gate['decision']!='READY':
                self.store.mutate(lambda s:s.update(reason=gate['reason']),event=None); return
            state=self.store.snapshot()
            try:resources=self.driver.resources()
            except OSError as error:
                if state['budget']['enforcement']!='notify_only':raise
                resources={'samplingError':str(error)[:300]}
            resources['rhActive']=gate['reason']=='rh_replay_overlap'
            start=start_gate(state,resources,now=self.clock())
            if start['allowed'] and state['budget']['enforcement']=='notify_only':
                warnings=[name for name,key,minimum in [('CPU','cpuCount',64),('内存','memoryAvailableBytes',250000000000),('磁盘','diskFreeBytes',100*1024**3)] if not isinstance(resources.get(key),(int,float)) or resources[key]<minimum]
                if warnings:self.store.alert(state['id']+':resources_advisory','NS资源预检告警','资源预检提示 '+','.join(warnings)+' 不足；按管理员要求仍自动尝试启动，容器保留硬资源上限。','warning',{'run':state['id']})
            if not start['allowed']:
                self.pause(start['reason'],'RH 已完成，但 NS '+('剩余运行时限不足（启动至少需要5分钟）。服务器仍按小时计费。' if start['reason']=='budget' else '资源启动门禁未满足。')); return
            self.store.mutate(lambda s:s.update(status='STARTING',reason='starting',startedAt=s.get('startedAt') or self.clock()),'starting')
            job=self.driver.launch(self.store.snapshot())
            self.store.mutate(lambda s:s.update(status='RUNNING',reason='running',worker=job),'launched')
            self.store.log('scheduler','NS Worker 已在独立资源与工具链中启动。')
            message=('NS 已与 RH 内核重放并行启动；RH 最终验证仍待完成，NS 暂用 220 GB 内存上限保护 RH。'
                     if state.get('parallelAdmission') and not state['rhEvidence'].get('persisted') else
                     'RH 所有必要检查及结果持久化成功，NS 资源与预算门禁通过。')
            self.store.alert(state['id']+':started','NS 验证启动',message,'info',{'run':state['id']})
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
                self.pause('launch_error' if current.get('status')=='STARTING' or current['rhEvidence'].get('persisted') else 'rh_evidence',str(error)[:700])


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

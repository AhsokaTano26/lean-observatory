"""Deterministic, explicitly synthetic scenario engine; never used by real runs."""
import math
import time


def metrics(s, now=None):
    now=time.time() if now is None else now
    t=max(0,now-(s.get('startedAt') or s['updatedAt']))
    busy=s['status']=='running' and s['phase']=='compile'
    cpu=(63 if busy else 23)+9*math.sin(t/15)+5*math.sin(t/5.3)+2*math.sin(t/1.7)
    memory=(90+7*math.sin(t/41)+2*math.sin(t/11))*1024**3
    disk_used=min(2400,62+t*.004)*1024**3
    rx=(6.2 if busy else .65)+(.8 if busy else .2)*math.sin(t/8)+.3*math.sin(t/2.5)
    tx=(1.7 if busy else .25)+.18*math.sin(t/11)+.05*math.sin(t/3)
    return dict(source='mock_host',sampledAt=now,stale=False,hostname='mock-linode-g8',platform='Ubuntu 24.04 LTS [MOCK]',
                cpuCount=64,cpuPercent=round(max(0,min(100,cpu)),1),memoryTotalBytes=256*1024**3,memoryUsedBytes=memory,memoryPercent=round(memory/(256*1024**3)*100,1),
                diskTotalBytes=2600*1024**3,diskUsedBytes=disk_used,diskPercent=round(disk_used/(2600*1024**3)*100,3),
                networkRxBytesPerSec=max(.05,rx)*1024**2,networkTxBytesPerSec=max(.03,tx)*1024**2,
                load=[round(max(0,cpu*.54+2*math.sin(t/19)),2),round(30+3*math.sin(t/50),2),round(25+2*math.sin(t/100),2)],limitations=['MOCK · 合成服务器指标，不来自真实 Linode'])


_WEIGHTS=[1+.2*math.sin(i*.68)+.12*math.cos(i*.31) for i in range(25)]

def compiled_count(n):
    progress=max(0,min(25,n-15));whole=int(progress)
    weight=sum(_WEIGHTS[:whole])+(_WEIGHTS[whole]*(progress-whole) if whole<25 else 0)
    return min(175187,round(175187*weight/sum(_WEIGHTS)))


def tick(s, seconds=1):
    if s['status'] != 'running':
        return
    s['elapsedSeconds'] += seconds
    s['activeSeconds'] += seconds
    s['workerHeartbeat'] = time.time()
    previous=s['mockTicks']
    s['mockTicks'] = round(previous+1/max(1,s.get('mockStepTicks',1)),10)
    n = s['mockTicks']
    phase = min(5, int(n // 5)) if n < 15 else (3 if n < 40 else (4 if n < 45 else 5))
    s['phase'] = s['stages'][phase]['id']
    for i, stage in enumerate(s['stages']):
        stage['status'] = 'passed' if i < phase else ('running' if i == phase else 'pending')
        if i <= phase and stage['startedAt'] is None:
            stage['startedAt'] = time.time()
        if i < phase:
            stage.update(exitCode=0, finishedAt=stage['finishedAt'] or time.time())
    if n >= 10:
        s['provenance'].update(sha256=s['provenance']['expectedSha256'], bytes=239275554, integrity='passed', inventorySha256='mock-only-not-a-real-file-manifest')
    if n >= 15:
        s['environment'].update(actualLean='Lean (version 4.33.1) [MOCK]', actualMathlib=s['environment']['mathlib'])
        c = s['compile']
        completed=compiled_count(n)
        rate=round(max(0,completed-c['succeeded'])/max(.001,seconds),1)
        c.update(total=175187,succeeded=completed,rate=rate,currentModule=f'Supplements.Kernels.MockModule{int(n)}')
    if previous < 25 <= n and s['scenario'] != 'success':
        status = {'failure': 'failed', 'interruption': 'interrupted', 'resource': 'resource_exhausted'}[s['scenario']]
        s.update(status=status, error={'failure': '模拟 Lean 编译错误 (exit 1)', 'interruption': '模拟 Worker 中断；可从持久化进度恢复', 'resource': '模拟内存不足；任务已停止，请调整资源后恢复'}[s['scenario']])
        s['stages'][3].update(status=status, exitCode=1 if status == 'failed' else 137)
        s['compile']['failed'] = 1 if status == 'failed' else 0
        s['compile']['rate'] = 0
    if n >= 45:
        for a in s['audits']:
            a.update(type='passed', axioms='passed', dependencies=['propext', 'Classical.choice', 'Quot.sound'], output='MOCK: synthetic audit output')
    if n >= 50:
        s.update(status='checks_completed', finishedAt=time.time())
        s['compile'].update(rate=0, failed=0)
        s['stages'][5].update(status='passed', exitCode=0, finishedAt=time.time())
        for a in s['audits']:
            a['replay'] = 'passed'
    s['proofAccepted'] = False

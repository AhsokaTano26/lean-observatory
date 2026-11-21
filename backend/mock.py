"""Deterministic, explicitly synthetic scenario engine; never used by real runs."""
import math
import time


def tick(s, seconds=1):
    if s['status'] != 'running':
        return
    s['elapsedSeconds'] += seconds
    s['activeSeconds'] += seconds
    s['workerHeartbeat'] = time.time()
    s['mockTicks'] += 1
    n = s['mockTicks']
    phase = min(5, n // 5) if n < 15 else (3 if n < 40 else (4 if n < 45 else 5))
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
        c.update(total=175187, succeeded=min(175187, int((n-15)/25*175187)), rate=round(6900 + 500*math.sin(n), 1), currentModule=f'Supplements.Kernels.MockModule{n}')
    if n == 25 and s['scenario'] != 'success':
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

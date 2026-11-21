"""Verification state. Pending checks never become successful by inference."""
import copy
import re
import time
import uuid

EXPECTED_HASH = '9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc'
EXPECTED_BYTES = 239275554
MATHLIB = '0df444a360eaa60ab8c11dca51a86af692955474'
THEOREMS = [
    ('riemannHypothesis', 'RiemannHypothesis'),
    ('riemannZeta_eq_zero_re', 'RiemannZetaZerosOnLine'),
    ('LFunction_ne_zero_of_half_lt_re', 'DirichletLNonvanishingRightOfHalf'),
    ('LFunction_eq_zero_re', 'DirichletLZerosOnLine'),
    ('LFunction_eq_zero_re_of_isPrimitive', 'PrimitiveDirichletLZerosOnLine'),
]
STAGES = [('download', '原始源码下载'), ('integrity', 'SHA-256 完整性校验'),
          ('dependencies', '锁定依赖准备'), ('compile', '完整源码编译'),
          ('audit', '类型与公理审计'), ('replay', '独立进程内核重放')]


def initial_state(mode='real'):
    return dict(id=uuid.uuid4().hex[:12], mode=mode, status='waiting', phase='download',
                desired='running', scenario='success', startedAt=None, finishedAt=None,
                updatedAt=time.time(), elapsedSeconds=0, activeSeconds=0,
                workerHeartbeat=None, error=None, proofAccepted=False,
                compile=dict(expectedTotal=175187, total=None, succeeded=0, failed=0,
                             rate=0, recent=[], currentModule=None, jobs=60),
                stages=[dict(id=i, label=l, status='pending', startedAt=None,
                             finishedAt=None, exitCode=None) for i, l in STAGES],
                audits=[dict(name=n, expectedType=t, type='pending', axioms='pending',
                             replay='pending', dependencies=[], output=None) for n, t in THEOREMS],
                provenance=dict(url='https://alpo.ge/', expectedSha256=EXPECTED_HASH,
                                sha256=None, expectedBytes=EXPECTED_BYTES, bytes=None,
                                hashSource='用户提供 + tamnd/riemann-lean 社区记录；非作者签名',
                                integrity='pending', inventorySha256=None),
                environment=dict(lean='v4.33.1', mathlib=MATHLIB, actualLean=None,
                                 actualMathlib=None, platform=None, python=None),
                semanticReview='pending', independentChecker='not_run',
                commands=[], artifacts=[], mockTicks=0)


def derived(state, now=None):
    s = copy.deepcopy(state)
    now = time.time() if now is None else now
    c = s['compile']
    if s['status']!='running': c['rate']=0
    if s['status']=='paused':
        for stage in s['stages']:
            if stage['status']=='running': stage['status']='paused'
    total = c['total']
    c['remaining'] = max(0, total - c['succeeded'] - c['failed']) if total is not None else None
    c['percent'] = round(min(100, 100 * c['succeeded'] / total), 2) if total else 0
    c['etaSeconds'] = round(c['remaining'] / c['rate']) if c['rate'] > 0 and c['remaining'] is not None and s['status'] == 'running' else None
    # All durations originate in the worker. Never advance a paused task in the browser.
    s['checksPassed'] = sum(x['status'] == 'passed' for x in s['stages'])
    s['overallPercent'] = round((s['checksPassed'] + (c['percent']/100 if s['phase'] == 'compile' and s['stages'][3]['status'] != 'passed' else 0))/6*100, 1)
    s['proofAccepted'] = False  # Semantic statement review is a separate human decision.
    c.pop('recent', None)
    return s


def audit_axioms(output, name):
    matches = re.findall(r"^'" + re.escape(name) + r"' depends on axioms:\s*\[([^\]]*)\]\s*$", output, re.MULTILINE)
    empty = re.findall(r"^'" + re.escape(name) + r"' does not depend on any axioms\s*$", output, re.MULTILINE)
    if len(matches)+len(empty)!=1:
        return dict(passed=False, dependencies=[], error='缺少可解析的公理输出')
    deps = [x.strip() for x in matches[0].split(',') if x.strip()] if matches else []
    forbidden = set(deps) - {'propext', 'Classical.choice', 'Quot.sound'}
    return dict(passed=not forbidden, dependencies=deps,
                error=('非允许公理: ' + ', '.join(sorted(forbidden))) if forbidden else None)

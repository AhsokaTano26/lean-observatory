"""Host-only Docker driver. Every mutation targets this add-on's own NS job.

``launch`` is called only after the controller has just rechecked the RH run
and complete run ledger. An online RH worker daemon is not active RH work.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from .gates import start_gate, validate_result
from .admission import verify_parallel, has_parallel
from .budget import normalize, available_seconds, runtime_usage


PROJECT = 'lean-observatory-ns'
RH_WORKER = 'lean-observatory-worker-1'
RUN_LABEL = 'io.lean-observatory.ns.run'
COMMIT_LABEL = 'io.lean-observatory.ns.commit'


class DockerDriver:
    def __init__(self, deployment, data_root, executor=None, rh_barrier=None):
        self.deployment = Path(deployment).resolve()
        self.data_root = Path(data_root).resolve()
        self.executor = executor or subprocess.run
        self.rh_barrier = rh_barrier

    def _run(self, argv, timeout=30, env=None):
        return self.executor(argv, capture_output=True, text=True, check=False,
                             timeout=timeout, env=env)

    @staticmethod
    def _name(state):
        run = state.get('id')
        if not isinstance(run, str) or not re.fullmatch(r'ns-[0-9a-f]{12}', run):
            raise ValueError('invalid NS run identity')
        return PROJECT + '-' + run

    def _inspect_name(self, name):
        result = self._run(['docker', 'container', 'inspect', name])
        if result.returncode:
            if 'No such container' in result.stderr or 'No such object' in result.stderr:
                return None
            raise RuntimeError('Docker inspection failed: ' + result.stderr[:400])
        try:
            rows = json.loads(result.stdout)
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError('invalid inspect response')
            return rows[0]
        except (ValueError, TypeError) as error:
            raise RuntimeError('Invalid Docker inspection response') from error

    def rh_running(self):
        row = self._inspect_name(RH_WORKER)
        return row is not None and row.get('State', {}).get('Running') is True

    def resources(self):
        available = 0
        try:
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemAvailable:'):
                    available = int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        disk_root = self.data_root
        while not disk_root.exists() and disk_root != disk_root.parent:
            disk_root = disk_root.parent
        return {'cpuCount': os.cpu_count() or 0, 'memoryAvailableBytes': available,
                'diskFreeBytes': shutil.disk_usage(disk_root).free}

    def start_resources(self, state):
        try:resources=self.resources()
        except (OSError,subprocess.SubprocessError) as error:
            if normalize(state['budget'])['enforcement']!='notify_only':raise
            resources={'samplingError':str(error)[:300]}
        return {**resources,'rhActive':False}

    def inspect(self, state):
        name = self._name(state)
        row = self._inspect_name(name)
        if row is None:
            return None
        labels = row.get('Config', {}).get('Labels') or {}
        if (row.get('Name') != '/' + name or labels.get('com.docker.compose.project') != PROJECT or
                labels.get(RUN_LABEL) != state['id'] or
                labels.get(COMMIT_LABEL) != state.get('spec', {}).get('commit')):
            raise RuntimeError('Refusing foreign container with colliding NS name')
        status = row.get('State', {})
        return {'running': status.get('Running') is True,
                'exitCode': None if status.get('Running') else status.get('ExitCode'),
                'containerId': row.get('Id'), 'image': row.get('Image'),
                'startedAt': status.get('StartedAt'), 'finishedAt': status.get('FinishedAt'),
                'oomKilled': status.get('OOMKilled') is True, 'name': name}

    def metrics(self, state):
        info=self.inspect(state)  # Ownership check precedes even read-only sampling.
        if not info or not info['running']:
            return {'source':'stopped','cpuPercent':None,'memoryBytes':None}
        try:
            result=self._run(['docker','stats','--no-stream','--format','{{json .}}',self._name(state)],timeout=5)
            if result.returncode:raise ValueError('stats unavailable')
            row=json.loads(result.stdout)
            cpu=float(row['CPUPerc'].rstrip('%'))
            match=re.fullmatch(r'([0-9.]+)\s*(B|KiB|MiB|GiB|TiB|kB|MB|GB|TB)',row['MemUsage'].split('/')[0].strip())
            if not match:raise ValueError('unknown memory unit')
            units={'B':1,'KiB':1024,'MiB':1024**2,'GiB':1024**3,'TiB':1024**4,'kB':1000,'MB':1000**2,'GB':1000**3,'TB':1000**4}
            memory=int(float(match[1])*units[match[2]])
            if not 0<=cpu<1e6 or memory<0:raise ValueError('invalid sample')
            return {'source':'docker_stats','cpuPercent':cpu,'memoryBytes':memory,'sampledAt':time.time()}
        except (ValueError,KeyError,TypeError,subprocess.SubprocessError):
            return {'source':'unavailable','cpuPercent':None,'memoryBytes':None}

    def _evidence(self, state):
        if not state.get('rhEvidence',{}).get('persisted') and has_parallel(state):
            verify_parallel(self.data_root,state)
            return
        evidence = state.get('rhEvidence', {})
        if evidence.get('runId') != state.get('rhRunId') or not evidence.get('runId'):
            raise ValueError('RH evidence run identity mismatch')
        for kind in ('result', 'logs'):
            relative = evidence.get(kind + 'Path')
            expected = evidence.get(kind + 'Sha256')
            size = evidence.get(kind + 'Bytes')
            if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
                raise ValueError('missing RH ' + kind + ' evidence path')
            path = (self.data_root / relative).resolve()
            if not path.is_relative_to(self.data_root) or not path.is_file():
                raise ValueError('RH evidence path outside NS data')
            if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
                raise ValueError('missing RH ' + kind + ' hash')
            if type(size) is not int or size <= 0 or path.stat().st_size != size:
                raise ValueError('RH ' + kind + ' evidence size mismatch')
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError('RH ' + kind + ' evidence hash mismatch')
            if kind == 'result':
                validate_result(json.loads(path.read_text()), state['rhRunId'])

    def launch(self, state):
        # No Docker calls or host resource inspection until the financial and
        # durable-dependency gates have passed, including the default cap=0.
        preliminary = start_gate(state, {})
        if preliminary['reason'] in ('budget', 'rh_evidence'):
            raise ValueError(preliminary['reason'])
        name = self._name(state)
        self._evidence(state)
        existing = self.inspect(state)
        if existing is not None and existing['running']:
            return existing
        allowed = start_gate(state, self.start_resources(state))
        if not allowed['allowed']:
            raise ValueError(allowed['reason'])
        if existing is not None:
            if not self.rh_barrier or not self.rh_barrier():raise ValueError('rh_active')
            result = self._run(['docker', 'container', 'start', name], timeout=120)
            if result.returncode:
                raise RuntimeError('NS resume failed: ' + result.stderr[:400])
            return self.inspect(state)
        env = {**os.environ, 'NS_DATA_ROOT': str(self.data_root), 'NS_RUN_ID': state['id'],
               'NS_CONTAINER_NAME': name, 'NS_SOURCE_COMMIT': state.get('spec', {}).get('commit', ''),
               'NS_MEMORY_BYTES':str(220000000000 if has_parallel(state) and not state.get('rhEvidence',{}).get('persisted') else 250000000000)}
        compose = ['docker', 'compose', '-p', PROJECT, '--project-directory', str(self.deployment),
                   '--env-file', str(self.deployment / '.env'), '-f', str(self.deployment / 'compose.ns-worker.yaml')]
        budget = normalize(state['budget'])
        remaining_seconds = 7200 if budget['enforcement']=='notify_only' else available_seconds(budget)
        began = time.monotonic()
        result = self._run([*compose, 'build', 'ns-worker'], timeout=min(7200, max(1, int(remaining_seconds))), env=env)
        if result.returncode:
            raise RuntimeError('NS image build failed: ' + result.stderr[:400])
        # A colliding container or changed resources after a long image build
        # never authorizes recreation of anything already present.
        existing = self.inspect(state)
        if existing is not None:
            return existing
        charged_state = {**state, 'budget': runtime_usage(budget, budget['usedHours']+max(0,time.monotonic()-began)/3600)}
        allowed = start_gate(charged_state, self.start_resources(state))
        if not allowed['allowed']:
            raise ValueError(allowed['reason'])
        if not self.rh_barrier or not self.rh_barrier():raise ValueError('rh_active')
        result = self._run([*compose, 'run', '--detach', '--no-deps', '--name', name, '-T', 'ns-worker'], timeout=120, env=env)
        if result.returncode:
            raise RuntimeError('NS launch failed: ' + result.stderr[:400])
        info = self.inspect(state)
        if info is None:
            raise RuntimeError('NS container was not registered after launch')
        return info

    def stop(self, state):
        info = self.inspect(state)
        if info is None or not info['running']:
            return
        result = self._run(['docker', 'container', 'stop', '--time', '30', self._name(state)], timeout=45)
        if result.returncode:
            raise RuntimeError('NS stop failed: ' + result.stderr[:400])

    def promote(self, state):
        """Raise only the matching NS container's memory ceiling, without restart."""
        if state.get('rhEvidence',{}).get('persisted') is not True:
            raise ValueError('RH final evidence required for NS resource promotion')
        self._evidence(state)
        info=self.inspect(state)
        if info is None:return
        result=self._run(['docker','container','update','--memory','250000000000',
                          '--memory-swap','250000000000',self._name(state)])
        if result.returncode:raise RuntimeError('NS resource promotion failed: '+result.stderr[:400])

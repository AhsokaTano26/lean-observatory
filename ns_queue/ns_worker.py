"""Fixed-source NS verification, isolated from RH and gated before any heavy operation.

This module implements preparation, not a claim that NS or its external checkers
have run. A zero-budget invocation records NOT_RUN and executes no child/download.
"""
import argparse
import copy
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import time
import urllib.request

from .process import run_process
from . import sandbox
from .store import QueueStore
from .budget import normalize, can_start, runtime_usage
from .gates import validate_result
from .admission import verify_parallel, has_parallel

STAGES = ('source', 'dependencies', 'compile', 'audit', 'kernel', 'independent', 'persist')
PIN = 'f9e8bc5b38b6e212696e8a30e3e91517af887bbd'
ARCHIVE_SHA = '8ac9b0b2db70385f1e466b6ad600476dcad62d687d78a38f24fd1e8662bd04a0'


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''): digest.update(chunk)
    return digest.hexdigest()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.partial')
    with temporary.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def load_manifest():
    return json.loads(Path(__file__).with_name('manifest.json').read_text())


def validate_spec(spec):
    canonical = load_manifest()
    if (spec != canonical or spec.get('commit') != PIN or
            spec.get('archiveSha256') != ARCHIVE_SHA or spec.get('expectedFileCount') != 2659):
        raise ValueError('NS specification differs from the fixed reviewed manifest')


def budget_available(budget, now=None):
    return can_start(budget, now)


def durable_rh(root, state):
    evidence = state.get('rhEvidence', {})
    if evidence.get('persisted') is not True and has_parallel(state):
        try:verify_parallel(root,state)
        except ValueError:return False
        return True
    if evidence.get('persisted') is not True or evidence.get('runId') != state['rhRunId']: return False
    try:
        for prefix in ['result', 'logs']:
            path = Path(root) / evidence[prefix + 'Path']
            if (path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()) or
                    path.stat().st_size != evidence[prefix + 'Bytes'] or
                    file_hash(path) != evidence[prefix + 'Sha256']): return False
        validate_result(json.loads((Path(root) / evidence['resultPath']).read_text()), state['rhRunId'])
    except (OSError, ValueError, TypeError, KeyError): return False
    return True


def extract_verified(archive, destination, expected_sha, expected_bytes):
    archive = Path(archive); destination = Path(destination)
    if archive.stat().st_size != expected_bytes or file_hash(archive) != expected_sha:
        raise ValueError('source archive bytes/SHA256 mismatch')
    # Validate every member before writing anything. No symlinks, hardlinks,
    # devices, precompiled declarations or archive-provided build roots.
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers(); roots = set(); names = set(); total = 0
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError('unsafe archive path')
            roots.add(path.parts[0]); relative = PurePosixPath(*path.parts[1:])
            if not (member.isfile() or member.isdir()): raise ValueError('nonregular source archive member')
            if '.lake' in path.parts or path.suffix in {'.olean', '.ilean', '.so', '.o', '.a'}:
                raise ValueError('archive contains precompiled/build artifacts')
            if str(relative) in names: raise ValueError('duplicate source archive member')
            names.add(str(relative)); total += member.size
        if len(roots) != 1 or total > 512 * 1024**2: raise ValueError('unexpected source archive layout/size')
        staging = destination.with_name(destination.name + '.partial')
        if staging.exists(): shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for member in members:
            relative = PurePosixPath(*PurePosixPath(member.name).parts[1:])
            if str(relative) == '.': continue
            target = staging / str(relative)
            if member.isdir(): target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o644)
        if destination.exists(): raise ValueError('refusing to replace existing source tree')
        staging.rename(destination)


def lean_code(text):
    """Remove nested Lean comments and string literals, retaining newlines for line audit."""
    out = []; index = 0; depth = 0; string = False
    while index < len(text):
        pair = text[index:index+2]; char = text[index]
        if depth:
            if pair == '/-': depth += 1; out.extend('  '); index += 2; continue
            if pair == '-/': depth -= 1; out.extend('  '); index += 2; continue
            out.append('\n' if char == '\n' else ' '); index += 1; continue
        if string:
            if char == '\\' and index + 1 < len(text): out.extend('  '); index += 2; continue
            if char == '"': string = False
            out.append('\n' if char == '\n' else ' '); index += 1; continue
        if pair == '/-': depth = 1; out.extend('  '); index += 2; continue
        if pair == '--':
            end = text.find('\n', index)
            if end < 0: end = len(text)
            out.extend(' ' * (end-index)); index = end; continue
        if char == '"': string = True; out.append(' ')
        else: out.append(char)
        index += 1
    if depth or string: raise ValueError('unterminated Lean comment/string in source audit')
    return ''.join(out)


def source_files(root):
    """Enumerate original files without traversing any dependency/build cache."""
    root = Path(root); files = []
    for base, directories, names in os.walk(root):
        directories[:] = sorted(name for name in directories if name != '.lake')
        files.extend(Path(base) / name for name in sorted(names))
    return sorted(files)


def audit_sources(root, spec):
    root = Path(root)
    files = [path for path in source_files(root) if path.suffix == '.lean']
    if len(files) != spec['expectedFileCount']: raise ValueError('original Lean file count mismatch')
    exceptions = {entry['path']: entry for entry in spec['sorryExceptions']}
    if any(not (root / name).is_file() for name in exceptions):
        raise ValueError('missing fixed challenge exception file')
    forbidden = re.compile(r'\b(?:sorry|admit|sorryAx|axiom|unsafe|implemented_by|extern|'
                           r'native_decide|run_tac|run_cmd|elab|elab_rules|macro|syntax|initialize|'
                           r'builtin_initialize|addDecl|addAndCompile|ofReduceBool|ofReduceNat|run_meta)\b'
                           r'|#eval|debug\.skipKernelTC|debug\.skip|trustLevel')
    inventory = {}
    for file in files:
        if file.is_symlink(): raise ValueError('symlink Lean source')
        relative = str(file.relative_to(root)); text = file.read_text(); digest = file_hash(file)
        if relative in exceptions:
            exception = exceptions[relative]
            if digest != exception['sha256']: raise ValueError('changed official challenge exception bytes')
            lines = text.splitlines(keepends=True)
            for line in exception['lines']:
                if lines[line-1].rstrip('\n\r') != '  sorry': raise ValueError('challenge placeholder line mismatch')
                lines[line-1] = '\n'
            text = ''.join(lines)
        match = forbidden.search(lean_code(text))
        if match: raise ValueError('forbidden proof bypass in ' + relative + ': ' + match.group())
        inventory[relative] = digest
    return {'files': len(files), 'inventory': inventory, 'sorryExceptions': spec['sorryExceptions'],
            'proofBypassCount': 0, 'status': 'PASSED', 'kind': 'STATIC_SOURCE_AUDIT'}


def verify_source_identity(original, actual, spec):
    expected = audit_sources(original, spec)
    observed = audit_sources(actual, spec)
    if expected['inventory'] != observed['inventory']:
        raise ValueError('sandbox project differs from verified source archive')
    return observed


def parse_audit(output, names):
    types = []; axioms = {}
    for line in output.splitlines():
        if 'NS_TYPE_OK|' in line:
            types.append(line.split('NS_TYPE_OK|', 1)[1].strip())
        if 'NS_AXIOMS|' in line:
            fields = line.split('NS_AXIOMS|', 1)[1].strip().split('|')
            if len(fields) != 2 or fields[0] in axioms: raise ValueError('duplicate/malformed axiom evidence')
            axioms[fields[0]] = [value.strip() for value in fields[1].split(',') if value.strip()]
    if sorted(types) != sorted(names) or set(axioms) != set(names):
        raise ValueError('both actual proof targets require exact type and axiom evidence')
    allowed = {'propext', 'Classical.choice', 'Quot.sound'}
    rows = []
    for name in names:
        if not axioms[name] or not set(axioms[name]) <= allowed:
            raise ValueError('unpermitted proof axiom for ' + name)
        rows.append({'name': name, 'type': 'PASSED', 'axioms': 'PASSED',
                     'dependencies': axioms[name], 'kernel': 'PENDING', 'independent': 'PENDING'})
    return rows


def validate_independent_output(output):
    required = ['Running nanoda kernel on solution', 'nanoda kernel accepts the solution',
                'Running Lean default kernel on solution.', 'Lean default kernel accepts the solution',
                'Your solution is okay!']
    if any(marker not in output for marker in required): raise ValueError('missing real Comparator/kernel acceptance')
    if re.search(r'fake[-_]landrun|unsandboxed|\[landrun:warn\]|best.effort|kernel rejects', output, re.I):
        raise ValueError('independent sandbox/checker did not meet strict requirements')


class Checkpoints:
    """Successful checkpoints are immutable and verified before skipping any work."""
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)

    def path(self, stage):
        if stage not in STAGES: raise ValueError('unknown checkpoint stage')
        return self.root / (stage + '.json')

    def run(self, stage, input_hash, action):
        path = self.path(stage)
        if path.exists():
            checkpoint = json.loads(path.read_text())
            if (checkpoint.get('status') != 'PASSED' or type(checkpoint.get('exitCode')) is not int or
                    checkpoint.get('exitCode') != 0 or
                    checkpoint.get('inputSha256') != input_hash or not checkpoint.get('outputs')):
                raise ValueError('checkpoint input/status changed: ' + stage)
            for output in checkpoint['outputs']:
                file = Path(output['path'])
                if (file.is_symlink() or not file.is_file() or file.stat().st_size != output['bytes'] or
                        file_hash(file) != output['sha256']):
                    raise ValueError('checkpoint artifact changed: ' + stage)
            return True
        outputs = action()
        if not outputs: raise ValueError('stage produced no durable evidence: ' + stage)
        evidence = []
        for file in outputs:
            file = Path(file)
            if file.is_symlink() or not file.is_file(): raise ValueError('invalid checkpoint output')
            evidence.append({'path': str(file.resolve()), 'bytes': file.stat().st_size, 'sha256': file_hash(file)})
        atomic_json(path, {'stage': stage, 'status': 'PASSED', 'exitCode': 0,
                           'inputSha256': input_hash, 'outputs': evidence, 'completedAt': time.time()})
        return False


class Blocked(RuntimeError): pass


class CommandFailed(RuntimeError):
    def __init__(self, message, code): super().__init__(message); self.code = code


class NSWorker:
    def __init__(self, root, executor=run_process, spec=None, sandbox_root=None):
        self.root = Path(root).resolve(); self.store = QueueStore(self.root); self.executor = executor
        self.spec = spec
        self.sandbox_root = Path(sandbox_root or os.environ.get('SANDBOX_ROOT', '/sandbox')).resolve()
        self.work = self.root / 'worker'; self.original = self.work / 'original'
        self.project = self.sandbox_root / 'work/ns/project'
        self.tools = self.sandbox_root / 'work/ns/tools'; self.stage = None
        self.run_start = None; self.initial_estimate = 0; self.seen_modules = set()

    def register_artifacts(self):
        """Publish complete raw evidence through the queue's own download root."""
        files = []
        for directory in [self.work / 'logs', self.work / 'checkpoints', self.root / 'artifacts']:
            if directory.is_dir(): files.extend(path for path in directory.rglob('*') if path.is_file())
        if self.work.is_dir():
            files.extend(path for path in self.work.iterdir() if path.is_file() and path.suffix != '.partial')
        entries = []
        for path in sorted(set(files)):
            if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                raise ValueError('artifact path escaped NS data volume')
            entries.append({'name': path.name, 'path': str(path.relative_to(self.root)),
                            'sha256': file_hash(path), 'bytes': path.stat().st_size})
        def publish(s):
            current = {entry.get('path', entry['name']): entry for entry in s.get('artifacts', [])}
            current.update({entry['path']: entry for entry in entries})
            s['artifacts'] = list(current.values())
        self.store.mutate(publish, 'artifacts_registered')
        return entries

    def _beat(self):
        state = self.store.snapshot(); budget = normalize(state['budget'])
        if state.get('desired') in {'PAUSED', 'CANCELLED', 'paused', 'cancelled'}:
            raise Blocked('operator_requested_stop')
        estimate = self.initial_estimate + (time.monotonic() - self.run_start) / 3600
        def beat(s):
            s['workerHeartbeat'] = time.time(); s['budget'] = runtime_usage(s['budget'],estimate)
            s['execution'] = 'RUNNING'; s['status'] = 'RUNNING'
        updated_budget=self.store.mutate(beat)['budget']
        if updated_budget['remainingHours']<=0 and updated_budget['enforcement']!='notify_only': raise Blocked('budget')

    def _command(self, argv, cwd=None, network=False, environment=None, stdout_path=None, timeout=259200):
        self._beat(); cwd = Path(cwd or self.project)
        home = cwd.parent / ('home-' + cwd.name)
        if not home.exists():
            home.mkdir(mode=0o700); os.chown(home, sandbox.BUILD_UID, sandbox.BUILD_UID)
        actual = sandbox.command(self.sandbox_root, cwd, argv, network=network, home=home,
                                 environment=environment)
        state = self.store.snapshot(); index = len(state.get('commands', []))
        log = self.work / 'logs' / f'{index:04d}-{self.stage}.log'
        record = {'stage': self.stage, 'argv': argv, 'cwd': str(cwd), 'status': 'RUNNING',
                  'startedAt': time.time(), 'finishedAt': None, 'exitCode': None,
                  'logFile': str(log.relative_to(self.root)), 'sandbox': True, 'buildUid': sandbox.BUILD_UID}
        self.store.mutate(lambda s: s.setdefault('commands', []).append(record), 'command_started')
        def line(text):
            self.store.log(self.stage, text, 'error' if 'error:' in text.lower() else 'info')
            if self.stage == 'compile':
                found = re.search(r'(?:Built|Replayed)\s+((?:NavierStokes|Euler|ComparatorChallenges)(?:\.[\w]+)*)', text)
                if found:
                    self.seen_modules.add(found[1])
                    def progress(s):
                        s['compile'].update(succeeded=len(self.seen_modules), currentModule=found[1])
                    self.store.mutate(progress)
        try:
            result = self.executor(actual, cwd=self.sandbox_root, log_path=log, on_line=line,
                heartbeat=self._beat, timeout=timeout, stdout_path=stdout_path,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
        except BaseException as error:
            def interrupted(s):
                s['commands'][index].update(status='INTERRUPTED', finishedAt=time.time(),
                    exitCode=getattr(error, 'child_exit_code', None), error=str(error))
            self.store.mutate(interrupted, 'command_interrupted'); raise
        def finish(s):
            s['commands'][index].update(status='PASSED' if result.exit_code == 0 and not result.termination else 'FAILED',
                exitCode=result.exit_code, finishedAt=time.time(), termination=result.termination,
                logSha256=file_hash(log))
        self.store.mutate(finish, 'command_finished')
        if result.exit_code != 0 or result.termination:
            raise CommandFailed('actual child failed: ' + str(argv) + ' (' + str(result.exit_code) + ')', result.exit_code)
        return result.output

    def _config(self, project):
        for relative, expected in self.spec['configuration'].items():
            if file_hash(project / relative) != expected['sha256']:
                raise ValueError('original configuration changed: ' + relative)

    def _source(self):
        archive = self.work / 'source.tar.gz'
        if not archive.exists():
            partial = archive.with_suffix('.partial')
            request = urllib.request.Request(self.spec['archiveUrl'], headers={'User-Agent': 'NS-fixed-verifier'})
            with urllib.request.urlopen(request, timeout=60) as response, partial.open('wb') as stream:
                size = 0
                while chunk := response.read(1024**2):
                    size += len(chunk)
                    if size > self.spec['archiveBytes']: raise ValueError('oversize source download')
                    stream.write(chunk); self._beat()
                stream.flush(); os.fsync(stream.fileno())
            partial.rename(archive)
        if not self.original.exists():
            extract_verified(archive, self.original, self.spec['archiveSha256'], self.spec['archiveBytes'])
        elif file_hash(archive) != self.spec['archiveSha256'] or archive.stat().st_size != self.spec['archiveBytes']:
            raise ValueError('changed existing source archive')
        self._config(self.original); report = audit_sources(self.original, self.spec)
        output = self.work / 'source-report.json'; atomic_json(output, report)
        sandbox.prepare(self.sandbox_root, self.original)
        self._config(self.project)
        verify_source_identity(self.original, self.project, self.spec)
        return [archive, output, *source_files(self.original), *source_files(self.project)]

    def _products(self, project=None):
        project = project or self.project
        return [project / '.lake/build/lib/lean' / path.relative_to(self.original).with_suffix('.olean')
                for path in sorted(self.original.rglob('*.lean'))]

    def _dependencies(self):
        if any(path.exists() for path in self._products()):
            raise ValueError('root project has precompiled artifacts before dependency preparation')
        # This action is skipped when a verified dependency checkpoint exists.
        # Otherwise a prior attempt may have frozen these nested trees before a
        # later cache/network failure. Discard them, without chowning/chmodding
        # untrusted existing files, and rebuild the fixed sources as BUILD_UID.
        expected_tools = self.sandbox_root / 'work/ns/tools'
        if self.tools != expected_tools or self.tools.is_symlink() or self.tools.resolve() != expected_tools:
            raise ValueError('tool rebuild path escaped the owned NS sandbox')
        if self.tools.exists():
            if not shutil.rmtree.avoids_symlink_attacks:
                raise RuntimeError('safe descriptor-based tool cleanup is unavailable')
            shutil.rmtree(self.tools)
        self.tools.mkdir(parents=True, exist_ok=True)
        os.chown(self.tools, sandbox.BUILD_UID, sandbox.BUILD_UID)
        self._command(['/bin/bash', '/opt/ns-queue/build-tools.sh'], self.tools, network=True)
        binary_paths = [self.tools / 'landrun/landrun', self.tools / 'nanoda/target/release/nanoda_bin',
                        self.tools / 'comparator/.lake/build/bin/comparator',
                        self.tools / 'comparator/.lake/packages/lean4export/.lake/build/bin/lean4export']
        if any(not path.is_file() or path.is_symlink() for path in binary_paths):
            raise Blocked('independent_tools_missing')
        actual = {}
        for name, expected in [('landrun', 'landrun'), ('nanoda', 'nanoda'), ('comparator', 'Comparator')]:
            actual[expected] = self._command(['git', '-C', '/work/ns/tools/' + name, 'rev-parse', 'HEAD'], self.tools).strip()
            if actual[expected] != self.spec['tools'][expected]['commit']:
                raise ValueError('independent tool revision mismatch: ' + name)
        exporter = self.tools / 'comparator/.lake/packages/lean4export'
        actual['lean4export'] = self._command(['git', '-C', '/work/ns/tools/comparator/.lake/packages/lean4export',
                                               'rev-parse', 'HEAD'], self.tools).strip()
        if actual['lean4export'] != self.spec['tools']['lean4export']['commit']:
            raise ValueError('exporter revision mismatch')
        sandbox.freeze(self.tools)
        version = self._command(['lean', '--version'])
        if not re.search(r'\bversion 4\.34\.0-rc2(?:[, )]|$)', version): raise ValueError('Lean toolchain mismatch')
        self._command(['lake', 'exe', 'cache', 'get'], network=True)
        self._config(self.project)
        dependencies = self._dependency_refs(self.project)
        if any(path.exists() for path in self._products()): raise ValueError('cache supplied root project artifacts')
        output = self.work / 'dependency-report.json'
        atomic_json(output, {'toolchain': version.strip(), 'dependencies': dependencies,
                            'toolRevisions': actual, 'toolBinaries': {str(path): file_hash(path) for path in binary_paths},
                            'compatibility': 'BUILT_PENDING_FULL_CHECK', 'rootBuildInitiallyEmpty': True})
        libraries = []
        for library in [self.tools / 'comparator/.lake/build/lib', exporter / '.lake/build/lib']:
            if library.is_dir(): libraries.extend(path for path in library.rglob('*') if path.is_file())
        return [output, *binary_paths, *libraries, *[self.project / path for path in self.spec['configuration']]]

    def _dependency_refs(self, project):
        result = {}
        for dependency in self.spec['dependencies']:
            path = '/' + str((project / '.lake/packages' / dependency['name']).relative_to(self.sandbox_root))
            revision = self._command(['git', '-C', path, 'rev-parse', 'HEAD'], project).strip()
            if revision != dependency['rev']: raise ValueError('locked dependency revision mismatch: ' + dependency['name'])
            result[dependency['name']] = revision
        return result

    def _compile(self):
        self._config(self.project); self._dependency_refs(self.project)
        self._command(['lake', 'build'])
        self._config(self.project)
        products = self._products()
        if any(not path.is_file() for path in products): raise ValueError('full build omitted original project modules')
        self.store.mutate(lambda s: s['compile'].update(total=2659, succeeded=2659, failed=0), 'full_compile_verified')
        output = self.work / 'compile-report.json'
        atomic_json(output, {'command': ['lake', 'build'], 'defaultTargets': self.spec['defaultTargets'],
                             'total': 2659, 'succeeded': 2659, 'failed': 0,
                             'rootArtifactsSuppliedByArchiveOrCache': False})
        # Lean 4 can split proof bodies into .olean.private/.olean.server files.
        # Bind all library artifacts, not just the public .olean headers.
        library = self.project / '.lake/build/lib/lean'
        return [output, *[path for path in library.rglob('*') if path.is_file()]]

    def _audit(self):
        self._config(self.project)
        audit_sources(self.project, self.spec)
        script = self.sandbox_root / 'work/ns/evidence/audit.lean'
        script.write_text(audit_script(self.spec['theorems'])); script.chmod(0o644)
        shutil.copyfile(script, self.work / 'audit.lean')
        output = self._command(['lake', 'env', 'lean', '/work/ns/evidence/audit.lean'])
        rows = parse_audit(output, self.spec['theorems'])
        self.store.mutate(lambda s: s.update(audits=rows), 'proof_axioms_verified')
        report = self.work / 'audit-report.json'; atomic_json(report, rows)
        return [script, report]

    def _tool_environment(self):
        return {'COMPARATOR_LANDRUN': '/usr/local/bin/comparator-landrun',
                'COMPARATOR_LEAN4EXPORT': '/work/ns/tools/comparator/.lake/packages/lean4export/.lake/build/bin/lean4export',
                'COMPARATOR_NANODA': '/work/ns/tools/nanoda/target/release/nanoda_bin'}

    def _kernel(self):
        exported = self.work / 'solution.ndjson'
        self._command(['lake', 'env', self._tool_environment()['COMPARATOR_LEAN4EXPORT'],
                       self.spec['solutionModule'], '--', *self.spec['theorems']], stdout_path=exported)
        # Export is copied into chroot as immutable supervisor-owned data.
        target = self.sandbox_root / 'work/ns/evidence/solution.ndjson'
        shutil.copyfile(exported, target); target.chmod(0o644)
        script = target.with_name('replay.lean'); script.write_text(REPLAY); script.chmod(0o644)
        shutil.copyfile(script, self.work / 'replay.lean')
        output = self._command(['lake', 'env', 'lean', '--run', '/work/ns/evidence/replay.lean',
                                '/work/ns/evidence/solution.ndjson'], self.tools / 'comparator')
        if 'NS_KERNEL_OK' not in output: raise ValueError('fresh Lean kernel replay did not accept export')
        report = self.work / 'kernel-report.json'
        atomic_json(report, {'status': 'PASSED', 'implementation': 'fresh Lean kernel', 'exportSha256': file_hash(exported)})
        self.store.mutate(lambda s: [row.update(kernel='PASSED') for row in s['audits']], 'fresh_kernel_verified')
        return [exported, script, report]

    def _independent(self):
        # Discard any previous incomplete checker build; never import challenge
        # into the proof-audit environment or supply project oleans to checker.
        checker = self.sandbox_root / 'work/ns/checker'
        if checker.exists(): shutil.rmtree(checker)
        home = checker.parent / 'home-checker'
        if home.exists(): shutil.rmtree(home)
        sandbox.prepare(self.sandbox_root, self.original, 'checker')
        self._command(['lake', 'exe', 'cache', 'get'], checker, network=True)
        self._config(checker); self._dependency_refs(checker)
        if any(path.exists() for path in self._products(checker)): raise ValueError('checker root was precompiled')
        af = self._command(['python3', '/opt/ns-queue/child.py', '--probe-af-unix'], checker)
        abi = self._command(['python3', '/opt/ns-queue/child.py', '--probe-landlock'], checker)
        if 'NS_AF_UNIX_DENIED' not in af or not re.search(r'NS_LANDLOCK_ABI\|(?:[4-9]|[1-9]\d+)\b', abi):
            raise Blocked('independent_sandbox_unavailable')
        probe = '/work/ns/evidence/landlock-write-probe'
        self._command(['python3', '-c', 'open(' + repr(probe) + ',"w").write("baseline")'], checker)
        (self.sandbox_root / probe.lstrip('/')).unlink()
        test = ('import sys\ntry: open(' + repr(probe) + ',"w").write("escaped")\n'
                'except PermissionError: print("NS_LANDLOCK_DENIED"); sys.exit(0)\nsys.exit(11)')
        denial = self._command(['/usr/local/bin/comparator-landrun', '--ro', '/', '--rox', '/usr',
                                '-ldd', '-add-exec', '--', 'python3', '-c', test], checker)
        if 'NS_LANDLOCK_DENIED' not in denial or '[landrun:warn]' in denial:
            raise Blocked('landlock_not_enforced')
        output = self._command(['lake', 'env', '/work/ns/tools/comparator/.lake/build/bin/comparator',
                                'ComparatorChallenges/NavierStokes.json'], checker,
                               environment=self._tool_environment())
        # Acceptance can appear beyond the runner's bounded diagnostic capture.
        # Scan the complete durable log, including any early sandbox warnings.
        complete_log = self.root / self.store.snapshot()['commands'][-1]['logFile']
        validate_independent_output(complete_log.read_text(errors='replace')); self._config(checker)
        report = self.work / 'independent-report.json'
        atomic_json(report, {'status': 'PASSED', 'toolPins': self.spec['tools'], 'challenge': self.spec['independent'],
                             'freshChecker': True, 'AF_UNIX': 'DENIED', 'landlock': 'ENFORCED',
                             'LeanKernel': 'PASSED', 'nanoda': 'PASSED'})
        self.store.mutate(lambda s: [row.update(independent='PASSED') for row in s['audits']], 'independent_verified')
        return [report, checker / 'ComparatorChallenges/NavierStokes.json']

    def _persist(self):
        self.register_artifacts()
        state = self.store.snapshot()
        if any(stage['status'] != 'PASSED' for stage in state['stages'] if stage['id'] != 'persist'):
            raise ValueError('cannot persist incomplete verification as completed')
        report = copy.deepcopy(state)
        report['artifacts'] = [entry for entry in report['artifacts'] if entry.get('path') != 'artifacts/verification-result.json']
        report.update(status='CHECKS_COMPLETED', execution='CHECKS_COMPLETED', finishedAt=time.time(),
                      proofAccepted=False, semanticReview='NOT_RUN')
        for stage in report['stages']:
            if stage['id'] == 'persist': stage.update(status='PASSED', exitCode=0, finishedAt=time.time())
        path = self.root / 'artifacts/verification-result.json'; atomic_json(path, report)
        return [path]

    def run(self):
        state = self.store.snapshot(); budget = normalize(state['budget'])
        reason = 'budget' if not budget_available(budget) else None
        # Budget is checked first: even hashing the potentially large RH archive
        # is deferred when this successor has no authorized compute budget.
        if reason is None and not durable_rh(self.root, state): reason = 'rh_evidence'
        if reason:
            self.store.mutate(lambda s: s.update(status='PAUSED', reason=reason, execution='NOT_RUN'), 'worker_not_run')
            return self.store.snapshot()
        self.spec = state['spec'] if self.spec is None else self.spec
        validate_spec(self.spec)
        if self.spec != state['spec']: raise ValueError('worker spec differs from durable queue spec')
        if os.geteuid() != 0 or not os.sys.platform.startswith('linux'):
            self.store.mutate(lambda s: s.update(status='PAUSED', reason='sandbox', execution='NOT_RUN'), 'worker_not_run')
            return self.store.snapshot()
        self.work.mkdir(parents=True, exist_ok=True)
        lock = (self.root / 'ns-worker.lock').open('a')
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: lock.close(); raise RuntimeError('another NS worker owns this volume')
        self.run_start = time.monotonic(); self.initial_estimate = budget['usedHours']
        checkpoint = Checkpoints(self.work / 'checkpoints')
        implementation = {name: file_hash(Path(__file__).with_name(name)) for name in
                          ['ns_worker.py', 'process.py', 'sandbox.py', 'child.py', 'build-tools.sh', 'manifest.json', 'budget.py', 'admission.py', 'gates.py']}
        previous = json_hash({'spec': self.spec, 'implementation': implementation})
        try:
            def recover(s):
                for cmd in s.get('commands', []):
                    if cmd['status'] == 'RUNNING': cmd.update(status='INTERRUPTED', exitCode=None, finishedAt=None)
                s.update(status='RUNNING', execution='RUNNING', reason=None,
                         startedAt=s.get('startedAt') or time.time(), workerHeartbeat=time.time())
                s.setdefault('compile', {'succeeded': 0, 'failed': 0, 'jobs': 60})
                s['compile']['jobs']=60
                s['compile']['total'] = 2659
            self.store.mutate(recover, 'worker_claimed')
            for stage in STAGES:
                self.stage = stage; self._beat()
                def start(s):
                    row = next(row for row in s['stages'] if row['id'] == stage)
                    row.update(status='RUNNING', startedAt=time.time(), finishedAt=None, exitCode=None, error=None)
                    s['phase'] = stage
                self.store.mutate(start, 'stage_started')
                def action():
                    before = len(self.store.snapshot().get('commands', []))
                    outputs = getattr(self, '_' + stage)()
                    commands = self.store.snapshot().get('commands', [])[before:]
                    return [*outputs, *[self.root / command['logFile'] for command in commands]]
                skipped = checkpoint.run(stage, previous, action)
                if stage == 'source' and skipped:
                    # A replacement container has fresh /etc even when its
                    # persistent source checkpoint and build volume are valid.
                    sandbox.prepare(self.sandbox_root, self.original)
                def finish(s):
                    row = next(row for row in s['stages'] if row['id'] == stage)
                    row.update(status='PASSED', finishedAt=time.time(), exitCode=0, restored=skipped,
                               checkpointSha256=file_hash(checkpoint.path(stage)))
                self.store.mutate(finish, 'stage_restored' if skipped else 'stage_passed')
                self.register_artifacts()
                previous = file_hash(checkpoint.path(stage))
            report = self.root / 'artifacts/verification-result.json'
            self.store.mutate(lambda s: s.update(status='CHECKS_COMPLETED', execution='CHECKS_COMPLETED',
                reason=None, finishedAt=time.time(), proofAccepted=False),
                'verification_persisted')
            self.register_artifacts()
        except BaseException as error:
            def failed(s):
                row = next((row for row in s['stages'] if row['id'] == self.stage), None)
                if row:
                    row.update(status='BLOCKED' if isinstance(error, Blocked) else 'FAILED',
                               exitCode=getattr(error, 'code', None), finishedAt=time.time(), error=str(error))
                s.update(status='PAUSED', reason=str(error) if isinstance(error, Blocked) else 'worker_failed',
                         execution='INCOMPLETE', error=str(error), workerHeartbeat=time.time())
            self.store.mutate(failed, 'worker_paused')
            self.store.log(self.stage or 'source', str(error), 'error')
            self.register_artifacts()
            failed_report = self.store.snapshot()
            failed_report['artifacts'] = [entry for entry in failed_report['artifacts']
                if entry.get('path') != 'artifacts/verification-result.json']
            atomic_json(self.root / 'artifacts' / f'failure-{time.time_ns()}.json', failed_report)
            atomic_json(self.root / 'artifacts/verification-result.json', failed_report)
            self.register_artifacts()
            if isinstance(error, (KeyboardInterrupt, SystemExit)): raise
        finally: lock.close()
        return self.store.snapshot()


def audit_script(names):
    if names != load_manifest()['theorems']: raise ValueError('unexpected proof audit targets')
    return '''import Lean
import NavierStokes.ComparatorSolution
open NavierStokes.Comparator
local notation "ℝ³" => EuclideanSpace ℝ (Fin 3)
example : ∀ (nu : ℝ), nu > 0 →
    ∃ (u₀ : ℝ³ → ℝ³) (f : ℝ³ → ℝ → ℝ³),
      InitialVelocityConditionDecay u₀ ∧ ForceConditionDecay f ∧
      ¬ (∃ v p, NavierStokesExistenceAndSmoothnessRn nu u₀ f v p) :=
  @NavierStokes.Comparator.navier_stokes_breakdown_R3
example : ∀ (nu : ℝ), nu > 0 →
    ∃ (u₀ : ℝ³ → ℝ³) (f : ℝ³ → ℝ → ℝ³),
      InitialVelocityConditionPeriodic u₀ ∧ ForceConditionPeriodic f ∧
      ¬ (∃ v p, NavierStokesExistenceAndSmoothnessPeriodic nu u₀ f v p) :=
  @NavierStokes.Comparator.navier_stokes_breakdown_periodic
run_cmd do
  let allowed : Array Lean.Name := #[`propext, `Classical.choice, `Quot.sound]
  for decl in #[`NavierStokes.Comparator.navier_stokes_breakdown_R3,
      `NavierStokes.Comparator.navier_stokes_breakdown_periodic] do
    match (← Lean.getEnv).find? decl with
    | some (.thmInfo _) => pure ()
    | _ => throwError "missing actual theorem declaration: {decl}"
    let axioms ← Lean.collectAxioms decl
    unless axioms.all (fun ax => allowed.contains ax) do
      throwError "unpermitted proof axioms: {axioms}"
    Lean.logInfo m!"NS_TYPE_OK|{decl}"
    Lean.logInfo m!"NS_AXIOMS|{decl}|{String.intercalate "," (axioms.toList.map toString)}"
'''


REPLAY = '''import Lean
import Comparator.Compare
def main (args : List String) : IO Unit := do
  let some path := args.head? | throw <| IO.userError "missing export"
  let ref ← IO.mkRef { data := (← IO.FS.readFile (System.FilePath.mk path)).toUTF8 }
  let stream := IO.FS.Stream.ofBuffer ref
  let solution ← Export.parseStream stream
  let env ← Lean.mkEmptyEnvironment
  let quotTargets := [`Quot.mk, `Quot.lift, `Quot.ind]
  let constants := quotTargets.foldl (init := solution.constMap) (·.erase ·)
  let checked ← env.toKernelEnv.replay constants
  for target in `Quot :: quotTargets do
    if let some expected := solution.constMap[target]? then
      let some actual := checked.find? target | throw <| IO.userError "missing quotient primitive"
      if expected != actual then throw <| IO.userError "quotient primitive mismatch"
  IO.println "NS_KERNEL_OK"
'''


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--root', default='/data')
    args = parser.parse_args(); result = NSWorker(args.root).run()
    print(json.dumps({'status': result['status'], 'execution': result.get('execution'), 'reason': result.get('reason')}))
    return 0 if result.get('execution') == 'CHECKS_COMPLETED' else 2


if __name__ == '__main__': raise SystemExit(main())

"""Worker checks use real files/processes; no NS proof or heavy tool build runs."""
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch


NAMES = ['NavierStokes.Comparator.navier_stokes_breakdown_R3',
         'NavierStokes.Comparator.navier_stokes_breakdown_periodic']


class NSWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def module(self, name='ns_worker'):
        try:
            return importlib.import_module('ns_queue.' + name)
        except ModuleNotFoundError as error:
            self.fail('worker capability has not been implemented: ' + str(error))

    def archive(self, entries):
        target = self.root / 'source.tar.gz'
        with tarfile.open(target, 'w:gz') as stream:
            for name, text in entries.items():
                content = text.encode()
                item = tarfile.TarInfo('fixed-root/' + name)
                item.size = len(content)
                stream.addfile(item, io.BytesIO(content))
        return target

    def test_manifest_pins_source_and_rejects_changed_state_spec(self):
        worker = self.module()
        spec = worker.load_manifest()
        worker.validate_spec(spec)
        for key, value in [('commit', 'a' * 40), ('expectedFileCount', 2658),
                           ('archiveSha256', '0' * 64)]:
            bad = copy.deepcopy(spec); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                worker.validate_spec(bad)
        self.assertEqual(spec['expectedFileCount'], 2659)
        self.assertEqual(spec['toolchain'], 'leanprover/lean4:v4.34.0-rc2')
        self.assertEqual(len(spec['dependencies']), 11)
        self.assertEqual(spec['theorems'], NAMES)
        self.assertEqual(spec['independent']['enable_nanoda'], True)

    def test_verified_extraction_rejects_wrong_hash_traversal_and_precompiled_files(self):
        worker = self.module()
        archive = self.archive({'A.lean': 'theorem yes : True := by trivial\n'})
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        worker.extract_verified(archive, self.root / 'good', digest, archive.stat().st_size)
        self.assertTrue((self.root / 'good/A.lean').is_file())
        with self.assertRaises(ValueError):
            worker.extract_verified(archive, self.root / 'bad-hash', '0' * 64, archive.stat().st_size)
        for entry in ['../../escape', '.lake/build/lib/lean/A.olean', 'A.olean']:
            archive = self.archive({entry: 'bad'})
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                worker.extract_verified(archive, self.root / 'bad-path',
                                        hashlib.sha256(archive.read_bytes()).hexdigest(), archive.stat().st_size)
        self.assertFalse((self.root.parent / 'escape').exists())

    def test_source_scan_allows_only_exact_challenge_bytes(self):
        worker = self.module()
        challenge = self.root / 'ComparatorChallenges/Challenge.lean'
        challenge.parent.mkdir()
        challenge.write_text('-- intentional challenge\ntheorem task : True := by\n  sorry\n')
        proof = self.root / 'Proof.lean'
        proof.write_text('/- nested /- sorry -/ axiom unsafe -/\n'
                         'theorem good : True := by trivial\n')
        exception = {'path': 'ComparatorChallenges/Challenge.lean',
                     'sha256': hashlib.sha256(challenge.read_bytes()).hexdigest(), 'lines': [3]}
        spec = {'expectedFileCount': 2, 'sorryExceptions': [exception]}
        self.assertEqual(worker.audit_sources(self.root, spec)['files'], 2)
        challenge.write_text(challenge.read_text() + '-- altered\n')
        with self.assertRaises(ValueError): worker.audit_sources(self.root, spec)
        challenge.unlink()
        for bypass in ['sorry', 'axiom fabricated : False',
                       'set_option debug.skipKernelTC true', 'native_decide',
                       'run_cmd do pure ()', '@[extern "x"] def lie : Bool := true']:
            proof.write_text(bypass + '\n')
            with self.subTest(bypass=bypass), self.assertRaises(ValueError):
                worker.audit_sources(self.root, {'expectedFileCount': 1, 'sorryExceptions': []})

    def test_source_scan_ignores_dependency_cache_and_accepts_structure_constant_field(self):
        worker = self.module()
        (self.root / 'Budget.lean').write_text('structure Budget where\n  constant : Nat\n'
            'def constant (C : Nat) := C\nexample :\n  constant 1 = 1 := rfl\n')
        cached = self.root / '.lake/packages/mathlib/Mathlib.lean'; cached.parent.mkdir(parents=True)
        cached.write_text('-- dependency cache, outside original project source\n')
        result = worker.audit_sources(self.root, {'expectedFileCount': 1, 'sorryExceptions': []})
        self.assertEqual(list(result['inventory']), ['Budget.lean'])

    def test_preexisting_sandbox_sources_must_match_verified_archive_inventory(self):
        worker = self.module()
        original = self.root / 'original'; actual = self.root / 'actual'
        original.mkdir(); actual.mkdir()
        (original / 'Proof.lean').write_text('theorem good : True := by trivial\n')
        (actual / 'Proof.lean').write_text('theorem other : True := by trivial\n')
        spec = {'expectedFileCount': 1, 'sorryExceptions': []}
        with self.assertRaises(ValueError): worker.verify_source_identity(original, actual, spec)
        (actual / 'Proof.lean').write_bytes((original / 'Proof.lean').read_bytes())
        worker.verify_source_identity(original, actual, spec)

    def test_axiom_parser_requires_both_actual_targets_and_no_sorry_or_compiler_axiom(self):
        worker = self.module()
        output = '\n'.join('NS_TYPE_OK|' + name + '\nNS_AXIOMS|' + name +
                           '|propext,Classical.choice,Quot.sound' for name in NAMES)
        rows = worker.parse_audit(output, NAMES)
        self.assertEqual([row['name'] for row in rows], NAMES)
        self.assertTrue(all(row['type'] == 'PASSED' and row['axioms'] == 'PASSED' for row in rows))
        for bad in [output.replace('Quot.sound', 'sorryAx'),
                    output.replace('Quot.sound', 'Lean.trustCompiler'),
                    output.split('NS_TYPE_OK|' + NAMES[1])[0],
                    output + '\nNS_AXIOMS|' + NAMES[0] + '|propext',
                    output.replace('NS_TYPE_OK|', 'not-validated|')]:
            with self.subTest(output=bad[-120:]), self.assertRaises(ValueError):
                worker.parse_audit(bad, NAMES)

    def test_real_child_exit_code_full_log_and_heartbeat_are_preserved(self):
        process = self.module('process')
        beats = []; lines = []
        result = process.run_process([sys.executable, '-u', '-c',
            'import sys,time; print("started"); print("diagnostic",file=sys.stderr); '
            'time.sleep(.2); sys.exit(7)'], cwd=self.root,
            log_path=self.root / 'child.log', on_line=lines.append,
            heartbeat=lambda: beats.append(True), heartbeat_interval=.03)
        self.assertEqual(result.exit_code, 7)
        self.assertIn('started', (self.root / 'child.log').read_text())
        self.assertIn('diagnostic', (self.root / 'child.log').read_text())
        self.assertGreaterEqual(len(beats), 2)
        self.assertIn('started', lines)

    def test_timeout_records_real_termination_instead_of_success(self):
        process = self.module('process')
        result = process.run_process([sys.executable, '-c', 'import time; time.sleep(5)'],
            cwd=self.root, log_path=self.root / 'timeout.log', timeout=.1)
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(result.termination, 'timeout')

    def test_heartbeat_budget_abort_kills_child_and_preserves_actual_exit_code(self):
        process = self.module('process'); beats = []
        def stop():
            beats.append(True)
            if len(beats) > 1: raise RuntimeError('budget exhausted')
        with self.assertRaises(RuntimeError) as error:
            process.run_process([sys.executable, '-u', '-c',
                'import time; print("running"); time.sleep(5)'], cwd=self.root,
                log_path=self.root / 'budget.log', heartbeat=stop, heartbeat_interval=.06)
        self.assertNotEqual(error.exception.child_exit_code, 0)
        self.assertIn('running', (self.root / 'budget.log').read_text())

    def test_worker_records_actual_injected_command_failure_and_never_checkpoints_it(self):
        worker = self.module(); process = self.module('process')
        store = importlib.import_module('ns_queue.store').QueueStore(self.root)
        store.initialize(worker.load_manifest(), '20565ace60c2', {'capUsd': 10})
        store.mutate(lambda state: state['rhEvidence'].update(persisted=True))
        def tiny_executor(argv, **kwargs):
            return process.run_process([sys.executable, '-c', 'print("real failure"); raise SystemExit(9)'], **kwargs)
        instance = worker.NSWorker(self.root, executor=tiny_executor, sandbox_root=self.root / 'sandbox')
        instance.project.mkdir(parents=True)
        (instance.project.parent / 'home-project').mkdir()
        instance.stage = 'audit'; instance.run_start = time.monotonic()
        instance.work.mkdir()
        checkpoints = worker.Checkpoints(self.root / 'checkpoints')
        with self.assertRaises(worker.CommandFailed) as error:
            checkpoints.run('audit', 'a' * 64, lambda: instance._command(['lean', 'audit.lean']))
        self.assertEqual(error.exception.code, 9)
        command = store.snapshot()['commands'][0]
        self.assertEqual((command['status'], command['exitCode']), ('FAILED', 9))
        self.assertEqual(len(command['logSha256']), 64)
        self.assertFalse(checkpoints.path('audit').exists())

    def test_failure_evidence_registers_download_paths_and_preserves_previous_artifacts(self):
        worker = self.module(); store = importlib.import_module('ns_queue.store').QueueStore(self.root)
        store.initialize(worker.load_manifest(), '20565ace60c2', {'capUsd': 0})
        old = self.root / 'artifacts/previous.json'; old.parent.mkdir()
        old.write_text('{"status":"INCOMPLETE"}\n')
        store.mutate(lambda state: state['artifacts'].append({'name': 'previous.json',
            'path': 'artifacts/previous.json', 'sha256': hashlib.sha256(old.read_bytes()).hexdigest(), 'bytes': old.stat().st_size}))
        log = self.root / 'worker/logs/0000-audit.log'; log.parent.mkdir(parents=True)
        log.write_text('actual failure diagnostic\n')
        checkpoint = self.root / 'worker/checkpoints/source.json'; checkpoint.parent.mkdir()
        checkpoint.write_text('{"status":"PASSED"}\n')
        instance = worker.NSWorker(self.root)
        instance.register_artifacts()
        entries = {entry['path']: entry for entry in store.snapshot()['artifacts']}
        self.assertEqual(set(entries), {'artifacts/previous.json', 'worker/logs/0000-audit.log',
                                        'worker/checkpoints/source.json'})
        self.assertEqual(entries['worker/logs/0000-audit.log']['sha256'], hashlib.sha256(log.read_bytes()).hexdigest())
        self.assertEqual(entries['worker/logs/0000-audit.log']['bytes'], 26)

    def test_export_stdout_stays_separate_from_stderr(self):
        process = self.module('process')
        result = process.run_process([sys.executable, '-c',
            'import sys; print("{\\\"meta\\\":1}"); print("diagnostic",file=sys.stderr)'],
            cwd=self.root, log_path=self.root / 'export.log', stdout_path=self.root / 'export.ndjson')
        self.assertEqual(result.exit_code, 0)
        self.assertEqual((self.root / 'export.ndjson').read_text(), '{"meta":1}\n')
        self.assertIn('diagnostic', (self.root / 'export.log').read_text())

    def test_checkpoints_skip_only_verified_immutable_stage_outputs(self):
        worker = self.module(); checkpoint = worker.Checkpoints(self.root / 'checkpoints')
        product = self.root / 'product'; calls = []
        def action():
            calls.append(True); product.write_text('actual child output'); return [product]
        self.assertFalse(checkpoint.run('source', 'a' * 64, action))
        self.assertTrue(worker.Checkpoints(self.root / 'checkpoints').run('source', 'a' * 64, action))
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ValueError): checkpoint.run('source', 'b' * 64, action)
        product.write_text('tampered')
        with self.assertRaises(ValueError): checkpoint.run('source', 'a' * 64, action)
        self.assertEqual(len(calls), 1)

    def test_dependency_retry_rebuilds_frozen_tools_after_cache_failure(self):
        worker = self.module(); process = self.module('process'); spec = worker.load_manifest()
        store = importlib.import_module('ns_queue.store').QueueStore(self.root)
        store.initialize(spec, '20565ace60c2', {'capUsd': 10})
        instance = worker.NSWorker(self.root, sandbox_root=self.root / 'sandbox')
        instance.spec = spec; instance.stage = 'dependencies'; instance.run_start = time.monotonic()
        instance.project.mkdir(parents=True); instance.work.mkdir()
        for name in ['project', 'tools']:
            (instance.project.parent / ('home-' + name)).mkdir()
        for name, item in spec['configuration'].items():
            target = instance.project / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item['text'])
        binaries = ['landrun/landrun', 'nanoda/target/release/nanoda_bin',
                    'comparator/.lake/build/bin/comparator',
                    'comparator/.lake/packages/lean4export/.lake/build/bin/lean4export']
        tool_refs = {'landrun': spec['tools']['landrun']['commit'],
                     'nanoda': spec['tools']['nanoda']['commit'],
                     'comparator': spec['tools']['Comparator']['commit'],
                     'comparator/.lake/packages/lean4export': spec['tools']['lean4export']['commit']}
        attempts = {'build': 0, 'cache': 0}
        outside = self.root / 'outside'; outside.write_text('must remain unchanged')
        def tiny_executor(argv, **kwargs):
            command = argv[next(i for i,arg in enumerate(argv) if arg in ('--exec','--exec-network')) + 1:]
            if command == ['/bin/bash', '/opt/ns-queue/build-tools.sh']:
                attempts['build'] += 1
                code = ('from pathlib import Path\n'
                        f'root=Path({str(instance.tools)!r})\n'
                        f'for name in {binaries!r}:\n'
                        ' p=root/name; p.parent.mkdir(parents=True,exist_ok=True)\n'
                        ' p.write_text("tiny pinned tool output"); p.chmod(0o755)\n'
                        f'for name,revision in {tool_refs!r}.items():\n'
                        ' p=root/name/".git/HEAD"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(revision)\n')
            elif command[:2] == ['git', '-C']:
                path = instance.sandbox_root / command[2].lstrip('/') / '.git/HEAD'
                code = f'from pathlib import Path; print(Path({str(path)!r}).read_text())'
            elif command == ['lean', '--version']:
                code = 'print("Lean (version 4.34.0-rc2, synthetic tiny fixture)")'
            elif command == ['lake', 'exe', 'cache', 'get']:
                attempts['cache'] += 1
                if attempts['cache'] == 1:
                    code = 'print("synthetic transient cache failure"); raise SystemExit(8)'
                else:
                    refs = {entry['name']: entry['rev'] for entry in spec['dependencies']}
                    code = ('from pathlib import Path\n'
                            f'root=Path({str(instance.project / ".lake/packages")!r})\n'
                            f'for name,revision in {refs!r}.items():\n'
                            ' p=root/name/".git/HEAD"; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(revision)\n')
            else: self.fail('unexpected source command in tiny retry fixture: ' + repr(command))
            return process.run_process([sys.executable, '-c', code], **kwargs)
        instance.executor = tiny_executor
        def local_freeze(path):
            # Real permission transition; root chown itself is unavailable in
            # the local test sandbox. No actual toolchain/build is involved.
            for entry in path.rglob('*'):
                if entry.is_file(): entry.chmod(0o555 if entry.stat().st_mode & 0o111 else 0o444)
        checkpoints = worker.Checkpoints(self.root / 'checkpoints')
        with patch.object(worker.os, 'chown'), patch.object(worker.sandbox, 'freeze', local_freeze):
            with self.assertRaises(worker.CommandFailed) as error:
                checkpoints.run('dependencies', 'a' * 64, instance._dependencies)
            self.assertEqual(error.exception.code, 8)
            self.assertFalse(checkpoints.path('dependencies').exists())
            self.assertEqual((instance.tools / binaries[0]).stat().st_mode & 0o222, 0)
            self.assertFalse(checkpoints.run('dependencies', 'a' * 64, instance._dependencies))
            self.assertTrue(checkpoints.run('dependencies', 'a' * 64, instance._dependencies))
        self.assertEqual(attempts, {'build': 2, 'cache': 2})
        self.assertEqual(outside.read_text(), 'must remain unchanged')
        self.assertEqual((instance.tools / binaries[0]).stat().st_mode & 0o222, 0)

    def test_zero_budget_never_invokes_executor_and_stays_not_run(self):
        worker = self.module(); store = importlib.import_module('ns_queue.store').QueueStore(self.root)
        store.initialize(worker.load_manifest(), '20565ace60c2', {'capUsd': 0})
        store.mutate(lambda state: state['rhEvidence'].update(persisted=True))
        calls = []
        result = worker.NSWorker(self.root, executor=lambda *a, **k: calls.append(a)).run()
        self.assertEqual((result['status'], result['reason'], result['execution']),
                         ('PAUSED', 'budget', 'NOT_RUN'))
        self.assertEqual(calls, [])
        self.assertTrue(all(stage['status'] == 'PENDING' for stage in result['stages']))

    def test_missing_durable_rh_evidence_never_invokes_executor(self):
        worker = self.module(); store = importlib.import_module('ns_queue.store').QueueStore(self.root)
        store.initialize(worker.load_manifest(), '20565ace60c2', {'capUsd': 10})
        calls = []
        result = worker.NSWorker(self.root, executor=lambda *a, **k: calls.append(a)).run()
        self.assertEqual(result['execution'], 'NOT_RUN')
        self.assertEqual(calls, [])
        self.assertNotEqual(result['status'], 'RUNNING')

    def test_rh_persisted_flag_without_matching_files_is_not_durable_evidence(self):
        worker = self.module(); store = importlib.import_module('ns_queue.store').QueueStore(self.root)
        store.initialize(worker.load_manifest(), '20565ace60c2', {'capUsd': 10})
        store.mutate(lambda state: state['rhEvidence'].update(persisted=True))
        calls = []
        result = worker.NSWorker(self.root, executor=lambda *a, **k: calls.append(a)).run()
        self.assertEqual((result['reason'], result['execution']), ('rh_evidence', 'NOT_RUN'))
        self.assertEqual(calls, [])

    def test_budget_reservation_cannot_be_reduced_below_300_seconds(self):
        worker = self.module()
        self.assertFalse(worker.budget_available({'capUsd': .27, 'hourlyUsd': 3.36,
            'estimatedUsd': 0, 'minStartSeconds': 0}))
        self.assertTrue(worker.budget_available({'capUsd': .28, 'hourlyUsd': 3.36,
            'estimatedUsd': 0, 'minStartSeconds': 300}))
        self.assertFalse(worker.budget_available({'capUsd': 10, 'hourlyUsd': 3.36,
            'estimatedUsd': -1, 'minStartSeconds': 300}))

    def test_independent_acceptance_requires_real_both_kernel_markers(self):
        worker = self.module()
        output = ('Running nanoda kernel on solution\nnanoda kernel accepts the solution\n'
                  'Running Lean default kernel on solution.\nLean default kernel accepts the solution\n'
                  'Your solution is okay!\n')
        worker.validate_independent_output(output)
        for bad in [output.replace('nanoda kernel accepts the solution', ''),
                    output.replace('Lean default kernel accepts the solution', ''),
                    output + '[landrun:warn] running unsandboxed\n',
                    output + 'fake-landrun\n']:
            with self.subTest(output=bad[-100:]), self.assertRaises(ValueError):
                worker.validate_independent_output(bad)

    def test_sandbox_cwd_cannot_escape_and_argv_always_drops_build_uid(self):
        sandbox = self.module('sandbox')
        root = self.root / 'sandbox'; cwd = root / 'work/ns/project'; cwd.mkdir(parents=True)
        argv = sandbox.command(root, cwd, ['lean', '--version'], network=False)
        self.assertIn('--userspec=10002:10002', argv)
        self.assertIn('--net', argv)
        self.assertIn('--pid', argv)
        self.assertIn('--mount', argv)
        self.assertIn('/opt/ns-queue/child.py', argv)
        with self.assertRaises(ValueError): sandbox.command(root, self.root, ['true'])

    def test_af_unix_filter_denies_socket_and_socketpair_but_allows_inet(self):
        child = self.module('child')
        for architecture, audit_arch, socket_nr, pair_nr in [
                ('x86_64', 0xc000003e, 41, 53), ('aarch64', 0xc00000b7, 198, 199)]:
            rules = child.socket_filter_program(architecture)
            def evaluate(number, domain):
                packet = {0: number, 4: audit_arch, 16: domain}; pc = 0; value = 0
                while True:
                    op, yes, no, operand = rules[pc]
                    if op == 0x20: value = packet[operand]; pc += 1
                    elif op == 0x15: pc += 1 + (yes if value == operand else no)
                    elif op == 0x35: pc += 1 + (yes if value >= operand else no)
                    elif op == 0x06: return operand
                    else: self.fail('unknown socket filter instruction')
            for syscall in [socket_nr, pair_nr]:
                with self.subTest(arch=architecture, syscall=syscall):
                    self.assertEqual(evaluate(syscall, 1), 0x00050001)
                    self.assertEqual(evaluate(syscall, 2), 0x7fff0000)


if __name__ == '__main__':
    unittest.main()

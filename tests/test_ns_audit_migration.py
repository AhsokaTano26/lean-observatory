"""Small real receipts verify an audit-only migration never reruns completed work."""
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ns_queue import ns_worker as worker
from ns_queue.store import QueueStore


class AuditMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve(); self.root = self.base / 'data'
        self.impl = self.base / 'impl'; self.impl.mkdir()
        self.names = ('ns_worker.py', 'process.py', 'sandbox.py', 'child.py', 'build-tools.sh',
                      'manifest.json', 'budget.py', 'admission.py', 'gates.py')
        for name in self.names: shutil.copyfile(Path(worker.__file__).with_name(name), self.impl / name)
        code = (self.impl / 'ns_worker.py').read_text()
        self.old = self.base / 'old.py'
        self.old.write_text(code.replace('\n    Lean.logInfo m!"NS_', '\n    logInfo m!"NS_'))
        (self.impl / 'ns_worker.py').write_text(self.old.read_text().replace(
            '\n    logInfo m!"NS_', '\n    Lean.logInfo m!"NS_'))
        self.store = QueueStore(self.root)
        self.store.initialize(worker.load_manifest(), 'rh-fixture', {'capHours': 1})
        self.cp = self.root / 'worker/checkpoints'; self.cp.mkdir(parents=True)
        self.allowed = (self.root / 'worker', self.base / 'sandbox/work/ns')
        self.allowed[1].mkdir(parents=True)
        implementation = {name: worker.file_hash(self.impl / name) for name in self.names}
        implementation['ns_worker.py'] = worker.file_hash(self.old)
        previous = worker.json_hash({'spec': worker.load_manifest(), 'implementation': implementation})
        self.original = {}; self.outputs = {}
        for number, stage in enumerate(('source', 'dependencies', 'compile')):
            output = self.allowed[number % 2] / (stage + '.bin'); output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(('real actual output ' + stage).encode()); self.outputs[output] = output.read_bytes()
            receipt = {'stage': stage, 'status': 'PASSED', 'exitCode': 0, 'completedAt': 100 + number,
                       'inputSha256': previous, 'outputs': [{'path': str(output), 'bytes': output.stat().st_size,
                                                           'sha256': worker.file_hash(output)}]}
            path = self.cp / (stage + '.json'); worker.atomic_json(path, receipt)
            self.original[stage] = path.read_bytes(); previous = worker.file_hash(path)
        def paused(state):
            state.update(status='PAUSED', phase='audit', execution='INCOMPLETE')
            state['commands'] = [{'stage': 'compile', 'argv': ['lake', 'build'], 'status': 'PASSED',
                                  'exitCode': 0, 'startedAt': 10, 'finishedAt': 20},
                                 {'stage': 'audit', 'argv': ['lean', 'audit.lean'], 'status': 'FAILED', 'exitCode': 1}]
            for row in state['stages'][:3]:
                row.update(status='PASSED', exitCode=0, startedAt=10, finishedAt=20,
                           checkpointSha256=worker.file_hash(self.cp / (row['id'] + '.json')))
        self.store.mutate(paused); self.state = self.store.snapshot()

    def migrate(self, execute=False):
        module = importlib.import_module('ns_queue.audit_migration')
        return module.migrate(self.root, self.old, implementation_dir=self.impl,
                              allowed_roots=self.allowed, execute=execute)

    def test_dry_run_and_execution_preserve_actual_work_and_are_idempotent(self):
        self.migrate()
        self.assertEqual(self.store.snapshot(), self.state)
        self.assertEqual({s: (self.cp / (s + '.json')).read_bytes() for s in self.original}, self.original)
        self.assertFalse((self.cp / 'migrations').exists())
        self.migrate(True); migrated = self.store.snapshot()
        self.assertEqual(migrated['commands'], self.state['commands'])
        for key in ('status', 'phase', 'execution', 'compile'): self.assertEqual(migrated[key], self.state[key])
        previous = None
        for stage, original_bytes in self.original.items():
            receipt_path = self.cp / (stage + '.json')
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o644)
            receipt = json.loads(receipt_path.read_bytes()); original = json.loads(original_bytes)
            self.assertEqual({k: v for k, v in receipt.items() if k not in ('inputSha256', 'checkpointMigration')},
                             {k: v for k, v in original.items() if k != 'inputSha256'})
            self.assertNotEqual(receipt['inputSha256'], original['inputSha256'])
            self.assertEqual(receipt['checkpointMigration']['originalSha256'], hashlib.sha256(original_bytes).hexdigest())
            if previous: self.assertEqual(receipt['inputSha256'], previous)
            previous = worker.file_hash(self.cp / (stage + '.json'))
            self.assertEqual(next(r for r in migrated['stages'] if r['id'] == stage)['checkpointSha256'], previous)
        self.assertEqual({p: p.read_bytes() for p in self.outputs}, self.outputs)
        transaction = self.cp / 'migrations/audit-lean-loginfo-v1'
        self.assertEqual(transaction.stat().st_mode & 0o777, 0o755)
        for stage, content in self.original.items():
            backup = self.cp / 'migrations/audit-lean-loginfo-v1' / (stage + '.original.json')
            self.assertEqual(backup.read_bytes(), content)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o444)
        self.migrate(True)
        self.assertEqual(self.store.snapshot(), migrated)
        self.assertEqual(len(migrated['checkpointMigrations']), 1)

    def test_other_code_change_or_old_code_change_is_rejected_without_mutation(self):
        for target in (self.impl / 'process.py', self.impl / 'ns_worker.py', self.old):
            original = target.read_bytes(); target.write_bytes(original + b'\n# unrelated change\n')
            with self.subTest(target=target), self.assertRaises(ValueError): self.migrate(True)
            target.write_bytes(original)
            self.assertEqual(self.store.snapshot(), self.state)
            self.assertFalse((self.cp / 'migrations').exists())

    def test_prevalidation_rejects_final_output_tampering_without_partial_commit(self):
        final = next(p for p in self.outputs if p.name == 'compile.bin'); final.write_bytes(b'tampered')
        with self.assertRaises(ValueError): self.migrate(True)
        self.assertEqual({s: (self.cp / (s + '.json')).read_bytes() for s in self.original}, self.original)
        self.assertEqual(self.store.snapshot(), self.state)
        self.assertFalse((self.cp / 'migrations').exists())

    def test_resume_after_first_receipt_commit_and_refuse_transaction_tampering(self):
        module = importlib.import_module('ns_queue.audit_migration'); original_write = module._replace_receipt
        calls = []
        def interrupted(path, content):
            original_write(path, content); calls.append(path)
            if len(calls) == 1: raise InterruptedError('simulated crash')
        with patch.object(module, '_replace_receipt', interrupted), self.assertRaises(InterruptedError): self.migrate(True)
        self.assertEqual(self.store.snapshot(), self.state)
        self.migrate(True)
        self.assertEqual(len(self.store.snapshot()['checkpointMigrations']), 1)
        manifest = self.cp / 'migrations' / module.MIGRATION_ID / 'manifest.json'
        self.assertEqual(manifest.stat().st_mode & 0o222, 0)
        manifest.chmod(0o644); manifest.write_text(manifest.read_text() + ' ')
        with self.assertRaises(ValueError): self.migrate(True)

    def test_rejects_receipt_tampering_invalid_state_later_success_and_symlink_output(self):
        for change in ('receipt', 'state', 'later', 'symlink', 'scope'):
            with self.subTest(change=change):
                if change == 'receipt':
                    path = self.cp / 'dependencies.json'; path.write_bytes(self.original['dependencies'] + b' ')
                elif change == 'state': self.store.mutate(lambda state: state.update(status='RUNNING'))
                elif change == 'later':
                    path = self.cp / 'audit.json'; path.write_text('{"status":"PASSED"}')
                elif change == 'scope':
                    path = self.cp / 'compile.json'; receipt = json.loads(self.original['compile'])
                    outside = self.base / 'outside.bin'; outside.write_bytes(b'real actual output compile')
                    receipt['outputs'][0]['path'] = str(outside); worker.atomic_json(path, receipt)
                else:
                    path = next(iter(self.outputs)); backup = path.with_suffix('.real'); path.rename(backup); path.symlink_to(backup)
                with self.assertRaises(ValueError): self.migrate(True)
                if change == 'receipt': path.write_bytes(self.original['dependencies'])
                elif change == 'scope': path.write_bytes(self.original['compile'])
                elif change == 'state': self.store.mutate(lambda state: state.update(status='PAUSED'))
                elif change == 'later': path.unlink()
                else: path.unlink(); backup.rename(path)
                self.assertFalse((self.cp / 'migrations').exists())


if __name__ == '__main__': unittest.main()

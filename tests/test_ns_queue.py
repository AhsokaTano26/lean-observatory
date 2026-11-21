"""Durable queue and fail-closed successor gates, using real SQLite files."""
import importlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


RH_ID = '20565ace60c2'
NS_SPEC = {'repo': 'openai/NavierStokesAndEuler',
           'commit': 'f9e8bc5b38b6e212696e8a30e3e91517af887bbd',
           'toolchain': 'leanprover/lean4:v4.34.0-rc2',
           'expectedFileCount': 2659}


def complete_rh():
    """Independent fixture matching the public RH API, including final artifact."""
    names = [('riemannHypothesis', 'RiemannHypothesis'),
             ('riemannZeta_eq_zero_re', 'RiemannZetaZerosOnLine'),
             ('LFunction_ne_zero_of_half_lt_re', 'DirichletLNonvanishingRightOfHalf'),
             ('LFunction_eq_zero_re', 'DirichletLZerosOnLine'),
             ('LFunction_eq_zero_re_of_isPrimitive', 'PrimitiveDirichletLZerosOnLine')]
    return {'run': {
        'id': RH_ID, 'mode': 'real', 'status': 'checks_completed',
        'finishedAt': 1795290000., 'proofAccepted': False,
        'stages': [{'id': stage, 'status': 'passed', 'exitCode': 0}
                   for stage in ['download', 'integrity', 'dependencies', 'compile', 'audit', 'replay']],
        'compile': {'total': 175187, 'succeeded': 175187, 'failed': 0},
        'audits': [{'name': name, 'expectedType': kind, 'type': 'passed',
                    'axioms': 'passed', 'replay': 'passed',
                    'dependencies': ['propext', 'Classical.choice', 'Quot.sound']}
                   for name, kind in names],
        'provenance': {'expectedSha256': '9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc',
                       'sha256': '9631b4f020199e580ba86178cb56c6e9b09f690c2369a80dc4334aa93f49c7fc',
                       'expectedBytes': 239275554, 'bytes': 239275554, 'integrity': 'passed'},
        'environment': {'lean': 'v4.33.1', 'actualLean': 'Lean (version 4.33.1, x86_64-unknown-linux-gnu, commit abcdef)',
                        'mathlib': '0df444a360eaa60ab8c11dca51a86af692955474',
                        'actualMathlib': '0df444a360eaa60ab8c11dca51a86af692955474'},
        'commands': [{'stage': 'replay', 'status': 'passed', 'exitCode': 0, 'finishedAt': 1795290000.}],
        'artifacts': [{'name': 'verification-result.json', 'sha256': 'a' * 64, 'bytes': 4096}]},
        'workerOnline': False}


class QueueStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.QueueStore = importlib.import_module('ns_queue.store').QueueStore
        self.store = self.QueueStore(self.temp.name)

    def initialize(self):
        return self.store.initialize(NS_SPEC, RH_ID, {'capUsd': 0})

    def test_initial_queue_survives_restart_and_cannot_be_reset_by_initialize(self):
        state = self.initialize()
        self.assertEqual(state['id'], 'ns-f9e8bc5b38b6')
        self.assertEqual((state['status'], state['reason']), ('QUEUED', 'waiting_rh'))
        self.assertEqual(state['spec'], NS_SPEC)
        self.assertEqual(state['rhRunId'], RH_ID)
        self.assertFalse(state['rhEvidence']['persisted'])
        self.assertEqual(state['budget']['hourlyUsd'], 3.36)
        self.assertEqual(state['budget']['minStartSeconds'], 300)
        self.assertEqual([s['id'] for s in state['stages']],
                         ['source', 'dependencies', 'compile', 'audit', 'kernel', 'independent', 'persist'])
        self.assertTrue(all(s['status'] == 'PENDING' and s['exitCode'] is None for s in state['stages']))
        self.store.mutate(lambda s: s.update(status='PAUSED', reason='budget'), 'budget_blocked')
        restarted = self.QueueStore(self.temp.name)
        self.assertEqual(restarted.snapshot()['reason'], 'budget')
        self.assertEqual(restarted.initialize(NS_SPEC, RH_ID, {'capUsd': 99})['budget']['capUsd'], 0)
        with self.assertRaises(ValueError):
            restarted.initialize({**NS_SPEC, 'commit': 'b' * 40}, RH_ID, {'capUsd': 0})

    def test_mutations_are_atomic_across_instances_and_roll_back_exceptions(self):
        self.initialize()
        self.store.mutate(lambda s: s.update(counter=0))
        def increment(_):
            store = self.QueueStore(self.temp.name)
            for _ in range(10):
                store.mutate(lambda s: s.update(counter=s['counter'] + 1), 'incremented')
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(increment, range(4)))
        self.assertEqual(self.store.snapshot()['counter'], 40)
        def broken(state):
            state['counter'] = -1
            raise RuntimeError('rollback')
        with self.assertRaises(RuntimeError):
            self.store.mutate(broken)
        self.assertEqual(self.store.snapshot()['counter'], 40)
        events = self.store.read_events(after=0, limit=1000)
        self.assertEqual(sum(e['event'] == 'incremented' for e in events), 40)
        self.assertEqual(self.store.read_events(after=events[-1]['id']), [])

    def test_logs_replay_monotonic_ids_after_restart(self):
        self.initialize()
        first = self.store.log('dependency', 'waiting for RH')
        last = self.store.log('budget', 'budget exhausted', 'warning')
        rows = self.QueueStore(self.temp.name).logs(after=first)
        self.assertEqual([(r['id'], r['stage'], r['message'], r['level']) for r in rows],
                         [(last, 'budget', 'budget exhausted', 'warning')])
        self.assertGreater(rows[0]['at'], 0)

    def test_outbox_deduplicates_and_persists_retry_backoff_and_acceptance(self):
        self.initialize()
        alert = self.store.alert('rh:failure', 'RH stopped', 'NS paused', fields={'run': RH_ID})
        self.assertEqual(self.store.alert('rh:failure', 'duplicate', 'ignored'), alert)
        pending = self.QueueStore(self.temp.name).outbox()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['fields'], {'run': RH_ID})
        self.assertEqual(pending[0]['attempts'], 0)
        self.store.ack_alert(alert, 'retry', 'connection reset')
        retried = self.store.outbox()[0]
        self.assertEqual(retried['attempts'], 1)
        self.assertEqual(retried['status'], 'retry')
        self.assertGreater(retried['nextAttemptAt'], retried['updatedAt'])
        self.store.ack_alert(alert, 'retry', 'timeout')
        self.assertGreater(self.store.outbox()[0]['nextAttemptAt'], retried['nextAttemptAt'])
        self.store.ack_alert(alert, 'accepted')
        self.assertEqual(self.QueueStore(self.temp.name).outbox(), [])
        self.assertEqual(self.store.alert('rh:failure', 'duplicate', 'ignored'), alert)
        with self.assertRaises(ValueError):
            self.store.ack_alert(alert, 'delivered')

    def test_sqlite_connection_enforces_durable_wal_and_full_sync(self):
        self.initialize()
        with self.store.db() as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(db.execute('PRAGMA synchronous').fetchone()[0], 2)

    def test_readonly_store_reads_existing_data_without_modifying_files(self):
        self.initialize()
        self.store.log('dependency', 'queued')
        before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(self.temp.name).iterdir()}
        reader = self.QueueStore.readonly(self.temp.name)
        self.assertEqual(reader.snapshot()['status'], 'QUEUED')
        self.assertEqual(reader.logs()[0]['message'], 'queued')
        self.assertEqual(reader.read_events()[0]['event'], 'initialized')
        after = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(self.temp.name).iterdir()}
        self.assertEqual(after, before)
        with self.assertRaises((PermissionError, sqlite3.OperationalError)):
            reader.log('bad', 'write forbidden')

    def test_readonly_missing_store_never_creates_data_directory(self):
        missing = Path(self.temp.name) / 'missing'
        with self.assertRaises(FileNotFoundError):
            self.QueueStore.readonly(missing)
        self.assertFalse(missing.exists())

    def test_readonly_includes_committed_wal_left_by_crashed_writer_without_touching_it(self):
        self.initialize()
        program = '''
import os,sqlite3,sys
db=sqlite3.connect(sys.argv[1])
db.execute('PRAGMA wal_autocheckpoint=0')
db.execute("INSERT INTO logs(at,stage,message,level) VALUES(1,'crash','durable WAL','info')")
db.commit()
os._exit(0)
'''
        subprocess.run([sys.executable, '-c', program, str(self.store.path)], check=True, timeout=10)
        self.assertTrue(Path(str(self.store.path) + '-wal').is_file())
        before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(self.temp.name).iterdir()}
        reader = self.QueueStore.readonly(self.temp.name)
        self.assertEqual(reader.logs()[0]['message'], 'durable WAL')
        after = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(self.temp.name).iterdir()}
        self.assertEqual(before, after)


class RHGateTests(unittest.TestCase):
    def setUp(self):
        gates = importlib.import_module('ns_queue.gates')
        self.gate = gates.rh_gate
        self.validate_result = gates.validate_result

    def test_real_machine_success_is_ready_with_proof_acceptance_false_and_stale_heartbeat(self):
        self.assertEqual(self.gate(complete_rh(), [], RH_ID)['decision'], 'READY')

    def test_active_unknown_missing_and_mismatched_runs_never_start(self):
        for status in ['queued', 'running', 'paused', 'waiting', 'unexpected']:
            with self.subTest(status=status):
                data = complete_rh(); data['run']['status'] = status
                self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')
        for key, value in [('id', 'another-run'), ('mode', 'mock')]:
            data = complete_rh(); data['run'][key] = value
            self.assertNotEqual(self.gate(data, [], RH_ID)['decision'], 'READY')
        for data in [None, {}, {'run': None}]:
            self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')

    def test_explicit_terminal_failure_pauses_but_historical_failed_runs_do_not(self):
        for status in ['failed', 'interrupted', 'cancelled', 'resource_exhausted']:
            data = complete_rh(); data['run']['status'] = status
            with self.subTest(status=status):
                self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'PAUSE')
        self.assertEqual(self.gate(complete_rh(), [{'id': 'old', 'status': 'failed'}], RH_ID)['decision'], 'READY')

    def test_other_active_ledger_and_unresolved_commands_block_ready(self):
        for status in ['queued', 'running', 'paused']:
            with self.subTest(status=status):
                self.assertEqual(self.gate(complete_rh(), [{'id': 'other', 'status': status}], RH_ID)['decision'], 'WAIT')
        data = complete_rh(); data['run']['commands'][0]['exitCode'] = None
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')
        data = complete_rh(); data['run']['commands'][0]['status'] = 'running'
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')

    def test_resolved_historical_command_failure_does_not_override_final_success(self):
        data = complete_rh()
        data['run']['commands'].insert(0, {'status': 'interrupted', 'exitCode': -9,
                                          'finishedAt': 1795280000.})
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'READY')

    def test_explicit_worker_stop_pauses_while_worker_heartbeat_does_not(self):
        data = complete_rh(); data['run']['status'] = 'running'; data['workerRunning'] = False
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'PAUSE')
        del data['workerRunning']
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')

    def test_malformed_nested_evidence_raises_value_error_in_result_validator(self):
        data = complete_rh(); data['run']['audits'][0]['name'] = []
        with self.assertRaises(ValueError):
            self.validate_result(data, RH_ID)

    def test_unknown_ledger_state_cannot_be_treated_as_inactive(self):
        self.assertEqual(self.gate(complete_rh(), [{'id': 'other', 'status': 'unknown'}], RH_ID)['decision'], 'WAIT')

    def test_malformed_statuses_wait_without_crashing_polling(self):
        data = complete_rh(); data['run']['status'] = []
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')
        self.assertEqual(self.gate(complete_rh(), [{'id': 'other', 'status': {}}], RH_ID)['decision'], 'WAIT')

    def test_missing_final_artifact_in_terminal_registration_window_waits(self):
        data = complete_rh(); data['run']['artifacts'] = []
        self.assertEqual(self.gate(data, [], RH_ID)['decision'], 'WAIT')
        # The report's embedded snapshot predates registration of its own hash.
        self.validate_result(data, RH_ID)
        for entry in [{'name': 'verification-result.json', 'sha256': 'a' * 63, 'bytes': 10},
                      {'name': 'verification-result.json', 'sha256': 'a' * 64, 'bytes': 0}]:
            data = complete_rh(); data['run']['artifacts'] = [entry]
            self.assertNotEqual(self.gate(data, [], RH_ID)['decision'], 'READY')

    def test_incomplete_or_forged_machine_evidence_fails_closed(self):
        changes = [lambda s: s.update(finishedAt=None),
                   lambda s: s['stages'].pop(),
                   lambda s: s['stages'][0].update(exitCode=False),
                   lambda s: s['stages'][0].update(exitCode='0'),
                   lambda s: s['compile'].update(succeeded=175186),
                   lambda s: s['compile'].update(failed=1),
                   lambda s: s['audits'].pop(),
                   lambda s: s['audits'][0].update(expectedType='False'),
                   lambda s: s['audits'][0].update(dependencies=['sorryAx']),
                   lambda s: s['audits'][0].update(replay='pending'),
                   lambda s: s['provenance'].update(sha256='b' * 64),
                   lambda s: s['environment'].update(actualMathlib='b' * 40),
                   lambda s: s['environment'].update(actualLean='Lean (version 4.34.0-rc2)'),
                   lambda s: s['commands'][0].update(exitCode=1)]
        for index, change in enumerate(changes):
            data = complete_rh(); change(data['run'])
            with self.subTest(change=index):
                self.assertNotEqual(self.gate(data, [], RH_ID)['decision'], 'READY')
                with self.assertRaises(ValueError):
                    self.validate_result(data, RH_ID)


class StartGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = importlib.import_module('ns_queue.gates').start_gate
        self.state = {'rhEvidence': {'persisted': True},
                      'budget': {'capUsd': 1., 'hourlyUsd': 3.36, 'minStartSeconds': 300, 'estimatedUsd': 0}}
        self.resources = {'cpuCount': 64, 'memoryAvailableBytes': 224 * 1024**3,
                          'diskFreeBytes': 100 * 1024**3, 'rhActive': False}

    def test_zero_budget_blocks_even_with_durable_rh_and_sufficient_resources(self):
        self.state['budget']['capUsd'] = 0
        self.assertEqual(self.gate(self.state, self.resources), {'allowed': False, 'reason': 'budget'})

    def test_durable_rh_and_minimum_reservation_required_before_start(self):
        self.state['rhEvidence']['persisted'] = False
        self.assertFalse(self.gate(self.state, self.resources)['allowed'])
        self.state['rhEvidence']['persisted'] = True
        self.state['budget'].update(capUsd=.28, estimatedUsd=0)
        self.assertTrue(self.gate(self.state, self.resources)['allowed'])
        self.state['budget']['estimatedUsd'] = .01
        self.assertFalse(self.gate(self.state, self.resources)['allowed'])

    def test_each_resource_threshold_and_explicit_no_active_rh_is_required(self):
        self.assertTrue(self.gate(self.state, self.resources)['allowed'])
        for key, value in [('cpuCount', 63), ('memoryAvailableBytes', 224 * 1024**3 - 1),
                           ('diskFreeBytes', 100 * 1024**3 - 1), ('rhActive', True), ('rhActive', None)]:
            resources = {**self.resources, key: value}
            with self.subTest(key=key, value=value):
                self.assertFalse(self.gate(self.state, resources)['allowed'])
        self.assertFalse(self.gate(self.state, {})['allowed'])


if __name__ == '__main__':
    unittest.main()

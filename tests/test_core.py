import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from backend.model import initial_state, derived, audit_axioms, EXPECTED_HASH
from backend.store import Store
from backend.mock import tick
from backend.integrity import verify_archive, safe_extract


class StateTests(unittest.TestCase):
    def test_pending_never_claims_success(self):
        s = derived(initial_state('real'), now=100)
        self.assertEqual(s['status'], 'waiting')
        self.assertIsNone(s['compile']['total'])
        self.assertIsNone(s['compile']['etaSeconds'])
        self.assertEqual(s['checksPassed'], 0)
        self.assertFalse(s['proofAccepted'])

    def test_accounting_is_bounded_and_eta_not_fabricated(self):
        s = initial_state('mock')
        s['status'] = 'running'
        s['compile'].update(total=100, succeeded=40, failed=2, rate=2)
        c = derived(s)['compile']
        self.assertEqual(c['percent'], 40)
        self.assertEqual(c['remaining'], 58)
        self.assertEqual(c['etaSeconds'], 29)
        s['compile']['rate'] = 0
        self.assertIsNone(derived(s)['compile']['etaSeconds'])

    def test_axioms_fail_closed(self):
        for text in ['', "'riemannHypothesis' depends on axioms: [sorryAx]", "'riemannHypothesis' depends on axioms: [Custom.oracle]"]:
            self.assertFalse(audit_axioms(text, 'riemannHypothesis')['passed'])
        self.assertTrue(audit_axioms("'riemannHypothesis' depends on axioms: [propext, Classical.choice, Quot.sound]", 'riemannHypothesis')['passed'])

    def test_mock_all_scenarios_and_resume(self):
        for scenario in ['success', 'failure', 'interruption', 'resource']:
            s = initial_state('mock')
            s['scenario'] = scenario
            s['status'] = 'running'
            for i in range(100):
                tick(s, 1)
                if s['status'] != 'running':
                    break
            expected = dict(success='checks_completed', failure='failed', interruption='interrupted', resource='resource_exhausted')[scenario]
            self.assertEqual(s['status'], expected)
            self.assertFalse(s['proofAccepted'])
            if scenario != 'success':
                before = s['compile']['succeeded']
                s['status'] = 'running'
                s['scenario'] = 'success'
                for i in range(100):
                    tick(s, 1)
                self.assertGreaterEqual(s['compile']['succeeded'], before)
                self.assertEqual(s['status'], 'checks_completed')

    def test_sqlite_survives_restart_and_logs_are_ordered(self):
        with tempfile.TemporaryDirectory() as d:
            a = Store(Path(d))
            s = a.create('mock', 'success')
            a.log(s['id'], 'info', '<script>untrusted</script>')
            b = Store(Path(d))
            self.assertEqual(b.snapshot()['id'], s['id'])
            self.assertIn('<script>', b.logs(s['id'])[-1]['message'])
            self.assertEqual(len(b.logs(s['id'], after=b.logs(s['id'])[-1]['id'])), 0)


class IntegrityTests(unittest.TestCase):
    def test_html_200_and_wrong_hash_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bad.tar.gz'
            p.write_bytes(b'<html>not found</html>')
            with self.assertRaises(ValueError):
                verify_archive(p, EXPECTED_HASH, 239275554)

    def test_traversal_and_symlink_rejected(self):
        for name, symlink in [('../escape', False), ('lean/file', True), ('/absolute', False)]:
            with tempfile.TemporaryDirectory() as d:
                p = Path(d) / 'test.tar.gz'
                with tarfile.open(p, 'w:gz') as t:
                    m = tarfile.TarInfo(name)
                    if symlink:
                        m.type = tarfile.SYMTYPE
                        m.linkname = '/etc/passwd'
                    t.addfile(m)
                with self.assertRaises(ValueError):
                    safe_extract(p, Path(d) / 'out')

class LogExportTests(unittest.TestCase):
    def test_explicit_zero_cursor_reads_oldest_instead_of_tail(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));s=store.create('mock')
            for i in range(1005): store.log(s['id'],'info',f'line-{i}')
            self.assertIn('创建',store.logs(s['id'],after=0,limit=1000)[0]['message'])
            self.assertEqual(store.logs(s['id'],limit=2)[-1]['message'],'line-1004')

class AuditParserRegressionTests(unittest.TestCase):
    def test_body_text_cannot_mask_real_sorry_axiom(self):
        text='theorem sample := "riemannHypothesis depends on axioms: [propext]"\n\'riemannHypothesis\' depends on axioms: [sorryAx]'
        self.assertFalse(audit_axioms(text,'riemannHypothesis')['passed'])

    def test_duplicate_axiom_records_fail_closed(self):
        text="'riemannHypothesis' depends on axioms: [propext]\n'riemannHypothesis' depends on axioms: [sorryAx]"
        self.assertFalse(audit_axioms(text,'riemannHypothesis')['passed'])

class SchedulingTests(unittest.TestCase):
    def test_old_resumed_run_remains_visible_to_scheduler(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d));old=store.create('mock')
            store.mutate(old['id'],lambda s:s.update(status='failed'))
            for i in range(32):
                s=store.create('mock');store.control(s['id'],'cancel')
            store.control(old['id'],'resume')
            self.assertIn(old['id'],[s['id'] for s in store.active_runs()])

class HistoryTests(unittest.TestCase):
    def test_history_supports_full_thirty_minutes_of_one_second_samples(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d))
            with store.db() as db:
                db.executemany('INSERT INTO samples(ts,payload) VALUES(?,?)', [(i,json.dumps({'sampledAt':i,'runId':'a'})) for i in range(2000)])
            samples=store.history(run='a')
            self.assertEqual(len(samples),1801)
            self.assertEqual(samples[-1]['sampledAt']-samples[0]['sampledAt'],1800)

    def test_history_does_not_mix_different_runs(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d))
            store.sample({'sampledAt':100,'runId':'a','cpuPercent':41})
            store.sample({'sampledAt':101,'runId':'b','cpuPercent':84})
            self.assertEqual([p['cpuPercent'] for p in store.history(run='a')],[41])

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from ns_queue.store import QueueStore

ROOT=Path(__file__).resolve().parents[1]


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def cli(self,*args):
        return subprocess.run([sys.executable,'-m','ns_queue.control','--root',self.temp.name,*args],cwd=ROOT,capture_output=True,text=True)
    def test_zero_budget_queue_is_initialized_once(self):
        first=self.cli('init','--hours','0');self.assertEqual(first.returncode,0,first.stderr)
        s=json.loads(first.stdout);self.assertEqual(s['status'],'QUEUED');self.assertEqual(s['budget']['capHours'],0)
        second=self.cli('init','--hours','99');self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(json.loads(second.stdout)['budget']['capHours'],0)
        self.assertEqual(len(QueueStore(self.temp.name).outbox()),1)
    def test_server_rental_origin_is_persisted_and_cannot_reset(self):
        self.assertEqual(self.cli('init','--hours','0').returncode,0)
        first=self.cli('set-budget','--hours','20','--started-at','2026-11-21T14:42:36Z')
        self.assertEqual(first.returncode,0,first.stderr)
        budget=json.loads(first.stdout)['budget']
        self.assertEqual(budget['scope'],'server');self.assertEqual(budget['capHours'],20)
        self.assertEqual(budget['deadlineAt']-budget['rentalStartedAt'],20*3600)
        self.assertEqual(self.cli('set-budget','--hours','20').returncode,0)
        self.assertNotEqual(self.cli('set-budget','--hours','20','--started-at','2026-11-21T14:43:36Z').returncode,0)
        self.assertEqual(QueueStore(self.temp.name).snapshot()['budget']['rentalStartedAt'],budget['rentalStartedAt'])
        for start in ['2026-11-21T14:42:36','2099-01-01T00:00:00Z']:
            self.assertNotEqual(self.cli('set-budget','--hours','20','--started-at',start).returncode,0)

    def test_concurrent_configuration_cannot_replace_committed_rental_origin(self):
        from ns_queue.control import main
        from tests.test_ns_budget import START,server_budget
        from unittest.mock import patch
        import contextlib,io
        self.assertEqual(self.cli('init','--hours','0').returncode,0)
        original=QueueStore.mutate;changed=[False]
        def race(store,fn,event='updated'):
            if not changed[0]:
                changed[0]=True
                original(store,lambda s:s.update(budget={**server_budget(),'rentalStartedAt':START+60}))
            return original(store,fn,event)
        with patch.object(QueueStore,'mutate',race),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
            main(['--root',self.temp.name,'set-budget','--hours','20','--started-at','2026-11-21T14:42:36Z'])
        self.assertEqual(QueueStore(self.temp.name).snapshot()['budget']['rentalStartedAt'],START+60)

    def test_budget_edits_are_validated_and_resume_requires_paused_state(self):
        self.assertEqual(self.cli('init','--hours','0').returncode,0)
        for value in ['nan','-1','inf']:
            self.assertNotEqual(self.cli('set-budget','--hours',value).returncode,0)
        store=QueueStore(self.temp.name);store.mutate(lambda s:s.update(status='PAUSED',reason='budget'))
        self.assertEqual(self.cli('set-budget','--hours','5','--started-at','2026-11-21T14:42:36Z').returncode,0)
        self.assertEqual(self.cli('resume').returncode,0)
        self.assertEqual(store.snapshot()['status'],'QUEUED')
        self.assertEqual(store.snapshot()['budget']['capHours'],5)
        self.assertNotEqual(self.cli('resume').returncode,0)

if __name__=='__main__':unittest.main()

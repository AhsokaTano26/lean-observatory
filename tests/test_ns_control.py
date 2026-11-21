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
        first=self.cli('init','--budget','0');self.assertEqual(first.returncode,0,first.stderr)
        s=json.loads(first.stdout);self.assertEqual(s['status'],'QUEUED');self.assertEqual(s['budget']['capUsd'],0)
        second=self.cli('init','--budget','99');self.assertEqual(second.returncode,0,second.stderr)
        self.assertEqual(json.loads(second.stdout)['budget']['capUsd'],0)
        self.assertEqual(len(QueueStore(self.temp.name).outbox()),1)
    def test_budget_edits_are_validated_and_resume_requires_paused_state(self):
        self.assertEqual(self.cli('init','--budget','0').returncode,0)
        for value in ['nan','-1','inf']:
            self.assertNotEqual(self.cli('set-budget','--usd',value).returncode,0)
        store=QueueStore(self.temp.name);store.mutate(lambda s:s.update(status='PAUSED',reason='budget'))
        self.assertEqual(self.cli('set-budget','--usd','5').returncode,0)
        self.assertEqual(self.cli('resume').returncode,0)
        self.assertEqual(store.snapshot()['status'],'QUEUED')
        self.assertEqual(store.snapshot()['budget']['capUsd'],5)
        self.assertNotEqual(self.cli('resume').returncode,0)

if __name__=='__main__':unittest.main()

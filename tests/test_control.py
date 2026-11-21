import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from backend.store import Store


class HostControlTests(unittest.TestCase):
    def call(self, root, *args, enable_real='0', environment=None):
        return subprocess.run([sys.executable,'-m','backend.control','--data',str(root),*args],env={**os.environ,'ENABLE_REAL':enable_real,**(environment or {})},capture_output=True,text=True,timeout=5)

    def test_real_task_can_be_queued_after_matching_online_acceptance(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'online.json';sha='1'*64
            path.write_text(json.dumps({'passed':True,'productionEligible':True,'checkedAt':time.time(),'url':'https://lean.tano.asia','sourceSha256':sha,'checks':{k:True for k in ['tls','source','resources','metrics','clean','readOnly','methods','sse']}}))
            p=self.call(d,'create','--mode','real',enable_real='1',environment={'ONLINE_RECEIPT':str(path),'SOURCE_SHA256':sha})
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(Store(Path(d)).raw()['mode'],'real')
            self.assertEqual(Store(Path(d)).raw()['status'],'queued')

    def test_host_cli_creates_and_controls_mock_without_http(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.call(d,'create','--mode','mock','--scenario','resource','--jobs','4')
            self.assertEqual(p.returncode,0,p.stderr)
            s=json.loads(p.stdout)
            store=Store(Path(d))
            self.assertEqual(store.raw(s['id'])['compile']['jobs'],4)
            for command,status in [('pause','paused'),('resume','running'),('cancel','cancelled')]:
                p=self.call(d,command,s['id'])
                self.assertEqual(p.returncode,0,p.stderr)
                self.assertEqual(store.raw(s['id'])['status'],status)
            p=self.call(d,'list')
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(p.stdout)[0]['id'],s['id'])

    def test_host_cli_real_task_gate_and_invalid_jobs(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertNotEqual(self.call(d,'create','--mode','real').returncode,0)
            self.assertNotEqual(self.call(d,'create','--mode','mock','--jobs','0').returncode,0)
            self.assertEqual(Store(Path(d)).runs(),[])
            p=self.call(d,'create','--mode','real',enable_real='1')
            self.assertNotEqual(p.returncode,0,'ENABLE_REAL alone cannot replace online deployment acceptance')
            self.assertEqual(Store(Path(d)).runs(),[])

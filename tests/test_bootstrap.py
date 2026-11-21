import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from scripts.gates import fingerprint

ROOT=Path(__file__).resolve().parents[1]

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        (self.root/'scripts').mkdir();(self.root/'reports').mkdir()
        for name in ['bootstrap_server.sh','gates.py']:
            source=ROOT/'scripts'/name
            if source.exists():shutil.copyfile(source,self.root/'scripts'/name)
        self.receipt={'sourceSha256':fingerprint(self.root),'checks':{name:{'exitCode':0} for name in ['backend','charts','build','browser','compose','http','worker_smoke','amd64_worker_smoke','lake_pipeline','apparmor_profile']}}
        (self.root/'reports/local-acceptance.json').write_text(json.dumps(self.receipt))

    def run_script(self,*args):
        return subprocess.run(['bash',str(self.root/'scripts/bootstrap_server.sh'),*args],capture_output=True,text=True)

    def test_default_dry_run_checks_source_and_writes_nothing(self):
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=self.run_script()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('DRY RUN',result.stdout);self.assertIn('ENABLE_REAL=0',result.stdout)
        self.assertIn('500 GiB',result.stdout);self.assertIn('certbot',result.stdout)
        self.assertIn('APPARMOR_PROFILE=lean-observatory-worker',result.stdout)
        self.assertIn('worker-fixture',result.stdout)
        after={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_stale_gate_rejected_before_any_host_changes(self):
        (self.root/'changed').write_text('new source')
        result=self.run_script('--dry-run');self.assertNotEqual(result.returncode,0)
        self.assertIn('本地',result.stderr+result.stdout)
        self.assertFalse((self.root/'.env').exists())

    def test_unknown_flags_cannot_execute(self):
        result=self.run_script('--force')
        self.assertNotEqual(result.returncode,0);self.assertFalse((self.root/'.env').exists())

if __name__=='__main__': unittest.main()

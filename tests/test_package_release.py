import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from scripts.gates import fingerprint,REQUIRED_CHECKS

ROOT=Path(__file__).resolve().parents[1]
class PackageReleaseTests(unittest.TestCase):
    def test_release_ownership_and_modes_work_on_a_fresh_root_server(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'scripts').mkdir();(root/'reports').mkdir()
            for name in ['gates.py','package_release.py']:shutil.copyfile(ROOT/'scripts'/name,root/'scripts'/name)
            source=root/'source.py';source.write_text(root.name);source.chmod(0o666)
            (root/'reports/local-acceptance.json').write_text(json.dumps({'sourceSha256':fingerprint(root),'checks':{k:{'exitCode':0} for k in REQUIRED_CHECKS}}))
            result=subprocess.run([sys.executable,str(root/'scripts/package_release.py')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            archive=Path(json.loads(result.stdout)['archive']);self.addCleanup(archive.unlink,missing_ok=True);self.addCleanup(Path(str(archive)+'.sha256').unlink,missing_ok=True)
            with tarfile.open(archive) as bundle:
                for entry in bundle.getmembers():
                    self.assertEqual((entry.uid,entry.gid),(0,0))
                    self.assertEqual(entry.mode & 0o022,0)
                    self.assertEqual(entry.mode & 0o6000,0)

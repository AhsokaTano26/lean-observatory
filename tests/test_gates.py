import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('gates',Path(__file__).resolve().parents[1]/'scripts/gates.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

class GateTests(unittest.TestCase):
    def test_missing_or_stale_receipt_blocks_remote(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'reports').mkdir()
            with self.assertRaises(RuntimeError):g.require_local_gate(root)
            checks={k:{'exitCode':0} for k in ['backend','charts','build','browser','compose','http','worker_smoke','amd64_worker_smoke','lake_pipeline','apparmor_profile']}
            report={'sourceSha256':g.fingerprint(root),'checks':checks}
            (root/'reports/local-acceptance.json').write_text(json.dumps(report))
            g.require_local_gate(root)
            (root/'changed.py').write_text('change')
            with self.assertRaises(RuntimeError):g.require_local_gate(root)

    def test_nonzero_check_blocks_even_matching_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'reports').mkdir();(root/'reports/local-acceptance.json').write_text(json.dumps({'sourceSha256':g.fingerprint(root),'checks':{'backend':{'exitCode':1}}}))
            with self.assertRaises(RuntimeError):g.require_local_gate(root)

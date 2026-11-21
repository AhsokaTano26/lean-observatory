import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class AcceptanceEnvironmentTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required for frontend runner test')
    def test_node_child_runs_instead_of_silently_skipping_under_node_parent(self):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('accept',root/'deploy/ns/local_acceptance.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'executed';fixture=Path(directory)/'fixture.test.mjs'
            fixture.write_text("import test from 'node:test';import{writeFileSync}from'node:fs';test('actually executed',()=>writeFileSync(process.env.ACCEPT_MARKER,'yes'));")
            env=m.execution_environment({**os.environ,'NODE_TEST_CONTEXT':'child-v8','ACCEPT_MARKER':str(marker)})
            result=subprocess.run(['node','--test',str(fixture)],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(marker.exists(),'Node child silently skipped its tests')

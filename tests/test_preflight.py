import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('preflight',Path(__file__).resolve().parents[1]/'scripts/preflight.py')
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class PreflightTests(unittest.TestCase):
    def test_fresh_server_without_docker_still_returns_a_report(self):
        namespace={}
        prefix=p.REMOTE.split('mem=')[0]
        exec(prefix,namespace)
        with patch('subprocess.run',side_effect=FileNotFoundError('docker')):
            try: result=namespace['cmd'](['docker','version'])
            except FileNotFoundError: self.fail('A fresh Ubuntu host must report a missing optional tool instead of aborting inspection')
        self.assertEqual(result['exitCode'],127)

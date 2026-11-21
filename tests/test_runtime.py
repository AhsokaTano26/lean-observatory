import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from backend.store import Store
from backend.runner import CommandRunner, CommandError
from backend.metrics import collect


class RuntimeTests(unittest.TestCase):
    def test_nonzero_exit_is_persisted_and_raised(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            s = store.create('real')
            runner = CommandRunner(store, s['id'])
            with self.assertRaises(CommandError):
                runner.run([sys.executable, '-c', 'print("failure evidence"); raise SystemExit(7)'], Path(d), 'compile')
            r = store.raw(s['id'])
            self.assertEqual(r['commands'][-1]['exitCode'], 7)
            self.assertIn('failure evidence', (Path(d)/'runs'/s['id']/r['commands'][-1]['logFile']).read_text())

    def test_command_capture_and_no_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d)); s = store.create('real')
            text = CommandRunner(store, s['id']).run([sys.executable, '-c', 'import sys; print(sys.argv[1])', '$(echo secret)'], Path(d), 'audit')
            self.assertIn('$(echo secret)', text)
            self.assertEqual(store.raw(s['id'])['commands'][0]['exitCode'], 0)

    def test_metrics_explicit_source_and_non_negative(self):
        m = collect(Path(tempfile.gettempdir()))
        self.assertEqual(m['source'], 'local_host')
        self.assertGreater(m['diskTotalBytes'], 0)
        self.assertGreater(m['cpuCount'], 0)
        self.assertIn('sampledAt', m)
        self.assertGreaterEqual(m['diskUsedBytes'], 0)

    def test_paused_eta_unknown(self):
        from backend.model import initial_state, derived
        s=initial_state('real'); s['status']='paused'
        s['compile'].update(total=100,succeeded=2,rate=2)
        self.assertIsNone(derived(s)['compile']['etaSeconds'])

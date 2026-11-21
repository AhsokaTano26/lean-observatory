import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from backend.api import make_server
from backend.store import Store


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.tmp.name))
        self.server=make_server(self.store, ('127.0.0.1',0), token='test-secret')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.tmp.cleanup()

    def req(self, path, data=None, token=None):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        return urllib.request.urlopen(urllib.request.Request(self.base+path, data=json.dumps(data).encode() if data is not None else None,headers=headers), timeout=3)

    def test_health_and_waiting_state(self):
        self.assertTrue(json.load(self.req('/healthz'))['ok'])
        self.assertIsNone(json.load(self.req('/api/state'))['run']['id'])

    def test_mutation_auth_and_invalid_scenario(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.req('/api/runs', {'mode':'mock'})
        self.assertEqual(e.exception.code,401); e.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.req('/api/runs', {'mode':'mock','scenario':'oops'},'test-secret')
        self.assertEqual(e.exception.code,400); e.exception.close()

    def test_real_is_disabled_until_deployment_gate(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.req('/api/runs', {'mode':'real'},'test-secret')
        self.assertEqual(e.exception.code,403); e.exception.close()

    def test_mock_report_and_sse_have_provenance(self):
        s=json.load(self.req('/api/runs',{'mode':'mock','scenario':'success'},'test-secret'))
        report=json.load(self.req('/api/report.json?run='+s['id']))
        self.assertEqual(report['run']['mode'],'mock')
        self.assertFalse(report['run']['proofAccepted'])
        with self.req('/api/events') as stream:
            lines=[stream.readline().decode() for _ in range(4)]
        self.assertIn('event: snapshot\n',lines)
        self.assertIn('"mode":"mock"',''.join(lines))

    def test_conflicting_task_rejected(self):
        self.req('/api/runs',{'mode':'mock'},'test-secret').close()
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.req('/api/runs',{'mode':'mock'},'test-secret')
        self.assertEqual(e.exception.code,409); e.exception.close()

    def test_full_log_download_contains_untruncated_command_output(self):
        import io,tarfile
        s=self.store.create('mock');raw=b'x'*24000+b'\n'
        (self.store.root/'runs'/s['id']/'command-000-compile.log').write_bytes(raw)
        with self.req('/api/logs/download?run='+s['id']) as response: blob=response.read()
        with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
            self.assertEqual(archive.extractfile('command-000-compile.log').read(),raw)
            self.assertIn('snapshot.json',archive.getnames())

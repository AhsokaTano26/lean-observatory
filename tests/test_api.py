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
        self.server=make_server(self.store, ('127.0.0.1',0))
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

    def test_dashboard_rejects_all_task_writes_even_with_previous_admin_token(self):
        s=self.store.create('mock')
        before=self.store.raw(s['id'])
        for method in ['POST','PUT','PATCH','DELETE']:
            for path in ['/api/runs','/api/control']:
                with self.subTest(method=method,path=path):
                    request=urllib.request.Request(self.base+path,data=json.dumps({'mode':'mock','run':s['id'],'action':'pause'}).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer test-secret'},method=method)
                    with self.assertRaises(urllib.error.HTTPError) as e:
                        urllib.request.urlopen(request,timeout=3)
                    self.assertEqual(e.exception.code,405)
                    self.assertEqual(e.exception.headers.get('Allow'),'GET')
                    e.exception.close()
        self.assertEqual(self.store.raw(s['id']),before)
        self.assertEqual(len(self.store.runs()),1)

    def test_mock_report_and_sse_have_provenance(self):
        s=self.store.create('mock','success')
        report=json.load(self.req('/api/report.json?run='+s['id']))
        self.assertEqual(report['run']['mode'],'mock')
        self.assertFalse(report['run']['proofAccepted'])
        with self.req('/api/events') as stream:
            lines=[stream.readline().decode() for _ in range(4)]
        self.assertIn('event: snapshot\n',lines)
        self.assertIn('"mode":"mock"',''.join(lines))

    def test_read_only_capability_and_task_history(self):
        s=self.store.create('mock')
        self.assertEqual(json.load(self.req('/api/state'))['capabilities'],{'readOnly':True})
        self.assertEqual(json.load(self.req('/api/runs'))[0]['id'],s['id'])

    def test_full_log_download_contains_untruncated_command_output(self):
        import io,tarfile
        s=self.store.create('mock');raw=b'x'*24000+b'\n'
        (self.store.root/'runs'/s['id']/'command-000-compile.log').write_bytes(raw)
        with self.req('/api/logs/download?run='+s['id']) as response: blob=response.read()
        with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
            self.assertEqual(archive.extractfile('command-000-compile.log').read(),raw)
            self.assertIn('snapshot.json',archive.getnames())

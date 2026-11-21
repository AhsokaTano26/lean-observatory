import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from ns_queue.store import QueueStore
from ns_queue.web import make_server, payload
from tests.test_ns_queue import NS_SPEC, RH_ID


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=QueueStore(self.temp.name); self.store.initialize(NS_SPEC,RH_ID,{'capUsd':0})
        self.server=make_server(QueueStore.readonly(self.temp.name),('127.0.0.1',0))
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.url='http://127.0.0.1:'+str(self.server.server_port)

    def get(self,path):
        with urllib.request.urlopen(self.url+path,timeout=3) as response:return response.read()

    def test_static_ui_and_evidence_driven_state(self):
        self.assertIn('Navier',self.get('/ns/').decode())
        state=json.loads(self.get('/api/state'))
        self.assertEqual(state['queue']['status'],'QUEUED')
        self.assertEqual(state['queue']['budget']['capUsd'],0)
        self.assertEqual(state['nsResources']['source'],'not_started')
        self.assertEqual(state['nsResources']['memoryBytes'],0)
        self.assertFalse(state['actualInvoiceAvailable'])

    def test_missing_observations_are_unknown_not_zero_usage(self):
        self.assertIsNone(payload(self.store)['rhEstimatedUsd'])
        self.store.mutate(lambda s:s.update(status='RUNNING',startedAt=1))
        state=payload(self.store)
        self.assertEqual(state['nsResources']['source'],'unavailable')
        self.assertIsNone(state['nsResources']['memoryBytes'])

    def test_all_mutations_are_rejected_without_changing_state(self):
        before=self.store.snapshot()
        for method in ['POST','PUT','PATCH','DELETE']:
            with self.subTest(method=method):
                request=urllib.request.Request(self.url+'/api/control',data=b'{}',method=method)
                with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code,405);self.assertEqual(caught.exception.headers['Allow'],'GET');caught.exception.close()
        self.assertEqual(before,self.store.snapshot())

    def test_sse_reconnect_replays_only_unseen_log_rows(self):
        first=self.store.log('scheduler','first')
        second=self.store.log('scheduler','second')
        request=urllib.request.Request(self.url+'/api/events',headers={'Last-Event-ID':str(first)})
        with urllib.request.urlopen(request,timeout=3) as response:
            packet=b''
            while not packet.endswith(b'\n\n'):packet+=response.readline()
        self.assertIn(b'event: snapshot',packet)
        data=json.loads(next(x[6:] for x in packet.splitlines() if x.startswith(b'data: ')))
        self.assertEqual([x['id'] for x in data['logs']],[second])


if __name__=='__main__': unittest.main()

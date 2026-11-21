import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ns_queue.notify import build_payload, deliver


class NotificationTests(unittest.TestCase):
    def test_payload_is_bounded_flat_and_uses_only_authorized_fields(self):
        body = build_payload({'title': '预算不足', 'message': '长消息' * 3000,
                              'level': 'warning', 'fields': {'任务': 'ns-test', '预算': 0}})
        self.assertLessEqual(len(json.dumps(body, ensure_ascii=False).encode()), 1500)
        self.assertLessEqual(set(body), {'title', 'message', 'source', 'level', 'timestamp', 'fields', 'url'})
        self.assertEqual(body['fields']['预算'], 0)
        self.assertIn('+00:00', body['timestamp'])
        self.assertTrue(body['message'])
        with self.assertRaises(ValueError):
            build_payload({'message': 'x', 'fields': {'nested': {'x': 1}}})

    def test_200_and_202_are_distinct_acknowledgements(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            status = 200
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(self.status); self.end_headers()
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/webhook'
        self.assertEqual(deliver(url, {'message': 'test'}, allow_local_http=True)['status'], 'sent')
        Handler.status = 202
        self.assertEqual(deliver(url, {'message': 'queued'}, allow_local_http=True)['status'], 'accepted')
        Handler.status = 500
        self.assertEqual(deliver(url, {'message': 'retry'}, allow_local_http=True)['status'], 'retry')
        self.assertEqual([x['message'] for x in received], ['test', 'queued', 'retry'])

    def test_insecure_or_credentialed_webhooks_are_rejected(self):
        for url in ['http://example.org/hook', 'https://u:p@example.org/hook', 'file:///etc/passwd']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                deliver(url, {'message': 'x'})


if __name__ == '__main__': unittest.main()

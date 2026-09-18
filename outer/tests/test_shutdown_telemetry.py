"""Provider queueing, cancellation and partial monitor observations are distinct."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from harness import gateway, live_usage, monitor, profiles, runtime, util


class ShutdownTelemetryTests(unittest.TestCase):
    def test_cancel_during_headers_or_stream_keeps_terminal_and_stops_socket(self):
        for sent_headers in (False, True):
            with self.subTest(sent_headers=sent_headers), tempfile.TemporaryDirectory() as tmp:
                entered, release = threading.Event(), threading.Event()
                class Upstream(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        if sent_headers:
                            self.send_response(200)
                            self.end_headers()
                            self.wfile.write(b': waiting ' + b'.' * 128 + b'\n\n')
                            self.wfile.flush()
                        entered.set()
                        release.wait(10)
                upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
                proxy = gateway.Gateway(('127.0.0.1', 0), tmp, 'A', 'test-model', 'test-canary',
                    upstream_host='127.0.0.1', upstream_port=upstream.server_port, tls=False)
                for server in (upstream, proxy):
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                client = http.client.HTTPConnection('127.0.0.1', proxy.server_port, timeout=5)
                try:
                    client.request('POST', '/v1/chat/completions', json.dumps({
                        'model':'test-model','stream':True,'messages':[{'role':'user','content':'fixture'}]}))
                    self.assertTrue(entered.wait(5))
                    proxy.cancel_and_shutdown()
                    proxy.server_close()
                    starts = util.read_lines(Path(tmp)/'started.jsonl')
                    ends = util.read_lines(Path(tmp)/'events.jsonl')
                    self.assertEqual(len(starts), 1)
                    self.assertEqual(len(ends), 1)
                    self.assertEqual(ends[0]['status'], 'cancelled')
                    self.assertIsNone(ends[0]['usage'])
                    self.assertEqual(ends[0]['response_sha256'],
                        util.sha256_file(Path(tmp)/ends[0]['response_file']))
                    self.assertFalse(proxy.active_sockets)
                    _, issues = live_usage.reconcile(starts, ends, 'A')
                    self.assertNotIn('incomplete_call_inventory', issues)
                    self.assertIn('request_not_completed', issues)
                finally:
                    client.close()
                    release.set()
                    proxy.shutdown(); proxy.server_close()
                    upstream.shutdown(); upstream.server_close()

    def test_partial_known_usage_is_not_a_complete_total(self):
        events = [{'status':'completed','usage':{'input_tokens':20,'output_tokens':5}},
                  {'status':'cancelled','usage':None}]
        totals = monitor.usage_totals(events)
        self.assertEqual(totals['input_tokens'], {'observed':20,'reported_requests':1,'total':None})
        self.assertEqual(totals['output_tokens'], {'observed':5,'reported_requests':1,'total':None})
        self.assertIsNone(monitor.usage_totals([])['input_tokens']['observed'])
        self.assertEqual(monitor.usage_totals(events[:1])['input_tokens']['total'],20)

    def test_monitor_trace_separates_reused_display_ids(self):
        event = {'request_id':'request','model_id':'test','status':'completed',
                 'started_at':'2026-09-18T00:00:00+00:00'}
        def trace(instance):
            return monitor.payload([event],'same-display-id', {'run_instance_id':instance})[
                'resourceSpans'][0]['scopeSpans'][0]['spans'][0]['traceId']
        self.assertNotEqual(trace('batch-A'), trace('batch-B'))

    def test_provider_timeout_is_frozen_separately_from_run_budget(self):
        condition = profiles.resolve(Path(__file__).resolve().parents[2], 'MS1-001', 'explore')
        options = runtime.opencode_config(condition)['provider']['sample2']['options']
        self.assertEqual(condition['budget']['value'],1800)
        self.assertEqual(options['timeout'],600000)
        self.assertEqual(options['headerTimeout'],600000)
        self.assertEqual(options['chunkTimeout'],600000)


if __name__ == '__main__':
    unittest.main()

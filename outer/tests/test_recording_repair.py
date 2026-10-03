"""Finite recording fault cases. Provider reports are observations, not billing."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import support
from harness import gateway, live_usage, profiles, runtime, util


class RecordingRepairTests(unittest.TestCase):
    def fixture(self, root, count=1, usage=True, done=True, conflict=False):
        raw = root / 'usage/raw'
        raw.mkdir(parents=True)
        util.write_new_json(root / 'manifest.json', {'schema_version':2,'run_id':'R',
            'run_instance_id':'I','stop_confirmed':True,'model_called':False})
        (root / 'inputs').mkdir()
        (root / 'inputs/prompt.txt').write_text('request', encoding='utf-8')
        context = {'method':'explore','blocks':[]}
        util.write_new_json(root / 'context.json', context)
        manifest = util.read_json(root / 'manifest.json')
        manifest['context_sha256'] = util.sha256_file(root / 'context.json')
        util.write_json_atomic(root / 'manifest.json', manifest)
        util.write_new_json(root / 'evidence/isolation.json', {'verified':True})
        util.append_line(root / 'evidence/agent.jsonl', {'type':'step_finish','sessionID':'native'})
        for i in range(count):
            rid = str(i)
            util.write_new_json(raw / (rid + '.request.json'), {'messages':[{'role':'user','content':'request'}]})
            native = {'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}
            item = {'model':'test-model','usage':native} if usage else {'model':'test-model'}
            stream = ('data: ' + json.dumps(item) + '\n\n' + ('data: [DONE]\n\n' if done else '')).encode()
            (raw / (rid + '.response.sse')).write_bytes(stream)
            event = {'run_id':'R','session_id':'I','event_id':rid,'request_id':rid,'model_id':'test-model',
                'request_file':rid+'.request.json','response_file':rid+'.response.sse',
                'request_sha256':util.sha256_file(raw/(rid+'.request.json')),
                'response_sha256':util.sha256_file(raw/(rid+'.response.sse')),
                'mode':'request','status':'completed' if done else 'cancelled',
                'usage':gateway.usage_from_native(native) if usage else None}
            util.append_line(raw / 'started.jsonl', {**event,'status':'started','usage':None})
            if conflict:
                event['usage'] = gateway.usage_from_native({'prompt_tokens':19,'completion_tokens':5})
            util.append_line(raw / 'events.jsonl', event)
        return raw

    def test_1094_controller_absent_initial_false_75_responses(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self.fixture(root, count=75, done=False)
            util.write_new_json(root / 'runtime.json', {'worker_started_at':'time'})
            evidence = live_usage.update_manifest_evidence(root)
            self.assertTrue(util.read_json(root / 'manifest.json')['model_called'])
            self.assertEqual(evidence['saved_response_count'], 75)
            normalized = live_usage.collect(root)
            self.assertEqual(normalized['observed_tokens'], 1875)
            self.assertIsNone(normalized['total_tokens'])
            self.assertFalse(normalized['usage_complete'])

    def test_partial_usage_absent_usage_and_done_only_never_manufacture_totals(self):
        for usage, done in ((True,False),(False,False),(False,True)):
            with self.subTest(usage=usage,done=done), tempfile.TemporaryDirectory() as t:
                root = Path(t)
                self.fixture(root, usage=usage, done=done)
                normalized = live_usage.collect(root)
                self.assertEqual(normalized['observed_tokens'], 25 if usage else None)
                self.assertFalse(normalized['usage_complete'])
                self.assertIsNone(normalized['total_tokens'])

    def test_1085_raw_journal_conflict_retains_both_amounts(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self.fixture(root, conflict=True)
            normalized = live_usage.collect(root)
            self.assertEqual(normalized['observed_tokens'],25)
            self.assertEqual(normalized['conflicts'][0]['journal_usage']['input_tokens'],19)
            self.assertEqual(normalized['conflicts'][0]['raw_usage']['input_tokens'],20)
            self.assertIsNone(normalized['total_tokens'])

    def test_before_send_is_distinct_from_after_send_before_ack(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            raw = self.fixture(root)
            for p in raw.iterdir(): p.unlink()
            self.assertEqual(live_usage.execution_evidence(root)['send_evidence'],'known_no_send')
            e = {'run_id':'R','session_id':'I','send_evidence':'unknown'}
            util.append_line(raw / 'transmission.jsonl',e)
            self.assertIsNone(live_usage.execution_evidence(root)['model_called'])
            util.append_line(raw / 'transmission.jsonl',{**e,'send_evidence':'observed_send'})
            result = live_usage.execution_evidence(root)
            self.assertTrue(result['model_called'])
            self.assertFalse(result['provider_acknowledged'])

    def test_parser_counts_last_cumulative_report_once_and_keeps_partial(self):
        data = b'data: {"usage":{"prompt_tokens":10,"completion_tokens":1}}\n\n'
        data += b'data: {"usage":{"prompt_tokens":10,"completion_tokens":3}}\n\n'
        data += b'data: {"usage":'
        result = gateway.parse_sse(data)
        self.assertEqual(result['usage']['input_tokens'],10)
        self.assertEqual(result['usage']['output_tokens'],3)
        self.assertFalse(result['stream_done'])
        self.assertTrue(result['parse_errors'])

    def test_storage_failure_before_send_stops_without_upstream(self):
        called = []
        with tempfile.TemporaryDirectory() as t:
            class Upstream(BaseHTTPRequestHandler):
                def do_POST(self): called.append(True)
                def log_message(self,*_): pass
            upstream = ThreadingHTTPServer(('127.0.0.1',0),Upstream)
            proxy = gateway.Gateway(('127.0.0.1',0),t,'R','test-model','canary',
                upstream_host='127.0.0.1',upstream_port=upstream.server_port,tls=False)
            threading.Thread(target=proxy.serve_forever,daemon=True).start()
            try:
                with patch.object(proxy,'record',side_effect=OSError('injected disk full')):
                    client = http.client.HTTPConnection('127.0.0.1',proxy.server_port,timeout=5)
                    client.request('POST','/v1/chat/completions',json.dumps({'model':'test-model',
                        'stream':True,'messages':[{'role':'user','content':'request'}]}))
                    response=client.getresponse()
                    self.assertEqual(response.status,507)
                    response.read(); client.close()
                self.assertTrue(proxy.failed.is_set())
                self.assertFalse(called)
            finally:
                proxy.shutdown(); proxy.server_close(); upstream.server_close()

    def test_declared_common_hash_matches_actual_worker_mount_path(self):
        repo=Path(__file__).resolve().parents[2]
        condition=profiles.resolve(repo,'MS1-001','explore','deepseek-migration-v1')
        prompt,context=profiles.prepare_prompt(condition,repo)
        self.assertIn('/inputs/legacy-source',prompt)
        self.assertEqual(context['common_sha256'],util.sha256_bytes(prompt.encode()))

    def test_foreign_instance_responses_cannot_prove_this_instance_called_model(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); raw=self.fixture(root)
            for name in ('started.jsonl','events.jsonl'):
                rows=util.read_lines(raw/name)
                for row in rows: row['session_id']='another-instance'
                (raw/name).write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
            evidence=live_usage.execution_evidence(root)
            self.assertIsNone(evidence['model_called'])
            self.assertEqual(evidence['attributed_saved_response_count'],0)
            self.assertIn('identity_mismatch',evidence['issues'])


if __name__ == '__main__': unittest.main()

"""Non-model regression tests: profiles, gateway, recording and isolation contracts."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from support import write_text
from harness import profiles, gateway, live_usage, runtime, security, util, preserve, ownership

REPO = Path(__file__).resolve().parents[2]


class ProfileTests(unittest.TestCase):
    def test_prepared_run_keeps_profiles_after_repository_edits(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)/'repo'
            shutil.copytree(REPO/'outer/profiles', repo/'outer/profiles')
            shutil.copytree(REPO/'inner/spec', repo/'inner/spec')
            task = profiles.read(repo, 'tasks', 'MS1-001')
            source = repo/'artifacts/sources'/task['start_state']['source_commit']
            source.mkdir(parents=True)
            (source/'source.txt').write_text('original public source')
            util.write_new_json(source.parent/(source.name+'.json'), {'files':util.tree_hashes(source)})
            prepared = repo/'artifacts/runtime/MS1-001'
            bundle = prepared/'evaluator'
            bundle.mkdir(parents=True)
            (bundle/'MusicStore.Evaluator.dll').write_bytes(b'non-executable-test-double')
            util.write_new_json(prepared/'lock.json', {'opencode_version':'1.17.11', 'versions':{},
                'evaluator_files':util.tree_hashes(bundle), 'evaluator_sha256':util.sha256_file(bundle/'MusicStore.Evaluator.dll'),
                'evaluator_build':{'clean_worktree':True}, 'images':{}})
            manifest = profiles.create(repo, Path(tmp)/'runs', 'MS1-001', 'explained', 1)
            root = Path(tmp)/'runs'/manifest['run_id']
            before = profiles.validate_run(root)
            task['migration_request'] = 'different task'
            util.write_json_atomic(repo/'outer/profiles/tasks/MS1-001.json', task)
            self.assertEqual(profiles.validate_run(root), before)
            context = util.read_json(root/'context.json')
            context['blocks'][0]['text'] = 'tampered'
            util.write_json_atomic(root/'context.json', context)
            with self.assertRaises(ValueError):
                profiles.validate_run(root)

    def test_axes_keep_the_public_contract_identical(self):
        conditions = [profiles.resolve(REPO, 'MS1-001', i) for i in ('explore', 'preload', 'explained')]
        self.assertEqual(len({c['migration_request'] for c in conditions}), 1)
        self.assertEqual(len({json.dumps(c['evaluation'], sort_keys=True) for c in conditions}), 1)
        self.assertEqual(len({c['intervention']['method'] for c in conditions}), 3)

    def test_profiles_reject_path_escape(self):
        for value in ('../task', '/absolute', 'x/y', 'x\\y', '', '..'):
            with self.assertRaises(ValueError):
                profiles.identifier(value)

    def test_preload_and_explanation_are_actual_prompt_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            relative = 'MvcMusicStore-Completed/MvcMusicStore/Controllers'
            (source / relative).mkdir(parents=True)
            write_text(source / relative / 'StoreController.cs', 'source-marker-unique')
            for name in ('preload', 'explained'):
                prompt, evidence = profiles.prepare_prompt(profiles.resolve(REPO, 'MS1-001', name), source)
                self.assertTrue(evidence['blocks'])
                self.assertTrue(all(b['text'] in prompt for b in evidence['blocks']))

    def test_child_environment_does_not_inherit_credentials(self):
        with patch.dict(os.environ, {'OPENCODE_GO_API_KEY': 'canary', 'OPENAI_API_KEY': 'canary',
                                     'GITHUB_TOKEN': 'canary', 'UNRELATED_SECRET': 'canary'}):
            child = security.child_environment()
            self.assertNotIn('canary', child.values())

    def test_all_agent_models_use_one_gateway(self):
        c = runtime.opencode_config(profiles.resolve(REPO, 'MS1-001', 'explore'))
        self.assertEqual(c['model'], c['small_model'])
        self.assertEqual(c['enabled_providers'], ['sample2'])
        self.assertEqual(c['permission']['task'], 'deny')
        self.assertNotIn('OPENCODE_GO_API_KEY', json.dumps(c))


class GatewayTests(unittest.TestCase):
    def test_provider_faults_and_missing_usage_are_not_successful_measurement(self):
        for mode in ('http_error', 'missing_usage', 'wrong_model', 'cut_stream', 'echo_secret'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                class Upstream(BaseHTTPRequestHandler):
                    def log_message(self, *_): pass
                    def do_POST(self):
                        self.rfile.read(int(self.headers['Content-Length']))
                        self.send_response(503 if mode == 'http_error' else 200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.end_headers()
                        item = {'model': 'other' if mode == 'wrong_model' else 'test-model',
                                'choices': [{'delta': {'content': 'secret-test-only' if mode == 'echo_secret' else 'partial'}}]}
                        if mode != 'missing_usage':
                            item['usage'] = {'prompt_tokens': 10, 'completion_tokens': 2}
                        text = 'data: ' + json.dumps(item) + '\n\n'
                        if mode != 'cut_stream':
                            text += 'data: [DONE]\n\n'
                        self.wfile.write(text.encode())
                upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
                proxy = gateway.Gateway(('127.0.0.1', 0), tmp, 'A', 'test-model', 'secret-test-only',
                    upstream_host='127.0.0.1', upstream_port=upstream.server_port, tls=False)
                for server in (upstream, proxy):
                    threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    client = http.client.HTTPConnection('127.0.0.1', proxy.server_port, timeout=5)
                    client.request('POST', '/v1/chat/completions', json.dumps({'model':'test-model',
                        'stream': True, 'messages':[{'role':'user','content':'fixture'}]}))
                    body = client.getresponse().read()
                    self.assertNotIn(b'secret-test-only', body)
                    client.close()
                finally:
                    proxy.shutdown(); proxy.server_close()
                    upstream.shutdown(); upstream.server_close()
                events, issues = live_usage.reconcile(util.read_lines(Path(tmp)/'started.jsonl'),
                    util.read_lines(Path(tmp)/'events.jsonl'), 'A')
                self.assertEqual(len(events), 1)
                if mode == 'missing_usage':
                    self.assertIsNone(events[0]['usage'])
                else:
                    self.assertTrue(issues)
                    self.assertTrue((Path(tmp)/'failure.jsonl').exists())
                for p in Path(tmp).iterdir():
                    self.assertNotIn(b'secret-test-only', p.read_bytes())

    def test_secret_redaction_across_every_chunk_boundary(self):
        raw = b'prefix secret-canary-123 suffix'
        for split in range(len(raw) + 1):
            filt = gateway.SecretFilter('secret-canary-123')
            result = filt.feed(raw[:split]) + filt.feed(raw[split:]) + filt.feed(b'', final=True)
            self.assertNotIn(b'secret-canary-123', result)
            self.assertIn(b'[REDACTED]', result)
            self.assertTrue(filt.detected)

    def test_optional_usage_is_unknown_not_zero(self):
        u = gateway.usage_from_native({'prompt_tokens': 10, 'completion_tokens': 2})
        self.assertIsNone(u['cache_read_tokens'])
        self.assertIsNone(u['reasoning_tokens'])

    def test_real_http_relay_records_every_call_without_credential(self):
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.server.seen = (self.path, self.headers['Authorization'], self.headers['x-opencode-session'], body)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                event = {'id': 'response-1', 'model': 'test-model', 'choices': [],
                         'usage': {'prompt_tokens': 20, 'completion_tokens': 5}}
                self.wfile.write(('data: ' + json.dumps(event) + '\n\ndata: [DONE]\n\n').encode())
        with tempfile.TemporaryDirectory() as tmp:
            upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
            proxy = gateway.Gateway(('127.0.0.1', 0), tmp, 'run-1', 'test-model', 'secret-test-only',
                                    upstream_host='127.0.0.1', upstream_port=upstream.server_port, tls=False)
            for server in (upstream, proxy):
                threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                request = {'model': 'test-model', 'stream': True, 'messages': [{'role': 'user', 'content': 'code task'}]}
                client = http.client.HTTPConnection('127.0.0.1', proxy.server_port)
                client.request('POST', '/v1/chat/completions', json.dumps(request))
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                response.read()
                client.close()
            finally:
                proxy.shutdown(); proxy.server_close()
                upstream.shutdown(); upstream.server_close()
            self.assertEqual(upstream.seen[1], 'Bearer secret-test-only')
            self.assertEqual(upstream.seen[2], 'run-1')
            events, issues = live_usage.reconcile(util.read_lines(Path(tmp) / 'started.jsonl'),
                                                 util.read_lines(Path(tmp) / 'events.jsonl'), 'run-1')
            self.assertEqual(issues, [])
            self.assertEqual(events[0]['usage']['input_tokens'], 20)
            for path in Path(tmp).iterdir():
                self.assertNotIn(b'secret-test-only', path.read_bytes())


class InventoryTests(unittest.TestCase):
    def test_numbered_read_mapping_requires_every_original_line(self):
        value = '<content>\n1: first\n2: second\n\n(End of file - total 2 lines)\n</content>'
        def locations(text):
            return live_usage.input_locations([{'role':'user','content':text}], 'first\nsecond\n')
        self.assertTrue(locations(value))
        self.assertFalse(locations(value.replace('second', 'different')))
        self.assertFalse(locations(value.replace('2: second', '3: second')))
        self.assertFalse(locations(value.replace('total 2', 'total 3')))
        self.assertFalse(live_usage.input_locations([{'role':'assistant','content':value}], 'first\nsecond\n'))

    def event(self):
        return {'run_id': 'A', 'session_id': 'A', 'request_id': 'r', 'event_id': 'r',
                'model_id': 'm', 'request_sha256': 'h', 'status': 'completed'}

    def test_unfinished_call_invalidates_inventory(self):
        _, issues = live_usage.reconcile([self.event()], [], 'A')
        self.assertIn('incomplete_call_inventory', issues)

    def test_same_display_run_name_in_another_batch_cannot_supply_usage(self):
        event = dict(self.event(), session_id='unique-instance-A')
        self.assertEqual(live_usage.reconcile([event], [event], 'A', 'unique-instance-A')[1], [])
        events, issues = live_usage.reconcile([event], [event], 'A', 'unique-instance-B')
        self.assertEqual(events, [])
        self.assertIn('identity_mismatch', issues)

    def test_duplicate_and_foreign_calls_are_rejected(self):
        event = self.event()
        self.assertTrue(live_usage.reconcile([event, event], [event], 'A')[1])
        self.assertTrue(live_usage.reconcile([event], [dict(event, run_id='B')], 'A')[1])

    def test_changed_request_cannot_be_joined(self):
        e = self.event()
        self.assertIn('event_identity_changed', live_usage.reconcile([e], [dict(e, request_sha256='other')], 'A')[1])

    def test_interrupted_jsonl_keeps_valid_originals_and_flags_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'events.jsonl'
            p.write_bytes(b'{"request_id":"first"}\n{"request_id":')
            records, issues = live_usage.journal(p)
            self.assertEqual(records, [{'request_id': 'first'}])
            self.assertEqual(issues, ['events.jsonl:invalid_line:2'])
            self.assertTrue(p.read_bytes().endswith(b'{"request_id":'))


class PreservationAndOwnershipTests(unittest.TestCase):
    def test_stopping_a_completed_run_does_not_rewrite_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            util.write_new_json(root/'manifest.json', {'ended_at':'recorded', 'stop_confirmed':True, 'end_reason':'completed'})
            before = util.tree_hashes(root)
            result = runtime.request_stop(root)
            self.assertTrue(result['already_stopped'])
            self.assertEqual(util.tree_hashes(root), before)

    def test_long_windows_paths_package_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'source'
            src.mkdir()
            (src / 'original.txt').write_text('evidence', encoding='utf-8')
            deep = Path(tmp) / ('a' * 90) / ('b' * 90) / ('c' * 90)
            archive = deep / 'archive'
            destination = deep / 'restored'
            try:
                reference = preserve.pack(archive, 'long-path-case', {'inputs': src})
                preserve.restore(archive, reference, destination)
                self.assertEqual(preserve.tree(destination), preserve.verify(archive, reference['package_id'])['files'])
                self.assertEqual((preserve.native_path(destination) / 'inputs/original.txt').read_text(), 'evidence')
            finally:
                import shutil
                self.assertTrue(deep.resolve().is_relative_to(Path(tmp).resolve()))
                if preserve.native_path(deep).exists():
                    shutil.rmtree(preserve.native_path(deep))

    def test_competing_controllers_cannot_own_the_same_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with ownership.lease(tmp):
                with self.assertRaises(BlockingIOError):
                    with ownership.lease(tmp):
                        self.fail('Second lease acquired')
            with ownership.lease(tmp):
                pass

    def test_missing_inspect_does_not_mean_confirmed_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            util.write_new_json(Path(tmp) / 'runtime.json', {'run_id': 'A', 'worker': 'w', 'gateway': 'g'})
            from subprocess import CompletedProcess
            with patch.object(runtime, 'inspect_container', return_value=None), patch.object(runtime, 'docker',
                    return_value=CompletedProcess([], 1, '', 'daemon unavailable')):
                self.assertFalse(runtime.stop_owned(tmp))

    def test_ownership_mismatch_never_stops_someone_elses_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            util.write_new_json(Path(tmp) / 'runtime.json', {'run_id': 'A', 'worker': 'w', 'gateway': 'g'})
            with patch.object(runtime, 'inspect_container', return_value={'Config': {'Labels': {'sample2.run':'B'}}}), \
                    patch.object(runtime, 'docker') as docker:
                with self.assertRaises(RuntimeError):
                    runtime.stop_owned(tmp)
                docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()

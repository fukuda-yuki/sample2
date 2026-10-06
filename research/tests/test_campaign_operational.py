"""Finite nonmodel adapter safety checks; integration receipts are separate."""
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
import uuid
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from research import campaign_operational as op
from research import pair_execution as pairs
from outer.harness import util


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_pins_are_required_and_actual_bytes_checked(self):
        repo = self.root / 'repo'; repo.mkdir()
        (repo / 'a.py').write_text('original')
        op.verify_pins(repo, {'a.py': util.sha256_file(repo / 'a.py')}, required=('a.py',))
        for pins in ({}, {'a.py': 'f' * 64}, {'../a.py': 'f' * 64}):
            with self.assertRaises(ValueError): op.verify_pins(repo, pins, required=('a.py',))

    def test_session_evidence_requires_exact_identity_and_empty_messages(self):
        receipt = {'created': {'id': 'ses_fixture'}, 'read': {'id': 'ses_fixture'},
                   'abort': True, 'messages': [], 'status': {}}
        self.assertEqual(op.validate_session(receipt), 'ses_fixture')
        for field, value in [('read', {'id': 'ses_foreign'}), ('messages', [{'id': 'msg'}]),
                             ('abort', False), ('status', {'ses_fixture': {'type': 'busy'}})]:
            changed = {**receipt, field: value}
            with self.assertRaises(ValueError): op.validate_session(changed)

    def test_run_guard_foreign_stale_stop_and_late_writer(self):
        run = self.root / 'run'; run.mkdir()
        util.write_new_json(run / 'manifest.json', {'run_id': 'a', 'run_instance_id': 'a' * 32})
        binding = {'run_id': 'a', 'run_instance_id': 'a' * 32}
        op.verify_run(run, binding)
        with self.assertRaises(ValueError): op.verify_run(run, {**binding, 'run_instance_id': 'b' * 32})
        util.write_new_json(run / 'stop-request.json', {'run_id': 'a', 'run_instance_id': 'b' * 32})
        with self.assertRaises(ValueError): op.verify_run(run, binding)
        before = op.inventory(run)
        (run / 'late.txt').write_text('late')
        with self.assertRaises(ValueError): op.verify_unchanged(run, before)

    def test_zero_gateway_count_inspects_actual_records(self):
        records = self.root / 'records'; records.mkdir()
        self.assertEqual(op.gateway_count(records), 0)
        (records / 'events.jsonl').write_text('{"event":"request"}\n')
        with self.assertRaises(ValueError): op.gateway_count(records)

    def test_stop_receipt_requires_gateway_ack_and_bound_scope(self):
        b = {'run_id': 'a', 'run_instance_id': 'a' * 32}
        r = {**b, 'confirmed': True, 'method': 'gateway_ack', 'admission_closed': True}
        op.validate_fence(r, b)
        for update in ({'method': 'fallback'}, {'run_instance_id': 'b' * 32}, {'confirmed': False}):
            with self.assertRaises(ValueError): op.validate_fence({**r, **update}, b)

    def test_real_pair_driver_postprocess_fault_cannot_replay_or_overwrite(self):
        batch = self.root / 'batch'
        plan = {'plan_sha256': 'a' * 64, 'cohort': 'finite', 'runtime': 'nonmodel',
                'pair_concurrency': 1, 'require_fixed_instances': True}
        cases = [{'run_id': 'a' + str(i), 'run_instance_id': uuid.uuid4().hex,
                  'pair': 1, 'slot': i, 'task': 'dummy', 'condition': 'dummy', 'attempt': i} for i in (1, 2)]
        def prepare(b):
            root = batch / b['run_id']; root.mkdir(parents=True)
            manifest = {**b, 'schema_version': 1, 'prompt_sha256': 'b' * 64,
                        'condition_sha256': 'c' * 64, 'stop_confirmed': True}
            util.write_new_json(root / 'manifest.json', manifest)
            return manifest
        def implement(repo, batch, rid):
            b = next(c for c in cases if c['run_id'] == rid)
            result = subprocess.run([sys.executable, '-B', '-c', 'print("nonmodel child")'],
                                    env=op.safe_environment(), capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            return {**b, 'stop_confirmed': True, 'model_calls': 0}
        def fault(*args): raise RuntimeError('deliberate bounded postprocess fault')
        result = pairs.execute_pair(plan, cases, batch, repo=self.root,
                                    prepare=prepare, implement=implement, postprocess=fault)
        self.assertEqual(result['reason'], 'postprocess_fault')
        before = op.inventory(batch)
        again = pairs.execute_pair(plan, cases, batch, repo=self.root,
                                   prepare=prepare, implement=implement, postprocess=fault)
        self.assertEqual(again['reason'], 'dispatched_identity_never_replayed')
        op.verify_unchanged(batch, before)
        self.assertTrue((batch / 'a1/postprocess-intent.json').is_file())
        self.assertFalse((batch / 'a1/postprocess-receipt.json').exists())

    def test_actual_os_lease_collision_subprocess(self):
        from outer.harness import ownership
        (self.root / 'control').mkdir()
        with ownership.lease(self.root / 'control'):
            self.assertTrue(op._lease_collision(self.root / 'control')['foreign_lease_rejected'])

    def test_publication_finish_rejects_proof_digest_before_writing(self):
        receipt = self.root / 'remote.json'
        receipt.write_text('{}')
        before = op.inventory(self.root)
        with self.assertRaises(ValueError):
            op.finish_publication(self.root, receipt, expected_receipt_sha256='f' * 64,
                                  expected_package_sha256='e' * 64)
        op.verify_unchanged(self.root, before)

    def test_actual_local_http_html_rejection_preserves_status(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self): self.send_error(403, 'Bounded local rejection')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def local_exec(*args, **kwargs):
            # Replace only Docker transport; execute the identical request/parser
            # script against a real local HTTP socket, without any model.
            return subprocess.run([sys.executable, '-B', *args[3:]],
                capture_output=True, text=True, env=op.safe_environment(), timeout=5, check=True)
        with mock.patch.object(op.runtime, 'docker', side_effect=local_exec):
            response = op._http('inert-container', server.server_port, 'POST', '/denied', {})
        self.assertEqual(response['status'], 403)
        self.assertIsNone(response['body'])
        self.assertEqual(len(response['response_sha256']), 64)

    def test_completion_mode_requires_actual_artifact_and_stopped_child(self):
        workspace = self.root / 'workspace'; workspace.mkdir()
        (workspace / 'partial.json').write_text('{}')
        op.validate_artifact_shape(workspace, partial=True, child_exit=137)
        with self.assertRaises(ValueError): op.validate_artifact_shape(workspace, partial=False, child_exit=0)
        (workspace / 'artifact.json').write_text('{}')
        with self.assertRaises(ValueError): op.validate_artifact_shape(workspace, partial=True, child_exit=0)
        op.validate_artifact_shape(workspace, partial=False, child_exit=0)
        with self.assertRaises(ValueError): op.validate_artifact_shape(workspace, partial=False, child_exit=None)

    def test_active_resource_sample_binds_both_real_roles_and_record_hash(self):
        b = {'run_id': 'a', 'run_instance_id': 'a' * 32}
        rows = [{**b, 'role': role, 'container_id': ('b' if role == 'worker' else 'c') * 64,
                 'running': True, 'memory_usage_bytes': 42} for role in ('worker', 'gateway')]
        p = self.root / 'sample.json'
        util.write_new_json(p, {'sample': {'ok': True, 'containers': rows}})
        snapshot = {'resource_healthy': True, 'sampled_at': 'fresh', 'evidence_files': {str(p): util.sha256_file(p)}}
        self.assertEqual(op.validate_active_sample(snapshot, b)['path'], str(p))
        changed = json.loads(p.read_text()); changed['sample']['containers'][0]['run_instance_id'] = 'd' * 32
        util.write_json_atomic(p, changed)
        with self.assertRaises(ValueError): op.validate_active_sample(snapshot, b)
        snapshot['evidence_files'][str(p)] = util.sha256_file(p)
        with self.assertRaises(ValueError): op.validate_active_sample(snapshot, b)


if __name__ == '__main__': unittest.main()

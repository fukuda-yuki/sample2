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

    def scoped_plan(self):
        base = self.root / 'new'; base.mkdir()
        protected = [str(self.root / 'original/runs/source-info-v5-100p2')]
        protected += [str(self.root / 'saved' / ('a' + str(i))) for i in range(7)]
        p = {'schema_version': 1, 'kind': op.KIND, 'backend': 'providerless-opencode-session',
             'max_model_calls': 0, 'max_runs': 4, 'max_sessions': 4, 'pair_concurrency': 1,
             'require_fixed_instances': True, 'protected_roots': protected,
             'historical_run_instance_ids': [uuid.uuid4().hex for _ in range(200)],
             'source': {'run_instance_id': uuid.uuid4().hex}, 'assignments': []}
        p['source']['run_instance_id'] = p['historical_run_instance_ids'][0]
        for i in (1, 2):
            p['assignments'].append({'campaign_id': 'campaign-' + str(i), 'cases': [
                {'run_id': 'run-' + str(i) + '-' + str(slot), 'run_instance_id': uuid.uuid4().hex,
                 'pair': 1, 'slot': slot, 'task': 'dummy', 'condition': 'dummy', 'attempt': slot,
                 'mode': 'middle_stop' if (i, slot) == (2, 2) else 'normal'} for slot in (1, 2)]})
        return base, p

    def test_scope_rejects_traversal_alias_foreign_uuid_overlap_without_writes(self):
        import copy
        base, p = self.scoped_plan(); op.validate_plan_scope(p, base)
        before = op.inventory(self.root)
        mutations = [lambda q: q['assignments'][0].update(campaign_id='../original'),
            lambda q: q['assignments'][0]['cases'][0].update(run_id='../../original'),
            lambda q: q['assignments'][1]['cases'][0].update(run_id=q['assignments'][0]['cases'][0]['run_id'].upper()),
            lambda q: q['assignments'][0]['cases'][0].update(run_instance_id=q['historical_run_instance_ids'][0]),
            lambda q: q.update(max_runs=True), lambda q: q.update(require_fixed_instances=1),
            lambda q: q['protected_roots'].__setitem__(0, str(base / 'original')),
            lambda q: q['protected_roots'].__setitem__(1, q['protected_roots'][0].upper())]
        for mutate in mutations:
            q = copy.deepcopy(p); mutate(q)
            with self.assertRaises(ValueError): op.validate_plan_scope(q, base)
            op.verify_unchanged(self.root, before)

    def test_stop_scope_does_not_require_corrupt_or_missing_integrity_inputs(self):
        base, p = self.scoped_plan()
        util.write_new_json(base / 'plan.json', p)
        p['source_pins'] = {}
        # Stop shares path/UUID guard only; never tries missing before/inputs.
        op.validate_plan_scope(p, base)
        with self.assertRaises((ValueError, FileNotFoundError)): op.checked_before_inventory(base, p)

    def before_fixture(self):
        base, p = self.scoped_plan()
        original = Path(p['protected_roots'][0]); original.mkdir(parents=True)
        for i, instance in enumerate(p['historical_run_instance_ids']):
            root = original / ('source-' + str(i)); root.mkdir()
            util.write_new_json(root / 'manifest.json', {'run_id': root.name, 'run_instance_id': instance})
        source = original / 'source-0'
        util.write_new_json(source / 'condition.json', {'dummy': True})
        util.write_new_json(source / 'snapshot.json', {'run_id': source.name, 'artifact_sha256': 'a' * 64})
        util.write_json_atomic(source / 'manifest.json', {'run_id': source.name,
            'run_instance_id': p['historical_run_instance_ids'][0], 'condition_sha256': util.sha256_file(source / 'condition.json'),
            'stop_confirmed': True, 'submission_fixed': True})
        p['source'] = {'run_id': source.name, 'run_instance_id': p['historical_run_instance_ids'][0],
                       'snapshot_sha256': util.sha256_file(source / 'snapshot.json'), 'artifact_sha256': 'a' * 64}
        before = {str(original): op.inventory(original)}
        for raw in p['protected_roots'][1:]:
            root = Path(raw); root.mkdir(parents=True); (root / 'saved.txt').write_text('immutable')
            before[str(root)] = op.inventory(root)
        util.write_new_json(base / 'original-before.json', before)
        p['original_before_sha256'] = util.sha256_file(base / 'original-before.json')
        inputs = base / 'saved-input'; inputs.mkdir()
        import shutil
        for name in ('manifest.json', 'snapshot.json', 'condition.json'): shutil.copyfile(source / name, inputs / name)
        util.write_new_json(inputs / 'source-bytes.json', op.inventory(source))
        p['input_inventory'] = op.inventory(inputs)
        util.write_new_json(base / 'plan.json', p)
        return base, p, before

    def test_stored_before_reused_without_rescanning_original_but_inputs_are_bound(self):
        base, p, before = self.before_fixture()
        actual_inventory = op.inventory
        calls = []
        def bounded_inventory(root):
            calls.append(Path(root)); self.assertEqual(Path(root), base / 'saved-input')
            return actual_inventory(root)
        with mock.patch.object(op, 'inventory', side_effect=bounded_inventory):
            self.assertEqual(op.checked_before_inventory(base, p), before)
        self.assertEqual(calls, [base / 'saved-input'])
        (base / 'saved-input/condition.json').write_text('tampered')
        unchanged = op.inventory(self.root)
        with self.assertRaises(ValueError): op.checked_before_inventory(base, p)
        op.verify_unchanged(self.root, unchanged)

    def test_before_digest_scope_manifest_count_and_source_join_fail_closed(self):
        import copy
        base, p, before = self.before_fixture()
        for change in (lambda q: q.update(original_before_sha256='f' * 64),
                       lambda q: q['source'].update(snapshot_sha256='e' * 64),
                       lambda q: q['source'].update(run_id='source-1')):
            q = copy.deepcopy(p); change(q)
            unchanged = op.inventory(self.root)
            with self.assertRaises(ValueError): op.checked_before_inventory(base, q)
            op.verify_unchanged(self.root, unchanged)
        del before[p['protected_roots'][0]]['source-199/manifest.json']
        util.write_json_atomic(base / 'original-before.json', before)
        p['original_before_sha256'] = util.sha256_file(base / 'original-before.json')
        with self.assertRaises(ValueError): op.checked_before_inventory(base, p)

    def test_missing_or_changed_full_after_blocks_normalize_and_finish_before_writes(self):
        base, p, before = self.before_fixture()
        receipt = self.root / 'remote.json'; util.write_new_json(receipt, {'package_sha256': 'c' * 64})
        for after in (None, {}, {**before, p['protected_roots'][1]: {'saved.txt': 'f' * 64}}):
            if after is not None: util.write_json_atomic(base / 'original-after.json', after)
            unchanged = op.inventory(self.root)
            for action in (lambda: op.normalize(base), lambda: op.finish_publication(base, receipt,
                    expected_receipt_sha256=util.sha256_file(receipt), expected_package_sha256='c' * 64)):
                if after is None:
                    with self.assertRaises(FileNotFoundError) as caught: action()
                    self.assertEqual(Path(caught.exception.filename), base / 'original-after.json')
                else:
                    with self.assertRaisesRegex(ValueError, 'Mandatory full original-after'): action()
                op.verify_unchanged(self.root, unchanged)
        util.write_json_atomic(base / 'original-after.json', before)
        self.assertEqual(op.checked_after_inventory(base, before), before)

    def test_emergency_owned_stop_works_with_missing_before_corrupt_inputs_and_sourcepins(self):
        base, p = self.scoped_plan()
        util.write_new_json(base / 'plan.json', p)
        (base / 'saved-input').mkdir(); (base / 'saved-input/tampered.txt').write_text('bad')
        campaign = base / 'campaigns' / p['assignments'][0]['campaign_id']
        (campaign / '_control').mkdir(parents=True)
        (campaign / 'runs/_control/providerless-acceptance').mkdir(parents=True)
        util.write_new_json(campaign / 'campaign.json', {'campaign_id': p['assignments'][0]['campaign_id'],
            'campaign_uuid': str(uuid.uuid4()), 'plan_sha256': util.sha256_file(base / 'plan.json')})
        util.write_new_json(campaign / 'phase.json', {'phase_id': 'providerless-acceptance'})
        binding = p['assignments'][0]['cases'][0]
        root = campaign / 'runs' / binding['run_id']; root.mkdir()
        util.write_new_json(root / 'runtime.json', binding)
        with mock.patch.object(op, '_cleanup_backend') as cleanup, mock.patch.object(op, 'verify_pins') as pins:
            result = op.emergency_stop(base, repo=self.root, expected_plan_sha256=util.sha256_file(base / 'plan.json'))
        cleanup.assert_called_once_with(root, binding); pins.assert_not_called()
        self.assertTrue(util.read_json(result)['results'][0]['cleanup_confirmed'])

    def test_malformed_plan_is_rejected_by_every_entry_without_writes_or_docker(self):
        base, p = self.scoped_plan()
        p['assignments'][0]['campaign_id'] = '../original'
        util.write_new_json(base / 'plan.json', p)
        receipt = self.root / 'remote.json'; util.write_new_json(receipt, {})
        unchanged = op.inventory(self.root)
        with mock.patch.object(op.runtime, 'docker') as docker:
            for action in (lambda: op.execute(base / 'plan.json', repo=self.root),
                lambda: op.emergency_stop(base, repo=self.root, expected_plan_sha256=util.sha256_file(base / 'plan.json')),
                lambda: op.normalize(base), lambda: op.finish_publication(base, receipt,
                    expected_receipt_sha256=util.sha256_file(receipt), expected_package_sha256='c' * 64)):
                with self.assertRaises(ValueError): action()
                op.verify_unchanged(self.root, unchanged)
        docker.assert_not_called()

    def test_raw_parent_link_rejected_before_resolve_erases_it(self):
        base, p = self.scoped_plan()
        alias = self.root / 'linked'
        try: alias.symlink_to(base, target_is_directory=True)
        except OSError:
            # Windows unprivileged hosts can still create directory junctions.
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(base)],
                capture_output=True, text=True, timeout=5, env=op.safe_environment())
            if result.returncode: self.skipTest('Host cannot create test symlink or junction')
        try:
            with self.assertRaises(ValueError): op.validate_plan_scope(p, alias / 'child')
        finally: alias.unlink() if alias.is_symlink() else alias.rmdir()

    def test_actual_cleanup_evidence_directory_links_rejected_without_protected_writes(self):
        base, p, before = self.before_fixture()
        assignment = p['assignments'][0]; case = assignment['cases'][0]
        evidence = base / 'campaigns' / assignment['campaign_id'] / 'runs' / case['run_id'] / 'evidence'
        evidence.mkdir(parents=True)
        target = Path(p['protected_roots'][1])
        unchanged = op.inventory(target)
        for name in ('admission-stop', 'network-cleanup'):
            with self.subTest(actual_writer_directory=name):
                alias = evidence / name
                try: alias.symlink_to(target, target_is_directory=True)
                except OSError:
                    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(target)],
                        capture_output=True, text=True, timeout=5, env=op.safe_environment())
                    if result.returncode: self.skipTest('Host cannot create test symlink or junction')
                try:
                    with mock.patch.object(op, '_cleanup_backend') as cleanup, mock.patch.object(op.runtime, 'docker') as docker:
                        with self.assertRaises(ValueError): op.validate_plan_scope(p, base)
                        with self.assertRaises(ValueError): op.emergency_stop(base, repo=self.root,
                            expected_plan_sha256=util.sha256_file(base / 'plan.json'))
                    cleanup.assert_not_called(); docker.assert_not_called()
                    op.verify_unchanged(target, unchanged)
                finally: alias.unlink() if alias.is_symlink() else alias.rmdir()


if __name__ == '__main__': unittest.main()

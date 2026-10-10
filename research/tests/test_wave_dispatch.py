"""Finite local tests. No Docker, credentials, API, scoring or publication."""
from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from outer.harness import util
from research import next_phase, pair_execution, wave_plan, wave_dispatch, wave_execution


class WaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name); self.batch = self.repo / 'runs/source-info-v5-100p2'
        plan = util.read_json(Path(__file__).parents[1] / 'protocols' / (next_phase.V5_ID + '.json'))
        self.original = {'plan': plan, 'assignments': next_phase.assignments(plan),
            'cohort': 'runs/source-info-v5-100p2', 'runtime_id': 'fixture'}
        original = self.repo / 'original.json'; util.write_new_json(original, self.original)
        old = self.batch / '_control/pair-journal.jsonl'; old.parent.mkdir(parents=True); old.write_bytes(b'')
        self.old = dict(dispatch={}, reserved={}, implementations={}, results={}, gates={i: {} for i in range(1, 6)}, pending=[])
        for p in self.original['assignments'][:5]:
            for c in p['cases']:
                binding = {**c, 'plan_sha256': util.sha256_file(original)}
                self.old['dispatch'][c['run_id']] = binding; self.old['reserved'][c['run_id']] = binding
                self.old['implementations'][c['run_id']] = {'receipt': {'stop_confirmed': True}}
                self.old['results'][c['run_id']] = {}
        self.old_patch = patch.object(pair_execution, 'state', return_value=self.old)
        self.old_patch.start(); self.addCleanup(self.old_patch.stop)
        code = self.repo / 'fixture.py'; code.write_text('fixture', encoding='utf8')
        policy = self.repo / 'policy.json'; util.write_new_json(policy, {'synthetic_nonlive': True})
        self.thresholds = {k: 1 for k in wave_plan.RESOURCE_LIMITS}
        self.phase = wave_plan.build(original, old, self.batch, thresholds=self.thresholds,
            source_commit='fixture', source_pins={'fixture.py': util.sha256_file(code)}, operational_policy=policy)
        self.path = self.repo / 'phase.json'; util.write_new_json(self.path, self.phase)
        self.digest = util.sha256_file(self.path)
        self.approval = dict(approved_by='user', authorized=True, authorization_reference='synthetic fixture only', phase_sha256=self.digest)
        evidence = self.repo / 'resource.json'; util.write_new_json(evidence, {'synthetic_nonlive': True})
        self.health = {**{k: True for k in wave_plan.HEALTH_FLAGS}, **self.thresholds,
            'escalation_healthy': True, 'sampled_at': 'fixture', 'evidence_files': {str(evidence): util.sha256_file(evidence)}}
        self.active = 0; self.peak = 0; self.lock = threading.Lock()
        self.sent = []; self.heavy = []; self.fenced = []

    def prepare(self, binding):
        manifest = {**binding, 'prompt_sha256': 'b' * 64, 'condition_sha256': 'c' * 64}
        util.write_new_json(self.batch / binding['run_id'] / 'manifest.json', manifest)
        return manifest

    def verify(self, binding):
        manifest = util.read_json(self.batch / binding['run_id'] / 'manifest.json')
        self.assertEqual(manifest['run_instance_id'], binding['run_instance_id'])

    def implement(self, repo, batch, rid):
        with self.lock:
            self.active += 1; self.peak = max(self.peak, self.active); self.sent.append(rid)
        time.sleep(.04)
        with self.lock: self.active -= 1
        manifest = util.read_json(batch / rid / 'manifest.json')
        receipt = dict(run_id=rid, run_instance_id=manifest['run_instance_id'], stop_confirmed=True, submission_fixed=True)
        util.write_new_json(batch / rid / 'implementation-receipt.json', receipt)
        return receipt

    def postprocess(self, repo, batch, rid, archive):
        self.assertEqual(self.active, 0)
        self.heavy.append(rid)
        # A quality failure is an observed outcome, never an operational stop.
        return {'run_id': rid, 'verdict': 'fail_critical', 'quality': 0}

    def publish(self, number, current, recovering):
        self.assertEqual(self.active, 0)
        root = self.repo / ('gate-' + str(number)); root.mkdir(exist_ok=True)
        values = {'publication': {'remote_assets_verified': True, 'urls': ['fixture'], 'package_sha256': 'a' * 64},
            'restore': {'hashes_match': True, 'extraction_sockets_blocked': True, 'package_sha256': 'a' * 64},
            'cleanup': {'cleanup_completed': True, 'original_runs_deleted': False, 'package_sha256': 'a' * 64}}
        for name, value in values.items():
            path = root / (name + '.json')
            if not path.exists(): util.write_new_json(path, value)
        gate = {'pair': number, 'cohort': self.phase['cohort'], 'plan_sha256': self.phase['original_bundle']['sha256'],
            'phase_sha256': self.digest,
            'run_instances': {r: d['run_instance_id'] for r, d in current['dispatch'].items() if d['pair'] == number},
            'evidence_files': {str(root / (n + '.json')): util.sha256_file(root / (n + '.json')) for n in values},
            'publication_receipt': str(root / 'publication.json'), 'roundtrip_receipt': str(root / 'restore.json'),
            'cleanup_receipt': str(root / 'cleanup.json')}
        path = root / 'gate.json'
        if not path.exists(): util.write_new_json(path, gate)
        return path

    def dispatcher(self, **kw):
        defaults = dict(prepare=self.prepare, verify=self.verify, implement=self.implement,
            postprocess=self.postprocess, publish=self.publish,
            reconcile=lambda b: util.read_json(self.batch / b['run_id'] / 'implementation-receipt.json'),
            fence=lambda owned: self.fenced.append(owned) or {'confirmed': True},
            snapshot=lambda: self.health, supervise=lambda active: None, publication_ready=lambda number, current: True)
        return wave_dispatch.Dispatcher(self.repo, self.path, self.approval, **{**defaults, **kw})

    def test_plan_preserves_global200_and_balances_shards(self):
        self.assertEqual(len(self.phase['assignments']), 95)
        cases = [c for p in self.phase['assignments'] for c in p['cases']]
        self.assertEqual({c['slot'] for c in cases}, set(range(11, 201)))
        self.assertEqual(len({c['run_instance_id'] for c in cases}), 190)
        self.assertEqual(Counter(self.phase['shards'].values()), {1: 24, 2: 24, 3: 24, 4: 23})
        self.assertEqual(self.phase['assignments'], self.original['assignments'][5:])

    def test_first_four_runs_then_eight_and_serial_quality_failures(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            self.assertEqual(dispatcher.execute_next(escalate=True)['pairs'], [6, 7])
            self.assertEqual(self.peak, 4)
            self.assertEqual(dispatcher.execute_next(escalate=True)['pairs'], [8, 9, 10, 11])
            self.assertEqual(self.peak, 8)
            self.assertEqual(len(set(self.sent)), 12)
            self.assertEqual(len(self.heavy), 12)
            self.assertEqual(len(dispatcher.current()['gates']), 6)
            self.assertFalse(self.fenced)
        self.assertEqual(Path(self.phase['old_journal']['path']).read_bytes(), b'')

    def test_unmet_escalation_stays_four_runs(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            dispatcher.execute_next()
            self.health['escalation_healthy'] = False
            self.assertEqual(dispatcher.execute_next(escalate=True)['pairs'], [8, 9])
            self.assertEqual(self.peak, 4)

    def test_phase_handoff_fences_legacy_and_second_process(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            script = "from research.pair_execution import exclusive\nfrom pathlib import Path\nwith exclusive(Path(__import__('sys').argv[1])): pass"
            result = subprocess.run([sys.executable, '-c', script, str(dispatcher.control)],
                cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            with self.assertRaises(OSError):
                with pair_execution.exclusive(dispatcher.control, phase_permit=self.digest): pass
        with self.assertRaisesRegex(ValueError, 'legacy entrypoint fenced'):
            with pair_execution.exclusive(dispatcher.control): pass
        with self.dispatcher().session(): pass

    def test_no_refill_before_every_gate_and_recovery_exact_once(self):
        calls = []
        def interrupted(number, current, recovering):
            calls.append((number, recovering))
            if number == 7 and not recovering: raise RuntimeError('synthetic remote interruption')
            return self.publish(number, current, recovering)
        dispatcher = self.dispatcher(publish=interrupted)
        with dispatcher.session():
            self.assertEqual(dispatcher.execute_next()['reason'], 'publication_fault')
            before = list(self.sent)
            self.assertEqual(dispatcher.execute_next()['reason'], 'durable_dispatch_stop')
            self.assertEqual(dispatcher.recover()['status'], 'wave_gated')
            self.assertEqual(self.sent, before)
            self.assertEqual(len(self.heavy), 4)
            self.assertEqual(calls, [(6, False), (7, False), (7, True)])

    def test_fault_closes_all_owned_and_does_not_score(self):
        def fault(repo, batch, rid):
            receipt = self.implement(repo, batch, rid)
            return {**receipt, 'error_type': 'synthetic_provider_fault'}
        dispatcher = self.dispatcher(implement=fault)
        with dispatcher.session():
            self.assertEqual(dispatcher.execute_next()['reason'], 'implementation_fault')
            self.assertTrue(dispatcher.stop_path.exists())
            self.assertEqual(len(self.fenced[0]), 3)
            self.assertFalse(self.heavy)
            self.assertEqual(dispatcher.execute_next()['reason'], 'durable_dispatch_stop')

    def test_health_has_no_quality_input_and_fault_is_durable(self):
        self.health['quality'] = 100
        dispatcher = self.dispatcher()
        with dispatcher.session():
            self.assertEqual(dispatcher.execute_next()['reason'], 'objective_health_hold')
            self.assertFalse(self.sent)

    def test_journal_tail_and_immutable_inputs_fail_closed(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            dispatcher.journal.parent.mkdir(parents=True, exist_ok=True)
            dispatcher.journal.write_bytes(b'{"partial":')
            with self.assertRaisesRegex(ValueError, 'Incomplete journal tail'): dispatcher.current()
        original = Path(self.phase['original_bundle']['path']); original.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Immutable transition'): self.dispatcher()

    def test_wrong_phase_approval_and_instance_fail_before_send(self):
        self.approval['phase_sha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'Separate exact-new-phase'): self.dispatcher()
        self.assertFalse(self.sent)

    def test_reserved_unsent_resume_keeps_instance_and_never_replays_sent(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            # Simulate a manager crash after durable reservation, before send.
            assignments = []
            for p in self.phase['assignments'][:2]:
                for case in p['cases']:
                    b = {**case, 'cohort': self.phase['cohort'], 'runtime': self.phase['runtime'],
                        'plan_sha256': self.phase['original_bundle']['sha256'], 'phase_sha256': self.digest,
                        'responsibility': self.phase['shards'][str(p['pair'])]}
                    manifest = self.prepare(b)
                    b.update(input_sha256=manifest['prompt_sha256'], condition_sha256=manifest['condition_sha256'])
                    assignments.append(b)
            dispatcher.record('wave_reserved', pairs=[6, 7], blocks=1, run_cap=4, assignments=assignments)
            auth = {**self.approval, 'journal_sha256': util.sha256_file(dispatcher.journal),
                'run_instances': {b['run_id']: b['run_instance_id'] for b in assignments}}
            self.assertEqual(dispatcher.resume_unsent(auth)['status'], 'wave_gated')
            self.assertEqual({r: b['run_instance_id'] for r, b in dispatcher.current()['dispatch'].items()}, auth['run_instances'])
            self.assertEqual(dispatcher.resume_unsent(auth)['reason'], 'no_reconciled_unsent_slot')
            self.assertEqual(len(self.sent), 4)

    def test_public_review_hold_has_no_remote_intent_or_fault_and_no_refill(self):
        ready = False
        dispatcher = self.dispatcher(publication_ready=lambda number, current: ready)
        with dispatcher.session():
            self.assertEqual(dispatcher.execute_next()['reason'], 'publication_review_pending')
            self.assertFalse(list(dispatcher.phase_control.glob('publication-intent-*')))
            self.assertFalse(dispatcher.stop_path.exists())
            self.assertEqual(dispatcher.execute_next()['reason'], 'previous_wave_gates_or_explicit_recovery')
            ready = True
            self.assertEqual(dispatcher.finish_wave()['status'], 'wave_gated')
            self.assertEqual(len(self.sent), 4)
            self.assertEqual(len(self.heavy), 4)

    def test_crash_after_send_intent_never_replays_and_recovers_every_owned(self):
        dispatcher = self.dispatcher(publication_ready=lambda number, current: False)
        with dispatcher.session():
            # Reserve normally without model work, then synthesize an intent-
            # to-submit crash for two sent assignments. Both stay ambiguous.
            def crash_implement(bindings):
                for b in bindings[:2]: dispatcher.record('dispatch', **b)
                return {'status': 'held'}
            with patch.object(dispatcher, '_implement', side_effect=crash_implement): dispatcher.execute_next()
            visited = []
            dispatcher.reconcile = lambda b: visited.append(b['run_id']) or {'stop_confirmed': False}
            self.assertEqual(dispatcher.recover()['reason'], 'stop_or_original_fix_unconfirmed')
            self.assertEqual(len(visited), 2)
            self.assertEqual(len(self.sent), 0)
            auth = {**self.approval, 'journal_sha256': util.sha256_file(dispatcher.journal),
                'run_instances': {r: b['run_instance_id'] for r, b in dispatcher.current()['reserved'].items()
                    if r not in dispatcher.current()['dispatch']}}
            self.assertEqual(dispatcher.resume_unsent(auth)['reason'], 'no_reconciled_unsent_slot')

    def test_recovered_stop_requires_healthy_bound_decision_before_new_wave(self):
        def interrupted(number, current, recovering):
            if number == 7 and not recovering: raise RuntimeError('fixture remote failure')
            return self.publish(number, current, recovering)
        dispatcher = self.dispatcher(publish=interrupted)
        with dispatcher.session():
            dispatcher.execute_next(); dispatcher.recover()
            auth = {**self.approval, 'journal_sha256': util.sha256_file(dispatcher.journal),
                'stop_sha256': util.sha256_file(dispatcher.stop_path), 'recovery_decision_reference': 'fixture health restoration'}
            self.assertEqual(dispatcher.clear_reconciled_stop(auth)['status'], 'ready')
            self.assertEqual(len(list(dispatcher.phase_control.glob('retained-stop-*'))), 1)
            self.assertEqual(dispatcher.execute_next()['pairs'], [8, 9])
            self.assertEqual(len(set(self.sent)), 8)

    def test_active_fault_uses_owned_bindings_even_if_journal_tail_corrupt(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            b = self.phase['assignments'][0]['cases'][0]
            dispatcher.owned_active[b['run_id']] = b
            dispatcher.journal.parent.mkdir(parents=True, exist_ok=True)
            dispatcher.journal.write_bytes(b'{"truncated":')
            result = dispatcher.fault('journal_fault')
            self.assertEqual(self.fenced[0], [b])
            self.assertTrue(result['evidence_errors'])
            self.assertTrue(dispatcher.closed.is_set())

    def test_fault_fences_before_any_full_validation(self):
        dispatcher = self.dispatcher()
        order = []
        with dispatcher.session():
            binding = self.phase['assignments'][0]['cases'][0]
            dispatcher.owned_active[binding['run_id']] = binding
            dispatcher.fence = lambda owned: order.append(('fence', owned)) or {'confirmed': True}
            def failed_validation():
                order.append(('validation', None))
                raise ValueError('Synthetic delayed/corrupt journal validation')
            with patch.object(dispatcher, 'current', side_effect=failed_validation):
                result = dispatcher.fault('fixture_resource_stale')
            self.assertEqual([x[0] for x in order], ['fence', 'validation'])
            self.assertEqual(order[0][1], [binding])
            self.assertTrue(result['evidence_errors'])

    def test_recovery_terminal_uses_reserved_binding_and_never_resends(self):
        dispatcher = self.dispatcher(publication_ready=lambda number, current: False)
        with dispatcher.session():
            def stopped_before_terminal(bindings):
                for b in bindings:
                    dispatcher.owned_active[b['run_id']] = b
                    dispatcher.record('dispatch', **b)
                    util.write_new_json(self.batch / b['run_id'] / 'implementation-receipt.json',
                        dict(run_id=b['run_id'], run_instance_id=b['run_instance_id'],
                             stop_confirmed=True, submission_fixed=True))
                return {'status': 'held'}
            with patch.object(dispatcher, '_implement', side_effect=stopped_before_terminal):
                dispatcher.execute_next()
            self.assertEqual(dispatcher.recover()['reason'], 'publication_review_pending')
            current = dispatcher.current()
            self.assertEqual(len(current['implementations']), 4)
            self.assertEqual(self.sent, [])
            for event in current['implementations'].values():
                binding = util.read_json(event['receipt_path'])['binding']
                self.assertNotIn('kind', binding)
                self.assertEqual(binding, current['reserved'][event['run_id']])
            prior = len(list(dispatcher.phase_control.glob('implemented-*.json')))
            dispatcher.recover()
            self.assertEqual(len(list(dispatcher.phase_control.glob('implemented-*.json'))), prior)

    def test_initial_preparation_crash_reuses_same_unstarted_instance(self):
        count = 0
        def partial(binding):
            nonlocal count
            count += 1
            manifest = self.prepare(binding)
            if count == 2: raise RuntimeError('fixture crash after prepare')
            return manifest
        dispatcher = self.dispatcher(prepare=partial)
        with dispatcher.session():
            with self.assertRaises(RuntimeError): dispatcher.execute_next()
            dispatcher.prepare = self.prepare
            self.assertEqual(dispatcher.execute_next()['status'], 'wave_gated')
            self.assertEqual(len(self.sent), 4)
            self.assertEqual(len(set(self.sent)), 4)

    def test_full_remaining95_fixed_pairs_exactly190_sends_final_single_pair(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            result = dispatcher.execute_next(escalate=True)
            self.assertEqual(result['pairs'], [6, 7])
            while result['status'] != 'complete':
                result = dispatcher.execute_next(escalate=True)
            current = dispatcher.current()
            self.assertEqual(len(current['dispatch']), 190)
            self.assertEqual(set(current['gates']), set(range(6, 101)))
            self.assertEqual(current['waves'][-1]['pairs'], [100])
            self.assertEqual(current['waves'][-1]['run_cap'], 2)
            self.assertEqual(len(set(self.sent)), 190)
            self.assertEqual(self.peak, 8)
            self.assertEqual(len(self.heavy), 190)

    def test_real_adapter_initiates_all_gateway_fences_before_worker_stops(self):
        adapter = wave_execution.HarnessAdapters.__new__(wave_execution.HarnessAdapters)
        adapter.batch = self.batch
        owned = self.phase['assignments'][0]['cases']
        for binding in owned:
            self.prepare(binding)
            util.write_new_json(self.batch / binding['run_id'] / 'runtime.json', binding)
        barrier = threading.Barrier(2)
        fenced = []
        def gateway(root):
            barrier.wait(timeout=3)
            binding = util.read_json(root / 'runtime.json')
            with self.lock: fenced.append(binding['run_id'])
            return {**binding, 'confirmed': True, 'observed_at': 'fixture'}
        def stop(root):
            self.assertEqual(len(fenced), 2)
            manifest = util.read_json(root / 'manifest.json'); manifest['stop_confirmed'] = True
            util.write_json_atomic(root / 'manifest.json', manifest)
        with patch.object(wave_execution.runtime, 'fence_owned', side_effect=gateway), patch.object(
                wave_execution.runtime, 'request_stop', side_effect=stop):
            receipt = adapter.fence(owned)
        self.assertTrue(receipt['http_fence_confirmed'])
        self.assertIsNotNone(receipt['effective_stop_at'])
        self.assertTrue(all(r['stop_confirmed'] for r in receipt['worker_stops']))

    def test_unsent_resume_blocks_when_a_sent_peer_stop_is_unconfirmed(self):
        dispatcher = self.dispatcher()
        with dispatcher.session():
            def partial(bindings):
                b = bindings[0]
                dispatcher.record('dispatch', **b)
                dispatcher.terminal('implemented', b, {'run_id': b['run_id'],
                    'run_instance_id': b['run_instance_id'], 'stop_confirmed': False, 'submission_fixed': False})
                return {'status': 'held'}
            with patch.object(dispatcher, '_implement', side_effect=partial): dispatcher.execute_next()
            self.assertEqual(dispatcher.resume_unsent({})['reason'], 'dispatched_peer_stop_or_collection_unreconciled')
            self.assertFalse(self.sent)


if __name__ == '__main__': unittest.main()

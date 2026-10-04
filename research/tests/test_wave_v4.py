"""Finite v4 successor tests; Temp fixtures and mocked sends only."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from outer.harness import util
from research import pair_execution, wave_dispatch, wave_plan, wave_sharing
from research.tests import test_wave_v3 as fixtures


class V4Tests(unittest.TestCase):
    prepare = fixtures.V3Tests.prepare
    implement = fixtures.V3Tests.implement
    verify = fixtures.V3Tests.verify
    postprocess = fixtures.V3Tests.postprocess
    publish = fixtures.V3Tests.publish
    dispatcher = fixtures.V3Tests.dispatcher
    reference = fixtures.V3Tests.reference

    def setUp(self):
        self.build = fixtures.V3Tests.build.__get__(self)
        fixtures.V3Tests.setUp(self)
        decision = fixtures.V3Tests.revised_decision(self)
        self.phase = self.build(recovery_decision=decision)
        util.write_json_atomic(self.path, self.phase); self.digest = util.sha256_file(self.path)
        self.approval = {**self.approval, 'phase_sha256': self.digest}
        fixtures.V3Tests.handoff(self)
        d = self.dispatcher()
        with d.session(): d.execute_next(); d.execute_next()
        self.v3path, self.v3digest, self.v3phase, self.v3journal = self.path, self.digest, self.phase, d.journal
        self.marker_bytes = {p: p.read_bytes() for p in (d.control/'phase-handoff.json',
            d.control/'phase-handoff-v2.json', d.control/'phase-handoff-v3.json')}
        current = wave_dispatch.state(d.journal, self.phase, self.digest)
        del self.build
        collector = self.repo/'v4-collector'; collector.mkdir()
        def save(name, value):
            path = collector/(name+'.json'); util.write_new_json(path, value); return self.reference(path)
        monitor = collector/'wave_resource_monitor.py'; monitor.write_bytes(Path(self.monitor['path']).read_bytes())
        probe = collector/'wave_resource_probe.py'; probe.write_bytes(b'bounded prewrite231 fixture')
        self.v4monitor, self.v4probe = self.reference(monitor), self.reference(probe)
        patch.object(wave_plan, 'V4_PROBE_SHA', self.v4probe['sha256']).start()
        self.fault = save('fault', {'sample': {'ok': False, 'error': 'OSError', 'timeout_seconds': 10,
            'transport_diagnostic': {'substage': 'pipe_open', 'errno': 22, 'winerror': 231,
                                     'bytes_written': 0, 'body_bytes_returned': 0}}})
        owned = [b for b in current['dispatch'].values() if b['pair'] in (16, 17)]
        self.acks = save('acks', {'phase_sha256': self.v3digest, 'owned': owned, 'evidence_errors': [],
            'receipt': {'http_fence_confirmed': True, 'effective_stop_at': '2026-10-04T12:50:57+00:00',
                'gateway_receipts': [{'run_id': b['run_id'], 'run_instance_id': b['run_instance_id'], 'confirmed': True,
                    'acknowledgement': {'run_id': b['run_id'], 'session_id': b['run_instance_id'], 'admission_closed': True}} for b in owned],
                'worker_stops': [{'run_id': b['run_id'], 'run_instance_id': b['run_instance_id'], 'stop_confirmed': True} for b in owned]}})
        self.boundary4 = save('boundary', {'kind': 'quiescent_post_v3_pipe_busy_boundary', 'at': '2026-10-04T13:00:00+00:00',
            'phase': self.reference(self.v3path), 'journal': self.reference(self.v3journal),
            'gates': {str(n): {'path': g['receipt_path'], 'sha256': g['receipt_sha256']} for n,g in current['gates'].items()},
            'actual_sent': 34, 'all_stopped_fixed': True, 'all17_gates_complete': True,
            'active_run_containers_at_final_recovery_sample': 0, 'recovery_controller_exit_code': 0})
        self.finite4 = save('finite', {'schema': 'prospective-pipe-busy-acquire-finite-v1',
            'old_probe': self.probe, 'candidate': self.v4probe, 'unchanged_monitor': self.v4monitor,
            'observed_failure': self.fault, 'finite_passed': True, 'old_cpu_identity_cases_passed': True,
            'all_ast_outside_native_constructor_unchanged': True,
            'deadline_checks': {'10_seconds': True, 'shorter_outer_deadline_preserved': True, 'above_10_rejected': True},
            'native_receipt': save('native', {'finite_native': True})})
        self.review4 = save('review', {'kind': 'prospective_pipe_busy_v4_independent_acceptance', 'status': 'passed',
            'finite_acceptance': self.finite4, 'resource_probe_sha256': self.v4probe['sha256'], 'historical_cause_resolved': False,
            'operationally_acceptable': True, 'input_references': [save('independent-input', {'finite_independent_fixture': True})]})
        prior_decision = util.read_json(self.v3phase['resource_collector_acceptance']['path'])
        self.authority4 = save('pipe-parent-instruction', {'kind': 'parent_explicit_pipe_busy_recovery_condition_instruction_v4',
            'authority': 'parent', 'message': 'Finite fixture limited pipe-only recovery instruction, never actual permission.',
            'formal_remaining_instances': 166, 'maximum_concurrent_runs': 4,
            'original_bundle_sha256': self.phase['original_bundle']['sha256'], 'predecessor_phase': self.reference(self.v3path),
            'observed_resource_fault': self.fault, 'received_after_observed_fault': True,
            'model_request_retry_authorized': False, 'hold_until_known_prewrite_acquisition_handling_verified': True,
            'not_a_new_human_reply': True})
        original_instruction = save('original-instruction', {'finite_standing_instruction': True})
        self.standing = save('standing', {'kind': 'standing_delegated_completion_with_parent_revised_recovery_condition',
            'approved_by': 'user', 'not_a_new_human_reply': True, 'parent_revised_instruction': prior_decision['parent_instruction'],
            'recovery_decision': self.v3phase['resource_collector_acceptance'],
            'original_instruction_path': original_instruction['path'], 'original_instruction_sha256': original_instruction['sha256']})
        self.acceptance_value = {'kind': 'resource_probe_prewrite_pipe_busy_v4_acceptance',
            'previous_probe_sha256': self.probe['sha256'], 'resource_probe_sha256': self.v4probe['sha256'],
            'resource_monitor_sha256': self.v4monitor['sha256'], 'operational_policy_sha256': self.phase['operational_policy']['sha256'],
            'source_commit': 'v4 fixture source', 'original_bundle_sha256': self.phase['original_bundle']['sha256'],
            'predecessor_journal_sha256': self.reference(self.v3journal)['sha256'],
            'prewrite_only': True, 'postwrite_retry': False, 'whole_probe_deadline_seconds': 10,
            'fail_closed_unchanged': True, 'historical_cause_resolved': False, 'remaining_original_instances': 166,
            'maximum_runs': 4, 'model_called': False, 'run_created': False,
            'finite_acceptance': self.finite4, 'independent_acceptance': self.review4, 'observed_resource_fault': self.fault,
            'stop_acknowledgements': self.acks, 'post_v3_boundary': self.boundary4, 'standing_completion_authority': self.standing,
            'parent_revised_recovery_authority': self.authority4,
            'parent_instruction_verbatim': util.read_json(self.authority4['path'])['message']}
        self.acceptance4 = save('acceptance', self.acceptance_value)
        self.phase = self.build()
        self.path = self.repo/'phase-v4.json'; util.write_new_json(self.path, self.phase); self.digest = util.sha256_file(self.path)
        self.approval = {**self.approval, 'phase_sha256': self.digest}
        self.sent.clear(); self.heavy.clear(); self.peak = 0

    def build(self, **changes):
        values = {'source_commit': 'v4 fixture source', 'source_pins': self.v3phase['source_pins'],
            'resource_monitor': self.v4monitor, 'resource_probe': self.v4probe, 'resource_collector_acceptance': self.acceptance4}
        return wave_plan.build_v4(self.v3path, self.v3journal, **{**values, **changes})

    def handoff(self): return wave_dispatch.handoff_v4(self.repo, self.path, self.approval)

    def test_original166_mapping_cap_and_publication_metadata(self):
        self.assertEqual(self.phase['assignments'], self.original['assignments'][17:])
        self.assertEqual(len({c['run_instance_id'] for p in self.phase['assignments'] for c in p['cases']}), 166)
        self.assertEqual(self.phase['shards'], {k:v for k,v in self.v3phase['shards'].items() if int(k)>=18})
        self.assertEqual(self.phase['responsibility_counts'], [sum(v==n for v in self.phase['shards'].values()) for n in range(1,5)])
        for change in ({'maximum_pairs':4}, {'escalation_allowed':True}, {'runtime':'changed'}, {'assignments':self.v3phase['assignments']}):
            with self.subTest(change=change), self.assertRaises(ValueError): wave_plan.validate({**self.phase, **change})
        self.handoff(); d = self.dispatcher()
        with d.session():
            d.execute_next(escalate=True); metadata = wave_sharing.Publisher(d).metadata(18)
            self.assertEqual(metadata['configured_wave_run_cap'], 4)
            self.assertEqual(metadata['ancestor_phase_sha256s'], [self.previous_digest,self.v2digest,self.v3digest])
            self.assertIn('does not authorize current v4', metadata['soak_binding'])
            self.assertEqual(d.recover()['status'], 'wave_gated')
        self.assertEqual(set(self.sent), {c['run_id'] for p in self.phase['assignments'][:2] for c in p['cases']})

    def test_missing_gate_open_lease_or_changed_history_rejected(self):
        with pair_execution.exclusive(self.batch/'_control', phase_permit=self.v3digest):
            with self.assertRaises(OSError): self.build()
        for path in (self.v3journal, Path(self.phase['predecessor_gates']['17']['path']),
                     Path(self.observations[0]['raw']['path']), Path(next(iter(self.observations[0]['monitor'])))):
            raw=path.read_bytes(); path.write_bytes(raw+b'changed')
            with self.assertRaises((ValueError,OSError)): self.build()
            path.write_bytes(raw)
        value=deepcopy(self.phase); value['predecessor_gates'].pop('17')
        with self.assertRaises(ValueError): wave_plan.validate(value)

    def test_exact_fault_ack_native_receipts_and_authority_required(self):
        for key in ('postwrite_retry', 'fail_closed_unchanged', 'historical_cause_resolved', 'whole_probe_deadline_seconds', 'parent_instruction_verbatim'):
            modified={**self.acceptance_value, key: 'invalid'}; util.write_json_atomic(self.acceptance4['path'], modified)
            with self.subTest(key=key), self.assertRaises(ValueError): self.build(resource_collector_acceptance=self.reference(self.acceptance4['path']))
        util.write_json_atomic(self.acceptance4['path'], self.acceptance_value)
        for path in (Path(self.fault['path']), Path(self.acks['path']), Path(util.read_json(self.finite4['path'])['native_receipt']['path']),
                     Path(util.read_json(self.review4['path'])['input_references'][0]['path'])):
            raw=path.read_bytes(); path.write_bytes(raw+b'changed')
            with self.assertRaises(ValueError): self.build()
            path.write_bytes(raw)

    def test_append_only_v4_handoff_fences_all_ancestors_and_rejects_gap(self):
        self.handoff(); self.handoff()
        for path, raw in self.marker_bytes.items(): self.assertEqual(path.read_bytes(), raw)
        for permit in (None, self.previous_digest, self.v2digest, self.v3digest):
            with self.assertRaises(ValueError):
                with pair_execution.exclusive(self.batch/'_control', phase_permit=permit): pass
        with pair_execution.exclusive(self.batch/'_control', phase_permit=self.digest): pass
        marker=self.batch/'_control/phase-handoff-v3.json'; saved=marker.read_bytes(); marker.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing immutable intermediate'):
            with pair_execution.exclusive(self.batch/'_control', phase_permit=self.digest): pass
        marker.write_bytes(saved)
        with self.assertRaisesRegex(ValueError, 'cannot be overwritten'):
            wave_dispatch.handoff_v4(self.repo,self.path,{**self.approval,'authorization_reference':'changed'})

    def test_all83_pairs166_mock_sends_stop_gates_max4(self):
        self.handoff(); d=self.dispatcher()
        with d.session():
            result=d.execute_next(escalate=True)
            while result['status']!='complete': result=d.execute_next(escalate=True)
            current=d.current()
            self.assertEqual(set(current['gates']),set(range(18,101)))
            self.assertEqual(len(current['dispatch']),166); self.assertEqual(len(set(self.sent)),166)
            self.assertEqual(self.peak,4); self.assertEqual(current['waves'][-1]['pairs'],[100])


if __name__ == '__main__': unittest.main()

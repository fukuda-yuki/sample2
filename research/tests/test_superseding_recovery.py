import json, tempfile, unittest
from pathlib import Path
from unittest import mock

from research import campaign_recovery as recovery, repaired_campaign as campaign, live_pilot


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value).encode('utf-8'))
    return path


HELD = {'classification': 'held_unresolved_evidence', 'recoverable': False, 'model_calls': 0}


def _usage(**over):
    value = dict(observed_requests=0, observed_tokens=dict(input_tokens=0, output_tokens=0), usage_complete=False,
                 total_tokens=None, usage_unknown=True, send_evidence='known_no_send', journal_errors=[],
                 transmission_issues=[], source_journals={}, technical_evidence=[])
    value.update(over)
    return value


class PreDispatchFaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.batch = base/'epoch'; self.wave_dir = base/'waves'/'w1'
        wave_path = _write(self.wave_dir/'spec.json', {'wave': 1})
        plan = _write(base/'plan.json', {'plan': 1}); epoch = _write(base/'epoch.json', {'epoch': 1})
        self.case = dict(pair=7, run_id='T-preload-1', run_instance_id='a'*32, condition='preload')
        self.root = self.batch/'pair-7'/self.case['run_id']
        (self.batch/'pair-7'/'_control').mkdir(parents=True)
        self.ctx = dict(epoch={'batch': str(self.batch)}, wave_path=wave_path, wave_ref=live_pilot.reference(wave_path),
                        campaign=live_pilot.reference(plan), wave={'epoch_plan': live_pilot.reference(epoch), 'pairs': [6, 7]})
        self.launch = dict(kind='repaired_campaign_wave_launcher_v1_result', wave=self.ctx['wave_ref'],
                           plan=self.ctx['campaign'], epoch_plan=self.ctx['wave']['epoch_plan'], pairs=[6, 7],
                           operational_complete=False, stop_requested=True, reason='campaign_stop',
                           stop={'reason': 'campaign_stop', 'durable_stop_paths': ['x']},
                           child={'exit_code': 0, 'exit_confirmed': True}, observer_closure={'confirmed': True},
                           errors=[], owned_runs=[self.not_allocated()])
        self._launch()

    def not_allocated(self, **over):
        return {**dict(run_id=self.case['run_id'], run_instance_id='a'*32, status='not_allocated', stop_attempted=False,
                       closure_confirmed=False, unknown=False, helper=None), **over}

    def _launch(self, **over):
        _write(self.wave_dir/'_launcher'/'result.json', {**self.launch, **over})

    def fault(self, usage=None, observation=HELD):
        return recovery._pre_dispatch_fault(self.ctx, self.case, self.root, usage or _usage(), observation)

    def test_all_conditions_give_positive_evidence(self):
        fact = self.fault()
        self.assertEqual(fact['category'], 'pre_dispatch_campaign_fault')
        self.assertEqual(fact['observed_requests'], 0)

    def test_prepared_unstarted_manifest_still_pre_dispatch(self):
        _write(self.root/'manifest.json', dict(run_id=self.case['run_id'], run_instance_id='a'*32, started_at=None, end_reason=None))
        self.assertIsNotNone(self.fault())
        _write(self.root/'manifest.json', dict(run_id=self.case['run_id'], run_instance_id='a'*32,
                                                started_at='2026-10-07T00:00:00+00:00', end_reason=None))
        self.assertIsNone(self.fault())

    def test_single_recorded_request_stays_held(self):
        self.assertIsNone(self.fault(_usage(observed_requests=1)))

    def test_any_usage_stays_held(self):
        self.assertIsNone(self.fault(_usage(observed_tokens=dict(input_tokens=1, output_tokens=0))))
        self.assertIsNone(self.fault(_usage(observed_tokens=dict(input_tokens=0, output_tokens=3))))
        self.assertIsNone(self.fault(_usage(total_tokens=5)))

    def test_unconfirmed_send_or_journal_stays_held(self):
        self.assertIsNone(self.fault(_usage(send_evidence='unknown')))
        self.assertIsNone(self.fault(_usage(source_journals={'started': {'path': 'x', 'sha256': 'y'}})))
        self.assertIsNone(self.fault(_usage(transmission_issues=['unreconciled_request_terminal_inventory'])))
        _write(self.root/'usage'/'raw'/'started.jsonl', {'request_id': 'r'})
        self.assertIsNone(self.fault())

    def test_dispatch_or_implementation_record_stays_held(self):
        journal = self.batch/'pair-7'/'_control'/'pair-journal.jsonl'
        with mock.patch.object(recovery.pair_execution, 'state', return_value={'dispatch': {self.case['run_id']: {}}, 'implementations': {}}):
            journal.write_text('', encoding='utf-8')
            self.assertIsNone(self.fault())
        with mock.patch.object(recovery.pair_execution, 'state', return_value={'dispatch': {}, 'implementations': {self.case['run_id']: {}}}):
            self.assertIsNone(self.fault())
        journal.unlink()
        for name in ('runtime.json', 'implementation-receipt.json'):
            path = _write(self.root/name, {})
            self.assertIsNone(self.fault()); path.unlink()

    def test_launcher_must_show_pre_dispatch_fault_and_release(self):
        for over in (dict(operational_complete=True), dict(stop_requested=False), dict(reason='user_stop'),
                     dict(child={'exit_confirmed': False}), dict(observer_closure={'confirmed': False}),
                     dict(errors=['e']), dict(pairs=[6]),
                     dict(owned_runs=[]), dict(owned_runs=[self.not_allocated(status='owned_allocated')]),
                     dict(owned_runs=[self.not_allocated(unknown=True)]), dict(owned_runs=[self.not_allocated(stop_attempted=True)]),
                     dict(owned_runs=[self.not_allocated(), self.not_allocated()]),
                     dict(owned_runs=[self.not_allocated(run_instance_id='b'*32)])):
            self._launch(**over)
            self.assertIsNone(self.fault(), over)
        (self.wave_dir/'_launcher'/'result.json').unlink()
        self.assertIsNone(self.fault())

    def test_non_held_observation_never_promoted(self):
        self.assertIsNone(self.fault(observation={'classification': 'already_evaluable', 'model_calls': 0}))


class DecidePairTests(unittest.TestCase):
    def arm(self, fault):
        value = dict(observation=HELD, usage=_usage(), opportunity='not_applicable', technical_evidence=[])
        if fault: value['pre_dispatch_fault'] = {'category': 'pre_dispatch_campaign_fault'}
        return value

    def test_pre_dispatch_fault_is_replacement_evidence(self):
        self.assertEqual(recovery.decide_pair({'explore': self.arm(True), 'preload': self.arm(True)}), 'replacement_eligible')

    def test_arm_without_evidence_keeps_pair_held(self):
        self.assertEqual(recovery.decide_pair({'explore': self.arm(False), 'preload': self.arm(True)}), 'held')
        self.assertEqual(recovery.decide_pair({'explore': self.arm(False), 'preload': self.arm(False)}), 'held')

    def test_any_send_uncertainty_keeps_pair_held(self):
        explore = self.arm(True); explore['usage'] = _usage(send_evidence='unknown')
        self.assertEqual(recovery.decide_pair({'explore': explore, 'preload': self.arm(True)}), 'held')


class SupersedingWrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.wave_dir = base/'w'; wave = _write(self.wave_dir/'spec.json', {'w': 1})
        plan = _write(base/'plan.json', {'p': 1})
        self.first = _write(base/'r0'/'closure.json', {'c': 0}); self.second = _write(base/'r1'/'closure.json', {'c': 1})
        self.wave_ref = live_pilot.reference(wave)
        _write(self.wave_dir/'closure.json', dict(wave=self.wave_ref, closed=True, recovery=live_pilot.reference(self.first)))
        self.ctx = dict(repo=base, campaign=live_pilot.reference(plan), wave_path=wave)
        self.value = dict(wave=self.wave_ref, campaign=self.ctx['campaign'])
        self.decision = base/'r0'/'decision.json'

    def check(self, wrapper, name='recovery-closure.json', verified=None):
        target = _write(self.wave_dir/name, wrapper)
        verified = verified if verified is not None else dict(wave=self.wave_ref, campaign=self.ctx['campaign'])
        with mock.patch.object(recovery, 'validate_closure', return_value=verified) as v:
            return recovery._superseding_wrapper(self.ctx, self.decision, self.value, target), v

    def test_verified_second_recovery_of_same_wave_tolerated(self):
        ok, v = self.check(dict(wave=self.wave_ref, closed=True, recovery=live_pilot.reference(self.second)))
        self.assertTrue(ok); v.assert_called_once()

    def test_foreign_or_malformed_wrappers_rejected(self):
        good = dict(wave=self.wave_ref, closed=True, recovery=live_pilot.reference(self.second))
        self.assertFalse(self.check(good, name='other.json')[0])
        self.assertFalse(self.check({**good, 'extra': 1})[0])
        self.assertFalse(self.check({**good, 'closed': False})[0])
        self.assertFalse(self.check({**good, 'wave': {'path': 'x', 'sha256': 'y'}})[0])
        self.assertFalse(self.check({**good, 'recovery': live_pilot.reference(self.first)})[0])
        self.assertFalse(self.check(good, verified=dict(wave={'path': 'z'}, campaign=self.ctx['campaign']))[0])

    def test_verification_failure_propagates(self):
        target = _write(self.wave_dir/'recovery-closure.json',
                        dict(wave=self.wave_ref, closed=True, recovery=live_pilot.reference(self.second)))
        with mock.patch.object(recovery, 'validate_closure', side_effect=ValueError('Recovery closure changed')):
            with self.assertRaises(ValueError):
                recovery._superseding_wrapper(self.ctx, self.decision, self.value, target)


class LedgerSupersessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base/'batch'; (self.root/'_control').mkdir(parents=True)
        self.wave_dir = self.root/'waves'/'w'; self.wave = _write(self.wave_dir/'spec.json', {'w': 1})
        self.plan = _write(base/'plan.json', {'p': 1})
        self.first = _write(base/'r0'/'closure.json', {'c': 0}); self.second = _write(base/'r1'/'closure.json', {'c': 1})
        self.wave_ref = live_pilot.reference(self.wave)
        self.closure = _write(self.wave_dir/'closure.json', dict(wave=self.wave_ref, closed=True, recovery=live_pilot.reference(self.first)))
        self.closure_bytes = self.closure.read_bytes()
        held = dict(kind='pair_recovery_decision', slot=7, wave=self.wave_ref, decision={'disposition': 'held'},
                    closure=live_pilot.reference(self.closure), not_before='t0')
        (self.root/'attempts.jsonl').write_bytes((json.dumps(held)+'\n').encode())

    def rows(self):
        return [json.loads(l) for l in (self.root/'attempts.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]

    def reconcile(self, disposition):
        value = {'decisions': {'7': {'disposition': disposition}}, 'retry_not_before': 't1'}
        with mock.patch.object(campaign, 'validate', return_value={'batch': str(self.root)}), \
             mock.patch.object(campaign, 'wave_spec', return_value={'pairs': [7], 'epoch_plan': {}}), \
             mock.patch.object(recovery, 'validate_closure', return_value=value), \
             mock.patch.object(campaign, 'verify_closure', return_value=True), \
             mock.patch.object(campaign, 'ledger', side_effect=lambda p: self.rows()), \
             mock.patch.object(campaign, 'stop_markers', return_value=[]):
            return campaign.reconcile_recovery.__wrapped__('repo', self.plan, self.wave, live_pilot.reference(self.second))

    def test_second_recovery_appends_superseding_decision(self):
        out = self.reconcile('replacement_eligible')
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['decision']['disposition'], 'held')
        self.assertEqual(rows[1]['decision']['disposition'], 'replacement_eligible')
        self.assertEqual(rows[1]['closure'], live_pilot.reference(self.wave_dir/'recovery-closure.json'))
        self.assertEqual(rows[1]['supersedes'], dict(closure=live_pilot.reference(self.closure), disposition='held'))
        self.assertEqual(self.closure.read_bytes(), self.closure_bytes)
        self.assertTrue(out['reconciled'])
        self.reconcile('replacement_eligible')
        self.assertEqual(len(self.rows()), 2, 'idempotent')

    def test_still_held_second_recovery_keeps_stop(self):
        out = self.reconcile('held')
        self.assertFalse(out['clearance'])
        self.assertEqual(self.rows()[-1]['decision']['disposition'], 'held')


class GatewayStartFaultTests(unittest.TestCase):
    """Dispatched Run whose gateway never started: zero-send evidence only."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.batch = base/'epoch'; self.wave_dir = base/'waves'/'w1'
        wave_path = _write(self.wave_dir/'spec.json', {'wave': 1})
        plan = _write(base/'plan.json', {'plan': 1}); epoch = _write(base/'epoch.json', {'epoch': 1})
        self.case = dict(pair=6, run_id='T-explore-1', run_instance_id='c'*32, condition='explore')
        self.root = r = self.batch/'pair-6'/self.case['run_id']
        self.journal = _write(self.batch/'pair-6'/'_control'/'pair-journal.jsonl', {})
        self.ctx = dict(epoch={'batch': str(self.batch)}, wave_path=wave_path, wave_ref=live_pilot.reference(wave_path),
                        campaign=live_pilot.reference(plan), wave={'epoch_plan': live_pilot.reference(epoch), 'pairs': [6, 7]})
        self.run = dict(run_id=self.case['run_id'], run_instance_id='c'*32, status='owned_allocated', stop_attempted=True,
                        closure_confirmed=True, unknown=False)
        self.launch = dict(kind='repaired_campaign_wave_launcher_v1_result', wave=self.ctx['wave_ref'],
                           plan=self.ctx['campaign'], epoch_plan=self.ctx['wave']['epoch_plan'], pairs=[6, 7],
                           operational_complete=False, stop_requested=True, reason='campaign_stop',
                           stop={'reason': 'campaign_stop', 'durable_stop_paths': ['x']},
                           child={'exit_confirmed': True}, observer_closure={'confirmed': True}, errors=[], owned_runs=[self.run])
        _write(self.wave_dir/'_launcher'/'result.json', self.launch)
        ident = dict(run_id=self.case['run_id'], run_instance_id='c'*32)
        _write(r/'manifest.json', {**ident, 'end_reason': 'environment_failure', 'stop_confirmed': True, 'started_at': 't'})
        _write(r/'evidence'/'runtime-error.json', {'type': 'RuntimeError', 'message': 'Gateway failed to start'})
        (r/'evidence'/'gateway.log').write_bytes(b'')
        (r/'usage'/'raw').mkdir(parents=True); (r/'usage'/'events.jsonl').write_bytes(b'')
        _write(r/'usage'/'normalized.json', {**ident, 'observed_request_count': 0, 'observed_call_count': 0, 'raw_files': [],
               'input_reached': False, 'execution_evidence': {'send_evidence': 'known_no_send', 'model_called': False,
               'started_count': 0, 'terminal_count': 0, 'saved_response_count': 0}})
        _write(r/'implementation-receipt.json', {**ident, 'stop_confirmed': True, 'collection_status': 'fixed', 'raw': {}})
        _write(r/'stop-result.json', {'run_id': self.case['run_id'], 'stop_confirmed': True, 'network_cleanup':
               {'run_instance_id': 'c'*32, 'confirmed': True, 'status': 'removed'}})
        _write(r/'runtime.json', ident)
        self.state = {'dispatch': {self.case['run_id']: dict(self.case)}, 'implementations': {}}

    def fault(self, usage=None, state=None):
        with mock.patch.object(recovery.pair_execution, 'state', return_value=state or self.state):
            return recovery._pre_dispatch_fault(self.ctx, self.case, self.root, usage or _usage(), HELD)

    def relaunch(self, **over):
        _write(self.wave_dir/'_launcher'/'result.json', {**self.launch, **over})

    def test_gateway_never_started_zero_send_is_evidence(self):
        fact = self.fault()
        self.assertEqual(fact['category'], 'gateway_start_campaign_fault')
        self.assertEqual((fact['observed_requests'], fact['observed_tokens']), (0, 0))

    def test_any_gateway_log_line_stays_held(self):
        (self.root/'evidence'/'gateway.log').write_bytes(b'listening\n')
        self.assertIsNone(self.fault())

    def test_any_usage_event_or_journal_stays_held(self):
        (self.root/'usage'/'events.jsonl').write_bytes(b'{"request_id":"r"}\n')
        self.assertIsNone(self.fault())
        (self.root/'usage'/'events.jsonl').write_bytes(b'')
        _write(self.root/'usage'/'raw'/'started.jsonl', {'request_id': 'r'})
        self.assertIsNone(self.fault())

    def test_requests_or_tokens_stay_held(self):
        self.assertIsNone(self.fault(_usage(observed_requests=1)))
        self.assertIsNone(self.fault(_usage(observed_tokens=dict(input_tokens=7, output_tokens=0))))
        self.assertIsNone(self.fault(_usage(source_journals={'events': {'path': 'x', 'sha256': 'y'}})))
        n = util_read(self.root/'usage'/'normalized.json')
        _write(self.root/'usage'/'normalized.json', {**n, 'observed_request_count': 1})
        self.assertIsNone(self.fault())
        _write(self.root/'usage'/'normalized.json', {**n, 'execution_evidence': {**n['execution_evidence'], 'started_count': 1}})
        self.assertIsNone(self.fault())
        _write(self.root/'usage'/'normalized.json', {**n, 'execution_evidence': {**n['execution_evidence'], 'model_called': True}})
        self.assertIsNone(self.fault())

    def test_implementation_record_stays_held(self):
        self.assertIsNone(self.fault(state={**self.state, 'implementations': {self.case['run_id']: {}}}))
        r = util_read(self.root/'implementation-receipt.json')
        _write(self.root/'implementation-receipt.json', {**r, 'raw': {'opencode': 'x'}})
        self.assertIsNone(self.fault())

    def test_unknown_or_unconfirmed_closure_stays_held(self):
        for over in (dict(unknown=True), dict(closure_confirmed=False), dict(stop_attempted=False), dict(status='not_allocated')):
            self.relaunch(owned_runs=[{**self.run, **over}])
            self.assertIsNone(self.fault(), over)
        self.relaunch(observer_closure={'confirmed': False}); self.assertIsNone(self.fault())
        self.relaunch()
        s = util_read(self.root/'stop-result.json')
        _write(self.root/'stop-result.json', {**s, 'network_cleanup': {**s['network_cleanup'], 'status': 'retained'}})
        self.assertIsNone(self.fault())

    def test_missing_campaign_fault_stop_stays_held(self):
        for over in (dict(reason='user_stop'), dict(stop={'reason': 'campaign_stop', 'durable_stop_paths': []}),
                     dict(stop={'reason': 'operator_stop', 'durable_stop_paths': ['x']}), dict(stop_requested=False),
                     dict(operational_complete=True)):
            self.relaunch(**over)
            self.assertIsNone(self.fault(), over)
        (self.wave_dir/'_launcher'/'result.json').unlink()
        self.assertIsNone(self.fault())

    def test_other_environment_failures_stay_held(self):
        _write(self.root/'evidence'/'runtime-error.json', {'type': 'RuntimeError', 'message': 'Worker failed'})
        self.assertIsNone(self.fault())
        _write(self.root/'evidence'/'runtime-error.json', {'type': 'RuntimeError', 'message': 'Gateway failed to start'})
        m = util_read(self.root/'manifest.json')
        _write(self.root/'manifest.json', {**m, 'end_reason': 'timeout'})
        self.assertIsNone(self.fault())

    def test_binding_must_match_case(self):
        self.assertIsNone(self.fault(state={**self.state, 'dispatch': {self.case['run_id']: {**self.case, 'run_instance_id': 'd'*32}}}))


def util_read(path):
    return json.loads(path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
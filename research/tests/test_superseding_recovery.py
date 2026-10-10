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


class NoSendRuleTests(unittest.TestCase):
    """Single rule: confirmed no-send is replacement evidence; any recorded
    request/usage or undeterminable send status stays held."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.batch = Path(self.tmp.name)/'epoch'
        self.case = dict(pair=6, run_id='T-explore-1', run_instance_id='c'*32, condition='explore')
        self.root = self.batch/'pair-6'/self.case['run_id']
        self.ctx = dict(epoch={'batch': str(self.batch)})

    def fault(self, usage=None):
        return recovery._no_send_fault(self.ctx, self.case, self.root, usage or _usage(), HELD)

    def test_never_created_run_is_confirmed_no_send(self):
        self.assertEqual(self.fault()['category'], 'confirmed_no_send')

    def test_started_run_with_empty_journals_is_confirmed_no_send(self):
        (self.root/'usage'/'raw').mkdir(parents=True); (self.root/'usage'/'events.jsonl').write_bytes(b'')
        (self.root/'usage'/'raw'/'started.jsonl').write_bytes(b'')
        _write(self.root/'usage'/'normalized.json', {'observed_request_count': 0, 'observed_call_count': 0,
               'execution_evidence': {'send_evidence': 'known_no_send', 'model_called': False, 'started_count': 0}})
        self.assertIsNotNone(self.fault(_usage(source_journals={'started': {'path': 'x', 'sha256': 'y'}})))

    def test_one_request_or_any_tokens_stays_held(self):
        self.assertIsNone(self.fault(_usage(observed_requests=1)))
        self.assertIsNone(self.fault(_usage(observed_tokens=dict(input_tokens=1, output_tokens=0))))
        self.assertIsNone(self.fault(_usage(observed_tokens=dict(input_tokens=0, output_tokens=2))))
        self.assertIsNone(self.fault(_usage(total_tokens=3)))
        self.assertIsNone(self.fault(_usage(technical_evidence=[{'category': 'provider'}])))

    def test_recorded_usage_event_or_request_journal_stays_held(self):
        _write(self.root/'usage'/'events.jsonl', {'request_id': 'r'})
        self.assertIsNone(self.fault())
        (self.root/'usage'/'events.jsonl').write_bytes(b'')
        _write(self.root/'usage'/'raw'/'started.jsonl', {'request_id': 'r'})
        self.assertIsNone(self.fault())

    def test_normalized_usage_reporting_a_request_stays_held(self):
        for value in ({'observed_request_count': 1}, {'observed_call_count': 1},
                      {'execution_evidence': {'started_count': 1}}, {'execution_evidence': {'model_called': True}}):
            _write(self.root/'usage'/'normalized.json', value)
            self.assertIsNone(self.fault(), value)

    def test_undeterminable_send_status_stays_held(self):
        self.assertIsNone(self.fault(_usage(send_evidence='unknown')))
        self.assertIsNone(self.fault(_usage(journal_errors=['invalid_json'])))
        self.assertIsNone(self.fault(_usage(transmission_issues=['unreconciled_request_terminal_inventory'])))
        (self.root/'usage').mkdir(parents=True); (self.root/'usage'/'normalized.json').write_bytes(b'{not json')
        self.assertIsNone(self.fault())

    def test_foreign_run_root_stays_held(self):
        self.assertIsNone(recovery._no_send_fault(self.ctx, self.case, self.batch/'pair-7'/self.case['run_id'], _usage(), HELD))


class DecidePairTests(unittest.TestCase):
    def arm(self, fault):
        value = dict(observation=HELD, usage=_usage(), opportunity='not_applicable', technical_evidence=[])
        if fault: value['no_send_fault'] = {'category': 'confirmed_no_send'}
        return value

    def test_confirmed_no_send_is_replacement_evidence(self):
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


if __name__ == '__main__':
    unittest.main()
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import next_phase
from research.next_phase_execution import execute


class ProspectiveStartTests(unittest.TestCase):
    def plan(self):
        return util.read_json(next_phase.REPO / next_phase.PLAN)

    def test_balanced_orders_and_exact_denominator(self):
        plan = self.plan()
        assigned = next_phase.assignments(plan)
        self.assertEqual(len(assigned), 64)
        self.assertEqual(len({c['run_id'] for p in assigned for c in p['cases']}), 128)
        for task in plan['task_ids']:
            selected = [p for p in assigned if p['task'] == task]
            self.assertEqual(len(selected), 32)
            self.assertEqual(sum(p['cases'][0]['condition'] == 'preload' for p in selected), 16)
        self.assertEqual(assigned, next_phase.assignments(plan))

    def test_old_protocol_or_paired_regime_cannot_enter_new_controller(self):
        plan = self.plan()
        plan['regime']['pair_concurrency'] = 2
        with self.assertRaises(ValueError): next_phase.validate_plan(plan)
        with self.assertRaises(ValueError): next_phase.validate_plan({'plan_id': 'old-catalog-320'})

    def test_ai_review_cannot_satisfy_human_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / 'evidence.json'
            util.write_new_json(evidence, {'verified': True})
            ledger = {k: {'status': 'passed', 'evidence': [next_phase.reference(evidence)]}
                for k in next_phase.PREREQUISITES}
            ledger['human_review'] = {'status': 'passed', 'actor': 'agent', 'reviewer': 'AI',
                'reviewed_at_utc': next_phase.now(), 'evidence': [next_phase.reference(evidence)]}
            self.assertIn('human_review:unbound_or_not_human', next_phase.ledger_reasons(ledger))
            ledger['human_review']['actor'] = 'human'
            ledger['human_review']['status'] = 'not_run'
            self.assertIn('human_review:not_run', next_phase.ledger_reasons(ledger))

    def test_blocked_check_cannot_read_key_or_start_worker(self):
        blocked = {'scientific_and_technical_ready': False, 'blocking_reasons': ['human_review:not_run']}
        with patch('research.next_phase.check', return_value=blocked), patch('outer.harness.runtime._gateway_credential') as key, patch('outer.harness.runtime.start') as start:
            self.assertEqual(execute(Path('.'), Path('no-bundle'), None), blocked)
            key.assert_not_called()
            start.assert_not_called()

    def test_approval_cannot_cover_changed_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle, approval = root / 'bundle.json', root / 'approval.json'
            util.write_new_json(bundle, {'fixed': True})
            util.write_new_json(approval, {'authorized': True, 'approved_by': 'user',
                'bundle_sha256': util.sha256_file(bundle), 'authorization_reference': 'Explicit future start instruction',
                'approved_at_utc': next_phase.now()})
            self.assertTrue(next_phase.approved(approval, bundle)['authorized'])
            bundle.write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError): next_phase.approved(approval, bundle)

    def test_old_review_cannot_authorize_new_input_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / 'passed.json'
            util.write_new_json(evidence, {'verified': True})
            ledger = {'selected_task_scope': {'status': 'passed', 'evidence': [next_phase.reference(evidence)],
                'asset_hashes': {'task/input.json': 'old-hash'}}}
            reasons = next_phase.ledger_reasons(ledger, scopes={'selected_task_scope': {'task/input.json': 'new-hash'}})
            self.assertIn('selected_task_scope:reviewed_asset_scope_mismatch', reasons)


if __name__ == '__main__': unittest.main()

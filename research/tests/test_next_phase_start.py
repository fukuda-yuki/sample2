import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import next_phase
from research.next_phase_execution import execute, provider_metadata


class ProspectiveStartTests(unittest.TestCase):
    def test_provider_metadata_is_recorded_and_unexpected_alias_pauses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / 'usage/raw'
            raw.mkdir(parents=True)
            self.assertEqual(provider_metadata(root, 'expected')['reported_metadata_state'], 'not_reported')
            (raw / 'call.response.sse').write_text('data: {"model":"expected"}\n\ndata: [DONE]\n')
            self.assertFalse(provider_metadata(root, 'expected')['unexpected_reported_model'])
            (raw / 'call.response.sse').write_text('data: {"model":"changed"}\n\ndata: [DONE]\n')
            self.assertTrue(provider_metadata(root, 'expected')['unexpected_reported_model'])

    def plan(self):
        return util.read_json(next_phase.REPO / next_phase.PLAN)

    def test_balanced_orders_and_exact_denominator(self):
        plan = self.plan()
        assigned = next_phase.assignments(plan)
        self.assertEqual(len(assigned), 64)
        self.assertEqual(len({c['run_id'] for p in assigned for c in p['cases']}), 128)
        for task in plan['task_ids']:
            selected = [p for p in assigned if p['task'] == task]
            self.assertEqual(len(selected), 16)
            self.assertEqual(sum(p['cases'][0]['condition'] == 'preload' for p in selected), 8)
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

    def test_old_execution_review_cannot_cover_changed_new_adapter(self):
        name = 'research/next_phase_execution.py'
        scopes = next_phase.acceptance_scopes({name: 'new'})
        self.assertEqual(scopes['execution_evidence'][name], 'new')
        ledger = {'execution_evidence': {'status': 'passed', 'evidence': [],
            'asset_hashes': {name: 'old'}}}
        self.assertIn('execution_evidence:reviewed_asset_scope_mismatch',
            next_phase.ledger_reasons(ledger, scopes=scopes))

    def test_human_confirmation_cannot_replace_independent_task_acceptance(self):
        reasons = next_phase.ledger_reasons({'human_review': {'status': 'passed',
            'actor': 'human', 'reviewer': 'reviewer', 'reviewed_at_utc': next_phase.now(),
            'evidence': []}})
        self.assertIn('independent_task_set:not_run', reasons)

    def delegated_fixture(self, root):
        plan = self.plan()
        evidence = root / 'finite-technical-evidence.json'
        util.write_new_json(evidence, {'fixture': True, 'status': 'passed'})
        pins = {'inner/tasks/fixture/contract.txt': 'bound-fixture-task',
            'inner/spec/fixture-1.3.0.json': 'bound-fixture-oracle',
            'outer/harness/runtime.py': 'bound-fixture-runtime',
            'outer/harness/evaluate.py': 'bound-fixture-evaluator',
            next_phase.PLAN: util.sha256_file(next_phase.REPO / next_phase.PLAN)}
        scopes = next_phase.acceptance_scopes(pins, plan)
        accepted = scopes['research_lead_review']
        ledger = {key: {'status': 'passed', 'asset_hashes': scopes[key],
            'evidence': [next_phase.reference(evidence)]} for key in next_phase.PREREQUISITES}
        ledger['human_review'] = {'status': 'not_run'}
        common = {'plan_id': plan['plan_id'], 'review_policy': next_phase.LEAD_REVIEW_POLICY,
            'plan_sha256': pins[next_phase.PLAN]}
        reviews = {
            'user_delegation': {**common, 'kind': 'research_lead_user_delegation',
                'role': 'user_delegation', 'actor': 'human', 'status': 'delegated',
                'authorization_scope': 'research_preparation_and_lead_acceptance',
                'user_instruction': next_phase.USER_DELEGATION_INSTRUCTION,
                'research_start_authorized': False, 'recorded_at_utc': next_phase.now()},
            'research_lead_decision': {**common, 'kind': 'research_lead_acceptance',
                'role': 'research_lead_decision', 'actor': 'ai', 'status': 'accepted',
                'reviewer': 'lead-test-fixture', 'reviewed_at_utc': next_phase.now(),
                'asset_hashes': accepted, 'human_review_status': 'not_run',
                'ordinary_user_acceptance_claimed': False, 'coverage_limitations': ['Synthetic unit fixture only'],
                'ordinary_workflow_evidence': [next_phase.reference(evidence)],
                'independent_source_oracle_evidence': [next_phase.reference(evidence)],
                'task_acceptance': {task: {'status': 'accepted',
                    'workflow_basis': 'ordinary_browser_observation', 'source_oracle_status': 'matched'}
                    for task in plan['task_ids']}},
            'independent_methodological_review': {**common, 'kind': 'independent_methodological_review',
                'role': 'independent_methodological_review', 'actor': 'ai', 'status': 'accepted',
                'reviewer': 'independent-test-fixture', 'reviewed_at_utc': next_phase.now(),
                'asset_hashes': accepted, 'human_review_status': 'not_run',
                'ordinary_user_acceptance_claimed': False,
                'independence_declaration': 'Independent synthetic methodological reviewer',
                'amendment_is_prospective': True}}
        roles = {}
        for role, data in reviews.items():
            path = root / (role + '.json')
            util.write_new_json(path, data)
            roles[role] = next_phase.reference(path)
        ledger['research_lead_review'] = {'status': 'passed', 'actor': 'ai',
            'reviewer': 'lead-test-fixture', 'reviewed_at_utc': next_phase.now(),
            'asset_hashes': accepted, 'role_evidence': roles, 'evidence': list(roles.values())}
        return plan, ledger, scopes

    def rewrite_role(self, ledger, role, change):
        reference = ledger['research_lead_review']['role_evidence'][role]
        path = Path(reference['path'])
        data = util.read_json(path)
        change(data)
        path.write_text(json.dumps(data), encoding='utf-8')
        updated = next_phase.reference(path)
        ledger['research_lead_review']['role_evidence'][role] = updated
        ledger['research_lead_review']['evidence'] = [
            updated if record == reference else record
            for record in ledger['research_lead_review']['evidence']]

    def test_v4_scientific_parameters_and_assignments_remain_identical_to_v3(self):
        before = util.read_json(next_phase.REPO / next_phase.V3_PLAN)
        after = self.plan()
        self.assertEqual(next_phase.assignments(before), next_phase.assignments(after))
        self.assertEqual({key: value for key, value in before.items()
                if key not in next_phase.ADMINISTRATIVE_FIELDS},
            {key: value for key, value in after.items()
                if key not in next_phase.ADMINISTRATIVE_FIELDS})
        for changed in ('provider_timeout_seconds', 'collection_policy'):
            with self.subTest(changed=changed):
                candidate = copy.deepcopy(after)
                candidate['settings'][changed] = 'changed'
                with self.assertRaises(ValueError): next_phase.validate_plan(candidate)
        after['acceptance_review_policy'] = 'skip-human'
        with self.assertRaises(ValueError): next_phase.validate_plan(after)
        before['acceptance_review_policy'] = next_phase.LEAD_REVIEW_POLICY
        with self.assertRaises(ValueError): next_phase.validate_plan(before)

    def test_bound_delegated_v4_passes_without_relabelling_legacy_human_review(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, ledger, scopes = self.delegated_fixture(Path(directory))
            self.assertEqual(next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan), [])
            self.assertEqual(ledger['human_review']['status'], 'not_run')
            legacy = util.read_json(next_phase.REPO / next_phase.V3_PLAN)
            self.assertIn('human_review:not_run', next_phase.ledger_reasons(ledger, plan=legacy))
            ledger['evaluation_chain']['status'] = 'not_run'
            self.assertIn('evaluation_chain:not_run',
                next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))

    def test_v4_requires_delegation_and_distinct_semantic_review_roles(self):
        refusals = [
            ('user_delegation', lambda data: data.update(user_instruction='Please start research')),
            ('user_delegation', lambda data: data.update(research_start_authorized=True)),
            ('research_lead_decision', lambda data: data.update(role='user_delegation')),
            ('research_lead_decision', lambda data: data.update(reviewed_at_utc='2026-10-03T00:00:00')),
            ('independent_methodological_review', lambda data: data.update(reviewer='lead-test-fixture')),
            ('independent_methodological_review', lambda data: data.update(status='not_run'))]
        for role, change in refusals:
            with self.subTest(role=role, change=change), tempfile.TemporaryDirectory() as directory:
                plan, ledger, scopes = self.delegated_fixture(Path(directory))
                self.rewrite_role(ledger, role, change)
                self.assertTrue(next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))
        with tempfile.TemporaryDirectory() as directory:
            plan, ledger, scopes = self.delegated_fixture(Path(directory))
            del ledger['research_lead_review']['role_evidence']['user_delegation']
            self.assertIn('research_lead_review:user_delegation:role_evidence_missing',
                next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))

    def test_v4_refuses_forged_human_actor_or_missing_task_source_workflow(self):
        for change in (
                lambda ledger: ledger['research_lead_review'].update(actor='human'),
                lambda ledger: ledger['human_review'].update(status='passed')):
            with tempfile.TemporaryDirectory() as directory:
                plan, ledger, scopes = self.delegated_fixture(Path(directory))
                change(ledger)
                self.assertTrue(next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))
        for change in (
                lambda data: data['task_acceptance'].pop('CU1-ENR-D'),
                lambda data: data.update(independent_source_oracle_evidence=[]),
                lambda data: data.update(ordinary_workflow_evidence=[]),
                lambda data: data.update(ordinary_user_acceptance_claimed=True)):
            with tempfile.TemporaryDirectory() as directory:
                plan, ledger, scopes = self.delegated_fixture(Path(directory))
                self.rewrite_role(ledger, 'research_lead_decision', change)
                self.assertTrue(next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))

    def test_v4_changed_review_evidence_or_assets_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            plan, ledger, scopes = self.delegated_fixture(Path(directory))
            independent = ledger['research_lead_review']['role_evidence']['independent_methodological_review']
            Path(independent['path']).write_text('{}', encoding='utf-8')
            self.assertIn('research_lead_review:independent_methodological_review:evidence_changed',
                next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))
        with tempfile.TemporaryDirectory() as directory:
            plan, ledger, scopes = self.delegated_fixture(Path(directory))
            changed = copy.deepcopy(scopes)
            changed['research_lead_review']['inner/tasks/fixture/contract.txt'] = 'different-task'
            self.assertIn('research_lead_review:reviewed_asset_scope_mismatch',
                next_phase.ledger_reasons(ledger, scopes=changed, plan=plan))
            source = Path(directory) / 'finite-technical-evidence.json'
            source.write_text('{}', encoding='utf-8')
            self.assertIn('research_lead_review:research_lead_decision:ordinary_workflow_evidence_changed',
                next_phase.ledger_reasons(ledger, scopes=scopes, plan=plan))

    def test_ready_gate_still_cannot_execute_without_exact_bundle_start_approval(self):
        with patch('research.next_phase.check', return_value={'scientific_and_technical_ready': True}), \
                patch('outer.harness.runtime._gateway_credential') as key, \
                patch('outer.harness.runtime.start') as start:
            with self.assertRaises(ValueError): execute(Path('.'), Path('no-bundle'), None)
            key.assert_not_called()
            start.assert_not_called()


if __name__ == '__main__': unittest.main()

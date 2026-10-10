"""Finite prospective-allocation and fail-closed v5 acceptance cases."""
import copy
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import util
from research import catalog_delivery, next_phase, paired_acceptance
from research.next_phase_analysis import summarize, slot_facts


class V5PlanTests(unittest.TestCase):
    def plan(self):
        return util.read_json(next_phase.REPO / next_phase.V5_PLAN)

    def test_exact_100_pairs_200_unique_fixed_instances_and_balanced_odd_orders(self):
        plan = self.plan()
        assigned = next_phase.assignments(plan)
        self.assertEqual(assigned, next_phase.assignments(plan))
        self.assertEqual(len(assigned), 100)
        cases = [c for p in assigned for c in p['cases']]
        for key in ('run_id', 'slot', 'run_instance_id'):
            self.assertEqual(len({c[key] for c in cases}), 200)
        self.assertEqual(Counter(c['condition'] for c in cases), {'explore': 100, 'preload': 100})
        self.assertEqual(Counter(p['cases'][0]['condition'] for p in assigned), {'explore': 50, 'preload': 50})
        for i, task in enumerate(plan['task_ids']):
            selected = [p for p in assigned if p['task'] == task]
            self.assertEqual(len(selected), 25)
            self.assertEqual(sum(p['cases'][0]['condition'] == 'explore' for p in selected), 13 if i % 2 == 0 else 12)

    def test_v5_hash_rejects_scientific_mutation_without_weakening_v4(self):
        for field, value in [('pair_concurrency', 1), ('run_internal_concurrency', 2), ('between_pair_overlap', True)]:
            plan = self.plan()
            plan['regime'][field] = value
            with self.assertRaises(ValueError): next_phase.validate_plan(plan)
        before = util.read_json(next_phase.REPO / next_phase.PLAN)
        self.assertEqual(len(next_phase.assignments(before)), 64)
        before['allocation']['pairs'] = 100
        with self.assertRaises(ValueError): next_phase.validate_plan(before)
        changed = self.plan()
        changed['settings']['model_id'] = 'other-model'
        with self.assertRaises(ValueError): next_phase.validate_plan(changed)

    def test_missing_actual_parallel_comparison_blocks_v5(self):
        self.assertEqual(paired_acceptance.ledger_reasons({}, self.plan(), {}),
            ['paired_execution_acceptance:not_run'])
        self.assertEqual(paired_acceptance.ledger_reasons(
            {'paired_execution_acceptance': {'status': 'passed', 'evidence': {}}}, self.plan(), {}),
            ['paired_execution_acceptance:original_comparison_not_accepted'])
        with self.assertRaises(ValueError):
            paired_acceptance.validate({'kind': 'mock-speedup', 'accepted': True}, self.plan(), {})

    def test_v5_review_scope_uses_v5_plan_and_new_controller_dependencies(self):
        pins = {next_phase.PLAN: 'v4', next_phase.V5_PLAN: 'v5',
            'research/paired_acceptance.py': 'new-validator', 'inner/tasks/test': 'task'}
        scopes = next_phase.acceptance_scopes(pins, self.plan())
        self.assertEqual(scopes['research_lead_review'][next_phase.V5_PLAN], 'v5')
        self.assertNotIn(next_phase.PLAN, scopes['research_lead_review'])
        self.assertEqual(scopes['execution_evidence']['research/paired_acceptance.py'], 'new-validator')

    def test_v5_live_driver_absent_blocks_even_an_acceptance_claim(self):
        with self.assertRaisesRegex(ValueError, 'dedicated v5 live comparison driver'):
            paired_acceptance.validate({'kind':'paired_execution_acceptance_v5'},self.plan(),
                {'execution_evidence':{}})

    def test_v5_publication_prefix_reaches_package_validation_without_remote_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix='source-info-v5-100p2-'+'a'*12+'-pair-'
            with patch.object(catalog_delivery,'verify_package',side_effect=ValueError('package validation reached')) as verify, patch.object(catalog_delivery,'release') as remote:
                with self.assertRaisesRegex(ValueError,'package validation reached'):
                    catalog_delivery.publish(Path(directory),prefix+'001','b'*40,tag_prefix=prefix)
                verify.assert_called_once()
                remote.assert_not_called()

    def test_facts_preserve_all_200_slots_and_do_not_count_unobserved_send_as_success(self):
        plan=self.plan(); assignments=next_phase.assignments(plan)
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory); path=repo/'bundle.json'
            bundle={'plan':plan,'assignments':assignments,'cohort':'runs/source-info-v5-100p2'}
            util.write_new_json(path,bundle)
            current={'dispatch':{},'gates':{}}
            facts=slot_facts(bundle,path,repo,current,[])
            self.assertEqual((facts['assigned_slots'],facts['actual_gateway_sent_runs'],facts['undispatched_runs']),(200,0,200))
            case=assignments[0]['cases'][0]
            binding={**case,'plan_sha256':util.sha256_file(path),'cohort':bundle['cohort']}
            current['dispatch'][case['run_id']]=binding
            root=repo/bundle['cohort']/case['run_id']
            util.write_new_json(root/'manifest.json',{'run_id':case['run_id'],
                'run_instance_id':case['run_instance_id'],'end_reason':'completed',
                'ended_at':'fixture','stop_confirmed':True})
            facts=slot_facts(bundle,path,repo,current,[])
            self.assertEqual((facts['normal_runs'],facts['incomplete_runs'],facts['actual_gateway_sent_runs']),(0,1,0))
            util.append_line(root/'usage/raw/events.jsonl',{'run_id':case['run_id'],
                'session_id':case['run_instance_id'],'send_evidence':'observed_send'})
            facts=slot_facts(bundle,path,repo,current,[])
            self.assertEqual((facts['normal_runs'],facts['actual_gateway_sent_runs']),(1,1))

    def test_all_200_unobserved_slots_remain_unknown_and_foreign_instance_rejected(self):
        plan = self.plan()
        assignments = next_phase.assignments(plan)
        args = dict(plan_sha256='bundle', cohort='runs/source-info-v5-100p2',
            measurement={'evaluation_version': {}, 'evaluator_sha256': {}})
        result = summarize(plan, assignments, [], bindings={}, **args)
        self.assertEqual(result['assigned_slots'], 200)
        self.assertEqual(result['dispatch_count'], 0)
        self.assertEqual(result['undispatched_or_no_result'], 200)
        self.assertEqual(result['execution_regime']['pair_concurrency'], 2)
        self.assertIsNone(result['all_assigned_token_difference'])
        case = assignments[0]['cases'][0]
        with self.assertRaises(ValueError):
            summarize(plan, assignments, [], bindings={case['run_id']: {**case,
                'run_instance_id': 'foreign'}}, **args)


if __name__ == '__main__': unittest.main()

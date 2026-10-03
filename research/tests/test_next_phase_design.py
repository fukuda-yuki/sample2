import copy
import unittest

from research.next_phase_design import calculate
from research.next_phase_analysis import summarize


class NextPhaseMeasurementTests(unittest.TestCase):
    def fixture(self):
        plan = {'plan_id': 'test', 'task_ids': ['A', 'B'], 'variant_weights': [0.5, 0.5],
            'arms': ['explore', 'preload'], 'allocation': {'runs': 4}}
        pairs = [{'task': task, 'cases': [{'task': task, 'run_id': task + arm, 'condition': arm} for arm in plan['arms']]} for task in plan['task_ids']]
        def row(task, arm, tokens, verdict='pass', complete=True):
            return {'run_id': task + arm, 'task_id': task, 'intervention_id': arm,
                'verdict': verdict, 'scoring': {'state': 'scored', 'research_status': 'complete'},
                'operation_status': 'complete', 'usage': {'usage_complete': complete, 'total_tokens': tokens}}
        return plan, pairs, row

    def test_all_assigned_missing_quality_and_tokens_are_not_zero(self):
        p, a, row = self.fixture()
        result = summarize(p, a, [])
        self.assertEqual(result['assigned_slots'], 4)
        self.assertEqual(result['all_assigned_quality_difference_identification_bounds'], [-1, 1])
        self.assertIsNone(result['all_assigned_token_difference'])
        self.assertFalse(result['all_assigned_token_contrast_identified'])

    def test_partial_total_cannot_supply_complete_case_or_primary(self):
        p, a, row = self.fixture()
        rows = [row('A', 'explore', 100), row('A', 'preload', 80, complete=False),
            row('B', 'explore', 200), row('B', 'preload', 100)]
        result = summarize(p, a, rows)
        self.assertIsNone(result['all_assigned_token_difference'])
        self.assertEqual(result['strata'][0]['complete_pair_token_count_secondary'], 0)
        self.assertIsNone(result['equal_variant_complete_pair_token_difference_secondary'])

    def test_variant_weights_and_product_failure(self):
        p, a, row = self.fixture()
        rows = [row('A', 'explore', 100), row('A', 'preload', 80, verdict='fail_critical'),
            row('B', 'explore', 200), row('B', 'preload', 100)]
        result = summarize(p, a, rows)
        self.assertEqual(result['all_assigned_token_difference'], -60)
        self.assertEqual(result['all_assigned_quality_difference_identification_bounds'], [-0.5, -0.5])
        self.assertFalse(result['quality_maintenance_claim'])

    def test_wrong_arm_or_duplicate_is_rejected(self):
        p, a, row = self.fixture()
        r = row('A', 'explore', 100)
        with self.assertRaises(ValueError): summarize(p, a, [r, r])
        r['intervention_id'] = 'preload'
        with self.assertRaises(ValueError): summarize(p, a, [r])

    def test_more_missingness_and_session_dependence_reduce_precision(self):
        data = calculate()
        rows = data['quality_precision_scenarios']
        def width(missing, icc):
            return next(r['quality_difference_ci95_half_width_normal'] for r in rows if r['discordance'] == .5 and r['missing_pair_fraction'] == missing and r['session_icc'] == icc)
        self.assertGreater(width(.25, .3), width(0, 0))
        self.assertFalse(data['new_family_effect_variance_identifiable'])
        self.assertEqual(data['assigned_runs'], 128)


if __name__ == '__main__': unittest.main()

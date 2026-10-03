import copy
from pathlib import Path
import tempfile
import unittest

from outer.harness import util
from research.next_phase_design import calculate
from research.next_phase_analysis import summarize, interval_sensitivity, terminal_row


class NextPhaseMeasurementTests(unittest.TestCase):
    def test_foreign_normalized_usage_and_changed_total_cannot_enter_terminal_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'usage/raw').mkdir(parents=True)
            path = root / 'usage/normalized.json'
            normalized = {'run_id': 'run', 'run_instance_id': 'instance',
                'total_tokens': 100, 'raw_bindings': []}
            util.write_new_json(path, normalized)
            version = root / 'usage/derivations/version'
            util.write_new_json(version / 'normalized.json', normalized)
            util.write_new_json(version / 'binding.json', {**normalized,
                'normalized_sha256': util.sha256_file(path), 'raw': []})
            binding = {'run_id': 'run', 'run_instance_id': 'instance'}
            row = {**binding, 'usage': {'total_tokens': 100}}
            implementation = {'receipt': {'raw': {}}}
            self.assertEqual(terminal_row(root, binding, {'row': row}, implementation, row), row)
            changed = {**normalized, 'run_instance_id': 'foreign'}
            util.write_json_atomic(path, changed)
            with self.assertRaises(ValueError):
                terminal_row(root, binding, {'row': row}, implementation, row)
            util.write_json_atomic(path, normalized)
            current = {**row, 'usage': {'total_tokens': 999}}
            with self.assertRaises(ValueError):
                terminal_row(root, binding, {'row': row}, implementation, current)

    def fixture(self):
        plan = {'plan_id': 'test', 'task_ids': ['A', 'B'], 'variant_weights': [0.5, 0.5],
            'arms': ['explore', 'preload'], 'allocation': {'runs': 4}}
        pairs = [{'task': task, 'cases': [{'task': task, 'run_id': task + arm, 'condition': arm, 'pair': i, 'slot': i * 2 + j} for j, arm in enumerate(plan['arms'])]} for i, task in enumerate(plan['task_ids'])]
        def row(task, arm, tokens, verdict='pass', complete=True):
            return {'run_id': task + arm, 'task_id': task, 'intervention_id': arm,
                'run_instance_id': 'inst-' + task + arm, 'synthetic': False,
                'verdict': verdict, 'scoring': {'state': 'scored', 'research_status': 'complete',
                    'evaluation_version': '1.3.0', 'evaluator_sha256': 'hash-' + task},
                'operation_status': 'complete', 'usage': {'usage_complete': complete, 'total_tokens': tokens}}
        self.binding = {c['run_id']: {**c, 'run_instance_id': 'inst-' + c['run_id'],
            'plan_sha256': 'plan-hash', 'cohort': 'new-study', 'input_sha256': 'input-hash',
            'condition_sha256': 'condition-hash'} for p in pairs for c in p['cases']}
        return plan, pairs, row

    def summarize(self, p, a, rows):
        return summarize(p, a, rows, bindings=self.binding, plan_sha256='plan-hash',
            cohort='new-study', measurement={'evaluation_version': '1.3.0',
                'evaluator_sha256': {'A': 'hash-A', 'B': 'hash-B'}})

    def test_all_assigned_missing_quality_and_tokens_are_not_zero(self):
        p, a, row = self.fixture()
        result = self.summarize(p, a, [])
        self.assertEqual(result['assigned_slots'], 4)
        self.assertEqual(result['all_assigned_quality_difference_identification_bounds'], [-1, 1])
        self.assertIsNone(result['all_assigned_token_difference'])
        self.assertFalse(result['all_assigned_token_contrast_identified'])

    def test_partial_total_cannot_supply_complete_case_or_primary(self):
        p, a, row = self.fixture()
        rows = [row('A', 'explore', 100), row('A', 'preload', 80, complete=False),
            row('B', 'explore', 200), row('B', 'preload', 100)]
        result = self.summarize(p, a, rows)
        self.assertIsNone(result['all_assigned_token_difference'])
        self.assertEqual(result['strata'][0]['complete_pair_token_count_secondary'], 0)
        self.assertIsNone(result['equal_variant_complete_pair_token_difference_secondary'])

    def test_variant_weights_and_product_failure(self):
        p, a, row = self.fixture()
        rows = [row('A', 'explore', 100), row('A', 'preload', 80, verdict='fail_critical'),
            row('B', 'explore', 200), row('B', 'preload', 100)]
        result = self.summarize(p, a, rows)
        self.assertEqual(result['all_assigned_token_difference'], -60)
        self.assertEqual(result['all_assigned_quality_difference_identification_bounds'], [-0.5, -0.5])
        self.assertFalse(result['quality_maintenance_claim'])

    def test_wrong_arm_or_duplicate_is_rejected(self):
        p, a, row = self.fixture()
        r = row('A', 'explore', 100)
        with self.assertRaises(ValueError): self.summarize(p, a, [r, r])
        r['intervention_id'] = 'preload'
        with self.assertRaises(ValueError): self.summarize(p, a, [r])

    def test_wrong_instance_technical_cohort_and_old_evaluator_are_rejected(self):
        p, a, row = self.fixture()
        r = row('A', 'explore', 100)
        for field, value in [('run_instance_id', 'old-instance'), ('synthetic', True)]:
            bad = copy.deepcopy(r); bad[field] = value
            with self.assertRaises(ValueError): self.summarize(p, a, [bad])
        bad = copy.deepcopy(r); bad['scoring']['evaluation_version'] = '1.2.0'
        with self.assertRaises(ValueError): self.summarize(p, a, [bad])
        self.binding[r['run_id']]['cohort'] = 'technical-old'
        with self.assertRaises(ValueError): self.summarize(p, a, [r])

    def test_paired_interval_uses_known_variance_and_session_sensitivity(self):
        results = interval_sensitivity([[-10, 10], [-10, 10]], [.5, .5])
        self.assertAlmostEqual(results[0]['normal_approximation_ci95'][1], 1.96 * 50 ** .5)
        self.assertGreater(results[2]['normal_approximation_ci95'][1], results[0]['normal_approximation_ci95'][1])
        self.assertIsNone(interval_sensitivity([[-10], [-20]], [.5, .5]))

    def test_more_missingness_and_session_dependence_reduce_precision(self):
        data = calculate()
        rows = data['quality_precision_scenarios']
        def width(missing, icc):
            return next(r['quality_difference_ci95_half_width_normal'] for r in rows if r['discordance'] == .5 and r['missing_pair_fraction'] == missing and r['session_icc'] == icc)
        self.assertGreater(width(.25, .3), width(0, 0))
        self.assertFalse(data['new_family_effect_variance_identifiable'])
        self.assertEqual(data['assigned_runs'], 128)


if __name__ == '__main__': unittest.main()

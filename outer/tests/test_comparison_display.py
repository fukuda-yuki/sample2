"""Synthetic read-only regression; no model or evaluator runs."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path.cwd() / 'outer/tests'))
from test_harness import HarnessTestCase
from harness import aggregate, cli, util


class ComparisonAndDisplayTests(HarnessTestCase):
    def test_changed_preparation_and_budget_are_separate_but_identical_conditions_group(self):
        path = self.repo / 'outer/conditions/TEST-001/condition.json'
        condition = util.read_json(path)
        condition['runtime_lock'] = {'images': {'worker': 'image-A'}}
        util.write_json_atomic(path, condition)
        self.create(attempt=1)
        condition['runtime_lock']['images']['worker'] = 'image-B'
        util.write_json_atomic(path, condition)
        self.create(attempt=2)
        condition['budget']['value'] += 1
        util.write_json_atomic(path, condition)
        self.create(attempt=3)
        self.create(attempt=4)
        groups = aggregate.compare(self.runs)['groups']
        self.assertEqual([1, 1, 2], sorted(len(g['run_ids']) for g in groups))
        self.assertEqual(4, sum(len(g['run_ids']) for g in groups))

    def test_no_observed_tokens_are_null_before_collection(self):
        m = self.create()
        self.assertIsNone(aggregate.row_for(self.runs, m['run_id'])['usage']['observed_tokens'])

    def test_status_reports_dispatch_before_finalization(self):
        m = self.create()
        root = self.runs / m['run_id']
        # Simulated gateway start only: never contact a provider in this test.
        util.append_line(root / 'usage/raw/started.jsonl', {'request_id': 'synthetic-status-probe'})
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            cli.main(['--repo', str(self.repo), '--runs-dir', str(self.runs), 'status', '--run', m['run_id']])
        state = json.loads(output.getvalue())
        self.assertEqual(1, state['requests_started'])
        self.assertTrue(state['model_called'])


if __name__ == '__main__':
    unittest.main()

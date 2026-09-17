"""Scoring hand-over rules, tested with a stand-in evaluator.

The stand-in is not the real evaluator; it exists so the outer harness's own
rules can be tested quickly. The real evaluator is exercised by
`python outer/verify/verify.py --repo .`.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    from . import support
except ImportError:  # started as a top-level module (discover -s outer/tests)
    import support
from harness import aggregate, evaluate, run as run_mod, util

STUB = Path(__file__).resolve().parent / 'stub_evaluator.py'


class RunFixture:
    """A completed dummy run with a fixed submission, ready to be scored."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo, self.runs, self.legacy, self.seed = support.make_env(self.root)
        self.manifest = run_mod.create_run(self.repo, self.runs, support.TASK_ID,
                                           support.CONDITION_ID, 1,
                                           {'legacy-source': self.legacy})
        run_mod.start_run(self.repo, self.runs, self.manifest['run_id'], 'dummy',
                          synthetic=True, scenario='ok', seed=self.seed)
        run_mod.collect_run(self.runs, self.manifest['run_id'])
        self.run_dir = self.runs / self.manifest['run_id']
        self.addCleanup(os.environ.pop, 'HARNESS_STUB_MODE', None)

    def score(self, mode='ok', **kwargs):
        os.environ['HARNESS_STUB_MODE'] = mode
        return evaluate.score_run(self.repo, self.runs, self.manifest['run_id'],
                                  evaluator=STUB, **kwargs)


class ScoreTestCase(RunFixture, unittest.TestCase):

    def test_scored_run_records_the_evaluator_output_unchanged(self):
        record = self.score('ok')
        self.assertEqual('scored', record['scoring_state'])
        self.assertEqual(0, record['evaluator_exit_code'])
        self.assertEqual('pass', record['verdict'])
        self.assertEqual(100.0, record['quality'])
        self.assertEqual([], record['mismatches'])
        self.assertEqual(record['artifact_sha256_outer'],
                         record['artifact_sha256_reported'])
        target = self.run_dir / record['directory']
        produced = util.read_json(target / 'evaluation.json')
        self.assertEqual(record['evaluation_id'], produced['evaluationId'])
        self.assertEqual('pass', produced['verdict'])

    def test_index_is_append_only_and_keeps_every_scoring(self):
        first = self.score('ok')
        second = self.score('ok')
        entries = evaluate.read_index(self.run_dir)
        self.assertEqual(2, len(entries))
        self.assertEqual(1, entries[0]['sequence'])
        self.assertEqual(2, entries[1]['sequence'])
        self.assertEqual(first['evaluation_id'], entries[0]['evaluation_id'])
        self.assertEqual(second['evaluation_id'], entries[1]['evaluation_id'])

    def test_same_artifact_and_version_at_the_same_sequence_repeats_the_id(self):
        first = self.score('ok')
        expected = '{}-{}-1.0.0-001'.format(support.TASK_ID,
                                            first['artifact_sha256_outer'][:12])
        self.assertEqual(expected, first['evaluation_id'])
        with self.assertRaises(FileExistsError):
            self.score('ok', sequence=1)
        directories = sorted(p.name for p in (self.run_dir / 'evaluations').iterdir()
                             if p.is_dir())
        self.assertEqual([expected], directories)
        leftovers = [p.name for p in (self.run_dir / 'evaluations').iterdir()
                     if p.name.startswith('.tmp-')]
        self.assertEqual([], leftovers)

    def test_rescoring_keeps_verdict_and_quality_and_only_the_sequence_differs(self):
        first = self.score('ok')
        second = self.score('ok')
        self.assertNotEqual(first['evaluation_id'], second['evaluation_id'])
        self.assertEqual(first['verdict'], second['verdict'])
        self.assertEqual(first['quality'], second['quality'])
        self.assertEqual(first['artifact_sha256_outer'], second['artifact_sha256_outer'])
        self.assertEqual(first['evaluation_id'].rsplit('-', 1)[0],
                         second['evaluation_id'].rsplit('-', 1)[0])

    def test_evaluator_fault_is_not_a_run_failure(self):
        record = self.score('fault')
        self.assertEqual('evaluator_fault', record['scoring_state'])
        self.assertEqual(2, record['evaluator_exit_code'])
        self.assertIsNone(record['quality'])
        self.assertEqual('error', record['verdict'])
        manifest = run_mod.load_manifest(self.runs, self.manifest['run_id'])
        self.assertEqual('completed', manifest['end_reason'])
        self.assertTrue(manifest['stop_confirmed'])
        row = aggregate.row_for(self.runs, self.manifest['run_id'])
        self.assertEqual('evaluator_fault', row['scoring']['state'])
        self.assertIsNone(row['quality'])
        self.assertIn('evaluator_fault', [issue['kind'] for issue in row['issues']])
        self.assertNotIn('execution', [issue['kind'] for issue in row['issues']])

    def test_missing_evaluator_output_is_a_fault(self):
        record = self.score('no-output')
        self.assertEqual('evaluator_fault', record['scoring_state'])
        self.assertIsNone(record['evaluation_id'])
        self.assertIsNone(record['quality'])

    def test_mismatches_are_rejected_and_kept_as_evidence(self):
        for mode, check in (('mismatch-task', 'task'), ('mismatch-spec', 'spec'),
                            ('mismatch-artifact', 'artifact'),
                            ('mismatch-version', 'evaluation_version'),
                            ('mismatch-path', 'artifact_path')):
            with self.subTest(mode=mode):
                record = self.score(mode)
                self.assertEqual('rejected_mismatch', record['scoring_state'])
                self.assertFalse(record['adopted'])
                self.assertIn(check, [item['check'] for item in record['mismatches']])
                self.assertTrue((self.run_dir / record['directory'] / 'evaluation.json').is_file())
                row = aggregate.row_for(self.runs, self.manifest['run_id'])
                self.assertIsNone(row['quality'])
                self.assertIsNone(row['verdict'])

    def test_adopted_score_carries_its_verdict_and_quality(self):
        record = self.score('ok')
        self.assertTrue(record['adopted'])
        self.assertEqual('pass', record['verdict'])
        self.assertEqual(100.0, record['quality'])

    def test_an_artifact_changed_after_collection_is_refused(self):
        """frozen/ is the artifact that was fixed; rewriting it is not that artifact."""
        frozen = self.run_dir / 'frozen' / 'MusicStore.Web' / 'Program.cs'
        frozen.write_text('// rewritten after collection\n', encoding='utf-8')
        record = self.score('ok')
        self.assertEqual('rejected_mismatch', record['scoring_state'])
        self.assertFalse(record['adopted'])
        self.assertIsNone(record['verdict'])
        self.assertIsNone(record['quality'])
        self.assertEqual(['artifact_sha256'],
                         [item['check'] for item in record['mismatches']])
        entry = record['mismatches'][0]
        self.assertEqual(entry['actual'], record['artifact_sha256_outer'])
        self.assertEqual(entry['expected'], record['artifact_sha256_frozen'])
        self.assertNotEqual(entry['expected'], entry['actual'])
        # 採点していないので評価器の出力は無い。拒否は index に残る。
        self.assertFalse((self.run_dir / record['directory'] / 'evaluation.json').is_file())
        rows = evaluate.read_index(self.run_dir)
        self.assertEqual(1, len(rows))
        self.assertEqual('rejected_mismatch', rows[0]['scoring_state'])
        self.assertEqual(record['mismatches'], rows[0]['mismatches'])

    def test_an_untouched_frozen_artifact_still_scores(self):
        record = self.score('ok')
        self.assertEqual(record['artifact_sha256_outer'], record['artifact_sha256_frozen'])

    def test_each_scoring_starts_from_an_empty_work_directory(self):
        """Two scorings must not share one work directory or its database.

        The stand-in refuses to score on a non-empty work directory, exactly as
        the real evaluator does, so the second scoring only succeeds when it was
        given a directory of its own.
        """
        first = self.score('work-marker')
        second = self.score('work-marker')
        self.assertEqual('scored', first['scoring_state'])
        self.assertEqual('scored', second['scoring_state'])
        self.assertNotEqual(first['work_dir'], second['work_dir'])
        self.assertEqual('001', Path(first['work_dir']).name)
        self.assertEqual('002', Path(second['work_dir']).name)
        self.assertEqual(self.run_dir / 'evaluation-work',
                         Path(first['work_dir']).parent)
        self.assertTrue((Path(first['work_dir']) / 'store.sqlite').is_file())

    def test_rejected_mismatch_is_not_used_in_the_aggregate(self):
        self.score('mismatch-artifact')
        row = aggregate.row_for(self.runs, self.manifest['run_id'])
        self.assertEqual('rejected_mismatch', row['scoring']['state'])
        self.assertIsNone(row['quality'])
        self.assertIsNone(row['verdict'])
        self.assertIn('mismatch', [issue['kind'] for issue in row['issues']])

    def test_blocked_verdict_is_kept_and_not_dropped(self):
        record = self.score('blocked')
        self.assertEqual('scored', record['scoring_state'])
        self.assertTrue(record['adopted'])
        self.assertEqual('blocked', record['verdict'])
        self.assertEqual(90.0, record['quality'])
        self.assertEqual(2, record['blocked_count'])
        row = aggregate.row_for(self.runs, self.manifest['run_id'])
        self.assertEqual('blocked', row['verdict'])
        self.assertEqual(90.0, row['quality'])
        self.assertIn('quality_blocked', [issue['kind'] for issue in row['issues']])
        self.assertNotIn('quality', [issue['kind'] for issue in row['issues']])

    def test_failed_verdict_is_reported_as_a_quality_issue(self):
        self.score('fail-critical')
        row = aggregate.row_for(self.runs, self.manifest['run_id'])
        self.assertEqual('fail_critical', row['verdict'])
        self.assertEqual(31.03, row['quality'])
        self.assertIn('quality', [issue['kind'] for issue in row['issues']])

    def test_scoring_requires_a_confirmed_stop_and_a_fixed_submission(self):
        other = run_mod.create_run(self.repo, self.runs, support.TASK_ID,
                                   support.CONDITION_ID, 2, {'legacy-source': self.legacy})
        with self.assertRaises(RuntimeError):
            evaluate.score_run(self.repo, self.runs, other['run_id'], evaluator=STUB)
        run_mod.start_run(self.repo, self.runs, other['run_id'], 'dummy',
                          synthetic=True, scenario='ok', seed=self.seed)
        with self.assertRaises(RuntimeError):
            evaluate.score_run(self.repo, self.runs, other['run_id'], evaluator=STUB)

    def test_changed_ledger_is_refused_before_scoring(self):
        (self.repo / 'inner' / 'spec' / 'requirements.json').write_text('{"changed": true}\n',
                                                                       encoding='utf-8')
        with self.assertRaises(RuntimeError):
            self.score('ok')

    def test_scoring_records_which_evaluator_build_scored(self):
        record = self.score('ok')
        build = util.sha256_file(STUB)
        self.assertEqual(build, record['evaluator_sha256'])
        self.assertEqual(build, record['evaluator_sha256_reported'])
        entry = evaluate.read_index(self.run_dir)[0]
        self.assertEqual(build, entry['evaluator_sha256'])
        row = aggregate.row_for(self.runs, self.manifest['run_id'])
        self.assertEqual(build, row['scoring']['evaluator_sha256'])

    def test_the_recorded_build_is_what_the_outer_invoked_not_what_was_claimed(self):
        """A stand-in that lies about its own hash must not change the record."""
        record = self.score('manifest-mismatch')
        self.assertEqual(util.sha256_file(STUB), record['evaluator_sha256'])
        self.assertEqual('f' * 64, record['evaluator_sha256_reported'])
        self.assertEqual('scored', record['scoring_state'])

    def test_a_pinned_evaluator_build_is_enforced(self):
        support.pin_evaluator(self.run_dir, util.sha256_file(STUB))
        self.assertEqual('scored', self.score('ok')['scoring_state'])

    def test_a_different_evaluator_build_is_refused_when_the_condition_pins_one(self):
        support.pin_evaluator(self.run_dir, '0' * 64)
        record = self.score('ok')
        self.assertEqual('rejected_mismatch', record['scoring_state'])
        self.assertFalse(record['adopted'])
        self.assertIsNone(record['verdict'])
        self.assertIsNone(record['quality'])
        self.assertEqual([{'check': 'evaluator_sha256', 'expected': '0' * 64,
                           'actual': util.sha256_file(STUB)}], record['mismatches'])
        self.assertEqual('0' * 64, record['evaluator_sha256_pinned'])
        self.assertEqual(util.sha256_file(STUB), record['evaluator_sha256'])

    def test_the_refused_build_is_kept_in_the_index(self):
        """A refusal must be diagnosable from the record alone."""
        support.pin_evaluator(self.run_dir, '0' * 64)
        self.score('ok')
        rows = evaluate.read_index(self.run_dir)
        self.assertEqual(1, len(rows))
        self.assertEqual('rejected_mismatch', rows[0]['scoring_state'])
        self.assertEqual('0' * 64, rows[0]['evaluator_sha256_pinned'])

    def test_pinning_without_provenance_is_refused(self):
        """A pinned hash with no stated origin cannot be diagnosed later."""
        path = Path(self.run_dir) / 'condition.json'
        for key in ('source_path', 'command', 'sdk_version', 'sha256_origin', 'clean_worktree'):
            with self.subTest(missing=key):
                support.pin_evaluator(self.run_dir, '0' * 64)
                data = util.read_json(path)
                data['evaluation']['evaluator_build'][key] = None
                util.write_json_atomic(path, data)
                with self.assertRaises(RuntimeError):
                    self.score('ok')
                self.assertEqual([], evaluate.read_index(self.run_dir))
                self.assertFalse((Path(self.run_dir) / 'evaluations').exists())

    def test_pinning_a_build_measured_outside_the_procedure_is_refused(self):
        """`clean_worktree` is a claim, not a detail: a false one is refused.

        The hash moves with the line endings of the evaluator sources, so a
        value measured on a rewritten worktree is not the recorded commit's.
        """
        path = Path(self.run_dir) / 'condition.json'
        support.pin_evaluator(self.run_dir, '0' * 64)
        data = util.read_json(path)
        data['evaluation']['evaluator_build']['clean_worktree'] = False
        util.write_json_atomic(path, data)
        with self.assertRaises(RuntimeError):
            self.score('ok')
        self.assertFalse((Path(self.run_dir) / 'evaluations').exists())

    def test_an_unpinned_condition_still_records_the_build(self):
        support.pin_evaluator(self.run_dir, None)
        record = self.score('ok')
        self.assertEqual('scored', record['scoring_state'])
        self.assertEqual(util.sha256_file(STUB), record['evaluator_sha256'])
        self.assertIsNone(record['evaluator_sha256_pinned'])

    def test_the_fault_path_also_records_the_build(self):
        record = self.score('no-output')
        self.assertEqual('evaluator_fault', record['scoring_state'])
        self.assertEqual(util.sha256_file(STUB), record['evaluator_sha256'])
        self.assertIsNone(record['evaluator_sha256_reported'])


class ScoringTimeoutTests(RunFixture, unittest.TestCase):
    """A scoring run that never returns must not leave the app behind."""

    def test_timeout_is_recorded_as_an_evaluator_fault(self):
        marker = self.root / 'grandchild.pid'
        os.environ['HARNESS_STUB_MARKER'] = str(marker)
        self.addCleanup(os.environ.pop, 'HARNESS_STUB_MARKER', None)
        record = self.score('sleep', timeout=5)
        self.assertEqual('evaluator_fault', record['scoring_state'])
        self.assertTrue(record['evaluator_timed_out'])
        self.assertEqual(5, record['timeout_seconds'])
        self.assertEqual(-1, record['evaluator_exit_code'])
        self.assertFalse(record['adopted'])
        self.assertIsNone(record['quality'])
        self.assertEqual('評価器の実行が上限を超えたため停止しました', record['reason'])
        row = aggregate.row_for(self.runs, self.manifest['run_id'])
        self.assertEqual('evaluator_fault', row['scoring']['state'])
        self.assertNotIn('execution', [issue['kind'] for issue in row['issues']])

    def test_timeout_takes_the_process_tree_down(self):
        marker = self.root / 'grandchild.pid'
        os.environ['HARNESS_STUB_MARKER'] = str(marker)
        self.addCleanup(os.environ.pop, 'HARNESS_STUB_MARKER', None)
        self.score('sleep', timeout=5)
        self.assertTrue(marker.is_file(), 'スタブが子プロセスを起動していない')
        grandchild = int(marker.read_text(encoding='utf-8'))
        self.addCleanup(_force_kill, grandchild)
        self.assertFalse(_is_alive(grandchild),
                         '評価器の子プロセスが残っている: ' + str(grandchild))


def _is_alive(pid):
    try:
        completed = subprocess.run(['tasklist', '/FI', 'PID eq {}'.format(pid), '/NH'],
                                   capture_output=True, text=True)
    except OSError:
        return None
    return str(pid) in completed.stdout


def _force_kill(pid):
    subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)


if __name__ == '__main__':
    unittest.main()

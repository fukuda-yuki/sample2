"""End-to-end harness rules with the dummy runner. No model is called."""
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from . import support
except ImportError:  # started as a top-level module (discover -s outer/tests)
    import support
from harness import aggregate, run as run_mod, util


class HarnessTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo, self.runs, self.legacy, self.seed = support.make_env(self.root)

    def create(self, attempt=1, inputs=None):
        return run_mod.create_run(self.repo, self.runs, support.TASK_ID,
                                  support.CONDITION_ID, attempt,
                                  inputs if inputs is not None
                                  else {'legacy-source': self.legacy})

    def start(self, run_id, scenario='ok', **kwargs):
        return run_mod.start_run(self.repo, self.runs, run_id, 'dummy',
                                 synthetic=True, scenario=scenario, seed=self.seed, **kwargs)


class CreateTests(HarnessTestCase):
    def test_create_is_exclusive(self):
        self.create()
        with self.assertRaises(FileExistsError):
            self.create()
        self.create(attempt=2)

    def test_create_records_input_hashes_and_size(self):
        manifest = self.create()
        recorded = util.read_json(self.runs / manifest['run_id'] / 'inputs-manifest.json')
        self.assertEqual(['legacy-source'], list(recorded['inputs']))
        self.assertEqual(2, recorded['file_count'])
        self.assertEqual(manifest['inputs_total_bytes'], recorded['total_bytes'])
        self.assertEqual(util.sha256_file(self.legacy / 'readme.txt'),
                         recorded['inputs']['legacy-source']['files']['readme.txt']['sha256'])

    def test_input_outside_allowlist_is_rejected(self):
        with self.assertRaises(ValueError):
            self.create(inputs={'inner/spec': self.repo / 'inner' / 'spec'})

    def test_private_areas_cannot_be_used_as_input(self):
        with self.assertRaises(ValueError):
            self.create(inputs={'legacy-source': self.repo / 'inner'})
        with self.assertRaises(ValueError):
            self.create(inputs={'legacy-source': self.repo / 'docs'})

    def test_condition_copy_is_fixed_in_the_run(self):
        manifest = self.create()
        run_dir = self.runs / manifest['run_id']
        self.assertEqual(util.sha256_file(run_dir / 'condition.json'),
                         manifest['condition_sha256'])
        source = self.repo / 'outer' / 'conditions' / support.TASK_ID / 'condition.json'
        (run_dir / 'condition.json').write_text('{}', encoding='utf-8')
        self.assertNotEqual(util.sha256_file(run_dir / 'condition.json'),
                            manifest['condition_sha256'])
        self.assertEqual('C01', util.read_json(source)['condition_id'])


class StartTests(HarnessTestCase):
    def test_dummy_runner_requires_synthetic(self):
        manifest = self.create()
        with self.assertRaises(ValueError):
            run_mod.start_run(self.repo, self.runs, manifest['run_id'], 'dummy',
                              scenario='ok', seed=self.seed)

    def test_manual_runner_requires_a_filled_agent(self):
        manifest = self.create()
        with self.assertRaises(ValueError):
            run_mod.start_run(self.repo, self.runs, manifest['run_id'], 'manual')

    def test_filled_agent_lets_a_manual_run_start_and_stay_running(self):
        support.fill_agent(self.repo)
        manifest = self.create()
        started = run_mod.start_run(self.repo, self.runs, manifest['run_id'], 'manual')
        self.assertIsNone(started['end_reason'])
        self.assertFalse(started['stop_confirmed'])
        self.assertEqual('manual', started['runner']['id'])
        self.assertEqual('running', run_mod.execution_state(started))

    def test_start_twice_is_refused(self):
        manifest = self.create()
        self.start(manifest['run_id'])
        with self.assertRaises(RuntimeError):
            self.start(manifest['run_id'])

    def test_unknown_runner_and_scenario_are_refused(self):
        manifest = self.create()
        with self.assertRaises(ValueError):
            run_mod.start_run(self.repo, self.runs, manifest['run_id'], 'codex',
                              synthetic=True)
        with self.assertRaises(ValueError):
            self.start(manifest['run_id'], scenario='not-a-scenario')

    def test_completed_dummy_run_confirms_the_process_exit(self):
        manifest = self.create()
        started = self.start(manifest['run_id'])
        self.assertEqual('completed', started['end_reason'])
        self.assertEqual(0, started['exit_code'])
        self.assertTrue(started['stop_confirmed'])
        self.assertEqual('process_exit', started['stop_method'])
        self.assertFalse(started['model_called'])
        self.assertTrue(started['synthetic'])

    def test_scripted_failure_is_agent_error(self):
        manifest = self.create()
        started = self.start(manifest['run_id'], scenario='crash')
        self.assertEqual('agent_error', started['end_reason'])
        self.assertEqual(3, started['exit_code'])
        self.assertTrue(started['stop_confirmed'])

    def test_timeout_is_recorded_and_the_process_is_stopped(self):
        manifest = self.create()
        started = self.start(manifest['run_id'], scenario='ok', timeout=0.001)
        self.assertEqual('timeout', started['end_reason'])
        self.assertTrue(started['stop_confirmed'])

    def test_runner_evidence_is_kept(self):
        manifest = self.create()
        self.start(manifest['run_id'])
        run_dir = self.runs / manifest['run_id']
        self.assertTrue((run_dir / 'evidence' / 'runner-stdout.log').is_file())
        self.assertTrue((run_dir / 'evidence' / 'runner-stderr.log').is_file())


class StopAndCollectTests(HarnessTestCase):
    def manual_start(self, workspace=True):
        support.fill_agent(self.repo)
        manifest = self.create()
        run_mod.start_run(self.repo, self.runs, manifest['run_id'], 'manual')
        if workspace:
            # The operator's agent produces the workspace; the harness never does.
            shutil.copytree(self.seed, self.runs / manifest['run_id'] / 'workspace')
        return manifest

    def test_declaration_only_is_not_a_stop_and_is_not_collected(self):
        manifest = self.manual_start()
        stopped = run_mod.stop_run(self.runs, manifest['run_id'], 'declaration_only',
                                   evidence_text='人が完了と申告した')
        self.assertFalse(stopped['stop_confirmed'])
        self.assertEqual('stop_unconfirmed', stopped['end_reason'])
        with self.assertRaises(RuntimeError):
            run_mod.collect_run(self.runs, manifest['run_id'])

    def test_operator_process_check_allows_collection(self):
        manifest = self.manual_start()
        run_mod.stop_run(self.runs, manifest['run_id'], 'operator_process_check',
                         evidence_text='残存プロセスが無いことを確認した')
        collected, snapshot = run_mod.collect_run(self.runs, manifest['run_id'])
        self.assertTrue(collected['submission_fixed'])
        self.assertEqual('fixed', snapshot['artifact_state'])
        self.assertEqual('operator_process_check', collected['stop_method'])

    def test_collect_before_start_is_refused(self):
        manifest = self.create()
        with self.assertRaises(RuntimeError):
            run_mod.collect_run(self.runs, manifest['run_id'])

    def test_missing_workspace_is_recorded_not_invented(self):
        manifest = self.manual_start(workspace=False)
        run_mod.stop_run(self.runs, manifest['run_id'], 'operator_process_check',
                         evidence_text='確認した')
        collected, snapshot = run_mod.collect_run(self.runs, manifest['run_id'])
        self.assertEqual('missing_workspace', snapshot['artifact_state'])
        self.assertFalse(collected['submission_fixed'])


class ArtifactTests(HarnessTestCase):
    def test_frozen_artifact_hash_matches_the_seed(self):
        manifest = self.create()
        self.start(manifest['run_id'])
        _, snapshot = run_mod.collect_run(self.runs, manifest['run_id'])
        self.assertEqual(util.artifact_hash(self.seed), snapshot['artifact_sha256'])
        self.assertEqual(snapshot['artifact_sha256'], snapshot['artifact_sha256_collected'])
        self.assertEqual([], snapshot['normalized'])
        self.assertFalse(snapshot['artifact_hash_changed_by_collection'])

    def test_line_endings_are_fixed_and_recorded(self):
        manifest = self.create()
        self.start(manifest['run_id'], scenario='crlf')
        _, snapshot = run_mod.collect_run(self.runs, manifest['run_id'])
        self.assertNotEqual(snapshot['artifact_sha256'],
                            snapshot['artifact_sha256_collected'])
        self.assertTrue(snapshot['artifact_hash_changed_by_collection'])
        self.assertTrue(snapshot['normalized'])
        self.assertEqual(util.artifact_hash(self.seed), snapshot['artifact_sha256'])
        kinds = {kind for entry in snapshot['normalized'] for kind in entry['changed']}
        self.assertIn('crlf_to_lf', kinds)
        self.assertIn('bom_removed', kinds)

    def test_generated_directories_are_excluded(self):
        manifest = self.create()
        self.start(manifest['run_id'])
        workspace = self.runs / manifest['run_id'] / 'workspace'
        (workspace / 'MusicStore.Web' / 'bin' / 'Release').mkdir(parents=True)
        (workspace / 'MusicStore.Web' / 'bin' / 'Release' / 'app.dll').write_bytes(b'x')
        (workspace / 'MusicStore.Web' / 'obj').mkdir()
        (workspace / 'MusicStore.Web' / 'obj' / 'a.json').write_text('{}')
        (workspace / 'store.sqlite').write_bytes(b'y')
        _, snapshot = run_mod.collect_run(self.runs, manifest['run_id'])
        self.assertEqual(util.artifact_hash(self.seed), snapshot['artifact_sha256'])
        self.assertIn('store.sqlite', snapshot['excluded_files'])
        frozen = self.runs / manifest['run_id'] / 'frozen'
        self.assertFalse((frozen / 'MusicStore.Web' / 'bin').exists())
        self.assertIn('bin', snapshot['excluded_directories'])

    def test_exclusions_cover_the_evaluator_exclusions(self):
        for name in ('bin', 'obj', '.git'):
            self.assertIn(name, util.EXCLUDED_DIRECTORIES)


class UsageLinkTests(HarnessTestCase):
    def collect_scenario(self, scenario):
        manifest = self.create()
        self.start(manifest['run_id'], scenario=scenario)
        run_mod.collect_run(self.runs, manifest['run_id'])
        return util.read_json(self.runs / manifest['run_id'] / 'usage' / 'normalized.json')

    def test_complete_usage(self):
        usage = self.collect_scenario('ok')
        self.assertEqual('complete', usage['state'])
        self.assertEqual(7420, usage['total_tokens'])
        self.assertEqual(usage['total_tokens'], usage['observed_tokens'])
        self.assertEqual(4, usage['observed_request_count'])

    def test_no_usage_is_not_zero(self):
        usage = self.collect_scenario('no-usage')
        self.assertEqual('missing', usage['state'])
        self.assertIsNone(usage['total_tokens'])
        self.assertEqual(0, usage['observed_tokens'])

    def test_partial_usage_is_missing(self):
        usage = self.collect_scenario('partial-usage')
        self.assertEqual('missing', usage['state'])
        self.assertIsNone(usage['total_tokens'])
        self.assertGreater(usage['observed_tokens'], 0)

    def test_conflicting_events_are_rejected(self):
        usage = self.collect_scenario('conflict-usage')
        self.assertEqual('missing', usage['state'])
        self.assertIsNone(usage['total_tokens'])
        self.assertIn('usage_events_rejected', usage['error'])

    def test_cumulative_and_request_modes_can_coexist_across_sessions(self):
        usage = self.collect_scenario('cumulative-usage')
        self.assertEqual('complete', usage['state'])
        self.assertEqual(7420, usage['total_tokens'])
        self.assertEqual(['session-main'], usage['cumulative_sessions'])

    def test_missing_usage_ids_are_recorded(self):
        usage = self.collect_scenario('no-usage-id')
        self.assertEqual('missing', usage['state'])
        self.assertIsNone(usage['total_tokens'])

    def test_missing_provenance_is_recorded(self):
        usage = self.collect_scenario('no-provenance')
        self.assertEqual('missing', usage['state'])
        self.assertEqual('usage_provenance_missing', usage['error'])

    def test_raw_usage_is_kept_unchanged(self):
        manifest = self.create()
        self.start(manifest['run_id'])
        run_mod.collect_run(self.runs, manifest['run_id'])
        raw = self.runs / manifest['run_id'] / 'usage' / 'raw' / 'usage-dump.json'
        self.assertTrue(raw.is_file())
        self.assertEqual('complete',
                         util.read_json(self.runs / manifest['run_id'] / 'usage'
                                        / 'normalized.json')['state'])


class AggregateTests(HarnessTestCase):
    def test_unscored_runs_stay_in_the_table(self):
        ok = self.create()
        self.start(ok['run_id'])
        run_mod.collect_run(self.runs, ok['run_id'])
        table = aggregate.build(self.runs)
        self.assertEqual(1, table['run_count'])
        row = table['runs'][0]
        self.assertEqual('not_attempted', row['scoring']['state'])
        self.assertIsNone(row['quality'])
        self.assertIsNone(row['verdict'])
        self.assertEqual('complete', row['usage']['state'])
        kinds = [issue['kind'] for issue in row['issues']]
        self.assertIn('not_scored', kinds)
        self.assertIn('synthetic', kinds)

    def test_failed_and_missing_runs_stay_in_the_table(self):
        good = self.create(attempt=1)
        self.start(good['run_id'])
        run_mod.collect_run(self.runs, good['run_id'])
        bad = self.create(attempt=2)
        self.start(bad['run_id'], scenario='crash')
        run_mod.collect_run(self.runs, bad['run_id'])
        table = aggregate.build(self.runs)
        self.assertEqual(2, table['run_count'])
        states = {row['run_id']: row['execution']['state'] for row in table['runs']}
        self.assertEqual('completed', states[good['run_id']])
        self.assertEqual('agent_error', states[bad['run_id']])
        bad_row = [row for row in table['runs'] if row['run_id'] == bad['run_id']][0]
        self.assertIn('execution', [issue['kind'] for issue in bad_row['issues']])
        self.assertIsNone(bad_row['quality'])

    def test_unstarted_run_is_not_started_state(self):
        manifest = self.create()
        table = aggregate.build(self.runs)
        row = table['runs'][0]
        self.assertEqual('not_started', row['execution']['state'])
        self.assertEqual('not_fixed', row['artifact']['state'])
        self.assertIsNone(row['usage']['total_tokens'])
        self.assertIn('usage', [issue['kind'] for issue in row['issues']])

    def test_aggregate_reads_saved_materials_only(self):
        manifest = self.create()
        self.start(manifest['run_id'])
        run_mod.collect_run(self.runs, manifest['run_id'])
        before = util.sha256_file(self.runs / manifest['run_id'] / 'snapshot.json')
        aggregate.build(self.runs)
        self.assertEqual(before, util.sha256_file(self.runs / manifest['run_id'] / 'snapshot.json'))
        self.assertFalse((self.runs / manifest['run_id'] / 'evaluations').exists())


if __name__ == '__main__':
    unittest.main()

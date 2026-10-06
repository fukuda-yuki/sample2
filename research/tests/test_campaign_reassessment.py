"""Bounded non-model same-version recovery tests; Docker/importer are mocked."""
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from outer.harness import browser_cleanup, browser_prerequisite, util
from research import campaign_reassessment as recovery


class CampaignReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = Path(recovery.__file__).resolve().parents[1]
        self.rid, self.instance = 'MS1-CONT-A-explore-6001', 'a'*32
        self.source = self.base/'batch/pair-1'/self.rid
        for name in ('frozen/bin', 'frozen/obj', 'evaluation-assets/evaluator', 'inputs', 'profiles',
                     'usage', 'evidence', 'telemetry'):
            (self.source/name).mkdir(parents=True, exist_ok=True)
        for name in ('frozen/app.cs', 'frozen/bin/old.bin', 'frozen/obj/cache', 'db.sqlite-wal', 'db.sqlite-shm'):
            (self.source/name).write_bytes(b'original '+name.encode())
        (self.source/'telemetry/monitor.db').write_bytes(b'preserve original failed monitor bytes')
        (self.source/'controller.lock').write_bytes(b'0')
        (self.source.parent/'_control').mkdir()
        (self.source.parent/'_control/dispatch.lock').write_bytes(b'0')
        (self.source/'STOP').write_text('original acquisition stop; preserve')
        (self.source/'evaluation-assets/evaluator/Evaluator.dll').write_bytes(b'accepted same version binary')
        util.write_new_json(self.source/'evaluation-assets/requirements.json',
            dict(taskId='MS1-CONT-A', specVersion='1.6.0', requirements=[]))
        util.write_new_json(self.source/'evaluation-assets/catalog.json', {})
        self.condition = dict(schema_version=2, task_id='MS1-CONT-A',
            runtime={'id': 'deepseek-music-repaired-v1'}, runtime_lock={'fixed': True},
            evaluation=dict(assembly='Evaluator.dll', evaluation_version='1.6.0',
                evaluator_sha256=util.sha256_file(self.source/'evaluation-assets/evaluator/Evaluator.dll'),
                spec_sha256=util.sha256_file(self.source/'evaluation-assets/requirements.json')))
        util.write_new_json(self.source/'condition.json', self.condition)
        util.write_new_json(self.source/'context.json', {'fixed': True})
        self.manifest = dict(schema_version=2, run_id=self.rid, run_instance_id=self.instance,
            stop_confirmed=True, submission_fixed=True, task_id='MS1-CONT-A', attempt=6001,
            condition_sha256=util.sha256_file(self.source/'condition.json'), input_files={}, profile_files={},
            assets_sha256=util.tree_hashes(self.source/'evaluation-assets'),
            context_sha256=util.sha256_file(self.source/'context.json'))
        util.write_new_json(self.source/'manifest.json', self.manifest)
        util.write_new_json(self.source/'snapshot.json', dict(run_id=self.rid,
            artifact_sha256=util.artifact_hash(self.source/'frozen')))
        self.events = [dict(request_id='request-1', model_id='deepseek-v4.1-flash', session_id=self.instance,
            started_at='2026-10-06T13:00:00+00:00', ended_at='2026-10-06T13:00:01+00:00',
            status='completed', usage=dict(input_tokens=9, output_tokens=4))]
        util.append_line(self.source/'usage/events.jsonl', self.events[0])
        util.write_new_json(self.source/'usage/normalized.json', {'usage_complete': True})
        util.write_new_json(self.base/'lock.json', self.condition['runtime_lock'])
        util.write_new_json(self.base/'browser.json', {})
        self.case = dict(task='MS1-CONT-A', pair=1, slot=1, condition='explore', attempt=6001,
                         run_id=self.rid, run_instance_id=self.instance)
        self.plan = dict(assignments=[dict(pair=1, cases=[self.case])], batch=str(self.base/'batch'),
            protected_roots=[str(self.base/'old')], browser_pin=recovery.live_pilot.reference(self.base/'browser.json'),
            runtime_locks={'deepseek-music-repaired-v1': recovery.live_pilot.reference(self.base/'lock.json')})
        util.write_new_json(self.base/'plan.json', self.plan)
        self.ref = recovery.live_pilot.reference(self.base/'plan.json')
        self.binding = dict(self.case, plan_sha256=self.ref['sha256'])
        util.write_new_json(self.source.parent/'phase.json', {'expected': 'child-phase'})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.verify = self.stack.enter_context(patch.object(recovery.acquisition_readiness, 'verify_main_phase', return_value=self.plan))
        self.readiness = self.stack.enter_context(patch.object(recovery.acquisition_readiness, 'readiness_for_main', return_value=True))
        self.stack.enter_context(patch.object(recovery.live_pilot, 'observer_phase', return_value={'expected': 'child-phase'}))
        self.journal = self.stack.enter_context(patch.object(recovery.pair_execution, 'state',
            return_value={'dispatch': {self.rid: self.binding}, 'implementations': {self.rid: {'fixed': True}}}))
        self.terminal = self.stack.enter_context(patch.object(recovery.live_pilot, 'validate_owned_terminal',
            return_value={'run_id': self.rid, 'run_instance_id': self.instance, 'native_session_id': 'native-1'}))
        self.stack.enter_context(patch.object(recovery.evaluate, 'validate_repaired_scoring_provenance', return_value=True))
        self.stack.enter_context(patch.object(recovery.catalog_environment, 'activated', side_effect=lambda *a: nullcontext()))
        self.stack.enter_context(patch.object(recovery.saved.runtime, 'scoring_command',
            return_value=('s2-score-'+'2'*32, ['docker', 'run', 'mock'])))
        # No accidental model or real Docker operation is possible in this suite.
        self.docker = self.stack.enter_context(patch.object(recovery.saved.runtime, 'docker',
            return_value=SimpleNamespace(stdout='', returncode=0)))
        self.stack.enter_context(patch.object(recovery.browser_review, 'http_phase_eligible', return_value=True))
        self.coverage = self.stack.enter_context(patch.object(recovery.browser_review, 'coverage_complete', return_value=True))
        self.stored = self.stack.enter_context(patch.object(recovery.browser_review, 'stored_coverage_complete', return_value=True))
        self.stack.enter_context(patch.object(recovery.browser_review, 'stored_failure', return_value={'requirements': ['R-001']}))
        self.stack.enter_context(patch.object(browser_cleanup, 'cleanup', side_effect=self.cleanup))
        self.runner = self.stack.enter_context(patch.object(recovery.evaluate, 'run_evaluator', side_effect=self.http))
        self.composer = self.stack.enter_context(patch.object(recovery.browser_review, 'complete_evaluation', side_effect=self.compose))
        self.importer = self.stack.enter_context(patch.object(recovery.monitor, 'link', side_effect=self.monitor))
        self.before = recovery.saved.byte_inventory(self.source)
        self.quality = 0
        self.faults = []
        self.product_prerequisite = False

    def prepare(self):
        ref = recovery.prepare(repo=self.repo, source=self.source, destination=self.base/'assessments', main_plan_ref=self.ref)
        self.stage = Path(ref['path']).parent
        self.a = util.read_json(ref['path'])
        return ref

    def cleanup(self, out, **kwargs):
        state = util.read_json(Path(out)/'browser-resources.json')
        receipt = dict(owner=state['owner'], run_instance_id=state['run_instance_id'], confirmed=True,
            status='complete', resources=[dict(r, confirmed=True, status='absent') for r in state['resources']])
        util.append_line(Path(out)/'browser-cleanup-attempts/index.jsonl', receipt)
        return receipt

    def output(self):
        return dict(taskId=self.condition['task_id'], artifactPath='/artifact',
            artifactSha256=self.a['source_artifact_sha256'], specSha256=self.a['new_spec_sha256'],
            evaluationVersion=self.a['evaluation_version'], researchStatus='complete', quality=self.quality,
            verdict='fail_critical', evaluatorFaults=self.faults, reviewRunInstanceId=self.a['assessment_id'])

    def http(self, command, repo, environment, stdout, stderr, timeout):
        self.assertNotIn('OPENCODE_GO_API_KEY', environment)
        self.assertLessEqual(timeout, 1800)
        self.assertIn('sample2.assessment='+self.a['assessment_id'], command)
        directory = self.stage/'output/http-only'
        output = self.output()
        requirement, check = ('R-001', 'C-001') if self.a['evaluation_version'] == '1.6.0' else ('EDU-R-001', 'E-001')
        if self.product_prerequisite:
            output.update(quality=None, researchStatus='incomplete', requirements=[{'id': requirement, 'judgement': 'fail'}])
        util.write_new_json(directory/'evaluation.json', output)
        util.append_line(directory/'results.jsonl', {'requirementId': requirement, 'checkId': check, 'judgement': 'fail'})
        util.write_new_json(directory/'evaluator-manifest.json', {'evaluatorSha256': self.a['evaluator_sha256']})
        return 2 if self.a['evaluation_version'] == '1.6.0' else 0, False

    def compose(self, repo, condition, frozen, http, work, assets, out, instance, sequence):
        self.assertEqual(instance, self.a['assessment_id'])
        if self.product_prerequisite:
            requirement, check, coverage = (('R-001', 'C-001', 'browserCartCoverage')
                if self.a['evaluation_version'] == '1.6.0' else ('EDU-R-001', 'E-001', 'browserReviewCoverage'))
            self.assertTrue(browser_prerequisite.save_if_unpublished(condition, frozen, http, work, assets, out,
                instance, version=self.a['evaluation_version'], requirement_id=requirement,
                build_check=check, coverage_field=coverage))
            util.write_new_json(out/'browser-intent.json', dict(run_instance_id=instance,
                artifact_sha256=self.a['source_artifact_sha256'], spec_sha256=self.a['new_spec_sha256'],
                baseline_evaluation_sha256=util.sha256_file(http/'evaluation.json'),
                baseline_results_sha256=util.sha256_file(http/'results.jsonl'),
                coverage='not_run_product_prerequisite', model_called=False, actor='agent'))
            util.write_new_json(out/'browser-cleanup.json', dict(confirmed=True, status='no_resources_created'))
            return 0
        value = self.output()
        value.update(baselineEvaluationSha256=util.sha256_file(http/'evaluation.json'),
                     baselineResultsSha256=util.sha256_file(http/'results.jsonl'))
        util.write_new_json(out/'evaluation.json', value)
        util.write_new_json(out/'evaluator-manifest.json', {'evaluatorSha256': self.a['evaluator_sha256']})
        browser_cleanup.register(out, instance, 'container', 's2-browser-'+'3'*32)
        self.cleanup(out)
        return 0

    def monitor(self, repo, root):
        root = Path(root)
        self.assertEqual(root.name, self.rid)
        self.assertEqual(util.read_json(root/'manifest.json')['run_instance_id'], self.instance)
        directory = root/'telemetry'
        directory.mkdir()
        payload = recovery.monitor.payload(self.events, self.rid, self.manifest)
        util.write_new_json(directory/'gateway.otlp.json', payload)
        db = sqlite3.connect(directory/'monitor.db')
        try:
            db.execute('CREATE TABLE raw_records(id INTEGER, payload_json TEXT)')
            db.execute('INSERT INTO raw_records VALUES(1, ?)', (json.dumps(payload),))
            db.commit()
        finally:
            db.close()
        totals = recovery.monitor.usage_totals(self.events)
        util.write_new_json(directory/'normalized-readback.json', [dict(experiment_id=self.rid, turn_count=1,
            **{key: value['observed'] for key, value in totals.items()})])
        link = dict(verified=True, usage_complete=True, request_count=1, usage_totals=totals,
            raw_sha256=util.sha256_file(directory/'gateway.otlp.json'), raw_record_ids=[1])
        util.write_new_json(root/'telemetry-link.json', link)
        return link

    def execute(self, ref):
        return recovery.execute(repo=self.repo, assessment_ref=ref, main_plan_ref=self.ref, timeout=10)

    def test_complete_copy_same_version_and_finite_failure_adopted(self):
        ref = self.prepare()
        self.assertEqual(self.a['evaluation_version'], self.a['source_evaluation_version'])
        self.assertNotEqual(self.a['assessment_id'], self.instance)
        self.assertEqual(self.a['source_run_id'], self.rid)
        self.assertEqual(recovery.saved.byte_inventory(Path(self.a['derivative_path_private'])), self.before)
        self.assertFalse((self.stage/'STOP').exists())
        result_ref = self.execute(ref)
        result = recovery.revalidate(repo=self.repo, result_ref=result_ref, main_plan_ref=self.ref)
        self.assertTrue(result['adopted'])
        self.assertEqual(result['quality'], 0)
        self.assertEqual(result['validation']['raw_verdict'], 'fail_critical')
        self.assertEqual(result['acquisition_count_increment'], 0)
        self.assertEqual(result['model_calls'], 0)
        self.assertFalse(result['resend_authorized'])
        self.assertEqual(recovery.saved.byte_inventory(self.source), self.before)
        self.assertEqual(recovery.saved.byte_inventory(Path(self.a['derivative_path_private'])), self.before)
        self.verify.assert_called()
        self.readiness.assert_called()
        self.assertTrue(any(call.kwargs.get('observe_resources') is True for call in self.terminal.call_args_list))
        self.assertTrue(all(call.args[0] in ('ps', 'network') for call in self.docker.call_args_list))

    def test_same_education_version(self):
        self.case['task'] = self.binding['task'] = self.condition['task_id'] = 'CU1-ENR-C'
        self.condition['evaluation']['evaluation_version'] = 'education-1.1.0'
        util.write_json_atomic(self.source/'condition.json', self.condition)
        self.manifest['condition_sha256'] = util.sha256_file(self.source/'condition.json')
        util.write_json_atomic(self.source/'manifest.json', self.manifest)
        self.before = recovery.saved.byte_inventory(self.source)
        ref = self.prepare()
        result = util.read_json(self.execute(ref)['path'])
        self.assertTrue(result['adopted'])
        self.assertEqual(self.a['evaluation_version'], 'education-1.1.0')

    def test_attempt_cannot_execute_twice(self):
        ref = self.prepare()
        self.execute(ref)
        with self.assertRaises(FileExistsError):
            self.execute(ref)
        self.assertEqual(self.runner.call_count, 1)

    def test_source_change_after_preparation_rejected_before_scoring(self):
        ref = self.prepare()
        (self.source/'db.sqlite-wal').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.execute(ref)
        self.runner.assert_not_called()

    def test_copy_change_or_wrong_plan_rejected(self):
        ref = self.prepare()
        root = Path(self.a['derivative_path_private'])
        (root/'frozen/bin/old.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.execute(ref)
        self.runner.assert_not_called()
        with self.assertRaises(ValueError):
            recovery.execute(repo=self.repo, assessment_ref=ref, main_plan_ref={'path': self.ref['path'], 'sha256': '0'*64})

    def test_unknown_transmission_and_unconfirmed_stop_held(self):
        self.journal.return_value = {'dispatch': {}, 'implementations': {}}
        report = recovery.classify(repo=self.repo, source=self.source, main_plan_ref=self.ref)
        self.assertEqual(report['classification'], 'held_unresolved_evidence')
        self.assertFalse(report['recoverable'])
        self.assertFalse(report['resend_authorized'])
        with self.assertRaises(ValueError):
            self.prepare()
        self.journal.return_value = {'dispatch': {self.rid: self.binding}, 'implementations': {self.rid: {}}}
        self.terminal.side_effect = ValueError('Owned terminal stop unconfirmed')
        report = recovery.classify(repo=self.repo, source=self.source, main_plan_ref=self.ref)
        self.assertEqual(report['classification'], 'held_unresolved_evidence')
        self.assertFalse((self.base/'assessments').exists())

    def test_live_source_lease_held(self):
        with recovery._existing_lock(self.source/'controller.lock'):
            report = recovery.classify(repo=self.repo, source=self.source, main_plan_ref=self.ref)
            self.assertEqual(report['classification'], 'held_unresolved_evidence')
        self.assertFalse((self.base/'assessments').exists())

    def test_orphaned_http_scorer_holds_without_guessing_owner(self):
        self.docker.return_value = SimpleNamespace(stdout='s2-score-'+'9'*32, returncode=0)
        report = recovery.classify(repo=self.repo, source=self.source, main_plan_ref=self.ref)
        self.assertEqual(report['classification'], 'held_unresolved_evidence')
        self.assertFalse(report['recoverable'])
        self.runner.assert_not_called()

    def test_no_reassessment_for_normal_low_quality_source(self):
        ref = self.prepare()
        out = self.source/'evaluations/normal'
        out.mkdir(parents=True)
        value = self.output()
        value['reviewRunInstanceId'] = self.instance
        util.write_new_json(out/'evaluation.json', value)
        util.write_new_json(out/'evaluator-manifest.json', {'evaluatorSha256': self.a['evaluator_sha256']})
        util.append_line(self.source/'evaluations/index.jsonl', {'directory': 'evaluations/normal', 'scoring_state': 'scored',
            'evaluation_sha256': util.sha256_file(out/'evaluation.json')})
        diagnosis = recovery.classify(repo=self.repo, source=self.source, main_plan_ref=self.ref)
        self.assertEqual(diagnosis['classification'], 'already_evaluable')
        self.assertEqual(diagnosis['quality'], 0)
        with self.assertRaisesRegex(ValueError, 'quality does not justify'):
            self.prepare()
        self.runner.assert_not_called()

    def test_numeric_quality_with_observer_fault_not_adopted(self):
        self.faults = ['observer missing assertion']
        ref = self.prepare()
        result = util.read_json(self.execute(ref)['path'])
        self.assertFalse(result['adopted'])
        self.assertEqual(result['validation']['validation_status'], 'observer_fault')
        self.assertIsNone(result['quality'])
        self.assertIsNotNone(result['archive'])

    def test_nonfinite_bool_or_out_of_range_quality_not_adopted(self):
        for value in (float('nan'), float('inf'), True, -1, 101):
            with self.subTest(value=value):
                self.quality = value
                ref = self.prepare()
                result = util.read_json(self.execute(ref)['path'])
                self.assertFalse(result['adopted'])
                self.assertIsNone(result['quality'])

    def test_missing_browser_or_foreign_cleanup_not_adopted(self):
        ref = self.prepare()
        self.stored.return_value = False
        result = util.read_json(self.execute(ref)['path'])
        self.assertFalse(result['adopted'])
        self.stored.return_value = True
        ref = self.prepare()
        with patch.object(recovery.saved, '_saved_cleanup_bound', return_value=False):
            result = util.read_json(self.execute(ref)['path'])
        self.assertFalse(result['adopted'])
        self.assertEqual(result['validation']['validation_status'], 'invalid_evidence')

    def test_monitor_fault_retained_without_invented_usage(self):
        ref = self.prepare()
        self.importer.side_effect = RuntimeError('Importer unavailable')
        result = util.read_json(self.execute(ref)['path'])
        self.assertFalse(result['adopted'])
        self.assertIsNone(result['monitor'])
        self.assertIsNotNone(result['archive'])
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertEqual(recovery.saved.byte_inventory(self.source), self.before)

    def test_changed_saved_result_or_archive_refused(self):
        ref = self.prepare()
        result_ref = self.execute(ref)
        (self.stage/'output/evaluation.json').write_text('{}')
        with self.assertRaises(ValueError):
            recovery.revalidate(repo=self.repo, result_ref=result_ref, main_plan_ref=self.ref)

    def test_foreign_source_path_and_protected_destination_refused(self):
        with self.assertRaises(ValueError):
            recovery.prepare(repo=self.repo, source=self.source, destination=self.base/'batch/new', main_plan_ref=self.ref)
        self.plan['assignments'][0]['cases'][0]['run_id'] = 'foreign-run'
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.base/'assessments').exists())

    def test_unconfirmed_source_browser_cleanup_refused(self):
        out = self.source/'evaluations/partial'
        out.mkdir(parents=True)
        browser_cleanup.register(out, self.instance, 'container', 's2-browser-'+'4'*32)
        with self.assertRaisesRegex(ValueError, 'ownership remains unresolved'):
            self.prepare()
        self.runner.assert_not_called()

    def test_campaign_child_uses_campaign_readiness_authority(self):
        from research import repaired_campaign
        util.write_new_json(self.base/'campaign.json', {'fixed': 'campaign-authority'})
        self.plan['campaign_authority'] = recovery.live_pilot.reference(self.base/'campaign.json')
        with patch.object(repaired_campaign, 'validate_readiness', create=True, return_value=True) as ready:
            self.prepare()
        ready.assert_called_once_with(self.repo, self.base/'campaign.json')
        self.readiness.assert_not_called()

    def test_forged_adoption_and_monitor_usage_tampering_refused(self):
        ref = self.prepare()
        result_ref = self.execute(ref)
        path = Path(result_ref['path'])
        result = util.read_json(path)
        result['quality'] = 100
        util.write_json_atomic(path, result)
        with self.assertRaisesRegex(ValueError, 'adoption is not reproducible'):
            recovery.revalidate(repo=self.repo, result_ref=recovery.live_pilot.reference(path), main_plan_ref=self.ref)
        monitor_root = self.stage.parent/'monitor'/self.rid
        (monitor_root/'usage/events.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'Monitor source'):
            recovery.revalidate(repo=self.repo, result_ref=recovery.live_pilot.reference(path), main_plan_ref=self.ref)

    def test_timeout_and_cleanup_fault_archive_raw_evidence(self):
        ref = self.prepare()
        self.runner.side_effect = lambda *args: (2, True)
        with patch.object(browser_cleanup, 'cleanup', side_effect=RuntimeError('cleanup unconfirmed')):
            result = util.read_json(self.execute(ref)['path'])
        self.assertFalse(result['adopted'])
        self.assertIsNotNone(result['archive'])
        self.assertEqual(util.read_json(self.stage/'result.json')['operation_status'], 'cleanup_unconfirmed')
        self.assertEqual(recovery.saved.byte_inventory(self.source), self.before)

    def test_archive_corruption_refused(self):
        ref = self.prepare()
        result_ref = self.execute(ref)
        result = util.read_json(result_ref['path'])
        archived = self.stage.parent/'archive/packages'/result['archive']['package_id']/'payload/run/db.sqlite-wal'
        archived.write_bytes(b'corruption')
        with self.assertRaises(ValueError):
            recovery.revalidate(repo=self.repo, result_ref=result_ref, main_plan_ref=self.ref)

    def test_product_build_failure_is_valid_evidence_not_technical_replacement(self):
        self.prepare()
        out = self.source/'evaluations/product-build-failure'
        http = out/'http-only'
        http.mkdir(parents=True)
        baseline = self.output()
        baseline.update(quality=None, researchStatus='incomplete', requirements=[{'id': 'R-001', 'judgement': 'fail'}])
        util.write_new_json(http/'evaluation.json', baseline)
        util.append_line(http/'results.jsonl', {'requirementId': 'R-001', 'checkId': 'C-001', 'judgement': 'fail'})
        for directory in (out, http):
            util.write_new_json(directory/'evaluator-manifest.json', {'evaluatorSha256': self.a['evaluator_sha256']})
        value = dict(baseline, reviewRunInstanceId=self.instance,
            browserCartCoverage='not_run_product_prerequisite',
            baselineEvaluationSha256=util.sha256_file(http/'evaluation.json'),
            baselineResultsSha256=util.sha256_file(http/'results.jsonl'))
        util.write_new_json(out/'evaluation.json', value)
        util.write_new_json(out/'browser-product-prerequisite.json', dict(run_instance_id=self.instance,
            artifact_sha256=self.a['source_artifact_sha256'], spec_sha256=self.a['new_spec_sha256'],
            evaluation_version='1.6.0', evaluator_sha256=self.a['evaluator_sha256'],
            status='not_run_product_prerequisite', published_application_established=False,
            model_called=False, browser_observed=False, requirement_id='R-001', build_check='C-001',
            baseline_evaluation_sha256=value['baselineEvaluationSha256'], baseline_results_sha256=value['baselineResultsSha256']))
        util.append_line(self.source/'evaluations/index.jsonl', dict(directory='evaluations/product-build-failure',
            scoring_state='evaluation_incomplete', evaluation_sha256=util.sha256_file(out/'evaluation.json')))
        result = recovery.classify(repo=self.repo, source=self.source, main_plan_ref=self.ref)
        self.assertEqual(result['classification'], 'normal_product_failure_partial_observation')
        self.assertTrue(result['valid_product_failure'])
        self.assertFalse(result['quality_observed_complete'])
        self.assertFalse(result['recoverable'])
        self.assertFalse(result['resend_authorized'])
        self.assertIsNone(result['quality'])
        with self.assertRaises(ValueError):
            self.prepare()

    def test_reassessment_product_failure_is_valid_same_attempt_not_numeric_adoption(self):
        self.product_prerequisite = True
        ref = self.prepare()
        result_ref = self.execute(ref)
        result = recovery.revalidate(repo=self.repo, result_ref=result_ref, main_plan_ref=self.ref)
        self.assertTrue(result['valid_product_failure'])
        self.assertFalse(result['adopted'])
        self.assertFalse(result['quality_observed_complete'])
        self.assertEqual(result['classification'], 'normal_product_failure_partial_observation')
        self.assertIsNone(result['quality'])
        self.assertEqual(result['source_run_instance_id'], self.instance)
        self.assertEqual(result['source_run_id'], self.rid)
        self.assertEqual(result['model_calls'], 0)
        recovery.live_pilot.checked(result['prerequisite_evidence'])
        self.assertEqual(recovery.saved.byte_inventory(self.source), self.before)

    def test_education_reassessment_product_failure_is_valid_with_null_quality(self):
        self.case['task'] = self.binding['task'] = self.condition['task_id'] = 'CU1-ENR-C'
        self.condition['evaluation']['evaluation_version'] = 'education-1.1.0'
        util.write_json_atomic(self.source/'condition.json', self.condition)
        self.manifest['condition_sha256'] = util.sha256_file(self.source/'condition.json')
        util.write_json_atomic(self.source/'manifest.json', self.manifest)
        self.product_prerequisite = True
        ref = self.prepare()
        result_ref = self.execute(ref)
        result = recovery.revalidate(repo=self.repo, result_ref=result_ref, main_plan_ref=self.ref)
        self.assertTrue(result['valid_product_failure'])
        self.assertFalse(result['adopted'])
        self.assertIsNone(result['quality'])

    def test_reassessment_product_failure_requires_monitor_and_bound_prerequisite(self):
        self.product_prerequisite = True
        ref = self.prepare()
        self.importer.side_effect = RuntimeError('monitor unavailable')
        result = util.read_json(self.execute(ref)['path'])
        self.assertFalse(result['valid_product_failure'])
        self.assertFalse(result['adopted'])
        self.importer.side_effect = self.monitor
        ref = self.prepare()
        result_ref = self.execute(ref)
        evidence = self.stage/'output/browser-product-prerequisite.json'
        raw = util.read_json(evidence)
        raw['run_instance_id'] = 'f'*32
        util.write_json_atomic(evidence, raw)
        with self.assertRaises(ValueError):
            recovery.revalidate(repo=self.repo, result_ref=result_ref, main_plan_ref=self.ref)
        self.assertFalse(recovery._validation(self.stage, self.a)['valid_product_failure'])

    def test_forged_valid_product_failure_flag_rejected_on_numeric_or_fault_outcome(self):
        ref = self.prepare()
        result_ref = self.execute(ref)
        path = Path(result_ref['path'])
        result = util.read_json(path)
        result.update(adopted=False, valid_product_failure=True, quality=None, quality_observed_complete=False,
            classification='normal_product_failure_partial_observation')
        util.write_json_atomic(path, result)
        with self.assertRaises(ValueError):
            recovery.revalidate(repo=self.repo, result_ref=recovery.live_pilot.reference(path), main_plan_ref=self.ref)


if __name__ == '__main__':
    unittest.main()

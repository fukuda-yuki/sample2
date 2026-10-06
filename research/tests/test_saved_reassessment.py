"""No model calls: reassessment must preserve acquisition and earlier scores."""
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from outer.harness import util
from research import saved_reassessment as reassess


class SavedReassessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'original'
        (self.source / 'frozen').mkdir(parents=True)
        (self.source / 'frozen/app.cs').write_text('original product')
        (self.source / 'evaluation-assets/evaluator').mkdir(parents=True)
        (self.source / 'evaluation-assets/evaluator/Old.dll').write_bytes(b'old binary')
        self.spec = {'taskId': 'EDU', 'specVersion': 'education-1.0.0',
                     'requirements': [{'id': 'R-001', 'checks': [{'id': 'E-001'}]}]}
        util.write_new_json(self.source / 'evaluation-assets/requirements.json', self.spec)
        util.write_new_json(self.source / 'evaluation-assets/catalog.json', {})
        self.original_hash = util.artifact_hash(self.source / 'frozen')
        util.write_new_json(self.source / 'snapshot.json', {'run_id': 'EDU-explore-1', 'artifact_sha256': self.original_hash})
        util.write_new_json(self.source / 'condition.json', {'schema_version': 2, 'task_id': 'EDU',
            'evaluation': {'assembly': 'Old.dll', 'evaluation_version': 'education-1.0.0',
                'spec_sha256': util.sha256_file(self.source/'evaluation-assets/requirements.json')},
            'runtime_lock': {'images': {'evaluator': 'sha256:dummy'}}})
        util.write_new_json(self.source / 'manifest.json', {'run_id': 'EDU-explore-1',
            'condition_sha256': util.sha256_file(self.source/'condition.json'),
            'assets_sha256': util.tree_hashes(self.source/'evaluation-assets'),
            'input_files': {}, 'profile_files': {},
            'context_sha256': util.sha256_file(self.source/'condition.json'),
            'run_instance_id': 'a' * 32, 'stop_confirmed': True, 'submission_fixed': True})
        (self.source/'context.json').write_bytes((self.source/'condition.json').read_bytes())
        (self.source/'inputs').mkdir(); (self.source/'profiles').mkdir()
        (self.source / 'evaluations').mkdir()
        (self.source / 'evaluations/index.jsonl').write_text('{"old": "score"}\n')
        self.bundle = self.root / 'new-build'; self.bundle.mkdir()
        (self.bundle / 'New.dll').write_bytes(b'new binary')
        self.new_spec = self.root / 'requirements-new.json'
        util.write_new_json(self.new_spec, {**self.spec, 'specVersion': 'education-1.1.0'})
        self.before = reassess.byte_inventory(self.source)

    def prepare(self, **changes):
        args = dict(source=self.source, destination=self.root/'assessments',
            evaluator_bundle=self.bundle, assembly='New.dll', spec=self.new_spec,
            evaluation_version='education-1.1.0', repair_contract='calendar-date-v1')
        args.update(changes)
        return reassess.prepare(**args)

    def test_new_assessment_identity_without_new_acquisition(self):
        stage = self.prepare(); record = util.read_json(stage/'assessment.json')
        self.assertEqual(record['kind'], 'saved_artifact_reassessment')
        self.assertEqual(record['source_run_instance_id'], 'a'*32)
        self.assertNotEqual(record['assessment_id'], record['source_run_instance_id'])
        self.assertEqual(record['acquisition_count_increment'], 0)
        self.assertEqual(reassess.byte_inventory(self.source), self.before)
        self.assertEqual(util.artifact_hash(stage/'frozen'), self.original_hash)

    def test_source_contamination_and_nonstopped_refused_before_output(self):
        with self.assertRaises(ValueError): self.prepare(destination=self.source/'assessments')
        (self.source/'frozen/app.cs').write_text('changed')
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse((self.root/'assessments').exists())

    def test_requirement_changes_and_same_version_refused(self):
        with self.assertRaises(ValueError): self.prepare(evaluation_version='education-1.0.0')
        util.write_json_atomic(self.new_spec, {**self.spec, 'specVersion': 'education-1.1.0', 'requirements': []})
        with self.assertRaises(ValueError): self.prepare()

    def test_partial_and_cleanup_failure_keep_original_and_raw_result(self):
        stage = self.prepare()
        def fake_run(command, repo, environment, out, err, timeout):
            self.assertNotIn('OPENCODE_GO_API_KEY', environment)
            self.assertLessEqual(timeout, 1800)
            util.write_new_json(stage/'output/http-only/evaluation.json', {
                'taskId': 'EDU', 'artifactPath': '/artifact', 'artifactSha256': self.original_hash,
                'specSha256': util.sha256_file(stage/'evaluation-assets/requirements.json'),
                'evaluationVersion': 'education-1.1.0', 'quality': None,
                'researchStatus': 'incomplete', 'verdict': 'fail_critical'})
            return 2, False
        name = 's2-score-' + '2'*32
        with patch.object(reassess.runtime, 'scoring_command', return_value=(name, ['docker', 'run', '--name', name, 'dummy'])), \
             patch.object(reassess.evaluate, 'run_evaluator', side_effect=fake_run), \
             patch.object(reassess.browser_cleanup, 'cleanup', side_effect=RuntimeError('cleanup failed')):
            result = reassess.execute(stage, repo=Path(reassess.__file__).resolve().parents[1])
        self.assertEqual(result['operation_status'], 'cleanup_unconfirmed')
        self.assertFalse(result['adopted'])
        self.assertEqual(result['raw_verdict'], 'fail_critical')
        self.assertTrue((stage/'output/http-only/evaluation.json').is_file())
        self.assertEqual(reassess.byte_inventory(self.source), self.before)
        with self.assertRaises(FileExistsError): reassess.execute(stage, repo=Path(reassess.__file__).resolve().parents[1])

    def test_output_wrong_identity_and_stop_do_not_become_pass(self):
        stage = self.prepare(); (stage/'STOP').write_text('stop')
        with patch.object(reassess.evaluate, 'run_evaluator') as runner:
            result = reassess.execute(stage, repo=Path(reassess.__file__).resolve().parents[1])
        runner.assert_not_called()
        self.assertEqual(result['operation_status'], 'stopped_before_execution')
        self.assertFalse(result['adopted'])
        self.assertEqual(reassess.byte_inventory(self.source), self.before)

    def test_corrupted_original_oracle_or_catalog_is_not_pinned_as_valid(self):
        (self.source/'evaluation-assets/catalog.json').write_text('{"corrupt":true}')
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse((self.root/'assessments').exists())

    def run_fake(self, stage, fake_run, **extra_patches):
        name = 's2-score-'+'2'*32
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(reassess.runtime, 'scoring_command',
                return_value=(name, ['docker','run','--name',name,'dummy'])))
            stack.enter_context(patch.object(reassess.evaluate, 'run_evaluator', side_effect=fake_run))
            stack.enter_context(patch.object(reassess.browser_cleanup, 'cleanup', return_value={'confirmed':True}))
            for target, value in extra_patches.values(): stack.enter_context(patch(target, **value))
            return reassess.execute(stage, repo=Path(reassess.__file__).resolve().parents[1])

    def complete_output(self, stage, *, instance=None):
        assessment = util.read_json(stage/'assessment.json')
        util.write_new_json(stage/'output/evaluation.json', {
            'taskId':'EDU', 'artifactPath':'/artifact', 'artifactSha256':self.original_hash,
            'specSha256':assessment['new_spec_sha256'], 'evaluationVersion':'education-1.1.0',
            'researchStatus':'complete', 'quality':100, 'verdict':'pass_auto',
            'reviewRunInstanceId': instance or assessment['assessment_id']})
        util.write_new_json(stage/'output/evaluator-manifest.json',
            {'evaluatorSha256':assessment['evaluator_sha256']})

    def test_missing_or_foreign_browser_evidence_does_not_adopt_numeric_pass(self):
        for foreign in (False, True):
            with self.subTest(foreign=foreign):
                stage = self.prepare()
                def run(*args):
                    self.complete_output(stage, instance='foreign' if foreign else None)
                    return 0, False
                result = self.run_fake(stage, run,
                    a=('outer.harness.browser_review.coverage_complete', {'return_value':True}),
                    b=('outer.harness.browser_review.stored_coverage_complete', {'return_value':foreign}),
                    c=('outer.harness.browser_cleanup.latest', {'return_value':{'confirmed':True,
                        'run_instance_id':util.read_json(stage/'assessment.json')['assessment_id']}}))
                self.assertFalse(result['adopted']); self.assertIsNone(result['quality'])
                self.assertTrue(result['source_unchanged'])

    def test_complete_bound_output_adopts_only_with_matching_cleanup(self):
        stage = self.prepare(); instance = util.read_json(stage/'assessment.json')['assessment_id']
        def run(command, repo, environment, out, err, timeout):
            self.assertIn('sample2.assessment='+instance, command)
            self.complete_output(stage); return 0, False
        result = self.run_fake(stage, run,
            a=('outer.harness.browser_review.coverage_complete', {'return_value':True}),
            b=('outer.harness.browser_review.stored_coverage_complete', {'return_value':True}),
            c=('outer.harness.browser_cleanup.latest', {'return_value':{'confirmed':True,'run_instance_id':instance}}))
        self.assertTrue(result['adopted']); self.assertEqual(result['quality'],100)
        self.assertTrue(result['source_unchanged'])

    def test_malformed_partial_json_keeps_raw_and_terminal_fault_receipt(self):
        stage = self.prepare()
        def run(*args):
            (stage/'output/http-only/evaluation.json').write_text('{broken')
            return 2,False
        result = self.run_fake(stage,run)
        self.assertEqual(result['operation_status'],'postprocessing_fault')
        self.assertFalse(result['adopted']); self.assertTrue((stage/'result.json').is_file())
        self.assertEqual((stage/'output/http-only/evaluation.json').read_text(),'{broken')
        self.assertEqual(reassess.byte_inventory(self.source),self.before)

    def test_foreign_container_collision_is_never_removed(self):
        stage = self.prepare(); name = 's2-score-'+'2'*32
        calls=[]
        def docker(*args,**kwargs):
            calls.append(args)
            if args[0]=='ps': return SimpleNamespace(stdout=json.dumps({'Names':name,'ID':'foreign-id'}),returncode=0)
            if args[0]=='inspect': return SimpleNamespace(stdout=json.dumps([{
                'Name':'/'+name,'Id':'foreign-id','Config':{'Labels':{'sample2.browser-review':'foreign'}}}]),returncode=0)
            self.fail('Foreign resource removal attempted')
        with patch.object(reassess.runtime,'scoring_command',return_value=(name,['docker','run','--name',name,'dummy'])), \
             patch.object(reassess.evaluate,'run_evaluator',return_value=(125,False)), \
             patch.object(reassess.runtime,'docker',side_effect=docker): result=reassess.execute(stage,repo=Path(reassess.__file__).resolve().parents[1])
        self.assertEqual(result['operation_status'],'cleanup_unconfirmed')
        self.assertFalse(result['adopted']); self.assertNotIn('rm',[a[0] for a in calls])
        self.assertEqual(reassess.byte_inventory(self.source),self.before)

    def test_stop_after_http_avoids_new_browser_execution(self):
        stage=self.prepare()
        def run(*args):
            (stage/'STOP').write_text('stop now')
            return 0,False
        with patch.object(reassess.browser_review,'complete_evaluation') as browser:
            result=self.run_fake(stage,run)
        browser.assert_not_called(); self.assertEqual(result['operation_status'],'stopped_after_http')
        self.assertFalse(result['adopted']); self.assertEqual(reassess.byte_inventory(self.source),self.before)


if __name__ == '__main__': unittest.main()

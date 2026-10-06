"""Read-only validation of already executed assessments; fixtures never dispatch."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from outer.harness import education_browser as school, util
from research import saved_reassessment as saved
from research.tests import test_saved_reassessment as fixtures


class SavedRevalidationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SavedReassessmentTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def stage(self, *, complete=True, failed=False):
        stage = self.fixture.prepare()
        a = util.read_json(stage/'assessment.json')
        out = stage/'output'; http = out/'http-only'; review = out/'browser-school'
        http.mkdir(parents=True); review.mkdir()
        identity = {'taskId':'EDU', 'artifactPath':'/artifact',
            'artifactSha256':a['source_artifact_sha256'], 'specSha256':a['new_spec_sha256'],
            'evaluationVersion':a['evaluation_version']}
        requirements = [{'id':'R-001','judgement':'fail' if failed else 'pass'}]
        baseline = {**identity, 'requirements':requirements, 'criticalFailed':['R-001'] if failed else []}
        util.write_new_json(http/'evaluation.json', baseline)
        (http/'results.jsonl').write_bytes(b'finite bound baseline\n')
        receipt = {'schemaVersion':2, 'actor':'agent', 'action':'create-edit-save' if complete else 'not-run-unsupported',
            'runInstanceId':a['assessment_id'], 'artifactSha256':a['source_artifact_sha256'],
            'specSha256':a['new_spec_sha256'], 'evaluationVersion':a['evaluation_version'],
            'baseUrl':'http://127.0.0.1:43210', 'faults':[], 'productFailures':[]}
        request = {k:receipt[k] for k in ('runInstanceId','artifactSha256','specSha256','evaluationVersion','baseUrl')}
        util.write_new_json(review/'request.json', request)
        receipt['requestSha256']=util.sha256_file(review/'request.json')
        for name in school.REFERENCES:
            (review/name).write_bytes(('finite evidence '+name).encode())
            receipt[name]={'path':name,'sha256':util.sha256_file(review/name)}
        util.write_new_json(review/'receipt.json', receipt)
        result={**identity, 'requirements':requirements, 'criticalFailed':['R-001'] if failed else [],
            'verdict':'fail_critical' if failed else 'pass', 'researchStatus':'complete' if complete else 'incomplete',
            'quality':83.33 if complete and failed else 100 if complete else None,
            'browserReviewCoverage':school.OBSERVED if complete else 'not_observed',
            'reviewRunInstanceId':a['assessment_id'],
            'browserReviewEvidenceSha256':util.sha256_file(review/'receipt.json'),
            'baselineEvaluationSha256':util.sha256_file(http/'evaluation.json'),
            'baselineResultsSha256':util.sha256_file(http/'results.jsonl'), 'evaluatorFaults':[]}
        util.write_new_json(out/'evaluation.json', result)
        for number,target in enumerate((http,out)):
            util.write_new_json(target/'evaluator-manifest.json', {'evaluatorSha256':a['evaluator_sha256']})
            owner='s2-browser-'+str(number)*32
            resource={'kind':'container','name':'s2-score-'+str(number)*32,'id':None}
            util.write_new_json(target/'browser-resources.json',
                {'owner':owner,'run_instance_id':a['assessment_id'],'resources':[resource]})
            util.write_new_json(target/'browser-cleanup.json',
                {'confirmed':True,'run_instance_id':a['assessment_id'],'owner':owner,'status':'complete',
                 'resources':[{**resource,'id':str(number)*64,'confirmed':True,'status':'removed'}]})
        util.write_new_json(stage/'result.json', {'schema_version':1,'assessment_id':a['assessment_id'],
            'operation_status':'evaluation_finished' if complete else 'evaluation_partial_or_fault',
            'adopted':False,'quality':None,'cleanup_confirmed':True,'source_unchanged':True,
            'errors':[],'evaluator_exit_code':0,'timed_out':False,'browser_exit_code':0 if complete else 2,
            'raw_result':'output/evaluation.json','raw_verdict':result['verdict'],
            'evaluator_sha256_reported':a['evaluator_sha256']})
        return stage

    def validate(self, stage, name='validation.json'):
        with patch.object(saved.runtime,'docker',side_effect=AssertionError('No Docker allowed')), \
             patch.object(saved.evaluate,'run_evaluator',side_effect=AssertionError('No execution allowed')):
            return saved.revalidate(stage,self.root/name)

    def test_complete_schema_two_normal_and_critical_failure_preserve_first_results(self):
        for failed in (False,True):
            stage=self.stage(failed=failed)
            stage_before=saved.byte_inventory(stage); source_before=saved.byte_inventory(self.fixture.source)
            receipt=self.validate(stage,'complete-'+str(failed)+'.json')
            self.assertTrue(receipt['adopted']); self.assertEqual(receipt['quality'],83.33 if failed else 100)
            self.assertNotEqual(receipt['validation_id'],util.read_json(stage/'assessment.json')['assessment_id'])
            self.assertEqual(saved.byte_inventory(stage),stage_before)
            self.assertEqual(saved.byte_inventory(self.fixture.source),source_before)
            self.assertFalse(util.read_json(stage/'result.json')['adopted'])

    def test_partial_quality_stays_null_and_finite_failure_is_separate(self):
        stage=self.stage(complete=False,failed=True)
        receipt=self.validate(stage)
        self.assertFalse(receipt['adopted']); self.assertIsNone(receipt['quality'])
        self.assertEqual(receipt['finite_failure']['verdict'],'fail_critical')
        self.assertEqual(receipt['finite_failure']['requirements'],['R-001'])
        self.assertEqual(receipt['validation_status'],'partial_observation')

    def test_output_identity_missing_or_foreign_and_reference_tamper_refuse_adoption(self):
        for case in ('foreign','missing','reference','dll','assets','config','cleanup','first-result'):
            stage=self.stage()
            if case=='foreign':
                p=stage/'output/evaluation.json'; value=util.read_json(p);value['reviewRunInstanceId']='foreign';util.write_json_atomic(p,value)
            elif case=='missing': (stage/'output/browser-school/request.json').unlink()
            elif case=='reference': (stage/'output/browser-school/after').write_bytes(b'tampered')
            elif case=='dll': (stage/'evaluation-assets/evaluator/New.dll').write_bytes(b'tampered')
            elif case=='assets': (stage/'evaluation-assets/catalog.json').write_bytes(b'{} changed')
            elif case=='config': (stage/'execution-config.json').write_bytes(b'{}')
            elif case=='cleanup':
                p=stage/'output/browser-cleanup.json';value=util.read_json(p);value['run_instance_id']='foreign';util.write_json_atomic(p,value)
            else:
                p=stage/'result.json';value=util.read_json(p);value['source_unchanged']=None;util.write_json_atomic(p,value)
            before=saved.byte_inventory(stage)
            with self.subTest(case=case):
                receipt=self.validate(stage,case+'.json')
                self.assertFalse(receipt['adopted']);self.assertIsNone(receipt['quality'])
                self.assertEqual(saved.byte_inventory(stage),before)

    def test_changed_current_controller_is_recorded_separately_from_execution_controller(self):
        stage=self.stage()
        actual=saved.controller_inventory(Path(saved.__file__).resolve().parents[1])
        changed=copy.deepcopy(actual);changed['research/saved_reassessment.py']='f'*64
        with patch.object(saved,'controller_inventory',return_value=changed): receipt=self.validate(stage)
        self.assertTrue(receipt['adopted'])
        self.assertEqual(receipt['validation_controller_inventory'],changed)
        self.assertEqual(receipt['evaluation_controller_inventory'],actual)
        self.assertFalse(receipt['evaluation_controller_matches_current'])

    def test_baseline_and_original_contract_links_are_required_even_for_complete_output(self):
        for field in ('baselineEvaluationSha256','baselineResultsSha256',
                      'source_evaluation_version','source_spec_sha256'):
            stage=self.stage()
            path=stage/('assessment.json' if field.startswith('source_') else 'output/evaluation.json')
            value=util.read_json(path);value[field]='fabricated-old-version' if field.endswith('version') else 'f'*64
            util.write_json_atomic(path,value)
            before=saved.byte_inventory(stage)
            with self.subTest(field=field):
                receipt=self.validate(stage,field+'.json')
                self.assertFalse(receipt['adopted']);self.assertIsNone(receipt['quality'])
                self.assertIsNone(receipt['finite_failure'])
                self.assertEqual(saved.byte_inventory(stage),before)

    def test_observer_fault_is_separate_from_partial_exit_two(self):
        partial=self.stage(complete=False,failed=True)
        receipt=self.validate(partial,'normal-partial.json')
        self.assertFalse(receipt['observer_fault'])
        self.assertEqual(receipt['observer_faults'],[])
        self.assertEqual(receipt['validation_status'],'partial_observation')
        faulted=self.stage()
        util.write_new_json(faulted/'output/browser-fault.json',{'type':'ObserverTraceFault','scoring_state':'evaluator_fault'})
        receipt=self.validate(faulted,'observer-fault.json')
        self.assertTrue(receipt['observer_fault']);self.assertFalse(receipt['adopted'])
        self.assertIsNone(receipt['quality'])

    def test_exclusive_outside_original_destination_and_revalidation_refuses_overwrite(self):
        stage=self.stage();self.validate(stage)
        with self.assertRaises(FileExistsError): self.validate(stage)
        for destination in (stage/'new.json',self.fixture.source/'new.json',stage/'output/evaluation.json'):
            with self.subTest(destination=str(destination)),self.assertRaises(ValueError):
                saved.revalidate(stage,destination)
        self.assertFalse((stage/'new.json').exists());self.assertFalse((self.fixture.source/'new.json').exists())


if __name__=='__main__':unittest.main()

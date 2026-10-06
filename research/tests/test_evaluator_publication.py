import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from research.public_readers import evaluator_publication_schema1 as public


def uid(value): return uuid.uuid5(uuid.NAMESPACE_URL, 'publication-fixture/' + value).hex


def dataset():
    rows=[]
    for i in range(7):
        complete=i in (0,1,3,6); failed=i==1
        reqs=[{'id':f'R-{n:03}', 'severity':'critical', 'weight':1,
            'reported_judgement':'fail' if failed and n<=2 else 'pass' if complete else 'blocked'} for n in range(1,13)]
        rows.append({'kind':'saved_artifact_reassessment','assessment_id':uid('assessment'+str(i)),
            'validation_id':uid('validation'+str(i)), 'source_run_id':'T-'+str(i%5),
            'source_run_instance_id':uid('source'+str(i%5)), 'source_campaign_uuid':None,
            'source_campaign_identity_status':'caller_asserted_unverified',
            'source_artifact_sha256':str(i%5)*64,'source_condition_sha256':'a'*64,'source_spec_sha256':'b'*64,
            'source_evaluation_version':'1.0.0','evaluation_version':'1.1.0' if i<5 else '1.2.0',
            'evaluator_sha256':'c'*64,'new_spec_sha256':'d'*64,'plan_commit_declared':'a'*40,
            'plan_sha256':'e'*64,'quality_method':'equal_requirement_weight_v1','requirements':reqs,
            'checks':[{'requirement_id':r['id'],'check_id':f'C-{n:03}','reported_judgement':r['reported_judgement']} for n,r in enumerate(reqs,1)],
            'raw_verdict':'fail_critical' if failed or not complete else 'pass',
            'raw_research_status':'complete' if complete else 'incomplete','reported_quality':83.33 if failed else 100 if complete else None,
            'validated_quality':83.33 if failed else 100 if complete else None,'adopted':complete,
            'validation_status':'complete_observation' if complete else 'partial_observation',
            'operation_status':'evaluation_finished','observer_fault':False,'source_bytes_unchanged':True,
            'assessment_bytes_unchanged':True,'cleanup_confirmed':True,'finite_failure':None,
            'cascade_warning':False,'model_calls':0,'acquisition_count_increment':0,
            'provenance':{name: {'outer/harness/reader.py':'a'*64} if name.endswith('_inventory') else 'a'*64 for name in public.PROVENANCE_KEYS}})
    campaigns=[]
    for i in range(2):
        runs=[{'run_id':f'fixture-{i}-{n}','run_instance_id':uid(f'dummy{i}-{n}'),'session_id':f'ses_fixture{i}{n}',
            **{name:True for name in ('session_create_verified','session_read_verified','session_abort_verified','admission_ack_verified','observer_ack_verified','stop_confirmed','cleanup_confirmed')},
            'artifact_sha256':'e'*64,'source_snapshot_sha256':'f'*64,'state':'gate_pending','publication_gate_complete':False} for n in range(2)]
        campaigns.append({'campaign_id':f'fixture-{i}','campaign_uuid':uid('campaign'+str(i)),
            'plan_sha256':'a'*64,'backend':'providerless-opencode-session','model_calls':0,'pairs':1,'runs':runs})
    operational={'schema_version':1,'kind':'nonmodel_operational_acceptance','campaigns':campaigns,
        'reassessment':{'assessment_id':uid('dummy-assessment'),'source_run_instance_id':campaigns[0]['runs'][0]['run_instance_id'],
            'source_artifact_sha256':'e'*64,'evaluation_version':'fixture-2','acquisition_count_increment':0},
        'publication_phase':'prepublication','publication_gate_complete':False,
        'phase_a_verification_sha256':None,'phase_a_package_sha256':None}
    return {'schema_version':1,'kind':'evaluator_repair_public_projection',
        'original_experiment':{'experiment_id':'original100','assignment_pairs':100,'assignment_runs':200,
            'bundle_sha256':'a'*64,'dataset_sha256':'b'*64,
            'release_url':'https://github.com/fukuda-yuki/sample2/releases/tag/source-info-fixture'},
        'assessments':rows,'operational_acceptance':operational,
        'observation_scopes':{r['assessment_id']:fixture_scope(r) for r in rows}}


def fixture_scope(row):
    checks=[{'requirement_id':c['requirement_id'],'check_id':c['check_id'],
        'has_unknown_observation':c['reported_judgement'] in (None,'blocked','error'),
        'has_observer_fault':c['reported_judgement']=='error'} for c in row['checks']]
    return {'method':'declared-output-and-check-flags-v1',
        'evaluation_json_sha256':row['provenance']['evaluation_json_sha256'],
        'results_jsonl_sha256':row['provenance']['results_jsonl_sha256'],
        'has_unchecked_scope':any(c['has_unknown_observation'] for c in checks),
        'has_observer_fault':any(c['has_observer_fault'] for c in checks),'checks':checks}


def policy(data,phase='prepublication'):
    ids=[r['assessment_id'] for r in data['assessments']]
    return {'package_id':'repair-fixture','expected_assessment_ids':ids,'required_history_assessment_ids':ids,
        'expected_assessment_versions':{r['assessment_id']:r['evaluation_version'] for r in data['assessments']},
        'required_history_row_sha256':{r['assessment_id']:hashlib.sha256(public.encode(r)).hexdigest() for r in data['assessments']},
        'required_evaluation_versions':['1.1.0','1.2.0'],'required_phase':phase}


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_seven_row_recomputation_quality_critical_partial_and_counts(self):
        result=public.derive(dataset())
        self.assertEqual(result['saved_assessment_count'],7);self.assertEqual(result['unique_saved_source_runs'],5)
        self.assertEqual(result['complete_observation_count'],4);self.assertEqual(result['partial_or_fault_count'],3)
        self.assertEqual(result['complete_verdict_counts'],{'fail_critical':1,'pass':3})
        self.assertEqual(result['nonmodel_operational_runs'],4);self.assertEqual(result['model_calls'],0)
        self.assertEqual(sorted(r['quality'] for r in result['assessments'] if r['quality'] is not None),[83.33,100,100,100])
        partial=next(r for r in result['assessments'] if not r['complete_observation'])
        self.assertEqual(len(partial['critical_unknown_labels']),12)
        self.assertEqual(partial['critical_reported_failed_labels'],[])

    def test_unfilled_revision_slot_and_missing_operational_acceptance_cannot_seal(self):
        data=dataset();p=policy(data);p['expected_assessment_ids'].append(uid('new-revision'))
        with self.assertRaises(ValueError):public.seal_package(self.root/'missing-revision',data=data,report=b'Finite fixture',policy=p)
        data['operational_acceptance']=None
        with self.assertRaises(ValueError):public.seal_package(self.root/'no-ops',data=data,report=b'Finite fixture',policy=policy(data))
        self.assertFalse((self.root/'missing-revision').exists());self.assertFalse((self.root/'no-ops').exists())

    def test_sealed_real_row_reader_runs_from_different_folder_and_does_not_overwrite(self):
        data=dataset();root=self.root/'package';public.seal_package(root,data=data,report=b'Finite seven-row fixture',policy=policy(data))
        expected=public.sha(root/'MANIFEST.json');out=self.root/'different'/'recomputed'
        command=[sys.executable,'-B','-X','utf8',str(root/'code/evaluator_publication.py'),'reproduce',
            '--package',str(root),'--out',str(out),'--expected-manifest-sha256',expected]
        result=subprocess.run(command,cwd=self.root,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((out/'summary.json').read_bytes(),(root/'results/summary.json').read_bytes())
        with self.assertRaises(ValueError):public.reproduce(root,out,expected)

    def test_tamper_unlisted_file_external_digest_and_paths_refuse_before_output(self):
        for kind in ('data','extra','digest'):
            data=dataset();root=self.root/kind;public.seal_package(root,data=data,report=b'Finite fixture',policy=policy(data));expected=public.sha(root/'MANIFEST.json')
            if kind=='data':(root/'data/assessments.json').write_text('{}')
            elif kind=='extra':(root/'extra.txt').write_text('extra')
            else:expected='f'*64
            out=self.root/(kind+'-recomputed')
            with self.assertRaises(ValueError):public.reproduce(root,out,expected)
            self.assertFalse(out.exists())
        for path in ('../outside','C:/outside','/outside','DATA/../outside','CON'):
            with self.subTest(path=path),self.assertRaises(ValueError):public.relative(path)

    def test_unreviewed_private_field_weight_and_unknown_quality_method_refused(self):
        for change in ('private','weight','method','duplicate','quality'):
            data=dataset();r=data['assessments'][0]
            if change=='private':r['source_path_private']='private absolute host path'
            elif change=='weight':r['requirements'][0]['weight']=2
            elif change=='method':r['quality_method']='unknown-method'
            elif change=='duplicate':data['assessments'][1]['assessment_id']=r['assessment_id']
            else:r['validated_quality']=99
            with self.subTest(change=change),self.assertRaises(ValueError):public.derive(data)

    def test_final_phase_requires_external_phase_a_proof_and_all_production_gates(self):
        data=dataset();p=policy(data,'final')
        with self.assertRaises(ValueError):public.seal_package(self.root/'wrong-phase',data=data,report=b'Finite fixture',policy=p)
        op=data['operational_acceptance'];op['publication_phase']='final';op['publication_gate_complete']=True
        with self.assertRaises(ValueError):public.seal_package(self.root/'missing-proof',data=data,report=b'Finite fixture',policy=p)
        op['phase_a_verification_sha256']='a'*64;op['phase_a_package_sha256']='b'*64
        for c in op['campaigns']:
            for r in c['runs']:r['publication_gate_complete']=True
        public.seal_package(self.root/'final',data=data,report=b'Finite fixture',policy=p)

    def test_contradictory_operational_counts_boolean_weight_and_missing_check_scope_denied(self):
        for change in ('top-calls','run-calls','assessment-calls','campaign-bool','weight-bool','missing-scope'):
            data=dataset();op=data['operational_acceptance']
            if change=='top-calls':op['model_calls']=1
            elif change=='run-calls':op['campaigns'][0]['runs'][0]['model_calls']=1
            elif change=='assessment-calls':op['reassessment']['model_calls']=1
            elif change=='campaign-bool':op['campaigns'][0]['model_calls']=False
            elif change=='weight-bool':data['assessments'][0]['requirements'][0]['weight']=True
            else:data['assessments'][0]['checks'].pop()
            with self.subTest(change=change),self.assertRaises(ValueError):public.derive(data)

    def test_projection_rejects_saved_stage_changes_despite_pinned_validation_receipt(self):
        stage=self.root/'saved';stage.mkdir();(stage/'metadata.json').write_bytes(b'original saved bytes')
        validation=self.root/'validation.json'
        validation.write_bytes(public.encode({'assessment_inventory_sha256_after':public.evidence_inventory_digest(stage)}))
        digest=public.sha(validation)
        (stage/'metadata.json').write_bytes(b'changed after validation')
        before=public.evidence_inventory_digest(stage)
        with self.assertRaisesRegex(ValueError,'changed since pinned validation'):
            public.normalize_assessment(stage=stage,validation=validation,plan=self.root/'absent-plan',expected_validation_sha256=digest)
        self.assertEqual(before,public.evidence_inventory_digest(stage))
        self.assertEqual(digest,public.sha(validation))

    def test_projection_preserves_missing_requirement_and_check_as_unknown(self):
        row=dataset()['assessments'][2];stage=self.root/'partial';out=stage/'output';baseline=out/'http-only'
        row['checks'][-1].update(check_id='E-012',reported_judgement='fail');row['requirements'][-1]['reported_judgement']='fail'
        baseline.mkdir(parents=True);assets=stage/'evaluation-assets';assets.mkdir()
        spec={'requirements':[{'id':r['id'],'severity':r['severity'],
            'checks':[{'id':c['check_id']} for c in row['checks'] if c['requirement_id']==r['id']]} for r in row['requirements']]}
        (assets/'requirements.json').write_bytes(public.encode(spec));(baseline/'evaluation.json').write_bytes(b'{}\n')
        (baseline/'results.jsonl').write_bytes(b'')
        result={'evaluationVersion':row['evaluation_version'],'artifactSha256':row['source_artifact_sha256'],
            'specSha256':public.sha(assets/'requirements.json'),'baselineEvaluationSha256':public.sha(baseline/'evaluation.json'),
            'baselineResultsSha256':public.sha(baseline/'results.jsonl'),'verdict':'error','researchStatus':'incomplete',
            'quality':None,'browserReviewCoverage':'not_run_or_partial',
            'requirements':[{'id':r['id'],'judgement':r['reported_judgement']} for r in row['requirements'][1:]]}
        (out/'evaluation.json').write_bytes(public.encode(result))
        (out/'results.jsonl').write_text(''.join(json.dumps({'requirementId':c['requirement_id'],'checkId':c['check_id'],
            'judgement':c['reported_judgement']})+'\n' for c in row['checks'][1:]),encoding='utf8')
        metadata={name:row[name] for name in ('assessment_id','source_run_id','source_run_instance_id','source_artifact_sha256',
            'source_condition_sha256','source_spec_sha256','source_evaluation_version','evaluation_version','evaluator_sha256')}
        metadata['new_spec_sha256']=result['specSha256'];(stage/'assessment.json').write_bytes(public.encode(metadata))
        (stage/'result.json').write_bytes(public.encode({'assessment_id':row['assessment_id'],'operation_status':'partial_or_fault','cleanup_confirmed':True}))
        plan=self.root/'plan.json';plan.write_bytes(public.encode({'source_commit':'a'*40}))
        v={name:row[name] for name in ('assessment_id','source_run_id','source_run_instance_id','validation_id','evaluation_version',
            'adopted','validation_status','observer_fault','source_bytes_unchanged','assessment_bytes_unchanged','model_calls','acquisition_count_increment')}
        v.update(quality=None,output_sha256=public.sha(out/'evaluation.json'),original_result_sha256=public.sha(stage/'result.json'),
            validation_implementation_sha256='a'*64,evaluation_controller_inventory={'outer/harness/a.py':'a'*64},
            validation_controller_inventory={'outer/harness/a.py':'a'*64},assessment_inventory_sha256_after=public.evidence_inventory_digest(stage))
        validation=self.root/'validation.json';validation.write_bytes(public.encode(v))
        projected=public.normalize_assessment(stage=stage,validation=validation,plan=plan,expected_validation_sha256=public.sha(validation))
        self.assertIsNone(projected['requirements'][0]['reported_judgement']);self.assertIsNone(projected['checks'][0]['reported_judgement'])
        derived=public.derive_assessment(projected);self.assertIsNone(derived['quality'])
        self.assertEqual(derived['requirement_counts'],{'blocked':10,'fail':1,'unknown':1})
        scope=public.normalize_observation_scope(stage=stage,validation=validation,expected_validation_sha256=public.sha(validation),row=projected)
        self.assertTrue(scope['checks'][0]['has_unknown_observation'])
        self.assertTrue(scope['checks'][-1]['has_unknown_observation'])
        self.assertIn('R-012',public.derive_assessment(projected,scope)['critical_unknown_labels'])
        self.assertEqual(len(scope['checks']),12)

    def test_seal_preserves_historical_row_bytes_and_exact_per_assessment_revision(self):
        for change in ('historical','version'):
            data=dataset();p=policy(data)
            if change=='historical':data['assessments'][0]['plan_sha256']='f'*64
            else:data['assessments'][0]['evaluation_version']='1.3.0'
            dest=self.root/change
            with self.subTest(change=change),self.assertRaises(ValueError):public.seal_package(dest,data=data,report=b'Finite fixture',policy=p)
            self.assertFalse(dest.exists())

    def test_known_failure_plus_residual_unknown_or_fault_is_not_complete(self):
        for marker in ('has_unknown_observation','has_observer_fault'):
            data=dataset();row=data['assessments'][0];scope=data['observation_scopes'][row['assessment_id']]
            row['requirements'][0]['reported_judgement']='fail';row['checks'][0]['reported_judgement']='fail'
            scope['checks'][0][marker]=True
            scope['has_unchecked_scope' if marker=='has_unknown_observation' else 'has_observer_fault']=True
            with self.subTest(marker=marker),self.assertRaisesRegex(ValueError,'cannot adopt quality'):public.derive(data)
            row.update(adopted=False,validated_quality=None,reported_quality=None,raw_verdict='fail_critical',
                raw_research_status='incomplete',validation_status='partial_observation')
            row['finite_failure']={'verdict':'fail_critical','requirements':[row['requirements'][0]['id']],'source':'composed'}
            result=public.derive_assessment(row,scope)
            self.assertFalse(result['complete_observation']);self.assertIsNone(result['quality'])
            self.assertIn('R-001',result['critical_reported_failed_labels']);self.assertIn('R-001',result['critical_unknown_labels'])
            self.assertEqual(result['bound_reported_failure'],row['finite_failure'])
            aggregate=public.derive(data)
            self.assertEqual(aggregate['observer_fault_count'],int(marker=='has_observer_fault'))
            self.assertEqual(aggregate['validation_observer_fault_count'],0)

    def test_partial_browser_aggregate_preserves_independently_observed_case(self):
        row=dataset()['assessments'][0];row['checks'][-2]['check_id']='C-015';row['checks'][-1]['check_id']='C-016'
        stage=self.root/'cases';out=stage/'output';out.mkdir(parents=True)
        (out/'evaluation.json').write_bytes(public.encode({'browserCartCoverage':'partial',
            'browserCartCases':{'C-015':'observed','C-016':'not_run'}}))
        (out/'results.jsonl').write_text(''.join(json.dumps({'requirementId':c['requirement_id'],'checkId':c['check_id'],
            'judgement':c['reported_judgement']})+'\n' for c in row['checks']),encoding='utf8')
        row['provenance']['evaluation_json_sha256']=public.sha(out/'evaluation.json')
        row['provenance']['results_jsonl_sha256']=public.sha(out/'results.jsonl')
        validation=self.root/'case-validation.json';validation.write_bytes(public.encode({'assessment_id':row['assessment_id'],
            'assessment_inventory_sha256_after':public.evidence_inventory_digest(stage)}))
        scope=public.normalize_observation_scope(stage=stage,validation=validation,expected_validation_sha256=public.sha(validation),row=row)
        cases={c['check_id']:c for c in scope['checks']}
        self.assertFalse(cases['C-015']['has_unknown_observation']);self.assertTrue(cases['C-016']['has_unknown_observation'])


if __name__=='__main__':unittest.main()

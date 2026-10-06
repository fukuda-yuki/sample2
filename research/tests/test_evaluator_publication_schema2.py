"""Finite schema2 publication tests; all study rows and attempts here are fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from research import evaluator_publication as p
from research.tests import test_evaluator_publication as fixtures


def uid(text):return uuid.uuid5(uuid.NAMESPACE_URL,'schema2-finite-fixture/'+text).hex


def fixture_attempt(source):
    row={'kind':'unvalidated_saved_reassessment_attempt','assessment_id':uid('http-only-'+str(source)),
        'validation_id':None,'validated':False,'quality':None,'source_run_id':'T-'+str(source),
        'source_run_instance_id':fixtures.uid('source'+str(source)),
        'source_campaign_uuid':None,'source_campaign_identity_status':'caller_asserted_unverified',
        'source_artifact_sha256':str(source)*64,'source_condition_sha256':'a'*64,'source_spec_sha256':'b'*64,
        'source_evaluation_version':'1.0.0','evaluation_version':'1.6.0','evaluator_sha256':'f'*64,
        'new_spec_sha256':'9'*64,'plan_commit_declared':'a'*40,'plan_sha256':'e'*64,
        'observed_stage':'http_only','browser_started':False,'pipeline_complete':False,
        'pipeline_gate_fault':'http_exit2_rejected_before_browser','evaluator_exit_code':2,'browser_exit_code':None,
        'cleanup_confirmed':True,'source_bytes_unchanged':True,'model_calls':0,'acquisition_count_increment':0,
        'http_raw_verdict':'pass','http_raw_research_status':'incomplete',
        'http_requirement_judgement_counts':{'pass':31},'http_check_judgement_counts':{'pass':33},
        'http_has_unknown_observations':True,'http_has_observer_faults':False,
        'provenance':{name:'a'*64 for name in p.ATTEMPT_PROVENANCE_KEYS}}
    return row


def fixtures11():
    data=fixtures.dataset();original7=copy.deepcopy(data['assessments'])
    attempts={'schema_version':2,'kind':'unvalidated_saved_reassessment_attempts',
        'attempts':[fixture_attempt(n) for n in (0,1,5,6)],'limits':['Finite unknown fixtures only']}
    data['schema_version']=2;data['attempts_reference']={'path':p.ATTEMPTS_PATH,'sha256':hashlib.sha256(p.encode(attempts)).hexdigest()}
    data['attempt_followups']={}
    template=data['assessments'][0]
    for attempt in attempts['attempts']:
        row=copy.deepcopy(template)
        for key in ('source_run_id','source_run_instance_id','source_artifact_sha256','source_condition_sha256','source_spec_sha256',
            'source_evaluation_version','evaluation_version','evaluator_sha256','new_spec_sha256','plan_commit_declared','plan_sha256'):row[key]=attempt[key]
        row.update(assessment_id=uid('new-full-pipeline-'+attempt['assessment_id']),validation_id=uid('new-validation-'+attempt['assessment_id']),
            reported_quality=None,validated_quality=None,adopted=False,validation_status='partial_observation',raw_research_status='incomplete',raw_verdict='error')
        for r in row['requirements']:r['reported_judgement']=None
        for c in row['checks']:c['reported_judgement']=None
        data['assessments'].append(row);data['observation_scopes'][row['assessment_id']]=fixtures.fixture_scope(row)
        data['attempt_followups'][attempt['assessment_id']]=row['assessment_id']
    policy={'package_id':'schema2-finite-fixture','expected_assessment_ids':[r['assessment_id'] for r in data['assessments']],
        'expected_assessment_versions':{r['assessment_id']:r['evaluation_version'] for r in data['assessments']},
        'required_history_assessment_ids':[r['assessment_id'] for r in original7],
        'required_history_row_sha256':{r['assessment_id']:hashlib.sha256(p.encode(r)).hexdigest() for r in original7},
        'required_evaluation_versions':['1.1.0','1.2.0','1.6.0'],'required_phase':'prepublication',
        'expected_unvalidated_attempt_ids':[r['assessment_id'] for r in attempts['attempts']],
        'expected_attempt_followups':copy.deepcopy(data['attempt_followups']),
        'required_unvalidated_attempt_row_sha256':{r['assessment_id']:hashlib.sha256(p.encode(r)).hexdigest() for r in attempts['attempts']}}
    return data,attempts,policy


class Schema2PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def make_http_stage(self,folder):
        row=fixture_attempt(0);stage=folder/'stage';output=stage/'output/http-only';output.mkdir(parents=True)
        assets=stage/'evaluation-assets';bundle=assets/'evaluator';bundle.mkdir(parents=True)
        (bundle/'MusicStore.Evaluator.dll').write_bytes(b'finite fixture DLL bytes; never executed')
        (assets/'requirements.json').write_bytes(p.encode({'requirements':[{'id':f'R-{n:03}'} for n in range(1,32)]}))
        metadata={k:row[k] for k in ('assessment_id','source_run_id','source_run_instance_id','source_artifact_sha256',
            'source_condition_sha256','source_spec_sha256','source_evaluation_version','evaluation_version')}
        metadata.update(evaluator_sha256=p.sha(bundle/'MusicStore.Evaluator.dll'),new_spec_sha256=p.sha(assets/'requirements.json'))
        (stage/'assessment.json').write_bytes(p.encode(metadata))
        result={'evaluationVersion':'1.6.0','artifactSha256':row['source_artifact_sha256'],'specSha256':metadata['new_spec_sha256'],
            'verdict':'pass','researchStatus':'incomplete','quality':None,'uncheckedScope':['private unknown browser detail'],
            'evaluatorFaults':[],'requirements':[{'id':f'R-{n:03}','judgement':'pass'} for n in range(1,32)]}
        (output/'evaluation.json').write_bytes(p.encode(result))
        (output/'evaluator-manifest.json').write_bytes(p.encode({'evaluationVersion':'1.6.0','artifactSha256':row['source_artifact_sha256'],
            'specSha256':metadata['new_spec_sha256'],'evaluatorSha256':metadata['evaluator_sha256']}))
        (output/'results.jsonl').write_text(''.join(json.dumps({'requirementId':f'R-{min(n,31):03}','checkId':f'C-{n:03}',
            'judgement':'pass','observation':'private observation body'})+'\n' for n in range(1,34)),encoding='utf8')
        initial={'assessment_id':row['assessment_id'],'evaluator_exit_code':2,'adopted':False,'quality':None,
            'full_bound_browser_observation':False,'raw_result':'output/http-only/evaluation.json','cleanup_confirmed':True,'source_unchanged':True}
        (stage/'result.json').write_bytes(p.encode(initial))
        plan=folder/'plan.json';plan.write_bytes(p.encode({'source_commit':'a'*40,'model_calls':0,'acquisition_count_increment':0}))
        aggregate=folder/'aggregate.json';aggregate.write_bytes(p.encode({'plan_sha256':p.sha(plan),'model_calls':0,
            'acquisition_count_increment':0,'cases':[{**initial,'source_run_id':row['source_run_id'],'stage':str(stage)}]}))
        return stage,plan,aggregate

    def test_projection_binding_eligibility_never_creates_validation_success(self):
        stage,plan,aggregate=self.make_http_stage(self.root/'eligible')
        before=p.evidence_inventory_digest(stage)
        row=p.normalize_unvalidated_attempt(stage=stage,plan=plan,aggregate=aggregate,
            expected_plan_sha256=p.sha(plan),expected_aggregate_sha256=p.sha(aggregate))
        self.assertEqual(p.evidence_inventory_digest(stage),before)
        self.assertFalse(row['validated']);self.assertFalse(row['pipeline_complete']);self.assertFalse(row['browser_started'])
        self.assertIsNone(row['validation_id']);self.assertIsNone(row['quality'])
        self.assertEqual(row['http_check_judgement_counts'],{'pass':33})
        self.assertNotIn('private observation body',p.encode(row).decode());self.assertNotIn('private unknown browser detail',p.encode(row).decode())
        self.assertNotIn(str(stage),p.encode(row).decode())

    def test_projection_rejects_changed_spec_dll_artifact_promoted_result_and_foreign_reference(self):
        for marker in ('spec','dll','artifact','adopted','composed','rawref','counter','aggregate-digest'):
            stage,plan,aggregate=self.make_http_stage(self.root/marker)
            if marker=='spec':(stage/'evaluation-assets/requirements.json').write_bytes(b'changed specification')
            elif marker=='dll':(stage/'evaluation-assets/evaluator/MusicStore.Evaluator.dll').write_bytes(b'changed DLL')
            elif marker=='artifact':
                path=stage/'output/http-only/evaluator-manifest.json';value=p.read(path);value['artifactSha256']='f'*64;path.write_bytes(p.encode(value))
            elif marker=='composed':(stage/'output/evaluation.json').write_bytes(b'{}\n')
            elif marker in ('adopted','rawref'):
                path=stage/'result.json';value=p.read(path)
                if marker=='adopted':value.update(adopted=True,quality=100)
                else:value['raw_result']='../foreign/evaluation.json'
                path.write_bytes(p.encode(value));group=p.read(aggregate);group['cases'][0].update(value);aggregate.write_bytes(p.encode(group))
            elif marker=='counter':
                value=p.read(plan);value['model_calls']=False;plan.write_bytes(p.encode(value))
                group=p.read(aggregate);group['plan_sha256']=p.sha(plan);aggregate.write_bytes(p.encode(group))
            expected=p.sha(aggregate) if marker!='aggregate-digest' else 'f'*64
            before=p.evidence_inventory_digest(stage)
            with self.subTest(marker=marker),self.assertRaises(ValueError):p.normalize_unvalidated_attempt(stage=stage,plan=plan,aggregate=aggregate,
                expected_plan_sha256=p.sha(plan),expected_aggregate_sha256=expected)
            self.assertEqual(p.evidence_inventory_digest(stage),before)

    def test_counter_units_typed_attempts_plus_explicit_unknown_report_rows(self):
        data,attempts,policy=fixtures11();summary=p.derive(data,attempts);p.check_policy(data,policy,attempts)
        self.assertEqual(summary['reported_assessment_count'],11);self.assertEqual(summary['all_saved_reassessment_attempt_count'],15)
        self.assertEqual(summary['unvalidated_http_only_attempt_count'],4);self.assertEqual(summary['unique_saved_source_runs'],7)
        self.assertEqual(summary['complete_observation_count'],4);self.assertEqual(summary['partial_or_fault_count'],7)
        self.assertEqual(summary['nonmodel_operational_runs'],4);self.assertEqual(summary['model_calls'],0)
        self.assertTrue(all(r['quality'] is None and not r['validated'] for r in summary['unvalidated_attempts']))

    def test_unknown_future_rows_missing_reject_before_seal(self):
        data,attempts,policy=fixtures11();data['assessments']=data['assessments'][:7]
        data['observation_scopes']={r['assessment_id']:data['observation_scopes'][r['assessment_id']] for r in data['assessments']}
        with self.assertRaises(ValueError):p.seal_package(self.root/'missing',data=data,attempts=attempts,report=b'Finite fixture',policy=policy)
        self.assertFalse((self.root/'missing').exists())

    def test_attempt_promotion_collision_lineage_counter_and_digest_denied(self):
        for marker in ('quality','validation','collision','artifact','dll','spec','source','version','counter','extra','digest'):
            data,attempts,policy=fixtures11();row=attempts['attempts'][0]
            if marker=='quality':row['quality']=100
            elif marker=='validation':row['validation_id']=uid('forbidden-validation')
            elif marker=='collision':row['assessment_id']=data['assessments'][0]['assessment_id']
            elif marker=='artifact':row['source_artifact_sha256']='f'*64
            elif marker=='dll':row['evaluator_sha256']='7'*64
            elif marker=='spec':row['new_spec_sha256']='f'*64
            elif marker=='source':row['source_run_instance_id']=uid('foreign-source')
            elif marker=='version':row['evaluation_version']='1.5.0'
            elif marker=='counter':row['model_calls']=1
            elif marker=='extra':attempts['attempts'].append(copy.deepcopy(row))
            else:data['attempts_reference']['sha256']='f'*64
            if marker!='digest':data['attempts_reference']['sha256']=hashlib.sha256(p.encode(attempts)).hexdigest()
            with self.subTest(marker=marker),self.assertRaises(ValueError):p.derive(data,attempts)

    def test_immutable_old_attempt_row_hash_and_relative_path_denied(self):
        for marker in ('row','path','slots'):
            data,attempts,policy=fixtures11()
            if marker=='row':
                attempts['attempts'][0]['plan_sha256']='f'*64
                data['attempts_reference']['sha256']=hashlib.sha256(p.encode(attempts)).hexdigest()
            elif marker=='path':data['attempts_reference']['path']='../private'
            else:policy['expected_unvalidated_attempt_ids'][0]=uid('unfilled-attempt')
            with self.subTest(marker=marker),self.assertRaises(ValueError):p.seal_package(self.root/marker,data=data,attempts=attempts,report=b'Finite fixture',policy=policy)
            self.assertFalse((self.root/marker).exists())

    def test_standalone_relative_recompute_uses_sidecar_and_refuses_tamper_overwrite(self):
        data,attempts,policy=fixtures11();root=self.root/'package'
        p.seal_package(root,data=data,attempts=attempts,report=b'Finite fixtures; not actual new four acceptance',policy=policy)
        expected=p.sha(root/'MANIFEST.json');output=self.root/'different'/'derived'
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(root/'code/evaluator_publication.py'),'reproduce',
            '--package',str(root),'--out',str(output),'--expected-manifest-sha256',expected],cwd=self.root,capture_output=True,text=True,timeout=20)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual((output/'summary.json').read_bytes(),(root/'results/summary.json').read_bytes())
        with self.assertRaises(ValueError):p.reproduce(root,output,expected)
        (root/p.ATTEMPTS_PATH).write_bytes(b'{}\n')
        with self.assertRaises(ValueError):p.reproduce(root,self.root/'tampered-output',expected)
        self.assertFalse((self.root/'tampered-output').exists())

    def test_additional_same_version_reassessments_use_explicit_followup_and_general_counts(self):
        data,attempts,policy=fixtures11()
        for old in copy.deepcopy(data['assessments'][-4:]):
            old['assessment_id']=uid('additional-'+old['assessment_id']);old['validation_id']=uid('additional-'+old['validation_id'])
            data['assessments'].append(old);data['observation_scopes'][old['assessment_id']]=fixtures.fixture_scope(old)
            policy['expected_assessment_ids'].append(old['assessment_id']);policy['expected_assessment_versions'][old['assessment_id']]=old['evaluation_version']
        summary=p.derive(data,attempts);p.check_policy(data,policy,attempts)
        self.assertEqual(summary['reported_assessment_count'],15);self.assertEqual(summary['all_saved_reassessment_attempt_count'],19)
        self.assertEqual(summary['unique_saved_source_runs'],7);self.assertEqual(summary['complete_observation_count'],4)
        self.assertTrue(all(not r['complete_observation'] and r['quality'] is None for r in summary['assessments'] if r['evaluation_version']=='1.6.0'))
        data['attempt_followups'][attempts['attempts'][0]['assessment_id']]=data['assessments'][-1]['assessment_id']
        with self.assertRaises(ValueError):p.derive(data,attempts)

    def test_wrong_missing_duplicate_or_policy_mismatched_designated_followup_is_denied(self):
        for marker in ('missing','duplicate','wrong-source','wrong-policy'):
            data,attempts,policy=fixtures11();first=attempts['attempts'][0]['assessment_id']
            if marker=='missing':data['attempt_followups'][first]=uid('missing-followup')
            elif marker=='duplicate':data['attempt_followups'][first]=data['attempt_followups'][attempts['attempts'][1]['assessment_id']]
            elif marker=='wrong-source':data['attempt_followups'][first]=data['assessments'][0]['assessment_id']
            else:policy['expected_attempt_followups'][first]=uid('foreign-policy-followup')
            with self.subTest(marker=marker),self.assertRaises(ValueError):p.seal_package(self.root/marker,data=data,attempts=attempts,report=b'Finite fixture',policy=policy)
            self.assertFalse((self.root/marker).exists())


if __name__=='__main__':unittest.main()

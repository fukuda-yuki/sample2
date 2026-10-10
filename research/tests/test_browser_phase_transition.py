"""Bound HTTP/browser phase transitions using opaque, nonmodel fixtures.

No evaluator, app, browser, Docker or provider is started. Composition callbacks
represent already-verified browser evidence; they do not test UI semantics.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from outer.harness import browser_review, evaluate, profiles, runtime, util
from research import saved_reassessment as reassess
from research.tests import test_saved_reassessment as saved_fixtures


def ledger(version='1.6.0'):
    rows=[{'id':f'R-{n:03d}','severity':'major','checks':[]} for n in range(1,32)]
    for n in range(1,34):
        r=1 if n==1 else 24 if n==33 else n-1
        rows[r-1]['checks'].append({'id':f'C-{n:03d}'})
    return {'taskId':'EDU','specVersion':version,'requirements':rows}


def http_files(directory,condition,artifact,*,unknown=False):
    directory.mkdir(parents=True,exist_ok=True)
    spec=ledger(condition['evaluation']['evaluation_version'])
    checks=[];requirements=[]
    for row in spec['requirements']:
        own=[]
        for check in row['checks']:
            state='fail' if unknown and check['id']=='C-012' else 'blocked' if unknown and check['id']=='C-014' else 'pass'
            own.append(state)
            checks.append({'requirementId':row['id'],'checkId':check['id'],'judgement':state,
                'unknownObservations':['finite fixture prerequisite not observed'] if state=='blocked' else [],'observationFaults':[]})
        status='fail' if 'fail' in own else 'blocked' if 'blocked' in own else 'pass'
        requirements.append({'id':row['id'],'severity':'major','judgement':status,
            'failedChecks':[c['checkId'] for c in checks if c['requirementId']==row['id'] and c['judgement']!='pass']})
    result={'taskId':condition['task_id'],'artifactPath':'/artifact','artifactSha256':artifact,
        'specSha256':condition['evaluation']['spec_sha256'],'specVersion':spec['specVersion'],
        'evaluationVersion':spec['specVersion'],'evaluationId':'finite-http-fixture','researchStatus':'incomplete',
        'quality':None,'verdict':'fail' if unknown else 'blocked','evaluatorFaults':[],
        'uncheckedScope':['R-013 finite unknown'] if unknown else [],'browserCartCoverage':'not_run_http_only',
        'browserCartCases':{},'browserCartEvidenceSha256':None,'reviewRunInstanceId':None,
        'baselineEvaluationSha256':None,'baselineResultsSha256':None,'requirements':requirements,
        'requirementCount':31,'passedCount':29 if unknown else 31,'failedCount':1 if unknown else 0,
        'blockedCount':1 if unknown else 0,'errorCount':0,'criticalFailed':[]}
    util.write_new_json(directory/'evaluation.json',result)
    (directory/'results.jsonl').write_text(''.join(json.dumps(c)+'\n' for c in checks),encoding='utf8')
    ids=[c['checkId'] for c in checks]
    util.write_new_json(directory/'evaluator-manifest.json',{'evaluatorSha256':condition['evaluation']['evaluator_sha256'],
        'evaluationVersion':spec['specVersion'],'evaluatorVersion':spec['specVersion'],
        'artifactPath':'/artifact','artifactSha256':artifact,'specSha256':condition['evaluation']['spec_sha256'],
        'ledgerCheckIds':ids,'implementedCheckIds':sorted(ids)})
    return result


class BrowserPhaseTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=saved_fixtures.SavedReassessmentTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root;self.repo=Path(reassess.__file__).resolve().parents[1]
        source=self.fixture.source
        util.write_json_atomic(source/'evaluation-assets/requirements.json',ledger('education-1.0.0'))
        condition=util.read_json(source/'condition.json')
        condition['evaluation']['spec_sha256']=util.sha256_file(source/'evaluation-assets/requirements.json')
        util.write_json_atomic(source/'condition.json',condition)
        (source/'context.json').write_bytes((source/'condition.json').read_bytes())
        manifest=util.read_json(source/'manifest.json')
        manifest.update(condition_sha256=util.sha256_file(source/'condition.json'),
            context_sha256=util.sha256_file(source/'context.json'),assets_sha256=util.tree_hashes(source/'evaluation-assets'))
        util.write_json_atomic(source/'manifest.json',manifest)
        util.write_json_atomic(self.fixture.new_spec,ledger())
        self.before=reassess.byte_inventory(source)

    def prepare(self,version='1.6.0'):
        util.write_json_atomic(self.fixture.new_spec,ledger(version))
        return self.fixture.prepare(evaluation_version=version,repair_contract='finite-phase-fixture')

    def arguments(self,stage,**changes):
        a=util.read_json(stage/'assessment.json');c=util.read_json(stage/'execution-config.json')
        args={'exit_code':2,'timed_out':False,'cleanup_confirmed':True,'stopped':False,
            'frozen':stage/'frozen','artifact_hash':a['source_artifact_sha256'],
            'spec':stage/'evaluation-assets/requirements.json','spec_hash':a['new_spec_sha256'],
            'evaluator_hash':a['evaluator_sha256']}
        args.update(changes);return c,args

    def compose(self,stage,*,unknown=False):
        def complete(*args):
            a=util.read_json(stage/'assessment.json');out=stage/'output';http=out/'http-only'
            result=util.read_json(http/'evaluation.json')
            result.update(researchStatus='incomplete' if unknown else 'complete',quality=None if unknown else 100,
                browserCartCoverage='agent_observed_C-015_C-016',reviewRunInstanceId=a['assessment_id'],
                baselineEvaluationSha256=util.sha256_file(http/'evaluation.json'),
                baselineResultsSha256=util.sha256_file(http/'results.jsonl'),browserCartEvidenceSha256='e'*64)
            util.write_new_json(out/'evaluation.json',result)
            (out/'results.jsonl').write_bytes((http/'results.jsonl').read_bytes())
            (out/'evaluator-manifest.json').write_bytes((http/'evaluator-manifest.json').read_bytes())
            util.write_new_json(out/'browser-cleanup.json',{'confirmed':True,'run_instance_id':a['assessment_id']})
            return 2 if unknown else 0
        return complete

    def execute(self,stage,*,unknown=False,code=2,timed_out=False,cleanup=True,stop=False,mutation=None):
        condition,args=self.arguments(stage)
        def run(*call):
            directory=stage/'output/http-only';http_files(directory,condition,args['artifact_hash'],unknown=unknown)
            if mutation:mutation(directory)
            if stop:(stage/'STOP').write_text('finite fixture stop')
            return code,timed_out
        name='s2-score-'+'1'*32
        with patch.object(reassess.runtime,'scoring_command',return_value=(name,['docker','run','dummy'])),\
             patch.object(reassess.evaluate,'run_evaluator',side_effect=run),\
             patch.object(reassess.browser_cleanup,'cleanup',return_value={'confirmed':cleanup}),\
             patch.object(reassess.browser_review,'complete_evaluation',side_effect=self.compose(stage,unknown=unknown)) as browser,\
             patch.object(reassess.browser_review,'stored_coverage_complete',return_value=True):
            result=reassess.execute(stage,repo=self.repo)
        return result,browser.call_count

    def test_5096_all_33_pass_http_exit_two_continues_to_independent_browser_phase(self):
        stage=self.prepare();result,calls=self.execute(stage)
        self.assertEqual(calls,1,'normal 1.6 HTTP exit2 must not suppress mandatory browser collection')
        self.assertEqual(result['evaluator_exit_code'],2)
        self.assertEqual(result['browser_exit_code'],0)
        self.assertTrue(result['adopted']);self.assertEqual(result['quality'],100)
        self.assertEqual(reassess.byte_inventory(self.fixture.source),self.before)

    def test_partial_http_unknown_and_known_failure_survive_browser_phase(self):
        stage=self.prepare();result,calls=self.execute(stage,unknown=True)
        self.assertEqual(calls,1);self.assertEqual(result['browser_exit_code'],2)
        self.assertFalse(result['adopted']);self.assertIsNone(result['quality'])
        baseline=util.read_json(stage/'output/http-only/evaluation.json');composed=util.read_json(stage/'output/evaluation.json')
        self.assertEqual(baseline['uncheckedScope'],composed['uncheckedScope'])
        self.assertEqual(baseline['requirements'],composed['requirements'])
        self.assertEqual(composed['verdict'],'fail');self.assertIsNone(composed['quality'])

    def test_helper_strict_context_and_metadata_boundaries(self):
        stage=self.prepare();c,args=self.arguments(stage);http=stage/'http';http_files(http,c,args['artifact_hash'])
        self.assertTrue(browser_review.http_phase_eligible(c,http,**args))
        for key,value in [('exit_code',1),('exit_code',True),('exit_code',125),('timed_out',True),
            ('timed_out',0),('cleanup_confirmed',False),('cleanup_confirmed',1),('stopped',True),('stopped',0)]:
            with self.subTest(key=key,value=value):self.assertFalse(browser_review.http_phase_eligible(c,http,**{**args,key:value}))
        original=util.read_json(http/'evaluation.json');manifest=util.read_json(http/'evaluator-manifest.json')
        for change in ({'evaluatorFaults':['observer error']},{'evaluatorFaults':None},{'errorCount':1},
            {'quality':100},{'artifactSha256':'0'*64},{'specSha256':'0'*64},{'evaluationVersion':'1.7.0'},
            {'browserCartCoverage':'observed'},{'browserCartCases':None},{'requirementCount':True},{'researchStatus':'complete'}):
            util.write_json_atomic(http/'evaluation.json',{**original,**change})
            with self.subTest(change=change):self.assertFalse(browser_review.http_phase_eligible(c,http,**args))
        util.write_json_atomic(http/'evaluation.json',original)
        for change in ({'evaluatorSha256':'0'*64},{'ledgerCheckIds':['C-001']},{'implementedCheckIds':['C-001']},
            {'evaluationVersion':'1.5.0'},{'artifactSha256':'0'*64}):
            util.write_json_atomic(http/'evaluator-manifest.json',{**manifest,**change})
            with self.subTest(change=change):self.assertFalse(browser_review.http_phase_eligible(c,http,**args))
        util.write_json_atomic(http/'evaluator-manifest.json',manifest)
        lines=(http/'results.jsonl').read_bytes();(http/'results.jsonl').write_bytes(lines+lines[:lines.index(b'\n')+1])
        self.assertFalse(browser_review.http_phase_eligible(c,http,**args))
        (http/'results.jsonl').write_bytes(lines)
        row=json.loads(lines.splitlines()[0]);row['observationFaults']=['observer fault']
        (http/'results.jsonl').write_bytes(json.dumps(row).encode()+b'\n'+b'\n'.join(lines.splitlines()[1:])+b'\n')
        self.assertFalse(browser_review.http_phase_eligible(c,http,**args))

    def test_saved_no_phase_two_on_fault_timeout_stop_cleanup_or_future_version(self):
        cases=[{'timed_out':True},{'cleanup':False},{'stop':True},{'code':125},
            {'mutation':lambda p:util.write_json_atomic(p/'evaluation.json',{**util.read_json(p/'evaluation.json'),'evaluatorFaults':['fault']})},
            {'mutation':lambda p:util.write_json_atomic(p/'evaluator-manifest.json',{**util.read_json(p/'evaluator-manifest.json'),'evaluatorSha256':'0'*64})}]
        for case in cases:
            with self.subTest(case=list(case)):
                stage=self.prepare();result,calls=self.execute(stage,**case)
                self.assertEqual(calls,0);self.assertFalse(result['adopted']);self.assertIsNone(result['quality'])
        stage=self.prepare('1.7.0');result,calls=self.execute(stage);self.assertEqual(calls,0)

    def test_legacy_code_zero_route_is_preserved_and_exit_two_is_not_expanded(self):
        for version in ('1.4.0','1.5.0'):
            for code in (0,2):
                stage=self.prepare(version);result,calls=self.execute(stage,code=code)
                with self.subTest(version=version,code=code):self.assertEqual(calls,int(code==0))

    def test_music_16_exit_zero_cannot_bypass_phase_or_validation_guards(self):
        stage=self.prepare();c,args=self.arguments(stage);http=stage/'http';http_files(http,c,args['artifact_hash'])
        for change in ({},{'evaluatorFaults':['observer fault'],'artifactSha256':'0'*64}):
            baseline=util.read_json(http/'evaluation.json')
            util.write_json_atomic(http/'evaluation.json',{**baseline,**change})
            with self.subTest(change=change):
                self.assertFalse(browser_review.http_phase_eligible(c,http,**{**args,'exit_code':0}))
        rejected=self.prepare();result,calls=self.execute(rejected,code=0)
        self.assertEqual(calls,0);self.assertFalse(result['adopted'])
        completed=self.prepare();result,calls=self.execute(completed);self.assertEqual(calls,1)
        util.write_json_atomic(completed/'result.json',{**result,'evaluator_exit_code':0})
        before=reassess.byte_inventory(completed)
        with patch.object(reassess.profiles,'validate_run'),\
             patch.object(reassess,'_saved_cleanup_bound',return_value=True),\
             patch.object(reassess.browser_review,'stored_coverage_complete',return_value=True):
            receipt=reassess.revalidate(completed,self.root/'invalid-exit-zero.json',repo=self.repo)
        self.assertFalse(receipt['adopted']);self.assertIsNone(receipt['quality'])
        self.assertEqual(receipt['validation_status'],'invalid_evidence')
        self.assertEqual(reassess.byte_inventory(completed),before)

    def test_pure_saved_validation_accepts_new_composed_exit_two_but_not_baseline_only(self):
        stage=self.prepare();result,calls=self.execute(stage);self.assertEqual(calls,1)
        before=reassess.byte_inventory(stage)
        with patch.object(reassess.profiles,'validate_run'),\
             patch.object(reassess,'_saved_cleanup_bound',return_value=True),\
             patch.object(reassess.browser_review,'stored_coverage_complete',return_value=True):
            receipt=reassess.revalidate(stage,self.root/'validation.json',repo=self.repo)
        self.assertEqual(receipt['validation_status'],'complete_observation');self.assertTrue(receipt['adopted'])
        self.assertEqual(reassess.byte_inventory(stage),before)
        immature=self.prepare();result,calls=self.execute(immature,stop=True);self.assertEqual(calls,0)
        with patch.object(reassess.profiles,'validate_run'),patch.object(reassess,'_saved_cleanup_bound',return_value=True):
            receipt=reassess.revalidate(immature,self.root/'immature-validation.json',repo=self.repo)
        self.assertFalse(receipt['adopted']);self.assertEqual(receipt['validation_status'],'invalid_evidence')

    def test_historical_exit_zero_retrospective_stop_is_preserved_new_exit_two_stop_rejects(self):
        for version,code,accepted in (('1.5.0',0,True),('1.6.0',2,False)):
            with self.subTest(version=version):
                stage=self.prepare(version);result,calls=self.execute(stage,code=code)
                self.assertEqual(calls,1);self.assertTrue(result['adopted'])
                # A STOP added after completed evidence historically did not
                # invalidate code-zero read-only validation. New exit-two
                # eligibility must not bypass its explicit STOP guard.
                (stage/'STOP').write_text('finite post-completion fixture signal')
                before=reassess.byte_inventory(stage)
                with patch.object(reassess.profiles,'validate_run'),\
                     patch.object(reassess,'_saved_cleanup_bound',return_value=True),\
                     patch.object(reassess.browser_review,'stored_coverage_complete',return_value=True):
                    receipt=reassess.revalidate(stage,self.root/('validation-stop-'+version+'.json'),repo=self.repo)
                self.assertEqual(receipt['adopted'],accepted)
                self.assertEqual(receipt['quality'],100 if accepted else None)
                self.assertEqual(reassess.byte_inventory(stage),before)

    def test_ordinary_scorer_uses_same_bound_exit_two_transition(self):
        for stop,code,expected in ((False,2,1),(True,2,0),(False,0,0)):
            with self.subTest(stop=stop,code=code):
                record,calls=self.ordinary_scorer_case(stop=stop,code=code)
                self.assertEqual(calls,expected)
                self.assertEqual(record['scoring_state'],'evaluation_incomplete' if expected else 'evaluator_fault')
                self.assertIsNone(record['quality']);self.assertFalse(record['adopted'])

    def ordinary_scorer_case(self,*,stop,code):
        stage=self.prepare();a=util.read_json(stage/'assessment.json');condition=util.read_json(stage/'execution-config.json')
        condition['evaluation'].update(spec_path='evaluation-assets/requirements.json',catalog_path='evaluation-assets/catalog.json',
            evaluator_build={'source_path':'finite fixture','command':['fixture'],'sdk_version':'8.0.0','sha256_origin':'fixture','clean_worktree':True})
        util.write_json_atomic(stage/'condition.json',condition)
        util.write_new_json(stage/'manifest.json',{'run_id':stage.name,'run_instance_id':a['assessment_id'],'stop_confirmed':True,'submission_fixed':True})
        util.write_new_json(stage/'snapshot.json',{'artifact_sha256':a['source_artifact_sha256']})
        def run(command,*args):
            http=Path(command[command.index('--out')+1]);http_files(http,condition,a['source_artifact_sha256'])
            if stop:(stage/'STOP').write_text('finite ordinary scoring stop')
            return code,False
        def compose(repo,c,frozen,http,published,assets,out,instance,sequence):
            data=util.read_json(http/'evaluation.json');data.update(researchStatus='incomplete',quality=None,
                browserCartCoverage='agent_assessed_C-015_C-016',reviewRunInstanceId=instance)
            util.write_new_json(out/'evaluation.json',data)
            (out/'evaluator-manifest.json').write_bytes((http/'evaluator-manifest.json').read_bytes())
            util.write_new_json(out/'browser-cleanup.json',{'confirmed':True,'run_instance_id':instance})
            return 2
        name='s2-score-'+'2'*32
        def scoring_command(c,f,o,w,a,v,s,*,native_work=False):
            self.assertFalse(native_work)
            return name,['docker','run','--out',str(o)]
        with patch.object(profiles,'validate_run'),\
             patch.object(runtime,'scoring_command',side_effect=scoring_command),\
             patch.object(runtime,'docker',return_value=SimpleNamespace(returncode=0)),\
             patch.object(evaluate,'run_evaluator',side_effect=run),\
             patch.object(evaluate.browser_cart,'complete_evaluation',side_effect=compose) as browser:
            record=evaluate.score_run(self.repo,stage.parent,stage.name)
        return record,browser.call_count


if __name__=='__main__':unittest.main()

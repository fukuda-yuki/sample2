"""No provider, Docker mutation, external writes or real reassessment."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from outer.harness import util
from research import campaign_recovery as subject, live_pilot


def arm(classification='already_evaluable', *, technical=False, send='observed_send', opportunity='already_observed'):
    return dict(observation={'classification':classification,'quality':0},
        assessment_adopted=False,opportunity=opportunity,
        usage={'send_evidence':send,'journal_errors':[],'transmission_issues':[]},
        technical_evidence=[{'category':'provider'}] if technical else [])


class DecisionTests(unittest.TestCase):
    def test_quality_zero_and_fail_are_valid(self):
        arms={'explore':arm(),'preload':arm()}
        for a in arms.values(): a['observation']['verdict']='fail_critical'
        self.assertEqual(subject.decide_pair(arms),'accept_same_attempt')

    def test_normal_generated_build_failure_is_valid_with_null_quality(self):
        arms={'explore':arm('normal_product_failure_partial_observation'),'preload':arm()}
        arms['explore']['observation'].update(quality=None,valid_product_failure=True)
        self.assertEqual(subject.decide_pair(arms),'accept_same_attempt')

    def test_timeout_or_generated_failure_alone_never_replaces(self):
        arms={'explore':arm('held_unresolved_evidence',opportunity='not_applicable'),'preload':arm()}
        arms['explore']['observation']['reason']='run timeout or generated code failed'
        self.assertEqual(subject.decide_pair(arms),'held')

    def test_terminal_provider_fault_after_saved_opportunity_can_replace_whole_pair(self):
        arms={'explore':arm('technical_observation_incomplete',technical=True,opportunity='exhausted'),'preload':arm()}
        self.assertEqual(subject.decide_pair(arms),'replacement_eligible')

    def test_unknown_send_never_blindly_replaced(self):
        arms={'explore':arm('held_unresolved_evidence',technical=True,send='unknown',opportunity='not_applicable'),'preload':arm()}
        self.assertEqual(subject.decide_pair(arms),'held')

    def test_ambiguous_saved_assessment_holds(self):
        arms={'explore':arm('technical_observation_incomplete',technical=True,opportunity='ambiguous'),'preload':arm()}
        self.assertEqual(subject.decide_pair(arms),'held')

    def test_same_attempt_assessment_adoption(self):
        arms={'explore':arm('technical_observation_incomplete',opportunity='exhausted'),'preload':arm()}
        arms['explore']['assessment_adopted']=True
        self.assertEqual(subject.decide_pair(arms),'accept_same_attempt')

    def test_newly_reassessed_product_failure_never_replaces_original_technical_fault(self):
        arms={'explore':arm('technical_observation_incomplete',technical=True,opportunity='exhausted'),'preload':arm()}
        arms['explore']['assessment_valid_product_failure']=True
        arms['explore']['reassessed_quality']=None
        self.assertEqual(subject.decide_pair(arms),'accept_same_attempt')

    def test_exact_two_conditions_required(self):
        with self.assertRaises(ValueError):subject.decide_pair({'explore':arm()})


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'run';self.root.mkdir()
        self.case=dict(run_id='run',run_instance_id='a'*32,condition='explore',pair=1)

    def journal(self,name,rows):
        path=self.root/'usage/raw'/(name+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
        return path

    def row(self,**extra):
        return dict(run_id='run',session_id='a'*32,request_id='req',**extra)

    def test_missing_usage_is_unknown_not_zero(self):
        result=subject.usage_evidence(self.root,self.case)
        self.assertIsNone(result['total_tokens']);self.assertTrue(result['usage_unknown'])
        self.assertEqual(result['send_evidence'],'known_no_send')

    def test_partial_usage_retains_observed_lower_bound(self):
        self.journal('started',[self.row()])
        self.journal('events',[self.row(status='provider_error',http_status=503,
            usage={'input_tokens':40},usage_complete=False,send_evidence='observed_send')])
        result=subject.usage_evidence(self.root,self.case)
        self.assertEqual(result['observed_tokens']['input_tokens'],40)
        self.assertIsNone(result['total_tokens']);self.assertEqual(len(result['technical_evidence']),1)

    def test_cancelled_or_completed_timeout_is_not_provider_fault(self):
        self.journal('events',[self.row(status='cancelled',error_type='TimeoutError')])
        self.assertEqual(subject.usage_evidence(self.root,self.case)['technical_evidence'],[])

    def test_wrong_uuid_is_held_and_not_added_to_tokens(self):
        self.journal('events',[dict(self.row(status='provider_error',usage={'input_tokens':999,'output_tokens':1}),session_id='b'*32)])
        result=subject.usage_evidence(self.root,self.case)
        self.assertTrue(result['journal_errors']);self.assertEqual(sum(result['observed_tokens'].values()),0)

    def test_malformed_journal_preserves_fault(self):
        self.journal('started',[self.row()]).write_text('{broken\n',encoding='utf-8')
        self.assertTrue(subject.usage_evidence(self.root,self.case)['journal_errors'])

    def test_known_no_send_terminal_is_reconciled(self):
        self.journal('started',[self.row()])
        self.journal('events',[self.row(status='transport_error',send_evidence='known_no_send')])
        result=subject.usage_evidence(self.root,self.case)
        self.assertEqual(result['send_evidence'],'known_no_send')
        self.assertIsNone(result['total_tokens'])

    def test_one_observed_response_does_not_resolve_another_missing_terminal(self):
        self.journal('started',[self.row(),dict(self.row(),request_id='second')])
        self.journal('events',[self.row(status='provider_error',send_evidence='observed_send',http_status=503)])
        result=subject.usage_evidence(self.root,self.case)
        self.assertIn('unreconciled_request_terminal_inventory',result['transmission_issues'])


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.repo=self.base/'repo';self.repo.mkdir()
        self.batch=self.base/'campaign';self.batch.mkdir()
        lock=self.batch/'_control/dispatch.lock';lock.parent.mkdir();lock.write_bytes(b'0')
        self.wave=self.batch/'waves'/'w'/'spec.json';self.wave.parent.mkdir(parents=True)
        self.epoch=self.base/'epoch';self.epoch.mkdir()
        self.cases=[dict(run_id=condition,condition=condition,run_instance_id=character*32,pair=1)
            for condition,character in [('explore','a'),('preload','b')]]
        self.pair=self.epoch/'pair-1';self.pair.mkdir()
        for case in self.cases:
            root=self.pair/case['run_id'];root.mkdir();(root/'STOP').write_text('original stop')
            (root/'private-original.bin').write_bytes(b'private-original')
        (self.pair/'journal.jsonl').write_text('original-journal')
        util.write_new_json(self.wave,{'pairs':[1]})
        self.plan=self.base/'plan.json';util.write_new_json(self.plan,{'fixed':100})
        self.launch=self.wave.parent/'_launcher'/'result.json';util.write_new_json(self.launch,{'retained':True})
        self.context=dict(repo=self.repo,plan={'batch':str(self.batch),'protected_roots':[],
            'source_commit':'f'*40,'bounds':{'retry_backoff_seconds':[60,300,900,3600]}},
            campaign=live_pilot.reference(self.plan),wave_ref=live_pilot.reference(self.wave),
            epoch={'batch':str(self.epoch)},wave_path=self.wave,
            wave={'pairs':[1],'assignments':[{'pair':1,'cases':self.cases}],
                'epoch_plan':{'path':str(self.base/'unused.json'),'sha256':'e'*64}})
        self.destination=self.base/'recovery'
        self.stack=[]
        for obj,name,kwargs in [(subject,'_context',{'return_value':self.context}),
                (subject,'_owned_closure',{'return_value':live_pilot.reference(self.launch)}),
                (subject.assessment,'classify',{'return_value':{'classification':'held_unresolved_evidence','recoverable':False}})]:
            patcher=patch.object(obj,name,**kwargs);patcher.start();self.addCleanup(patcher.stop)
        from research import repaired_campaign
        patcher=patch.object(repaired_campaign,'ledger',return_value=[{'kind':'pair_attempt_reserved','slot':1}])
        patcher.start();self.addCleanup(patcher.stop)

    def recover(self):
        return subject.recover_wave(self.repo,self.plan,self.wave,self.destination)

    def test_full_originals_archived_and_unchanged(self):
        before=subject.assessment.saved.byte_inventory(self.pair)
        ref=self.recover();value=subject._read(ref)
        self.assertEqual(before,subject.assessment.saved.byte_inventory(self.pair))
        self.assertEqual(value['decisions']['1']['disposition'],'held')
        self.assertEqual(value['initial_logical_denominator'],100)
        self.assertEqual(value['backoff_seconds'],60)
        package=subject.preserve.verify(self.destination/'private-archive',value['original_archive']['package_id'],value['original_archive']['sha256'])
        self.assertIn('pair-1/explore/private-original.bin',package['files'])
        self.assertIn('pair-1/explore/STOP',package['files'])
        self.assertEqual(ref,self.recover())

    def test_original_change_invalidates_decision(self):
        ref=self.recover();(self.pair/'explore/STOP').write_text('changed')
        with self.assertRaisesRegex(ValueError,'Original fault evidence changed'):
            subject.validate_recovery(self.repo,ref,self.plan,self.wave)

    def test_unknown_new_original_file_invalidates_decision(self):
        ref=self.recover();(self.wave.parent/'other.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Unexpected additions'):
            subject.validate_recovery(self.repo,ref,self.plan,self.wave)

    def test_exact_append_only_campaign_wrapper_is_allowed(self):
        ref=self.recover();closure=self.destination/'closure.json';util.write_new_json(closure,{'fixture':True})
        util.write_new_json(self.wave.parent/'recovery-closure.json',dict(wave=self.context['wave_ref'],closed=True,
            recovery=live_pilot.reference(closure)))
        subject.validate_recovery(self.repo,ref,self.plan,self.wave)

    def test_public_projection_omits_private_logs_paths_and_program_bytes(self):
        ref=self.recover();public=self.base/'public-fault'
        with patch.object(subject.sharing,'scan',return_value=None):
            subject.stage_public(self.repo,ref,1,public)
        raw=(public/'public/fault-data.json').read_text(encoding='utf-8')
        self.assertNotIn(str(self.base),raw)
        self.assertNotIn('private-original"',raw)
        files=subject.sharing.inventory(public/'public')
        self.assertEqual(set(files),{'fault-data.json','MANIFEST.json','README.md','reproduce.py'})
        extracted=subject._extract(public/'public',public/'extraction.json')
        self.assertEqual(subject._read(extracted),subject._public_data(subject._read(ref),1))

    def test_publication_without_exact_review_never_calls_transport(self):
        ref=self.recover();public=self.base/'public-fault'
        with patch.object(subject.sharing,'scan',return_value=None):subject.stage_public(self.repo,ref,1,public)
        review=self.base/'review.json';util.write_new_json(review,{'publication_approved':True,'reviewed_inventory':{}})
        with patch.object(subject.delivery,'publish') as publish,self.assertRaisesRegex(ValueError,'Exact public-byte'):
            subject.share_public(self.repo,ref,1,public,review)
        publish.assert_not_called()

    def test_recoverable_arm_assessed_once_and_same_instance_adopted(self):
        assessment_root=self.base/'fake-assessment';assessment_root.mkdir()
        result=assessment_root/'result.json';util.write_new_json(result,{'fixture':True})
        ref=live_pilot.reference(result)
        def verified(**kwargs):
            return dict(adopted=True,quality=0,source_run_instance_id=self.cases[0]['run_instance_id'])
        ctx=self.context;case=self.cases[0]
        with patch.object(subject.assessment,'classify',return_value={'classification':'technical_scoring_missing','recoverable':True}), \
             patch.object(subject.assessment,'prepare',return_value=ref) as prepare, \
             patch.object(subject.assessment,'execute',return_value=ref) as execute, \
             patch.object(subject.assessment,'revalidate',side_effect=verified):
            one=subject._assess_arm(ctx,case,self.pair/case['run_id'],self.base/'arm-assessment')
            two=subject._assess_arm(ctx,case,self.pair/case['run_id'],self.base/'arm-assessment')
        self.assertEqual(one,two);self.assertTrue(one['assessment_adopted'])
        self.assertEqual(prepare.call_count,1);self.assertEqual(execute.call_count,1)

    def test_interrupted_assessment_is_not_repeated(self):
        holder=self.base/'arm-assessment';util.write_new_json(holder/'assessment-intent.json',{'started':True})
        case=self.cases[0]
        with patch.object(subject.assessment,'classify',return_value={'classification':'technical_scoring_missing','recoverable':True}), \
             patch.object(subject.assessment,'prepare') as prepare,patch.object(subject.assessment,'execute') as execute:
            one=subject._assess_arm(self.context,case,self.pair/case['run_id'],holder)
        self.assertEqual(one['opportunity'],'ambiguous');prepare.assert_not_called();execute.assert_not_called()

    def test_new_assessment_product_failure_stays_valid_and_nonnumeric(self):
        result=self.base/'assessment-result.json';util.write_new_json(result,{'fixture':True})
        ref=live_pilot.reference(result);case=self.cases[0]
        with patch.object(subject.assessment,'classify',return_value={'classification':'technical_scoring_missing','recoverable':True}), \
             patch.object(subject.assessment,'prepare',return_value=ref), \
             patch.object(subject.assessment,'execute',return_value=ref), \
             patch.object(subject.assessment,'revalidate',return_value=dict(adopted=False,valid_product_failure=True,
                 classification='normal_product_failure_partial_observation',quality=None,
                 source_run_instance_id=case['run_instance_id'])):
            observed=subject._assess_arm(self.context,case,self.pair/case['run_id'],self.base/'product-failure')
        self.assertTrue(observed['valid_data']);self.assertTrue(observed['assessment_valid_product_failure'])
        self.assertFalse(observed['assessment_adopted']);self.assertIsNone(observed['reassessed_quality'])
        self.assertEqual(subject.decide_pair({'explore':observed,'preload':arm()}),'accept_same_attempt')

    def test_mocked_release_restore_cleanup_and_bound_closure(self):
        ref=self.recover();workspace=self.base/'public-fault'
        with patch.object(subject.sharing,'known_secret',return_value=b'fixture-scan-secret-never-transmitted'):
            subject.stage_public(self.repo,ref,1,workspace)
            review=self.base/'review.json'
            # Noncanonical formatting exercises preservation of exact review bytes.
            review.write_text(json.dumps({'publication_approved':True,
                'reviewed_inventory':subject.sharing.inventory(workspace/'public')}),encoding='utf-8')
            state={}
            def publish(package,tag,commit,**kwargs):
                asset=subject.delivery.verify_package(package)
                names=[p['name'] for p in asset['parts']]+['pair.manifest.json','public-review.json','scan.json']
                state['remote']=dict(id=101,tag_name=tag,
                    html_url='https://github.com/'+subject.delivery.REPOSITORY+'/releases/tag/'+tag,
                    assets=[dict(id=i+1,name=n,size=(package/n).stat().st_size,
                        digest='sha256:'+util.sha256_file(package/n),
                        browser_download_url='https://github.com/'+subject.delivery.REPOSITORY+'/releases/download/'+tag+'/'+n)
                        for i,n in enumerate(names)])
                return {r['name']:r['browser_download_url'] for r in state['remote']['assets']}
            def download(url,target):
                target.write_bytes((workspace/'package'/Path(urlparse(url).path).name).read_bytes())
            with patch.object(subject.delivery,'publish',side_effect=publish), \
                 patch.object(subject.delivery,'release',side_effect=lambda tag:state['remote']), \
                 patch.object(subject.delivery,'gh',return_value=json.dumps({'object':{'type':'commit','sha':'f'*40}})), \
                 patch.object(subject.delivery,'download',side_effect=download):
                gate=subject.share_public(self.repo,ref,1,workspace,review)
        self.assertFalse((workspace/'public').exists());self.assertFalse((workspace/'package').exists())
        subject._verify_publication(gate,ref,1)
        closure=subject.close_recovery(self.repo,self.plan,self.wave,ref,{'1':gate})
        verified=subject.validate_closure(self.repo,self.plan,self.wave,closure)
        self.assertTrue(verified['closed']);self.assertFalse(verified['acquisition_success'])
        self.assertEqual(verified['decisions']['1']['disposition'],'held')
        self.assertEqual(closure,subject.close_recovery(self.repo,self.plan,self.wave,ref,{'1':gate}))
        # Simulated gate-write interruption: only this test's own generated
        # private fixture gate is removed; publication files remain immutable.
        Path(gate['path']).unlink()
        with patch.object(subject.delivery,'publish') as forbidden:
            recovered=subject.share_public(self.repo,ref,1,workspace,review)
        forbidden.assert_not_called();self.assertEqual(gate,recovered)


if __name__=='__main__':unittest.main()

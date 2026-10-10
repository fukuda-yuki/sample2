"""No provider, Docker mutation, external writes or real reassessment."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
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

    def test_versioned_technical_retry_retains_unknown_usage(self):
        arms={'explore':arm('held_unresolved_evidence',technical=True,send='unknown',opportunity='not_applicable'),'preload':arm()}
        arms['explore']['usage']['transmission_issues'] = ['terminal_missing']
        before = copy.deepcopy(arms)
        self.assertEqual(subject.decide_pair(arms, subject.TECHNICAL_RETRY_POLICY), 'replacement_eligible')
        self.assertEqual(arms, before)
        self.assertEqual(subject.decide_pair(arms), 'held')

    def test_versioned_retry_cannot_replace_low_quality_or_unclassified_failure(self):
        self.assertEqual(subject.decide_pair({'explore':arm(),'preload':arm()}, subject.TECHNICAL_RETRY_POLICY), 'accept_same_attempt')
        arms={'explore':arm('held_unresolved_evidence',send='unknown',opportunity='not_applicable'),'preload':arm()}
        self.assertEqual(subject.decide_pair(arms, subject.TECHNICAL_RETRY_POLICY), 'held')

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

    def test_cancelled_null_usage_preserves_prior_observed_tokens(self):
        self.journal('started',[dict(self.row(),request_id='completed'),self.row()])
        self.journal('events',[
            dict(self.row(status='completed',usage={'input_tokens':40,'output_tokens':2},usage_complete=True),request_id='completed'),
            self.row(status='cancelled',usage=None,usage_complete=False,send_evidence='observed_send')])
        result=subject.usage_evidence(self.root,self.case)
        self.assertEqual(result['observed_tokens'],{'input_tokens':40,'output_tokens':2})
        self.assertIsNone(result['total_tokens'])
        self.assertTrue(result['usage_unknown'])
        self.assertEqual(result['technical_evidence'],[])

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
            util.write_new_json(root/'manifest.json',dict(run_id=case['run_id'],
                run_instance_id=case['run_instance_id'],end_reason='operator_stop'))
            # One recorded request keeps these preservation fixtures held under
            # the confirmed no-send replacement rule.
            started=root/'usage'/'raw'/'started.jsonl';started.parent.mkdir(parents=True)
            started.write_bytes((json.dumps(dict(run_id=case['run_id'],session_id=case['run_instance_id'],
                request_id='fixture-request'))+'\n').encode())
        (self.pair/'journal.jsonl').write_text('original-journal')
        util.write_new_json(self.wave,{'pairs':[1]})
        self.plan=self.base/'plan.json';util.write_new_json(self.plan,{'fixed':100})
        self.launch=self.wave.parent/'_launcher'/'result.json';util.write_new_json(self.launch,{'retained':True})
        self.context=dict(repo=self.repo,plan={'batch':str(self.batch),'protected_roots':[], 'source_pins':{},
            'source_commit':'f'*40,'bounds':{'retry_backoff_seconds':[60,300,900,3600]}},
            campaign=live_pilot.reference(self.plan),wave_ref=live_pilot.reference(self.wave),
            epoch={'batch':str(self.epoch)},wave_path=self.wave,
            wave={'pairs':[1],'assignments':[{'pair':1,'cases':self.cases}],
                'epoch_plan':{'path':str(self.base/'unused.json'),'sha256':'e'*64}})
        self.destination=self.base/'recovery'
        self.controller=dict(kind=subject.CONTROLLER_KIND, source_repo=str(self.base/'separate-controller'),
            source_commit='c'*40, source_pins={'research/campaign_recovery.py':'d'*64},
            pins_sha256=subject._pins_digest({'research/campaign_recovery.py':'d'*64}),
            entrypoint='research/campaign_recovery.py',clean_committed_at_creation=True)
        self.stack=[]
        for obj,name,kwargs in [(subject,'_context',{'return_value':self.context}),
                (subject,'_owned_closure',{'return_value':live_pilot.reference(self.launch)}),
                (subject,'_capture_controller',{'return_value':self.controller}),
                (subject,'_validate_controller',{'side_effect':lambda value,plan:value}),
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
        self.assertEqual(value['source_commit'],'f'*40)
        self.assertEqual(value['recovery_controller'],self.controller)
        self.assertEqual(util.read_json(self.destination/'intent.json')['recovery_controller'],self.controller)
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
        facts=json.loads(raw)
        self.assertEqual(facts['acquisition_source_commit'],'f'*40)
        self.assertEqual(facts['recovery_controller_commit'],'c'*40)
        self.assertEqual(facts['recovery_controller_pins_sha256'],self.controller['pins_sha256'])
        self.assertEqual(facts['arms']['explore']['acquisition_end_reason'],'operator_stop')
        self.assertTrue(facts['arms']['explore']['acquisition_end_reason_observed'])
        self.assertNotIn('private-original"',raw)
        files=subject.sharing.inventory(public/'public')
        self.assertEqual(set(files),{'fault-data.json','MANIFEST.json','README.md','reproduce.py'})
        extracted=subject._extract(public/'public',public/'extraction.json')
        self.assertEqual(subject._read(extracted),subject._public_data(subject._read(ref),1))

    def test_creation_controller_rejection_writes_no_output_or_originals(self):
        before=subject.complete_byte_inventory(self.epoch)
        with patch.object(subject,'_capture_controller',side_effect=ValueError('Uncommitted controller')):
            with self.assertRaisesRegex(ValueError,'Uncommitted controller'):
                self.recover()
        self.assertFalse(self.destination.exists())
        self.assertEqual(before,subject.complete_byte_inventory(self.epoch))

    def test_decision_controller_tamper_disagrees_with_intent(self):
        ref=self.recover();value=subject._read(ref)
        value['recovery_controller']['source_commit']='e'*40
        util.write_json_atomic(Path(ref['path']),value)
        with self.assertRaisesRegex(ValueError,'immutable intent'):
            subject.validate_recovery(self.repo,live_pilot.reference(ref['path']),self.plan,self.wave)

    def test_existing_decision_uses_recorded_controller_not_new_capture(self):
        ref=self.recover()
        with patch.object(subject,'_capture_controller',side_effect=AssertionError('must not recapture')):
            self.assertEqual(ref,self.recover())

    def test_missing_controller_provenance_is_rejected(self):
        ref=self.recover();value=subject._read(ref)
        del value['recovery_controller']
        util.write_json_atomic(Path(ref['path']),value)
        with self.assertRaisesRegex(ValueError,'immutable intent'):
            subject.validate_recovery(self.repo,live_pilot.reference(ref['path']),self.plan,self.wave)

    def test_changed_acquisition_end_reason_is_rejected(self):
        ref=self.recover();value=subject._read(ref)
        value['decisions']['1']['arms']['explore']['acquisition_outcome']['end_reason']='completed'
        util.write_json_atomic(Path(ref['path']),value)
        with self.assertRaisesRegex(ValueError,'preserved acquisition end reason'):
            subject.validate_recovery(self.repo,live_pilot.reference(ref['path']),self.plan,self.wave)

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

    def test_owned_cleanup_receipts_appended_after_recovery_are_accepted(self):
        evaluation=self.pair/'explore'/'evaluations'/('attempt-1-'+'f'*32)
        util.write_new_json(evaluation/'browser-resources.json',{'owner':'s2-browser-'+'1'*32})
        ref=self.recover()
        receipts=evaluation/'browser-cleanup-attempts'
        util.write_new_json(receipts/(('2'*32)+'-1-intent.json'),{'intent':True})
        util.write_new_json(receipts/(('2'*32)+'-result.json'),{'confirmed':True})
        (receipts/'index.jsonl').write_text('{}\n')
        with patch.object(subject.assessment.saved,'_saved_cleanup_bound',return_value=True) as bound:
            subject.validate_recovery(self.repo,ref,self.plan,self.wave)
        bound.assert_called_with(evaluation,self.cases[0]['run_instance_id'])
        with patch.object(subject.assessment.saved,'_saved_cleanup_bound',return_value=False):
            with self.assertRaisesRegex(ValueError,'Unexpected additions'):
                subject.validate_recovery(self.repo,ref,self.plan,self.wave)

    def test_other_additions_or_changed_receipts_remain_rejected(self):
        evaluation=self.pair/'explore'/'evaluations'/('attempt-1-'+'f'*32)
        util.write_new_json(evaluation/'browser-resources.json',{'owner':'s2-browser-'+'1'*32})
        ref=self.recover()
        with patch.object(subject.assessment.saved,'_saved_cleanup_bound',return_value=True):
            for name in ('browser-cleanup-attempts/notes.json','other/'+'2'*32+'-result.json'):
                with self.subTest(name=name):
                    extra=evaluation/name;util.write_new_json(extra,{})
                    with self.assertRaisesRegex(ValueError,'Unexpected additions'):
                        subject.validate_recovery(self.repo,ref,self.plan,self.wave)
                    extra.unlink()
            (evaluation/'browser-resources.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError,'Original fault evidence changed'):
                subject.validate_recovery(self.repo,ref,self.plan,self.wave)

    def owned_authority(self,policy=None,predecessor=True):
        from research import repaired_campaign
        plan=self.base/'successor-plan.json'
        if plan.exists():plan.unlink()
        util.write_new_json(plan,dict(policy=policy or repaired_campaign.policy(),
            predecessor={'plan':self.context['campaign']} if predecessor else {}))
        return dict(repo=str(self.base/'successor-repo'),plan=live_pilot.reference(plan))

    def test_owned_completion_publishes_nothing_and_closes_bound_recovery(self):
        from research import repaired_campaign
        ref=self.recover();authority=self.owned_authority()
        with patch.object(repaired_campaign,'validate',side_effect=lambda repo,path:util.read_json(path)), \
             patch.object(subject.delivery,'publish',side_effect=AssertionError('no publication')), \
             patch.object(subject.delivery,'package',side_effect=AssertionError('no package')):
            closure=subject.close_recovery(self.repo,self.plan,self.wave,ref,None,owned_authority=authority)
            verified=subject.validate_closure(self.repo,self.plan,self.wave,closure)
            self.assertEqual(closure,subject.close_recovery(self.repo,self.plan,self.wave,ref,None,owned_authority=authority))
        gate=util.read_json(self.destination/'owned-recovery-gate-1.json')
        self.assertEqual(gate['kind'],subject.OWNED_GATE_KIND);self.assertFalse(gate['publication_performed'])
        self.assertFalse(gate['acquisition_success']);self.assertEqual(gate['disposition'],'held')
        self.assertTrue(verified['closed']);self.assertFalse(verified['acquisition_success'])

    def test_owned_completion_requires_owned_policy_authority(self):
        from research import repaired_campaign
        ref=self.recover()
        with patch.object(repaired_campaign,'validate',side_effect=lambda repo,path:util.read_json(path)):
            with self.assertRaisesRegex(ValueError,'owned-policy authority'):
                subject.close_recovery(self.repo,self.plan,self.wave,ref,None)
            with self.assertRaisesRegex(ValueError,'owned closure policy'):
                subject.close_recovery(self.repo,self.plan,self.wave,ref,None,
                    owned_authority=self.owned_authority(policy=repaired_campaign.legacy_policy()))
            with self.assertRaisesRegex(ValueError,'direct successor'):
                subject.close_recovery(self.repo,self.plan,self.wave,ref,None,
                    owned_authority=self.owned_authority(predecessor=False))
        self.assertFalse((self.destination/'closure.json').exists())

    def test_owned_gate_tamper_is_rejected(self):
        from research import repaired_campaign
        ref=self.recover();authority=self.owned_authority()
        with patch.object(repaired_campaign,'validate',side_effect=lambda repo,path:util.read_json(path)):
            closure=subject.close_recovery(self.repo,self.plan,self.wave,ref,None,owned_authority=authority)
            for key,value in [('disposition','accept_same_attempt'),('publication_performed',True),('acquisition_success',True)]:
                with self.subTest(key=key):
                    path=self.destination/'owned-recovery-gate-1.json';original=util.read_json(path)
                    util.write_json_atomic(path,dict(original,**{key:value}))
                    with self.assertRaises(ValueError):
                        subject._verify_publication(live_pilot.reference(path),ref,1)
                    util.write_json_atomic(path,original)
            subject.validate_closure(self.repo,self.plan,self.wave,closure)

    def test_historical_owned_gate_without_authority_still_validates(self):
        ref=self.recover();value=subject._read(ref)
        path=self.destination/'owned-recovery-gate-1.json'
        util.write_new_json(path,dict(kind=subject.OWNED_GATE_KIND,recovery=ref,slot=1,campaign=value['campaign'],
            wave=value['wave'],source_commit=value['source_commit'],quality_acceptance=False,acquisition_success=False,
            publication_performed=False,disposition='held'))
        self.assertEqual(subject._verify_publication(live_pilot.reference(path),ref,1)['disposition'],'held')

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


class ControllerProvenanceTests(unittest.TestCase):
    """Synthetic committed checkout; Git blob reads are mocked, never mutated."""

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name)/'recorded-v2';self.repo.mkdir()
        self.plan={'source_pins':{'profiles/acquisition.json':'a'*64}}
        names=subject.CONTROLLER_MINIMUM | {'research/repair_spec.py','research/another_helper.py',
            'outer/harness/util.py','inner/browser/observer.cjs','profiles/acquisition.json'}
        for name in names:
            path=self.repo/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(('synthetic-controller:'+name).encode('utf-8'))
        pins={name:util.sha256_file(self.repo/name) for name in sorted(names)}
        self.value=dict(kind=subject.CONTROLLER_KIND,source_repo=str(self.repo),source_commit='c'*40,
            source_pins=pins,pins_sha256=subject._pins_digest(pins),
            entrypoint='research/campaign_recovery.py',clean_committed_at_creation=True)
        self.git=patch.object(subject.repaired_runtime,'_git',
            side_effect=lambda repo,*args:'c'*40 if args==('rev-parse','HEAD') else '')
        self.git_mock=self.git.start();self.addCleanup(self.git.stop)
        self.blobs=patch.object(subject.repaired_runtime,'_committed_files')
        self.blob_mock=self.blobs.start();self.addCleanup(self.blobs.stop)

    def validate(self,value=None):
        return subject._validate_controller(self.value if value is None else value,self.plan)

    def test_historical_record_validates_from_future_import_location(self):
        with patch.object(subject,'__file__',str(self.repo.parent/'future-v3/research/campaign_recovery.py')):
            self.assertEqual(self.validate(),self.value)
        self.blob_mock.assert_called_once_with(self.repo,'c'*40,self.value['source_pins'])
        self.assertTrue(all(call.args[0]==self.repo for call in self.git_mock.call_args_list))

    def test_recorded_controller_byte_change_is_rejected(self):
        (self.repo/'outer/harness/preserve.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source changed'):
            self.validate()

    def test_declared_pin_change_cannot_hide_source_change(self):
        self.value['source_pins']['outer/harness/preserve.py']='0'*64
        self.value['pins_sha256']=subject._pins_digest(self.value['source_pins'])
        with self.assertRaisesRegex(ValueError,'source changed'):
            self.validate()

    def test_required_helper_omission_is_rejected_even_with_matching_digest(self):
        del self.value['source_pins']['outer/harness/preserve.py']
        self.value['pins_sha256']=subject._pins_digest(self.value['source_pins'])
        with self.assertRaisesRegex(ValueError,'pins are incomplete'):
            self.validate()

    def test_pin_digest_change_is_rejected(self):
        self.value['pins_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Invalid recovery controller provenance'):
            self.validate()

    def test_wrong_commit_is_rejected(self):
        self.value['source_commit']='d'*40
        with self.assertRaisesRegex(ValueError,'checkout changed'):
            self.validate()

    def test_wrong_source_repo_is_rejected(self):
        self.value['source_repo']=str(self.repo.parent/'not-controller')
        with self.assertRaises((ValueError,FileNotFoundError)):
            self.validate()

    def test_committed_blob_mismatch_is_not_accepted(self):
        self.blob_mock.side_effect=ValueError('Current file differs from committed Git blob')
        with self.assertRaisesRegex(ValueError,'committed Git blob'):
            self.validate()

    def test_dirty_recorded_checkout_is_rejected(self):
        self.git_mock.side_effect=lambda repo,*args:'c'*40 if args==('rev-parse','HEAD') else ' M changed.py'
        with self.assertRaisesRegex(ValueError,'checkout changed'):
            self.validate()

    def test_capture_binds_actual_imported_repo_not_acquisition_pins(self):
        actual=Path(subject.__file__).resolve().parents[1]
        value=subject._capture_controller({'source_pins':{'research/campaign_recovery.py':'0'*64}})
        self.assertEqual(value['source_repo'],str(actual))
        self.assertEqual(value['source_pins']['research/campaign_recovery.py'],
            util.sha256_file(actual/'research/campaign_recovery.py'))
        self.assertNotEqual(value['source_repo'],str(self.repo))

    def test_capture_rejects_mixed_import_checkouts(self):
        foreign=SimpleNamespace(__file__=str(self.repo/'research/another_helper.py'))
        with patch.dict(subject.sys.modules,{'research.foreign_recovery_fixture':foreign}):
            with self.assertRaisesRegex(ValueError,'different source checkout'):
                subject._capture_controller({'source_pins':{}})

    def test_capture_pins_imported_nested_reader_without_changing_historical_minimum(self):
        from research.public_readers import evaluator_publication_schema1 as reader
        actual=Path(subject.__file__).resolve().parents[1]
        name=Path(reader.__file__).resolve().relative_to(actual).as_posix()
        self.assertNotIn(name,subject._controller_names(actual,{'source_pins':{}}))
        value=subject._capture_controller({'source_pins':{}})
        self.assertEqual(value['source_pins'][name],util.sha256_file(actual/name))


if __name__=='__main__':unittest.main()

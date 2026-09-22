"""Bounded revision/continuation tests in private synthetic repositories only.

Model dispatch, profile verification and environment readiness are stand-ins.
The real journal, approval, proposal, seal, comparison, adoption, recovery,
observation, analysis, public staging and relocated-reader code paths run.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research import catalog_date_revision as revision, catalog_identity as identity
from research import catalog_execution as execution, catalog_share as sharing
from research import catalog_delivery as delivery, catalog_confirmatory as analysis
from research import catalog_observations as observations, catalog_pilot as pilot
from research.catalog_allocation_review import read, sha256, write_new
from research.tests.test_catalog_identity import run_input, body, save_request

REPO = Path(__file__).resolve().parents[2]


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.old = read(REPO / revision.OLD_PATH)
        for name in [revision.OLD_PATH, *self.old['execution']['code_hashes'], *revision.ADDED_CODE,
                     'inner/spec/requirements.json', 'inner/spec/requirements-1.2.0.json']:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, target)
        shutil.copytree(REPO / 'research/sharing', self.repo / 'research/sharing', dirs_exist_ok=True)
        self.batch = self.repo / self.old['runs_dir']
        self.control = self.batch / '_control'
        self.control.mkdir(parents=True)
        self.root = self.batch / self.old['slots'][0]['run_id']
        self.baseline = self.repo / self.old['probe'] / 'MS1-001-catalog-expanded-001'
        run_input(self.root, 'Tue Sep 22 2026'); run_input(self.baseline, 'Sun Sep 20 2026')
        write_new(self.root / 'manifest.json', {'run_id': self.root.name, 'intervention_id': 'catalog-expanded',
            'stop_confirmed': True, 'network_cleanup': {'confirmed': True}, 'end_reason': 'completed'})
        write_new(self.root / 'context.json', {})
        write_new(self.root / 'inputs-manifest.json', {})
        self.row = {'run_id': self.root.name, 'task_id': self.old['task'], 'attempt': 1001,
                    'intervention_id': 'catalog-expanded', 'run_instance_id': 'synthetic-instance',
                    'artifact': {'state':'fixed'}, 'operation_status':'complete', 'verdict':'fail',
                    'scoring': {'state':'scored','research_status':'complete','evaluation_version':'1.2.0',
                                'evaluator_sha256':self.old['fixed_conditions']['evaluator_sha256']}}
        write_new(self.root / 'usage/raw/first-request-contract.json', {'verified':True,
            'prompt_sha256':self.old['fixed_conditions']['initial_prompt_sha256']['catalog-expanded']})
        response=self.root/'usage/raw/first.response.sse'; response.write_bytes(b'synthetic response; no provider call')
        self.usage={'input_tokens':10,'output_tokens':2,'total_tokens':12}
        event={'request_id':'synthetic-request','status':'completed','http_status':200,
               'response_model_id':self.old['model'],'response_sha256':sha256(response),'usage':self.usage}
        (self.root/'usage/raw/events.jsonl').write_text(json.dumps(event)+'\n',encoding='utf-8')
        write_new(self.root/'usage/normalized.json',{'usage_complete':True,'total_tokens':12,'inventory_issues':[]})
        (self.root/'evidence').mkdir(); (self.root/'evidence/agent.jsonl').write_bytes(b'')
        shutil.copyfile(self.repo/revision.OLD_PATH,self.control/'frozen-plan.json')
        write_new(self.control/'start-approval.json',{'authorized':True,'approved_by':'user','plan_sha256':revision.OLD_SHA,
            'authorization_reference':'SYNTHETIC test authorization only','approved_at_utc':'2026-09-22T13:34:19Z'})
        write_new(self.control/'launch-receipt.json',{'analysis_plan_sha256':revision.OLD_SHA,
            'frozen_analysis_code_hashes':{n:self.old['execution']['code_hashes'][n] for n in self.old['launch']['required_code_files']},
            'pre_dispatch_verified':True,'checked_at_utc':'2026-09-22T13:34:35Z',
            'resource_capacity_confirmation':{'verified':True,'evidence_reference':'synthetic'},
            'identity_and_browser_pin_checks':{'verified':True,'evidence_reference':'synthetic'},
            'dispatch_journal_path':self.old['runs_dir']+'/_control/journal.jsonl',
            'approval_sha256':sha256(self.control/'start-approval.json')})
        self.seal=self.control/(self.root.name+'.seal.json')
        write_new(self.seal,{'run_id':self.root.name,'directory_present':True,'files':sharing.inventory(self.root)})
        case=self.old['slots'][0]
        events=[{'at':'2026-09-22T13:34:34Z','kind':'begin','plan_sha256':revision.OLD_SHA,'assigned':640},
                {'at':'2026-09-22T13:34:35Z','kind':'admission','case':case},
                {'at':'2026-09-22T13:34:36Z','kind':'dispatch','case':case,'plan_sha256':revision.OLD_SHA},
                {'at':'2026-09-22T13:51:09Z','kind':'result','case':case,'stops':['initial_request_differs_from_probe'],
                 'row':self.row,'seal_path':str(self.seal),'seal_sha256':sha256(self.seal)},
                {'at':'2026-09-22T13:51:10Z','kind':'pause','reason':'run_fault','stops':['initial_request_differs_from_probe']}]
        self.journal=self.control/'journal.jsonl'
        self.journal.write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
        self.old_journal=self.journal.read_bytes()
        self.before={p.name:p.read_bytes() for p in self.control.iterdir()}
        self.original_inventory=sharing.inventory(self.root)
        revision.propose(self.repo)
        self.plan_path=self.repo/revision.NEW_PATH; self.plan=read(self.plan_path)
        self.record=self.repo/revision.RECORD_PATH
        self.approval=self.repo/'synthetic-new-approval.json'
        write_new(self.approval,{'authorized':True,'approved_by':'user','plan_sha256':sha256(self.plan_path),
            'amendment_sha256':sha256(self.record),'authorization_reference':'SYNTHETIC fixture, never real user approval',
            'approved_at_utc':(revision.utc(self.plan['date_revision']['proposed_at_utc'])+timedelta(microseconds=1)).isoformat()})

    def adopt(self):
        return revision.adopt(self.plan_path,self.approval,self.repo,lambda *_:{})

    def run_driver(self, sent):
        def dispatch(plan,case,batch,env,repo):
            sent.append(case['run_id'])
            write_new(batch/case['run_id']/'manifest.json',{'synthetic':True})
            return {'stops':[],'row':{'synthetic':True},'cli_exit_code':0}
        return execution.execute(self.plan_path,self.approval,repo=self.repo,verify=lambda *_:{},
            dispatch=dispatch,stage_pair=lambda *args:self.repo/'synthetic-stage-not-published')

    def observation(self):
        with patch.object(observations.aggregate,'row_for',return_value=self.row), \
                patch.object(observations.evaluate,'last_scoring',return_value=None), \
                patch.object(observations,'provider_response',return_value=(self.usage,[],[self.plan['model']],[],True)):
            result=observations.observe(self.root,{**self.plan,'probe':str(self.repo/self.plan['probe'])})
        result['case']=self.plan['slots'][0]
        return result

    def analysis_data(self):
        return {'cohort':self.plan['cohort'],'plan_sha256':sha256(self.plan_path),
                'launch_receipt':read(self.control/'launch-receipt.json'),
                'date_revision_history':revision.validate_history(self.plan_path,self.repo),
                'runs':[self.observation()]}

    def test_proposal_is_post_result_and_does_not_modify_or_adopt_the_batch(self):
        record=read(self.record)
        self.assertTrue(record['after_first_result_seen']); self.assertFalse(record['resumption_authorized'])
        self.assertEqual(record['resume_at'],self.old['slots'][1])
        self.assertEqual(self.journal.read_bytes(),self.old_journal)
        self.assertFalse((self.control/revision.ADOPTION).exists())
        self.assertEqual(sharing.inventory(self.root),self.original_inventory)
        with self.assertRaisesRegex(ValueError,'overwrite'): revision.propose(self.repo)

    def test_unapproved_or_unadopted_revision_never_dispatches(self):
        sent=[]
        with self.assertRaises(FileNotFoundError): self.run_driver(sent)
        invalid=read(self.approval); invalid['authorized']=False
        self.approval.write_text(json.dumps(invalid),encoding='utf-8')
        with self.assertRaises(ValueError): self.adopt()
        self.assertEqual(sent,[]); self.assertEqual(self.journal.read_bytes(),self.old_journal)

    def test_approval_must_bind_amendment_and_be_after_proposal(self):
        original=self.approval.read_bytes()
        for change in ({'amendment_sha256':'0'*64},{'plan_sha256':revision.OLD_SHA},
                       {'approved_at_utc':'2026-09-20T00:00:00Z'},{'authorization_reference':''}):
            invalid=read(self.approval); invalid.update(change)
            self.approval.write_text(json.dumps(invalid),encoding='utf-8')
            with self.assertRaises(ValueError): self.adopt()
            self.approval.write_bytes(original)
        self.assertEqual(self.journal.read_bytes(),self.old_journal)

    def test_unrelated_plan_changes_rejected_even_with_rewritten_record(self):
        original=self.plan_path.read_bytes(); original_record=self.record.read_bytes()
        edits=[lambda p:p.update(model='other'), lambda p:p['budget'].update(run_seconds=1),
               lambda p:p['analysis'].update(confidence=.9),lambda p:p['quality'].update(loss_margin=.1),
               lambda p:p['slots'][1].update(condition='catalog-expanded'),
               lambda p:p['fixed_conditions'].update(evaluator_sha256='0'*64)]
        for edit in edits:
            p=deepcopy(self.plan); edit(p); self.plan_path.write_text(json.dumps(p),encoding='utf-8')
            self.record.write_text(json.dumps(revision.amendment_record(p,sha256(self.plan_path),self.old)),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'unrelated'): revision.validate_proposal(self.plan_path,self.repo)
        self.plan_path.write_bytes(original); self.record.write_bytes(original_record)

    def test_code_and_amendment_tampering_are_rejected(self):
        source=self.repo/'research/catalog_identity.py'; original=source.read_bytes()
        source.write_bytes(original+b'\n# edited\n')
        with self.assertRaisesRegex(ValueError,'code hash'): self.adopt()
        source.write_bytes(original)
        r=read(self.record); r['after_first_result_seen']=False
        self.record.write_text(json.dumps(r),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Amendment record'): self.adopt()

    def test_hash_updates_outside_the_bounded_code_set_are_rejected(self):
        plan=deepcopy(self.plan)
        name='outer/harness/run.py'
        (self.repo/name).write_bytes((self.repo/name).read_bytes()+b'\n# unrelated change\n')
        plan['execution']['code_hashes'][name]=sha256(self.repo/name)
        self.plan_path.write_text(json.dumps(plan),encoding='utf-8')
        self.record.write_text(json.dumps(revision.amendment_record(plan,sha256(self.plan_path),self.old)),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'code-file scope'):
            revision.validate_proposal(self.plan_path,self.repo)

    def test_old_journal_and_seal_changes_prevent_adoption(self):
        raw=self.journal.read_bytes()
        self.journal.write_bytes(raw.replace(b'"assigned": 640',b'"assigned": 639'))
        with self.assertRaisesRegex(ValueError,'journal byte prefix'): self.adopt()
        self.journal.write_bytes(raw)
        self.seal.write_bytes(self.seal.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'Run seal'): self.adopt()

    def test_original_launch_receipt_is_never_rewritten_to_current_hashes(self):
        receipt=read(self.control/'launch-receipt.json')
        receipt['frozen_analysis_code_hashes'].update({n:self.plan['execution']['code_hashes'][n] for n in analysis.REQUIRED_CODE})
        (self.control/'launch-receipt.json').write_text(json.dumps(receipt),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Original plan/launch'): self.adopt()

    def test_adoption_retains_pause_and_is_idempotent_without_rewriting_receipts(self):
        self.assertEqual(self.adopt()['status'],'amendment_adopted_pause_retained')
        adopted=sharing.inventory(self.control)
        self.adopt()
        self.assertEqual(sharing.inventory(self.control),adopted)
        sent=[]; self.assertEqual(self.run_driver(sent)['reason'],'run_fault'); self.assertEqual(sent,[])
        for name,raw in self.before.items():
            if name!='journal.jsonl': self.assertEqual((self.control/name).read_bytes(),raw)
        self.assertTrue(self.journal.read_bytes().startswith(self.old_journal))

    def test_missing_altered_and_duplicate_journal_history_rejected(self):
        self.adopt(); original=self.journal.read_bytes()
        for raw in (self.old_journal,original.replace(b'"date_revision"',b'"unknown_revision"'),
                    original+original.splitlines(keepends=True)[-1]):
            self.journal.write_bytes(raw)
            with self.assertRaisesRegex(ValueError,'history'): revision.validate_history(self.plan_path,self.repo)
        self.journal.write_bytes(original)

    def test_unknown_or_old_plan_dispatch_after_amendment_is_rejected(self):
        self.adopt(); original=self.journal.read_bytes()
        for event in ({'kind':'unapproved_revision'},
                      {'kind':'dispatch','case':self.old['slots'][1],'plan_sha256':revision.OLD_SHA}):
            execution.append(self.journal,event)
            with self.assertRaises(ValueError): revision.validate_history(self.plan_path,self.repo)
            self.journal.write_bytes(original)

    def test_interrupted_adoption_is_reconciled_without_a_second_revision_event(self):
        with patch.object(execution,'append',side_effect=OSError('synthetic crash after receipt')):
            with self.assertRaises(OSError): self.adopt()
        receipt=(self.control/revision.ADOPTION).read_bytes()
        self.assertEqual(self.journal.read_bytes(),self.old_journal)
        self.adopt()
        self.assertEqual((self.control/revision.ADOPTION).read_bytes(),receipt)
        self.assertEqual(sum(e['kind']=='date_revision' for e in execution.events(self.journal)),1)

    def test_simulated_recovery_dispatches_only_compact_and_preserves_slot_one(self):
        self.adopt(); proof=self.repo/'synthetic-recovery-proof.json'
        write_new(proof,{'kind':'synthetic resource/readiness evidence; no real environment claim'})
        evidence=self.repo/'synthetic-recovery.json'
        write_new(evidence,{'plan_sha256':sha256(self.plan_path),'journal_sha256':sha256(self.journal),
            'verified':True,'owned_resources_reconciled':True,'api_or_environment_recovered':True,
            'explanation':'Synthetic date-only recovery test','evidence_files':{str(proof):sha256(proof)}})
        execution.recover(self.plan_path,evidence,repo=self.repo,verify=lambda *_:{})
        sent=[]; self.assertEqual(self.run_driver(sent)['reason'],'public_review_required')
        self.assertEqual(sent,[self.old['slots'][1]['run_id']])
        self.assertEqual(sharing.inventory(self.root),self.original_inventory)
        self.assertEqual(self.seal.read_bytes(),self.before[self.seal.name])
        self.assertTrue(self.journal.read_bytes().startswith(self.old_journal))
        self.assertEqual(len(execution.state(self.plan,self.journal)['results']),2)

    def test_stop_assessment_and_observer_use_identical_comparison(self):
        with patch.object(pilot.profiles,'validate_run'):
            old_stops=pilot.assess(self.root,{**self.old,'probe':str(self.repo/self.old['probe'])},self.row)
            new_stops=pilot.assess(self.root,{**self.plan,'probe':str(self.repo/self.plan['probe'])},self.row)
        observed=self.observation()['initial_input']
        self.assertEqual(old_stops,['initial_request_differs_from_probe']); self.assertEqual(new_stops,[])
        self.assertEqual(observed['comparison'],identity.compare_initial(self.root,self.baseline,self.plan))
        self.assertFalse(observed['comparison']['raw_common_equal'])
        self.assertTrue(observed['semantic_match_to_mock'])

    def test_terminal_result_retains_comparison_audit_including_failed_structure(self):
        import subprocess
        write_new(self.root/'archive-reference.json',{'package_id':'synthetic','sha256':'a'*64})
        with patch.object(execution.subprocess,'run',return_value=subprocess.CompletedProcess([],0)), \
                patch.object(execution.aggregate,'row_for',return_value=self.row), \
                patch.object(execution.machine,'verify_conditions'), \
                patch.object(execution.preserve,'verify'), \
                patch.object(execution.catalog_storage,'retain_completed',return_value={'synthetic':True}), \
                patch.object(pilot.profiles,'validate_run'):
            result=execution.run_case(self.plan,self.plan['slots'][0],self.batch,{},self.repo)
            self.assertTrue(result['initial_input_comparison']['normalized_equal'])
            self.assertFalse(result['initial_input_comparison']['raw_common_equal'])
            log=self.control/(self.root.name+'.log'); log.unlink()  # owned synthetic test log only
            damaged=body(); damaged['messages'][0]['content']=damaged['messages'][0]['content'].replace("Today's date:", 'Changed label:')
            save_request(self.root,damaged)
            result=execution.run_case(self.plan,self.plan['slots'][0],self.batch,{},self.repo)
            self.assertIn('initial_request_differs_from_probe',result['stops'])
            self.assertFalse(result['initial_input_comparison']['structure_valid'])
            log.unlink()  # owned synthetic test log only
            (self.root/'usage/raw/started.jsonl').unlink()
            result=execution.run_case(self.plan,self.plan['slots'][0],self.batch,{},self.repo)
            self.assertIn('initial_request_differs_from_probe',result['stops'])
            self.assertIsNone(result['initial_input_comparison'])

    def test_absent_initial_request_is_missing_in_observation_and_analysis(self):
        self.adopt()
        (self.root/'usage/raw/started.jsonl').write_bytes(b'')
        self.assertIsNone(identity.compare_initial(self.root,self.baseline,self.plan))
        observed=self.observation()['initial_input']
        self.assertIsNone(observed['comparison'])
        self.assertFalse(observed['semantic_match_to_mock'])
        with patch.object(analysis,'REPO',self.repo):
            result=analysis.analyze(self.plan,self.analysis_data(),plan_path=self.plan_path)
        self.assertIsNone(result['rows'][0]['initial_input_comparison'])

    def test_analysis_requires_history_and_recomputes_comparison_from_raw_files(self):
        self.adopt(); data=self.analysis_data()
        with patch.object(analysis,'REPO',self.repo):
            result=analysis.analyze(self.plan,data,plan_path=self.plan_path)
            self.assertEqual(result['assigned_runs'],640)
            self.assertEqual(result['date_revision_history'],data['date_revision_history'])
            self.assertFalse(result['token_inference']['eligible'])
            damaged=deepcopy(data); damaged.pop('date_revision_history')
            with self.assertRaisesRegex(ValueError,'history'): analysis.analyze(self.plan,damaged,plan_path=self.plan_path)
            damaged=deepcopy(data); damaged['runs'][0]['initial_input']['comparison']['raw_common_equal']=True
            with self.assertRaisesRegex(ValueError,'comparison'): analysis.analyze(self.plan,damaged,plan_path=self.plan_path)

    def test_relocated_public_reader_validates_old_receipt_and_same_date_rule(self):
        self.adopt(); workspace=self.repo/'artifacts/test-public'
        sharing.stage(self.repo,workspace,plan_path=self.plan_path,pair=1)
        public=workspace/'public'
        local=sharing.extract(public)
        self.assertEqual(local['date_revision_history'],revision.validate_history(self.plan_path,self.repo))
        self.assertEqual(local['runs'][0]['initial_input_comparison'],identity.compare_initial(self.root,self.baseline,self.plan))
        output=self.repo/'relocated-offline-extraction.json'
        delivery.offline_extract(public,output)
        self.assertEqual(read(output),local)
        self.assertEqual(sha256(public/self.old['runs_dir']/'_control/launch-receipt.json'),sha256(self.control/'launch-receipt.json'))
        with patch.object(analysis,'REPO',self.repo):
            local_analysis=analysis.analyze(self.plan,self.analysis_data(),plan_path=self.plan_path)
        data=self.analysis_data()
        with patch.object(analysis,'REPO',public):
            public_analysis=analysis.analyze(self.plan,data,plan_path=public/revision.NEW_PATH)
        self.assertEqual(public_analysis,local_analysis)
        self.assertEqual(sharing.inventory(self.root),self.original_inventory)

    def test_public_extractor_rejects_missing_revision_reference(self):
        self.adopt(); workspace=self.repo/'artifacts/test-public'
        sharing.stage(self.repo,workspace,plan_path=self.plan_path,pair=1)
        manifest=workspace/'public/MANIFEST.json'; value=read(manifest)
        del value['date_revision_plan']; manifest.write_text(json.dumps(value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'revision plan reference'): sharing.extract(workspace/'public')


if __name__ == '__main__': unittest.main()

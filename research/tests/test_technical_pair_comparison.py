"""Finite synthetic receipts only; no credential, Docker, model or remote calls."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from outer.harness import profiles, util
from research import next_phase, pair_execution, paired_acceptance as acceptance, catalog_delivery
from research import technical_pair_comparison as technical


class PreparationVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.batch = Path(self.tmp.name)
        self.case = {'run_id':'A', 'run_instance_id':'1'*32}
        self.path = self.batch / 'A/manifest.json'
        self.monitor = technical.PreparedRuns(self.batch)

    def test_intermediate_manifest_is_not_ready_then_complete_identity_is_monitored(self):
        util.write_new_json(self.path, {'run_id':'A', 'started_at':None, 'model_called':False})
        with self.assertRaises(KeyError):
            _ = util.read_json(self.path)['run_instance_id']  # Original race.
        self.assertEqual(list(self.monitor.manifests()), [])
        util.write_json_atomic(self.path, self.case)
        self.monitor.register(self.case)
        self.assertEqual(list(self.monitor.manifests()), [(self.path.parent,self.case,self.case)])

    def test_incomplete_registration_is_rejected(self):
        util.write_new_json(self.path, {'run_id':'A'})
        with self.assertRaises(KeyError): self.monitor.register(self.case)
        self.assertEqual(list(self.monitor.manifests()), [])

    def test_missing_or_changed_registered_identity_remains_a_fault(self):
        util.write_new_json(self.path, self.case); self.monitor.register(self.case)
        util.write_json_atomic(self.path, {'run_id':'A'})
        with self.assertRaises(KeyError): list(self.monitor.manifests())
        util.write_json_atomic(self.path, {**self.case,'run_instance_id':'2'*32})
        with self.assertRaisesRegex(ValueError,'Registered monitoring identity'): list(self.monitor.manifests())

    def test_stop_during_preparation_notifies_both_roots_and_blocks_registration(self):
        cases = [self.case, {'run_id':'B','run_instance_id':'2'*32}]
        for case in cases: util.write_new_json(self.batch / case['run_id'] / 'manifest.json', {'run_id':case['run_id']})
        latch = technical.StopLatch(self.batch,cases,stop=lambda root:self.fail('No runtime exists'))
        latch.latch('preparation_fault')
        self.assertTrue(all((self.batch/c['run_id']/'stop-request.json').exists() for c in cases))
        util.write_json_atomic(self.path,self.case)
        with self.assertRaisesRegex(RuntimeError,'admission stopped'):
            with latch.admit(self.case): self.monitor.register(self.case)
        self.assertEqual(list(self.monitor.manifests()), [])


class SeparatePreparationPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.batch = self.root / '_technical-sharing-v5-100p2-20261003'
        util.write_new_json(self.batch / '_control/safety-stop.json',
                            {'reason':'safety_monitor_fault','error_type':'KeyError'})
        util.write_new_json(self.batch / 'A/manifest.json',
                            {'model_called':False,'started_at':None})
        original = self.root / 'original-bundle.json'
        util.write_new_json(original, {'cohort':'runs/'+self.batch.name,'source_commit':'old'})
        self.proof = self.root / 'proof.json'
        util.write_new_json(self.proof, {'cohort':str(self.batch),
            'original_bundle':next_phase.reference(original),'original_code_commit':'old',
            'counts':{'technical_actual_dispatched_runs':0,'technical_dispatch_records':0},
            'safety_stop':util.read_json(self.batch/'_control/safety-stop.json'),
            'inventory':{p.relative_to(self.batch).as_posix():{'sha256':util.sha256_file(p),
                'bytes':p.stat().st_size} for p in self.batch.rglob('*') if p.is_file()}})

    def test_separate_fixed_identities_do_not_replace_initial_slots(self):
        old_cohort, old = technical.comparison_assignments('initial',['explore','preload'])
        new_cohort, new = technical.comparison_assignments('monitorfix-20261004',['explore','preload'])
        self.assertNotEqual(old_cohort,new_cohort)
        old_ids={c['run_instance_id'] for p in old for c in p['cases']}
        new_ids={c['run_instance_id'] for p in new for c in p['cases']}
        self.assertFalse(old_ids & new_ids); self.assertEqual(len(new_ids),4)
        self.assertEqual([c['slot'] for p in new for c in p['cases']],[1,2,3,4])
        self.assertEqual([c['attempt'] for p in new for c in p['cases']],[90061,90061,90062,90062])

    def test_unchanged_original_unsent_preparation_fault_is_verified(self):
        technical.verify_preparation_failure(next_phase.reference(self.proof))

    def test_changed_original_or_new_dispatch_cannot_expand_total_bound(self):
        (self.batch/'A/manifest.json').write_text('{"model_called":true}')
        with self.assertRaisesRegex(ValueError,'Stopped original changed'):
            technical.verify_preparation_failure(next_phase.reference(self.proof))

    def test_ambiguous_runtime_exists_is_rejected_even_with_updated_inventory(self):
        util.write_new_json(self.batch/'A/runtime.json',{'ambiguous':True})
        proof=util.read_json(self.proof)
        proof['inventory']={p.relative_to(self.batch).as_posix():{'sha256':util.sha256_file(p),
            'bytes':p.stat().st_size} for p in self.batch.rglob('*') if p.is_file()}
        util.write_json_atomic(self.proof,proof)
        with self.assertRaisesRegex(ValueError,'send/start ambiguity'):
            technical.verify_preparation_failure(next_phase.reference(self.proof))


class StopLatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.batch=Path(self.tmp.name); (self.batch/'_control').mkdir()
        self.cases=[{'run_id':n,'run_instance_id':str(i)*32} for i,n in enumerate(('A','B'),1)]
        for c in self.cases:
            util.write_new_json(self.batch/c['run_id']/'manifest.json',c)
            util.write_new_json(self.batch/c['run_id']/'runtime.json',{
                **c,'worker':'worker-'+c['run_id'],'started_at':'startup'})

    def test_all_notifications_precede_wait_even_when_stop_record_cannot_be_saved(self):
        stopped=[]
        def stop(root):
            self.assertTrue(all((self.batch/c['run_id']/'stop-request.json').exists() for c in self.cases))
            stopped.append(root.name)
        latch=technical.StopLatch(self.batch,self.cases,stop=stop)
        original=util.write_new_json
        def write(path,value):
            if Path(path)==latch.path: raise OSError('Synthetic storage failure')
            return original(path,value)
        with patch.object(util,'write_new_json',side_effect=write): latch.latch('fixture_fault')
        self.assertEqual(set(stopped),{'A','B'}); self.assertTrue(latch.stopped())
        with self.assertRaises(RuntimeError):
            with latch.admit(self.cases[0]): self.fail('Stop admission must remain closed')

    def test_worker_not_created_is_ineligible_for_stats_then_created_worker_is_observed(self):
        active=[(self.batch/c['run_id'],c) for c in self.cases]
        self.assertEqual(technical.resource_owners(self.batch,active),[])
        path=self.batch/'A/runtime.json'; state=util.read_json(path)
        state['worker_started_at']='created'; util.write_json_atomic(path,state)
        self.assertEqual(technical.resource_owners(self.batch,active),[{
            'name':'worker-A','run_instance_id':'1'*32}])
        state['stop_confirmed']=True; util.write_json_atomic(path,state)
        self.assertEqual(technical.resource_owners(self.batch,active),[])

    def test_persisted_stop_is_respected_by_fresh_manager(self):
        first=technical.StopLatch(self.batch,self.cases,stop=lambda root:None)
        first.latch('fixture_fault')
        second=technical.StopLatch(self.batch,self.cases,stop=lambda root:None)
        with self.assertRaises(RuntimeError):
            with second.admit(self.cases[1]): pass

    def test_stopped_originals_remain_byte_identical_during_fault_stop(self):
        before={}
        for c in self.cases:
            path=self.batch/c['run_id']/'manifest.json'; data=util.read_json(path)
            data['stop_confirmed']=True; util.write_json_atomic(path,data)
            before[c['run_id']]=util.tree_hashes(path.parent)
        with patch.object(technical.runtime,'request_stop') as stop:
            technical.StopLatch(self.batch,self.cases,stop=stop).latch('fixture fault')
            stop.assert_not_called()
        self.assertEqual(before,{c['run_id']:util.tree_hashes(self.batch/c['run_id']) for c in self.cases})

    def test_damaged_current_manifest_cannot_block_peer_stop_notification(self):
        (self.batch/'A/manifest.json').write_text('{damaged synthetic manifest')
        stopped=[]
        def stop(root):
            self.assertTrue((self.batch/'B/stop-request.json').exists())
            stopped.append(root.name)
        technical.StopLatch(self.batch,self.cases,stop=stop).latch('fixture storage fault')
        self.assertEqual(set(stopped),{'A','B'})


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.batch=self.root/'runs/_technical-sharing-fixture'
        self.control=self.batch/'_control'; self.control.mkdir(parents=True)
        self.plan=util.read_json(next_phase.REPO/next_phase.V5_PLAN)
        self.planpath=self.root/'scientific-plan.json'; util.write_new_json(self.planpath,self.plan)
        self.pins={next_phase.V5_PLAN:util.sha256_file(self.planpath),
            'research/technical_pair_comparison.py':'explicit-synthetic-driver'}
        self.scopes=next_phase.acceptance_scopes(self.pins,self.plan)
        self.assignments=[{'pair':n,'task':'MS1-CONT-A','cases':[{
            'pair':n,'slot':2*(n-1)+pos,'position':pos,'block':n,'task':'MS1-CONT-A',
            'condition':arm,'attempt':90050+n,'run_id':f'fixture-{n}-{arm}',
            'run_instance_id':str(2*(n-1)+pos)*32}
            for pos,arm in enumerate(self.plan['arms'],1)]} for n in (1,2)]
        self.fixedpath=self.root/'fixed.json'
        self.fixed={**technical.LIMITS,'kind':'finite_v5_technical_comparison_plan',
            'created_at':self.stamp(0),'settings':self.plan['settings'],'conditions':{},
            'assignments':self.assignments,'cohort':'runs/_technical-sharing-fixture',
            'source_commit':'synthetic-not-a-live-acceptance',
            'plan_reference':next_phase.reference(self.planpath),
            'execution_asset_hashes':self.scopes['execution_evidence']}
        util.write_new_json(self.fixedpath,self.fixed)
        self.bundlepath=self.root/'bundle.json'
        self.bundle={'kind':'continuity_sharing_technical_fixture','source_commit':self.fixed['source_commit'],
            'plan':self.plan,'assignments':self.assignments,'cohort':self.fixed['cohort'],
            'technical_plan':next_phase.reference(self.fixedpath),'pinned_files':self.pins}
        util.write_new_json(self.bundlepath,self.bundle)
        digest=util.sha256_file(self.bundlepath)
        self.journal=self.control/'pair-journal.jsonl'; self.journal.write_text('{}\n')
        self.current={k:{} for k in ('reserved','dispatch','implementations','gates')}
        blocks=[]
        for number,start,end in ((1,10,100),(2,110,170)):
            windows={}; owners=[]; samples=[]
            for case in self.assignments[number-1]['cases']:
                rid=case['run_id']; instance=case['run_instance_id']; root=self.batch/rid
                begin=(20 if case['position']==1 else 40) if number==1 else 115
                finish=begin+10 if number==1 else 150
                binding={**case,'plan_sha256':digest,'cohort':self.fixed['cohort'],
                    'condition_sha256':'fixture-condition','input_sha256':'fixture-input','at':self.stamp(begin-1)}
                self.current['reserved'][rid]=binding; self.current['dispatch'][rid]=binding
                util.write_new_json(root/'manifest.json',{'run_instance_id':instance,'stop_confirmed':True,
                    'end_reason':'completed','condition_sha256':'fixture-condition','prompt_sha256':'fixture-input',
                    'started_at':self.stamp(begin),'ended_at':self.stamp(finish)})
                util.write_new_json(root/'runtime.json',{'run_instance_id':instance,'worker':'worker-'+rid})
                util.write_new_json(root/'usage/normalized.json',{'run_instance_id':instance,
                    'usage_complete':True,'inventory_complete':True,'total_tokens':5})
                event={'request_id':rid,'run_id':rid,'session_id':instance,'status':'completed',
                    'usage_complete':True,'model_id':self.plan['settings']['model_id'],
                    'response_model_id':self.plan['settings']['model_id'],'send_evidence':'observed_send',
                    'http_status':200,'transmitted_at':self.stamp(begin+1),'ended_at':self.stamp(finish-1),
                    'usage':{'input_tokens':2,'output_tokens':3}}
                util.append_line(root/'usage/raw/events.jsonl',event)
                util.append_line(root/'usage/raw/started.jsonl',{'request_id':rid})
                self.current['implementations'][rid]={'receipt':{'stop_confirmed':True,
                    'raw':util.tree_hashes(root/'usage/raw')}}
                owners.append({'name':'worker-'+rid,'run_instance_id':instance})
                samples.append({'Name':'worker-'+rid,'CPUPerc':'1%','MemUsage':'1MiB / 2GiB',
                    'BlockIO':'0B / 0B','NetIO':'1kB / 1kB'})
                windows[rid]=begin
            resource=self.control/f'resource-{number}.jsonl'
            # Serial workers must each have a sample in its distinct window.
            for owner,sample in zip(owners,samples):
                util.append_line(resource,{'at':self.stamp(windows[owner['name'].removeprefix('worker-')]+2),
                    'pair':number,'bundle_sha256':digest,'exit_code':0,'error_present':False,
                    'owners':[owner],'samples':[sample]})
            gatepath=self.control/f'gate-{number}.json'; util.write_new_json(gatepath,{'fixture':True})
            self.current['gates'][number]={'at':self.stamp(end),'receipt':str(gatepath)}
            startpath=self.control/f'start-{number}.json'
            util.write_new_json(startpath,{'at':self.stamp(start),'pair':number,'bundle_sha256':digest,
                'technical_plan_sha256':self.bundle['technical_plan']['sha256']})
            completed=self.control/f'completed-{number}.json'
            util.write_new_json(completed,{'at':self.stamp(end-1),'pair':number,'bundle_sha256':digest,
                'technical_plan_sha256':self.bundle['technical_plan']['sha256'],
                'result':{'reason':'pair_publication_restore_cleanup_required'}})
            blocks.append({'pair':number,'concurrency':number,'technical_bundle':next_phase.reference(self.bundlepath),
                'journal':next_phase.reference(self.journal),'execute_start':next_phase.reference(startpath),
                'resource_samples':next_phase.reference(resource),'normal_completion':next_phase.reference(completed),
                'total_elapsed_seconds':end-start})
        self.comparison={'kind':'paired_execution_acceptance_v5','plan_sha256':util.sha256_file(self.planpath),
            'execution_asset_hashes':self.scopes['execution_evidence'],'maximum_dispatches':4,
            'research_runs_included':False,'fixed_comparison_plan':next_phase.reference(self.fixedpath),'blocks':blocks}
        stack=self.enterContext(ExitStack())
        for target,name,kwargs in [(pair_execution,'state',{'return_value':self.current}),
            (pair_execution,'_validate_gate',{}),(acceptance,'actual_remote',{}),
            (pair_execution,'events',{'return_value':[{'kind':'pair_reserved','pair':n,'concurrency':n} for n in (1,2)]}),
            (profiles,'validate_run',{'return_value':profiles.resolve(next_phase.REPO,'MS1-CONT-A','explore','deepseek-research-v2')}),
            (acceptance.machine,'verify_conditions',{})]:
            stack.enter_context(patch.object(target,name,**kwargs))

    @staticmethod
    def stamp(seconds):
        return (datetime(2026,10,3,tzinfo=timezone.utc)+timedelta(seconds=seconds)).isoformat()

    def validate(self): return acceptance.validate(self.comparison,self.plan,self.scopes)

    def mutate_event(self,pair,arm,**values):
        rid=f'fixture-{pair}-{arm}'; root=self.batch/rid; path=root/'usage/raw/events.jsonl'
        event=util.read_lines(path)[0]; event.update(values)
        path.write_text(__import__('json').dumps(event)+'\n')
        self.current['implementations'][rid]['receipt']['raw']=util.tree_hashes(root/'usage/raw')

    def test_structural_fixture_passes_while_real_transport_is_separately_mocked(self):
        result=self.validate(); self.assertTrue(result['accepted'])
        self.assertEqual(result['actual_dispatches'],4); self.assertEqual(result['gateway_calls'],4)

    def test_different_instance_http_overlap_is_required(self):
        self.mutate_event(2,'explore',ended_at=self.stamp(125))
        self.mutate_event(2,'preload',transmitted_at=self.stamp(130))
        with self.assertRaisesRegex(ValueError,'HTTP overlap'): self.validate()

    def test_partial_usage_and_foreign_provider_are_rejected(self):
        self.mutate_event(2,'preload',usage={'input_tokens':None,'output_tokens':3})
        with self.assertRaisesRegex(ValueError,'Usage incomplete'): self.validate()

    def test_actual_resource_failure_is_not_accepted(self):
        block=self.comparison['blocks'][1]; path=Path(block['resource_samples']['path'])
        rows=util.read_lines(path); rows[0]['exit_code']=1
        path.write_text(''.join(__import__('json').dumps(r)+'\n' for r in rows))
        block['resource_samples']=next_phase.reference(path)
        with self.assertRaisesRegex(ValueError,'Resource monitor failed'): self.validate()

    def test_campaign_stop_survives_preservation_gate(self):
        util.write_new_json(self.control/'safety-stop.json',{'reason':'synthetic monitor fault'})
        with self.assertRaisesRegex(ValueError,'safety/monitor fault'): self.validate()

    def test_slowdown_is_not_adopted(self):
        self.current['gates'][2]['at']=self.stamp(210)
        self.comparison['blocks'][1]['total_elapsed_seconds']=100
        with self.assertRaisesRegex(ValueError,'did not improve'): self.validate()

    def test_missing_normal_completion_bars_adoption(self):
        Path(self.comparison['blocks'][0]['normal_completion']['path']).unlink()
        with self.assertRaises(OSError): self.validate()

    def test_extra_dispatch_is_not_a_four_run_comparison(self):
        self.current['dispatch']['extra']={}
        with self.assertRaisesRegex(ValueError,'Extra or missing'): self.validate()


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.repo=Path(self.tmp.name); self.path=self.repo/'bundle.json'; self.path.write_text('{}')
        self.bundle={'cohort':'runs/_technical-sharing-v5-100p2-20261003','runtime_id':'fixture',
            'technical_plan':{'sha256':'fixed'},'assignments':[{'pair':n,'cases':[
                {'pair':n,'run_id':f'{n}-{arm}','run_instance_id':str(n*2+i)*32} for i,arm in enumerate(('a','b'))]}
                for n in (1,2)]}
        self.batch=self.repo/self.bundle['cohort']; self.fixed={**technical.LIMITS,'conditions':{}}
        self.current={'gates':{},'reserved':{}}
        self.enterContext(patch.object(technical,'check',return_value=(self.bundle,self.fixed)))
        self.enterContext(patch.object(pair_execution,'state',return_value=self.current))
        self.enterContext(patch.object(technical,'browser_postprocess',return_value=lambda *a:None))

    def test_fault_then_preservation_gate_still_cannot_start_second_block(self):
        with patch.object(pair_execution,'execute_pair',return_value={'status':'held','reason':'implementation_fault'}) as send:
            self.assertEqual(technical.execute(self.repo,self.path)['reason'],'implementation_fault')
            self.current['gates'][1]={'fixture':'later preservation gate'}
            self.assertEqual(technical.execute(self.repo,self.path)['reason'],'technical_safety_stop')
            self.assertEqual(send.call_count,1)

    def test_exception_is_latched_and_does_not_authorize_restart(self):
        with patch.object(pair_execution,'execute_pair',side_effect=ValueError('Synthetic pre-dispatch fault')) as send:
            with self.assertRaises(ValueError): technical.execute(self.repo,self.path)
            self.assertEqual(technical.execute(self.repo,self.path)['reason'],'technical_safety_stop')
            self.assertEqual(send.call_count,1)

    def test_uncertain_start_without_normal_completion_never_replays(self):
        control=self.batch/'_control'; control.mkdir(parents=True)
        util.write_new_json(control/'execute-start-1.json',{'at':'fixture uncertain start'})
        with patch.object(pair_execution,'execute_pair') as send:
            self.assertEqual(technical.execute(self.repo,self.path)['reason'],'technical_start_uncertain_never_replayed')
            send.assert_not_called()
        self.current['gates'][1]={'fixture':'later preservation gate'}
        with patch.object(pair_execution,'execute_pair') as send:
            self.assertEqual(technical.execute(self.repo,self.path)['reason'],'previous_technical_block_not_normally_completed')
            send.assert_not_called()


class RemoteReadbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.tag='source-info-v5-100p2-fixture-pair-001'
        expected={'part-000.bin':('a'*64,10),'pair.manifest.json':('b'*64,None),
            'public-review.json':('c'*64,None),'scan.json':('d'*64,None)}
        self.urls={n:f'https://github.com/{catalog_delivery.REPOSITORY}/releases/download/{self.tag}/{n}' for n in expected}
        self.remote={'tag_name':self.tag,'assets':[{'name':n,'digest':'sha256:'+d,
            'size':s if s is not None else 1,'browser_download_url':self.urls[n]} for n,(d,s) in expected.items()]}
        self.remote_path=self.root/'readback.json'; util.write_new_json(self.remote_path,self.remote)
        self.pub={'transport_mode':'github-release-anonymous-download-v1',
            'actual_remote_readback':next_phase.reference(self.remote_path),'urls':self.urls,
            'asset_manifest':{'parts':[{'name':'part-000.bin','sha256':'a'*64,'bytes':10}],
                'review_sha256':'c'*64,'scan_sha256':'d'*64}}
        self.pubpath=self.root/'publication.json'; util.write_new_json(self.pubpath,self.pub)
        restored=self.root/'restore.json'; util.write_new_json(restored,{'download_urls':self.urls,
            'metadata_hashes':{'pair.manifest.json':'b'*64}})
        self.gate={'publication_receipt':str(self.pubpath),'roundtrip_receipt':str(restored),
            'evidence_files':{str(self.remote_path):util.sha256_file(self.remote_path)}}

    def test_exact_real_transport_marker_public_assets_and_download_urls(self):
        self.assertTrue(acceptance.actual_remote(self.gate))

    def test_injected_transport_never_establishes_live_acceptance(self):
        self.pub['transport_mode']='injected-test-transport'; util.write_json_atomic(self.pubpath,self.pub)
        with self.assertRaisesRegex(ValueError,'Injected transport'): acceptance.actual_remote(self.gate)

    def test_mismatched_remote_digest_even_with_updated_receipt_hash_is_rejected(self):
        self.remote['assets'][0]['digest']='sha256:'+'f'*64
        util.write_json_atomic(self.remote_path,self.remote)
        self.pub['actual_remote_readback']=next_phase.reference(self.remote_path)
        util.write_json_atomic(self.pubpath,self.pub)
        self.gate['evidence_files'][str(self.remote_path)]=util.sha256_file(self.remote_path)
        with self.assertRaisesRegex(ValueError,'remote asset hash/URL'): acceptance.actual_remote(self.gate)


if __name__=='__main__': unittest.main()

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from outer.harness import util
from research import live_pilot, live_pilot_launcher, readiness_recovery as recovery


class RecoveryControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.original = self.root / 'original'; self.original.mkdir()
        util.write_new_json(self.original / 'STOP.json', {'unchanged': True})
        self.base = self.root / 'recovery'; self.base.mkdir()
        self.start = (datetime.now(timezone.utc)-timedelta(seconds=1200)).isoformat()
        self.plan = dict(kind=recovery.KIND, batch=str(self.base), phase_id='a'*32,
            bounds=dict(live_pilot.BOUNDS), settings={'model_id':'deepseek-v4.1-flash'},
            assignments=[{'pair':2, 'cases':[dict(pair=2, slot=i, task='CU1-ENR-C',
                condition=arm, attempt=1, run_id='CU1-ENR-C-'+arm+'-001',
                run_instance_id=chr(98+i)*32) for i,arm in enumerate(('explore','preload'),1)]}],
            carried=dict(sent_runs=2, requests=140, observed_tokens=11946268,
                accumulated_run_seconds=2102.502), original_wall_start_utc=self.start)

    def test_immutable_accounting_added_without_original_stop_targets(self):
        before=util.tree_hashes(self.original)
        watch=recovery.RecoveryWatch(self.plan,'f'*64)
        with patch.object(live_pilot.PilotWatch,'counters',return_value=dict(requests=3,
                observed_tokens=50, accumulated_run_seconds=10, wall_seconds=1200,
                longest_active_run_seconds=10, disk_free_bytes=10**12, http_inflight=1)):
            counts=watch.counters()
        self.assertEqual(counts['requests'],143)
        self.assertEqual(counts['observed_tokens'],11946318)
        self.assertAlmostEqual(counts['accumulated_run_seconds'],2112.502)
        self.assertEqual(watch.bindings,[])
        watch.latch('test')
        self.assertEqual(before,util.tree_hashes(self.original))

    def test_launcher_original_deadline_never_restarts(self):
        self.assertLess(live_pilot_launcher.invocation_wall(self.plan,{'sha256':'f'*64}),7801)
        expired=copy.deepcopy(self.plan)
        expired['original_wall_start_utc']=(datetime.now(timezone.utc)-timedelta(seconds=9001)).isoformat()
        with self.assertRaises(TimeoutError): live_pilot_launcher.invocation_wall(expired,{'sha256':'f'*64})

    def test_launcher_only_exact_remaining_pair(self):
        self.assertEqual(live_pilot_launcher.selected_pairs(self.plan),self.plan['assignments'])
        with self.assertRaises(ValueError): live_pilot_launcher.selected_pairs(self.plan,1)
        forged=copy.deepcopy(self.plan); forged['assignments'][0]['pair']=1
        with self.assertRaises(ValueError): live_pilot_launcher.selected_pairs(forged)

    def test_main_recovery_reference_never_falls_back_to_old_failed_pilot(self):
        from research import acquisition_readiness as main
        owner={'readiness_recovery_plan':{'path':'p','sha256':'f'*64},
               'readiness_recovery_result':{'path':'r','sha256':'e'*64}}
        with patch.object(recovery,'ready',side_effect=ValueError('not ready')), patch.object(main,'pilot_ready') as old:
            with self.assertRaisesRegex(ValueError,'not ready'): main.readiness_for_main(self.root,owner)
            old.assert_not_called()
        del owner['readiness_recovery_result']
        with self.assertRaises(ValueError): main.readiness_for_main(self.root,owner)

    def sealed_fixture(self,source_pins=None):
        oldcases=[]
        for number,task in ((1,'MS1-CONT-A'),(2,'CU1-ENR-C')):
            oldcases.append(dict(pair=number,cases=[dict(pair=number,slot=slot,task=task,condition=arm,
                attempt=1,run_id=task+'-'+arm+'-001',run_instance_id=str(number*2+slot)*32)
                for slot,arm in enumerate(('explore','preload'),1)]))
        old=dict(kind=live_pilot.KIND,schema_version=1,batch=str(self.original),phase_id='1'*32,
            cohort='runs/original',bounds=dict(live_pilot.BOUNDS),require_fixed_instances=True,
            pair_concurrency=2,assignments=oldcases,source_pins=source_pins or {},settings=dict(model_id='deepseek-v4.1-flash',
            provider='opencode-go',use_balance=False,paid_fallback=False),task_revision='evaluators-20261006',
            runtime_by_task={'MS1-CONT-A':'deepseek-music-repaired-v1','CU1-ENR-C':'deepseek-education-repaired-v1'})
        oldpath=self.root/'old-plan.json'; util.write_new_json(oldpath,old); oldref=live_pilot.reference(oldpath)
        resultpath=self.original/'result.json'; util.write_new_json(resultpath,dict(kind=live_pilot.KIND,
            plan_sha256=oldref['sha256'],pilot_operational_complete=False,fault={'reason':'postprocess_fault'},
            watcher_shutdown_verified=True))
        launcherpath=self.original/'_launcher/result.json'
        util.write_new_json(launcherpath,dict(kind='live_pilot_launcher_result_v1',plan=oldref,
            operational_complete=False,child_pid=3,child=dict(pid=3,initial_exit_code=0,
                terminated=False,killed=False,exit_code=0,unknown=False)))
        util.write_new_json(self.original/'_launcher/intent.json',dict(plan=oldref,started_at=self.start))
        util.write_new_json(self.original/'_launcher/registration.json',dict(plan=oldref,child_pid=3))
        util.write_new_json(self.original/'execution-intent.json',dict(plan_sha256=oldref['sha256'],started_at=self.start))
        util.write_new_json(self.original/'_control/dispatch-stop.json',dict(plan_sha256=oldref['sha256']))
        journal={'dispatch':{c['run_id']:c for c in oldcases[0]['cases']}}
        for c in oldcases[0]['cases']:
            util.write_new_json(self.original/'pair-1'/c['run_id']/'manifest.json',
                dict(end_reason='completed',exit_code=0,duration_seconds=20))
        invpath=self.root/'inventory.json'; util.write_new_json(invpath,util.tree_hashes(self.original))
        closure=dict(kind='failed_repaired_pilot_sealed_closeout_v1',original_plan=oldref,
            original_batch=str(self.original),original_inventory=live_pilot.reference(invpath),
            original_result=live_pilot.reference(resultpath),original_launcher_result=live_pilot.reference(launcherpath),
            original_failed_status_preserved=True,sent_run_replay_authorized=False,ready=False,new_100_dispatched=False,
            original_wall_start_utc=self.start,original_wall_seconds=9000,observer_ack_confirmed=True,observer_exit_code=0,
            scoped_process_matches=[],never_started_pair2_observer_not_claimed_stopped=True,
            resource_observations=[dict(name=str(i),owned=True,running=False) for i in range(4)]+
                [dict(network=str(i),present=False) for i in range(2)],remaining_original_cases=oldcases[1]['cases'],
            request_count_consumed=2,observed_tokens_consumed=6,run_seconds_consumed=40,
            logical_sent_runs=2,generation_complete_runs=2,stop_target_runs=2,stop_confirmed_runs=2,
            scoring_reached_runs=0,unallocated_unsent_runs=2)
        closepath=self.root/'closeout.json'; util.write_new_json(closepath,closure)
        plan=dict(self.plan,original_plan=oldref,original_closeout=live_pilot.reference(closepath),
            assignments=[oldcases[1]],carried=dict(sent_runs=2,requests=2,observed_tokens=6,accumulated_run_seconds=40))
        return plan,journal,closure

    def source_leaves(self,journal):
        from contextlib import ExitStack
        stack=ExitStack()
        stack.enter_context(patch.object(recovery.pair_execution,'state',return_value=journal))
        stack.enter_context(patch.object(live_pilot,'validate_owned_terminal',
            side_effect=lambda root,binding: {'native_session_id':binding['run_instance_id']}))
        stack.enter_context(patch.object(live_pilot.live_usage,'journal',side_effect=lambda path:
            ([{}],[]) if path.name=='started.jsonl' else ([{'usage':{'input_tokens':2,'output_tokens':1}}],[])))
        return stack

    def test_sealed_source_changed_rejected_before_any_allocation(self):
        plan,journal,_=self.sealed_fixture()
        with self.source_leaves(journal): self.assertEqual(recovery.sealed_original(plan)[0]['kind'],live_pilot.KIND)
        (self.original/'STOP.json').write_text('tamper')
        snapshot=util.tree_hashes(self.root)
        with self.source_leaves(journal),self.assertRaisesRegex(ValueError,'original bytes changed'):
            recovery.sealed_original(plan)
        self.assertEqual(snapshot,util.tree_hashes(self.root))

    def test_reset_counter_or_wall_or_education_uuid_rejected_no_writes(self):
        plan,journal,_=self.sealed_fixture(); before=util.tree_hashes(self.root)
        for field,value in [('carried',dict(sent_runs=2,requests=0,observed_tokens=0,accumulated_run_seconds=0)),
                ('original_wall_start_utc',datetime.now(timezone.utc).isoformat()),
                ('assignments',[{'pair':2,'cases':[]}])]:
            forged=copy.deepcopy(plan); forged[field]=value
            with self.source_leaves(journal),self.assertRaises(ValueError): recovery.sealed_original(forged)
        self.assertEqual(before,util.tree_hashes(self.root))

    def test_historical_education_allocation_rejected_even_if_inventory_resealed(self):
        plan,journal,closure=self.sealed_fixture()
        target=self.original/'pair-2'/plan['assignments'][0]['cases'][0]['run_id']; target.mkdir(parents=True)
        util.write_new_json(target/'manifest.json',{'unexpected':True})
        # Fixture authority deliberately knows the new bytes, but unsent lineage
        # still rejects independently of the general immutable byte guard.
        inv=self.root/'inventory-2.json'; util.write_new_json(inv,util.tree_hashes(self.original))
        closure['original_inventory']=live_pilot.reference(inv)
        second=self.root/'closeout-2.json'; util.write_new_json(second,closure)
        plan['original_closeout']=live_pilot.reference(second)
        before=util.tree_hashes(self.root)
        with self.source_leaves(journal),self.assertRaisesRegex(ValueError,'Education was allocated'):
            recovery.sealed_original(plan)
        self.assertEqual(before,util.tree_hashes(self.root))

    def test_stopped_owned_proof_unknown_or_foreign_rejected(self):
        plan,journal,closure=self.sealed_fixture()
        closure['resource_observations'][0]['owned']=False
        second=self.root/'foreign-closeout.json'; util.write_new_json(second,closure)
        plan['original_closeout']=live_pilot.reference(second)
        before=util.tree_hashes(self.root)
        with self.source_leaves(journal),self.assertRaisesRegex(ValueError,'stopped owned'):
            recovery.sealed_original(plan)
        self.assertEqual(before,util.tree_hashes(self.root))

    def test_original_carried_plus_new_run_cap(self):
        watch=recovery.RecoveryWatch(self.plan,'f'*64)
        for binding in self.plan['assignments'][0]['cases']: watch.register(self.base/'pair-2',binding)
        with self.assertRaisesRegex(ValueError,'four-Run cap'):
            watch.register(self.base/'pair-2',self.plan['assignments'][0]['cases'][0])

    def full_fixture(self):
        from research.tests.test_live_pilot import PlanBoundaries
        fixture=PlanBoundaries(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        sealed,journal,_=self.sealed_fixture({name:sha for name,sha in fixture.plan['source_pins'].items() if name.endswith('.json')})
        plan=dict(fixture.plan,kind=recovery.KIND,original_plan=sealed['original_plan'],
            original_closeout=sealed['original_closeout'],assignments=sealed['assignments'],
            carried=sealed['carried'],original_wall_start_utc=self.start,
            original_pilot_adoption=False,sent_run_replay_authorized=False)
        plan['protected_roots'].append(str(self.original))
        for name in recovery.EXTRA_PINS:
            path=fixture.repo/name; path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(name); plan['source_pins'][name]=util.sha256_file(path)
        plan['launch_supervisor']=live_pilot.reference(fixture.repo/'research/live_pilot_launcher.py')
        proof=self.root/'music.json'; util.write_new_json(proof,{'only':'mocked saved validator leaf'})
        plan['saved_music_postprocessing']=live_pilot.reference(proof)
        rows=[dict(source_run_instance_id=case['run_instance_id'],assessment_id=chr(97+i)*32,
            model_dispatch_count=0,acquisition_count_increment=0,original_pilot_adoption=False)
            for i,case in enumerate(util.read_json(live_pilot.checked(plan['original_plan']))['assignments'][0]['cases'])]
        return fixture,plan,journal,rows

    def test_create_actual_typed_allocation_one_child_no_old_writes_no_model(self):
        fixture,plan,journal,rows=self.full_fixture()
        before=util.tree_hashes(self.original)
        path=self.root/'recovery-plan.json'; util.write_new_json(path,plan)
        with self.source_leaves(journal),patch('research.saved_postprocessing_recovery.validate_saved_music_postprocessing',return_value=rows), \
                patch.object(live_pilot,'execute_owned_pair_scope') as dispatch:
            result=recovery.create(fixture.repo,path)
            with self.assertRaises(FileExistsError): recovery.create(fixture.repo,path)
            dispatch.assert_not_called()
        base=Path(plan['batch'])
        self.assertFalse((base/'pair-1').exists()); self.assertTrue((base/'pair-2/phase.json').exists())
        self.assertEqual(util.read_json(base/'pair-2/phase.json')['kind'],recovery.OBSERVER_KIND)
        self.assertFalse(result['model_dispatched']); self.assertEqual(before,util.tree_hashes(self.original))

    def test_full_validator_identity_source_budget_and_music_faults_zero_mutations(self):
        fixture,plan,journal,rows=self.full_fixture()
        changes=[lambda p:p.update(batch=str(self.original/'new')),
            lambda p:p['bounds'].update(max_runs=6),lambda p:p['bounds'].update(max_runs=True),
            lambda p:p['source_pins'].pop(recovery.EXTRA_PINS[0]),
            lambda p:p['runtime_locks']['deepseek-education-repaired-v1'].update(sha256='f'*64),
            lambda p:p['assignments'][0]['cases'][0].update(run_instance_id='a'*32),
            lambda p:p.update(original_pilot_adoption=True),lambda p:p['settings'].update(use_balance=True)]
        before=util.tree_hashes(self.root); other=util.tree_hashes(fixture.root)
        with self.source_leaves(journal),patch('research.saved_postprocessing_recovery.validate_saved_music_postprocessing',return_value=rows):
            recovery.validate_plan(plan,fixture.repo)
            for change in changes:
                bad=copy.deepcopy(plan); change(bad)
                with self.assertRaises((ValueError,KeyError)): recovery.validate_plan(bad,fixture.repo)
        with self.source_leaves(journal),patch('research.saved_postprocessing_recovery.validate_saved_music_postprocessing',side_effect=ValueError('saved music incomplete')):
            with self.assertRaisesRegex(ValueError,'saved music incomplete'): recovery.validate_plan(plan,fixture.repo)
        self.assertEqual(before,util.tree_hashes(self.root)); self.assertEqual(other,util.tree_hashes(fixture.root))

    def test_stop_only_new_education_roots_preserves_sealed_music(self):
        before=util.tree_hashes(self.original)
        watch=recovery.RecoveryWatch(self.plan,'f'*64)
        for binding in self.plan['assignments'][0]['cases']:
            root=self.base/'pair-2'/binding['run_id']; root.mkdir(parents=True)
            util.write_new_json(root/'manifest.json',{'run_instance_id':binding['run_instance_id']})
            util.write_new_json(root/'runtime.json',dict(run_id=binding['run_id'],run_instance_id=binding['run_instance_id']))
            watch.register(self.base/'pair-2',binding)
        with patch.object(live_pilot.runtime,'request_stop',return_value={'stop_confirmed':True}) as stop:
            watch.latch('observer_fault')
            self.assertEqual({Path(c.args[0]) for c in stop.call_args_list},
                {self.base/'pair-2'/c['run_id'] for c in self.plan['assignments'][0]['cases']})
            watch.latch('second_fault'); self.assertEqual(stop.call_count,2)
        self.assertEqual(before,util.tree_hashes(self.original))

    def launcher_receipt_fixture(self):
        plan=dict(self.plan,source_commit='a'*40)
        repo=self.root/'source'; repo.mkdir(); source=repo/'research/live_pilot_launcher.py'
        source.parent.mkdir(); source.write_text('fixture source')
        path=self.root/'plan.json'; util.write_new_json(path,plan); ref=live_pilot.reference(path)
        approval=self.root/'approval.json'; util.write_new_json(approval,dict(plan_sha256=ref['sha256'],
            authorized=True,approved_by='user',authorization_reference='finite fixture authorization'))
        directory=self.base/'_launcher'
        intent=dict(kind='live_pilot_launcher_v1',schema_version=1,plan=ref,selected_pair=None,
            phase_id=plan['phase_id'],source_sha256=util.sha256_file(source),controller_source_commit='a'*40,
            launch_id='b'*32,launcher_pid=1,parent_pid=2,approval=live_pilot.reference(approval),
            started_at=datetime.now(timezone.utc).isoformat(),
            command=[sys.executable,'-B','-X','utf8','-m','research.readiness_recovery','execute',ref['path'],
                     '--repo',str(repo),'--approval',str(approval)])
        util.write_new_json(directory/'intent.json',intent)
        util.write_new_json(directory/'registration.json',dict(intent,child_pid=3))
        proof=dict(ready=True,plan=ref,model_runs=4,new_model_runs=2,original_pilot_adoption=False)
        proofpath=directory/'terminal-proof.json'; util.write_new_json(proofpath,proof)
        result=dict(kind='live_pilot_launcher_result_v1',plan=ref,approval=intent['approval'],
            controller_source_commit='a'*40,launch_id='b'*32,launcher_pid=1,child_pid=3,
            source_sha256=intent['source_sha256'],selected_pair=None,operational_complete=True,
            watcher_shutdown_verified=True,stop_requested=False,new_main_authorized=False,model_runs=2,
            child_exit_code=0,verification_child_exit_code=0,verification_child_pid=4,
            elapsed_seconds=10,terminal_proof=live_pilot.reference(proofpath))
        util.write_new_json(directory/'verification-registration.json',{'pid':4})
        util.write_new_json(directory/'result.json',result)
        return repo,plan,ref,proof,directory,result

    def test_launcher_terminal_actual_identity_command_exit_wall_and_proof_binding(self):
        repo,plan,ref,proof,directory,result=self.launcher_receipt_fixture()
        original=util.tree_hashes(self.original)
        validate=lambda:live_pilot_launcher.validate_launcher_terminal(repo,plan,ref,proof,
            controller_module='research.readiness_recovery')
        validate()
        for key,value in [('child_exit_code',1),('verification_child_pid',9),('model_runs',4),
                ('elapsed_seconds',9000),('plan',{'path':'foreign','sha256':'f'*64})]:
            wrong=dict(result); wrong[key]=value; util.write_json_atomic(directory/'result.json',wrong)
            snapshot=util.tree_hashes(self.root)
            with self.assertRaises(ValueError): validate()
            self.assertEqual(snapshot,util.tree_hashes(self.root))
        util.write_json_atomic(directory/'result.json',result)
        util.write_json_atomic(directory/'terminal-proof.json',dict(proof,model_runs=200))
        with self.assertRaises(ValueError): validate()
        self.assertEqual(original,util.tree_hashes(self.original))

    def test_saved_combined_ceiling_recomputation_rejects_reset_overshoot_and_partial_lines(self):
        for case in self.plan['assignments'][0]['cases']:
            root=self.base/'pair-2'/case['run_id']; raw=root/'usage/raw'; raw.mkdir(parents=True)
            util.write_new_json(root/'manifest.json',{'duration_seconds':20})
            (raw/'started.jsonl').write_text('{}\n',encoding='utf-8')
            (raw/'events.jsonl').write_text('{"usage":{"input_tokens":2,"output_tokens":1}}\n',encoding='utf-8')
        self.assertEqual(recovery.combined_consumed(self.plan),dict(requests=142,observed_tokens=11946274,
            accumulated_run_seconds=2142.502))
        for key,value in [('requests',599),('observed_tokens',29999999),('accumulated_run_seconds',7199)]:
            forged=copy.deepcopy(self.plan); forged['carried'][key]=value
            with self.assertRaisesRegex(ValueError,'finite ceilings'): recovery.combined_consumed(forged)
        path=self.base/'pair-2'/self.plan['assignments'][0]['cases'][0]['run_id']/'usage/raw/events.jsonl'
        path.write_text('{"usage":',encoding='utf-8')
        before=util.tree_hashes(self.root)
        with self.assertRaises(ValueError): recovery.combined_consumed(self.plan)
        self.assertEqual(before,util.tree_hashes(self.root))

    def test_main_rejects_logical_pilot_uuid_collisions_direct_and_recovery_routes(self):
        from research.tests.test_acquisition_readiness import ReadinessFixture
        from research import acquisition_readiness as main
        fixture=ReadinessFixture(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        sealed,_,_=self.sealed_fixture(); oldref=sealed['original_plan']
        old=util.read_json(live_pilot.checked(oldref)); collision=old['assignments'][1]['cases'][0]['run_instance_id']
        recovered=self.root/'typed-recovery.json'
        util.write_new_json(recovered,{'kind':recovery.KIND,'original_plan':oldref})
        for route in ('direct','recovery'):
            plan=copy.deepcopy(fixture.plan)
            if route=='direct': plan['readiness_pilot_plan']=oldref
            else:
                plan['readiness_recovery_plan']=live_pilot.reference(recovered)
                plan['readiness_recovery_result']=sealed['original_closeout']
                for name in recovery.EXTRA_PINS:
                    target=fixture.repo/name; target.write_text(name)
                    plan['source_pins'][name]=util.sha256_file(target)
            plan['assignments'][0]['cases'][0]['run_instance_id']=collision
            util.write_json_atomic(fixture.plan_path,plan); before=util.tree_hashes(fixture.root)
            with patch.object(util,'write_new_json') as writer,self.assertRaisesRegex(ValueError,'foreign main Run UUID'):
                main.create(fixture.repo,fixture.plan_path)
            writer.assert_not_called(); self.assertEqual(before,util.tree_hashes(fixture.root))
            fixture.dispatch.assert_not_called()

    def test_actual_failed_launcher_nested_child_schema_and_negative_identity(self):
        plan,journal,_=self.sealed_fixture()
        launched=util.read_json(self.original/'_launcher/result.json')
        registration=util.read_json(self.original/'_launcher/registration.json')
        before=util.tree_hashes(self.root)
        recovery.validate_failed_launcher(launched,registration,plan['original_plan'])
        for key,value in [('pid',99),('exit_code',1),('exit_code',False),('unknown',True),('unknown',None)]:
            wrong=copy.deepcopy(launched); wrong['child'][key]=value
            with self.assertRaises(ValueError): recovery.validate_failed_launcher(wrong,registration,plan['original_plan'])
        wrong=copy.deepcopy(launched); wrong['child_pid']=99
        with self.assertRaises(ValueError): recovery.validate_failed_launcher(wrong,registration,plan['original_plan'])
        wrong=copy.deepcopy(launched); del wrong['child']; wrong['child_exit_code']=0
        with self.assertRaises(ValueError): recovery.validate_failed_launcher(wrong,registration,plan['original_plan'])
        self.assertEqual(before,util.tree_hashes(self.root))


if __name__=='__main__': unittest.main()
